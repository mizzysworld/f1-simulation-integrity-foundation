from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from f1sim.data.snapshots import (
    JsonValue,
    Snapshot,
    SnapshotRecord,
    build_snapshot,
    load_snapshot,
    save_immutable,
)
from f1sim.models.baselines import grid_only
from f1sim.reporting.receipt import prediction_hash, publish_prediction
from f1sim.schemas import CanonicalPrediction, Event, PredictionReceipt, SnapshotIdentity

NOW = datetime(2026, 1, 1, tzinfo=UTC)
EVENT_ID = "snapshot-event"


def record(at: datetime, payload: object = None) -> SnapshotRecord:
    return SnapshotRecord(
        source="synthetic",
        observed_at=at,
        published_at=at,
        eligible_from=at,
        payload=cast(dict[str, JsonValue], {"value": 1} if payload is None else payload),
    )


def make_snapshot(event_id: str = EVENT_ID, *, synthetic: bool = True) -> Snapshot:
    return build_snapshot((record(NOW),), NOW, NOW, synthetic=synthetic, event_id=event_id)


def test_snapshot_content_id_integrity_and_anti_overwrite(tmp_path: Path) -> None:
    snapshot = make_snapshot()
    path = save_immutable(snapshot, tmp_path)
    assert save_immutable(snapshot, tmp_path) == path
    corrupt = snapshot.model_copy(update={"snapshot_hash": "0" * 64})
    with pytest.raises(ValueError, match="content address"):
        save_immutable(corrupt, tmp_path)
    path.write_text("corrupt", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing"):
        save_immutable(snapshot, tmp_path)


def test_created_at_event_and_full_hash_are_identity_inputs() -> None:
    base = make_snapshot()
    later = build_snapshot(
        base.records,
        base.cutoff,
        NOW + timedelta(seconds=1),
        synthetic=True,
        event_id=base.event_id,
    )
    other_event = build_snapshot(base.records, base.cutoff, NOW, synthetic=True, event_id="other")
    assert len({base.snapshot_hash, later.snapshot_hash, other_event.snapshot_hash}) == 3
    collision = base.model_copy(update={"created_at": later.created_at})
    with pytest.raises(ValueError, match="content address"):
        save_immutable(collision, Path("/unused"))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_snapshot_payload_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValidationError, match="non-finite"):
        record(NOW, {"nested": [value]})


def test_snapshot_payload_rejects_objects_and_round_trips_canonical_json() -> None:
    with pytest.raises(ValidationError, match="unsupported Python object"):
        record(NOW, {"bad": object()})
    original = record(NOW, {"nested": [1, "x", True, None, {"n": 1.5}]})
    restored = SnapshotRecord.model_validate_json(original.model_dump_json())
    assert restored.model_dump(mode="json") == original.model_dump(mode="json")


def test_future_leak_rejected() -> None:
    with pytest.raises(ValidationError, match="future-leaking"):
        build_snapshot(
            (record(NOW + timedelta(seconds=1)),),
            NOW,
            NOW,
            synthetic=False,
            event_id=EVENT_ID,
        )


def test_operational_datetimes_reject_naive_and_serialize_as_utc() -> None:
    naive = datetime(2026, 1, 1)
    with pytest.raises(ValidationError, match="timezone"):
        record(naive)
    eastern = datetime(2025, 12, 31, 19, tzinfo=timezone(-timedelta(hours=5)))
    snapshot = build_snapshot(
        (record(eastern),), eastern, eastern, synthetic=True, event_id=EVENT_ID
    )
    utc_snapshot = make_snapshot()
    assert snapshot.snapshot_hash == utc_snapshot.snapshot_hash
    assert snapshot.model_dump_json().count("2026-01-01T00:00:00Z") >= 5


def test_snapshot_persistence_rejects_symlink_target(tmp_path: Path) -> None:
    snapshot = make_snapshot()
    external = tmp_path / "external.json"
    external.write_bytes(snapshot.model_dump_json().encode())
    destination = tmp_path / f"{snapshot.snapshot_id}.json"
    destination.symlink_to(external)
    with pytest.raises(FileExistsError, match="refusing"):
        save_immutable(snapshot, tmp_path)


def test_snapshot_loader_reads_opened_inode_during_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_snapshot = make_snapshot()
    alternate_snapshot = build_snapshot(
        original_snapshot.records,
        original_snapshot.cutoff,
        NOW + timedelta(seconds=1),
        synthetic=True,
        event_id=original_snapshot.event_id,
    )
    path = save_immutable(original_snapshot, tmp_path / "original")
    alternate_path = save_immutable(alternate_snapshot, tmp_path / "alternate")
    backup = path.with_suffix(".opened")
    original_open = os.open
    swapped = False

    def replace_after_open(target: os.PathLike[str] | str, flags: int, mode: int = 0o777) -> int:
        nonlocal swapped
        descriptor = original_open(target, flags, mode)
        if Path(target) == path and not swapped:
            swapped = True
            path.rename(backup)
            path.symlink_to(alternate_path)
        return descriptor

    monkeypatch.setattr(os, "open", replace_after_open)
    loaded = load_snapshot(path)
    assert loaded.snapshot_id == original_snapshot.snapshot_id
    assert path.is_symlink()


def receipt_for(
    event: Event, snapshot: Snapshot, *, synthetic: bool
) -> tuple[CanonicalPrediction, PredictionReceipt]:
    identity = SnapshotIdentity(
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.snapshot_hash,
        cutoff=snapshot.cutoff,
        event_id=snapshot.event_id,
        synthetic=snapshot.synthetic,
    )
    prediction = grid_only(event, snapshot=identity)
    receipt = PredictionReceipt(
        receipt_id="receipt-test",
        event_id=event.event_id,
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.snapshot_hash,
        input_hash=prediction.input_hash,
        output_hash=prediction_hash(prediction),
        cutoff=snapshot.cutoff,
        created_at=NOW,
        model_id=prediction.model_id,
        model_version=prediction.model_version,
        field_size=prediction.field_size,
        schema_version="0.2",
        ruleset_id=event.ruleset.ruleset_id,
        code_version="test",
        dependency_lock_hash="c" * 64,
        python_version="3.12.0",
        runtime="cpython",
        seed=1,
        runs=1,
        status="complete",
        synthetic=synthetic,
    )
    return prediction, receipt


def test_synthetic_prediction_cannot_publish(toy_event: Event, tmp_path: Path) -> None:
    snapshot = make_snapshot(toy_event.event_id)
    prediction, receipt = receipt_for(toy_event, snapshot, synthetic=True)
    with pytest.raises(ValueError, match="synthetic"):
        publish_prediction(prediction, receipt, tmp_path, snapshot=Path("/unused"))


def test_synthetic_bypass_flags_are_rejected(toy_event: Event, tmp_path: Path) -> None:
    snapshot = make_snapshot(toy_event.event_id)
    prediction, receipt = receipt_for(toy_event, snapshot, synthetic=True)
    with pytest.raises(ValidationError, match="synthetic flag"):
        CanonicalPrediction.model_validate({**prediction.model_dump(), "synthetic": False})
    forged = prediction.model_copy(update={"synthetic": False})
    forged_receipt = receipt.model_copy(update={"synthetic": False})
    with pytest.raises(ValueError, match="embedded synthetic"):
        publish_prediction(forged, forged_receipt, tmp_path, snapshot=Path("/unused"))


def test_receipt_synthetic_and_safe_id_are_enforced(toy_event: Event) -> None:
    snapshot = make_snapshot(toy_event.event_id)
    prediction, receipt = receipt_for(toy_event, snapshot, synthetic=True)
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        PredictionReceipt.model_validate({**receipt.model_dump(), "receipt_id": "../escape"})
    real = Event.model_validate({**toy_event.model_dump(), "is_synthetic": False})
    real_snapshot = make_snapshot(real.event_id, synthetic=False)
    prediction, receipt = receipt_for(real, real_snapshot, synthetic=False)
    with pytest.raises(ValueError, match="synthetic mismatch"):
        publish_prediction(
            prediction,
            receipt.model_copy(update={"synthetic": True}),
            Path("/unused"),
            snapshot=Path("/unused"),
        )


def test_publication_requires_and_validates_snapshot_file(toy_event: Event, tmp_path: Path) -> None:
    real = Event.model_validate({**toy_event.model_dump(), "is_synthetic": False})
    snapshot = make_snapshot(real.event_id, synthetic=False)
    prediction, receipt = receipt_for(real, snapshot, synthetic=False)
    snapshot_path = save_immutable(snapshot, tmp_path / "snapshots")
    bad_cutoff = receipt.model_copy(update={"cutoff": NOW + timedelta(seconds=1)})
    with pytest.raises(ValueError, match="snapshot cutoff"):
        publish_prediction(prediction, bad_cutoff, tmp_path / "out", snapshot=snapshot_path)
    link = tmp_path / "snapshot-link.json"
    link.symlink_to(snapshot_path)
    with pytest.raises(ValueError, match="regular non-symlink"):
        publish_prediction(prediction, receipt, tmp_path / "out", snapshot=link)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(snapshot.model_dump_json().replace(real.event_id, "forged-event"))
    with pytest.raises(ValueError, match="content address"):
        publish_prediction(prediction, receipt, tmp_path / "out", snapshot=tampered)


def test_publication_requires_persisted_non_synthetic_snapshot(
    toy_event: Event, tmp_path: Path
) -> None:
    real = Event.model_validate({**toy_event.model_dump(), "is_synthetic": False})
    snapshot = make_snapshot(real.event_id, synthetic=False)
    prediction, receipt = receipt_for(real, snapshot, synthetic=False)
    with pytest.raises(ValueError, match="does not exist"):
        publish_prediction(
            prediction,
            receipt,
            tmp_path / "out",
            snapshot=tmp_path / "never-persisted.json",
        )

    synthetic_snapshot = make_snapshot(real.event_id, synthetic=True)
    with pytest.raises(ValidationError, match="synthetic states"):
        receipt_for(real, synthetic_snapshot, synthetic=False)


def test_receipt_integrity_and_rollback_safe_pair(
    toy_event: Event, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Event.model_validate({**toy_event.model_dump(), "is_synthetic": False})
    snapshot = make_snapshot(real.event_id, synthetic=False)
    prediction, receipt = receipt_for(real, snapshot, synthetic=False)
    snapshot_path = save_immutable(snapshot, tmp_path / "snapshots")
    output_dir = tmp_path / "out"
    bad = receipt.model_copy(update={"output_hash": "0" * 64})
    with pytest.raises(ValueError, match="output hash"):
        publish_prediction(prediction, bad, output_dir, snapshot=snapshot_path)

    original = os.symlink

    def fail_commit(source: Path, destination: Path, *, target_is_directory: bool = False) -> None:
        raise OSError("synthetic atomic-commit failure")

    monkeypatch.setattr(os, "symlink", fail_commit)
    with pytest.raises(OSError):
        publish_prediction(prediction, receipt, output_dir, snapshot=snapshot_path)
    assert list(output_dir.iterdir()) == []

    monkeypatch.setattr(os, "symlink", original)
    prediction_path, receipt_path = publish_prediction(
        prediction, receipt, output_dir, snapshot=snapshot_path
    )
    assert prediction_path.parent == receipt_path.parent == output_dir / receipt.receipt_id
    assert prediction_path.parent.is_symlink()


def test_publication_never_overwrites_concurrent_destination(
    toy_event: Event, tmp_path: Path
) -> None:
    real = Event.model_validate({**toy_event.model_dump(), "is_synthetic": False})
    snapshot = make_snapshot(real.event_id, synthetic=False)
    prediction, receipt = receipt_for(real, snapshot, synthetic=False)
    snapshot_path = save_immutable(snapshot, tmp_path / "snapshots")
    competing = tmp_path / receipt.receipt_id
    competing.mkdir()
    marker = competing / "competitor.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        publish_prediction(prediction, receipt, tmp_path, snapshot=snapshot_path)
    assert marker.read_text(encoding="utf-8") == "keep"

    race_directory = tmp_path / "race"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                publish_prediction,
                prediction,
                receipt,
                race_directory,
                snapshot=snapshot_path,
            )
            for _ in range(2)
        ]
    outcomes: list[tuple[Path, Path] | FileExistsError] = []
    for future in futures:
        try:
            outcomes.append(future.result())
        except FileExistsError as error:
            outcomes.append(error)
    assert sum(isinstance(outcome, tuple) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, FileExistsError) for outcome in outcomes) == 1
    assert (race_directory / receipt.receipt_id).is_symlink()
    assert len(list(race_directory.iterdir())) == 2
