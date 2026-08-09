"""Immutable content-addressed local snapshot storage."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from f1sim.schemas.models import UtcDatetime

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def _validate_json_value(value: object, path: str = "payload") -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, list):
        return [_validate_json_value(item, f"{path}[]") for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{path} object keys must be strings")
        return {key: _validate_json_value(item, f"{path}.{key}") for key, item in value.items()}
    raise ValueError(f"{path} contains unsupported Python object {type(value).__name__}")


class SnapshotRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source: str = Field(min_length=1)
    observed_at: UtcDatetime
    published_at: UtcDatetime
    eligible_from: UtcDatetime
    payload: dict[str, JsonValue]

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, value: object) -> dict[str, JsonValue]:
        validated = _validate_json_value(value)
        if not isinstance(validated, dict):
            raise ValueError("payload must be a JSON object")
        return validated


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_id: str
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: str = Field(min_length=1)
    cutoff: UtcDatetime
    created_at: UtcDatetime
    synthetic: bool
    records: tuple[SnapshotRecord, ...]

    @model_validator(mode="after")
    def reject_future_leak(self) -> Snapshot:
        for record in self.records:
            if max(record.observed_at, record.published_at, record.eligible_from) > self.cutoff:
                raise ValueError("future-leaking record exceeds snapshot cutoff")
        return self


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _content_body(snapshot: Snapshot) -> dict[str, object]:
    return {
        "event_id": snapshot.event_id,
        "cutoff": snapshot.cutoff.isoformat(),
        "created_at": snapshot.created_at.isoformat(),
        "synthetic": snapshot.synthetic,
        "records": [record.model_dump(mode="json") for record in snapshot.records],
    }


def validate_snapshot_integrity(snapshot: Snapshot) -> None:
    digest = hashlib.sha256(_canonical_bytes(_content_body(snapshot))).hexdigest()
    if snapshot.snapshot_hash != digest or snapshot.snapshot_id != f"snap-{digest[:16]}":
        raise ValueError("snapshot content address does not match full serialized identity content")


def build_snapshot(
    records: tuple[SnapshotRecord, ...],
    cutoff: datetime,
    created_at: datetime,
    synthetic: bool,
    *,
    event_id: str,
) -> Snapshot:
    if cutoff.utcoffset() is None or created_at.utcoffset() is None:
        raise ValueError("cutoff and created_at must include timezone information")
    normalized_cutoff = cutoff.astimezone(UTC)
    normalized_created_at = created_at.astimezone(UTC)
    provisional = Snapshot(
        snapshot_id="pending",
        snapshot_hash="0" * 64,
        event_id=event_id,
        cutoff=normalized_cutoff,
        created_at=normalized_created_at,
        synthetic=synthetic,
        records=records,
    )
    digest = hashlib.sha256(_canonical_bytes(_content_body(provisional))).hexdigest()
    return provisional.model_copy(
        update={"snapshot_id": f"snap-{digest[:16]}", "snapshot_hash": digest}
    )


def load_snapshot(path: Path) -> Snapshot:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("snapshot file must be a regular non-symlink file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            encoded = handle.read()
    except FileNotFoundError:
        raise ValueError("snapshot file does not exist") from None
    except OSError as error:
        raise ValueError("snapshot file must be a regular non-symlink file") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        snapshot = Snapshot.model_validate_json(encoded)
    except ValueError as error:
        raise ValueError("snapshot file is not a valid immutable Snapshot") from error
    validate_snapshot_integrity(snapshot)
    return snapshot


def save_immutable(snapshot: Snapshot, directory: Path) -> Path:
    validate_snapshot_integrity(snapshot)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{snapshot.snapshot_id}.json"
    encoded = _canonical_bytes(snapshot)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o644,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
    except FileExistsError:
        mode = path.lstat().st_mode
        if path.is_symlink() or not stat.S_ISREG(mode) or path.read_bytes() != encoded:
            raise FileExistsError(f"refusing to overwrite immutable snapshot {path}") from None
    return path
