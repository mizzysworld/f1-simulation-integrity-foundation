"""Content-bound receipt persistence with atomic, read-only bundle publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

from pydantic import BaseModel

from f1sim.data.snapshots import load_snapshot, validate_snapshot_integrity
from f1sim.schemas import CanonicalPrediction, PredictionReceipt

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _canonical_bytes(value: BaseModel, *, exclude: set[str] | None = None) -> bytes:
    return json.dumps(
        value.model_dump(mode="json", exclude=exclude),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def prediction_bytes(prediction: CanonicalPrediction) -> bytes:
    return _canonical_bytes(prediction)


def prediction_hash(prediction: CanonicalPrediction) -> str:
    return hashlib.sha256(prediction_bytes(prediction)).hexdigest()


def receipt_id_for(receipt: PredictionReceipt) -> str:
    digest = hashlib.sha256(_canonical_bytes(receipt, exclude={"receipt_id"})).hexdigest()
    return f"receipt-{digest}"


def _validate_prediction_receipt(
    prediction: CanonicalPrediction, receipt: PredictionReceipt
) -> None:
    relationships = (
        (prediction.event_id, receipt.event_id, "event"),
        (prediction.model_id, receipt.model_id, "model"),
        (prediction.model_version, receipt.model_version, "model version"),
        (prediction.ruleset_id, receipt.ruleset_id, "ruleset"),
        (prediction.field_size, receipt.field_size, "field"),
        (prediction.input_hash, prediction.baseline_input.canonical_hash(), "envelope hash"),
        (prediction.input_hash, receipt.input_hash, "input hash"),
        (prediction_hash(prediction), receipt.output_hash, "output hash"),
    )
    for actual, expected, label in relationships:
        if actual != expected:
            raise ValueError(f"prediction and receipt {label} mismatch")
    if receipt.receipt_id != receipt_id_for(receipt):
        raise ValueError("receipt identity is not content-bound")


def _read_bundle_files(bundle: Path) -> tuple[bytes, bytes]:
    directory_descriptor = -1
    try:
        directory_descriptor = os.open(
            bundle,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise ValueError("published bundle target must be a regular directory")

        def read_regular(name: str) -> bytes:
            descriptor = -1
            try:
                descriptor = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_descriptor,
                )
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ValueError("published bundle members must be regular files")
                with os.fdopen(descriptor, "rb") as handle:
                    descriptor = -1
                    return handle.read()
            except OSError as error:
                raise ValueError("published bundle member failed no-follow validation") from error
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

        prediction = read_regular("prediction.json")
        receipt = read_regular("receipt.json")
        current = os.stat(bundle, follow_symlinks=False)
        if (
            not stat.S_ISDIR(current.st_mode)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ValueError("published bundle changed during validation")
        return prediction, receipt
    except OSError as error:
        raise ValueError("published bundle target failed no-follow validation") from error
    finally:
        if directory_descriptor >= 0:
            os.close(directory_descriptor)


def load_published_bundle(
    published_directory: Path,
) -> tuple[CanonicalPrediction, PredictionReceipt]:
    if not _SAFE_ID.fullmatch(published_directory.name):
        raise ValueError("published receipt path is not a safe identifier")
    try:
        published = published_directory.lstat()
        if not stat.S_ISLNK(published.st_mode):
            raise ValueError("published receipt must be an atomic bundle link")
        target = os.readlink(published_directory)
    except OSError as error:
        raise ValueError("published receipt link does not exist") from error
    if Path(target).name != target or not target.startswith(f".bundle-{published_directory.name}-"):
        raise ValueError("published receipt link target is invalid")
    prediction_data, receipt_data = _read_bundle_files(published_directory.parent / target)
    current = published_directory.lstat()
    if (
        not stat.S_ISLNK(current.st_mode)
        or (published.st_dev, published.st_ino) != (current.st_dev, current.st_ino)
        or os.readlink(published_directory) != target
    ):
        raise ValueError("published receipt link changed during validation")
    try:
        prediction = CanonicalPrediction.model_validate_json(prediction_data)
        receipt = PredictionReceipt.model_validate_json(receipt_data)
    except ValueError as error:
        raise ValueError("published bundle contains invalid canonical JSON") from error
    if receipt.receipt_id != published_directory.name:
        raise ValueError("receipt identity does not match its published path")
    _validate_prediction_receipt(prediction, receipt)
    return prediction, receipt


def publish_prediction(
    prediction: CanonicalPrediction,
    receipt: PredictionReceipt,
    directory: Path,
    *,
    snapshot: Path,
) -> tuple[Path, Path]:
    if receipt.synthetic != prediction.synthetic:
        raise ValueError("prediction and receipt synthetic mismatch")
    if prediction.baseline_input.event.is_synthetic:
        raise ValueError("embedded synthetic events cannot be published as real forecasts")
    if prediction.synthetic:
        raise ValueError("synthetic fixtures cannot be published as real forecasts")
    prediction = CanonicalPrediction.model_validate(prediction.model_dump())
    receipt = PredictionReceipt.model_validate(receipt.model_dump())
    if receipt.status != "complete":
        raise ValueError("only complete runs can be published")
    envelope_snapshot = prediction.baseline_input.snapshot
    if envelope_snapshot is None:
        raise ValueError("non-synthetic publication requires a snapshot")
    resolved_snapshot = load_snapshot(snapshot)
    validate_snapshot_integrity(resolved_snapshot)
    relationships = (
        (envelope_snapshot.snapshot_id, receipt.snapshot_id, "snapshot ID"),
        (envelope_snapshot.snapshot_hash, receipt.snapshot_hash, "snapshot hash"),
        (envelope_snapshot.cutoff, receipt.cutoff, "snapshot cutoff"),
        (envelope_snapshot.event_id, prediction.event_id, "snapshot event"),
        (resolved_snapshot.snapshot_id, envelope_snapshot.snapshot_id, "snapshot file ID"),
        (resolved_snapshot.snapshot_hash, envelope_snapshot.snapshot_hash, "snapshot file hash"),
        (resolved_snapshot.cutoff, envelope_snapshot.cutoff, "snapshot file cutoff"),
        (resolved_snapshot.event_id, envelope_snapshot.event_id, "snapshot file event"),
        (resolved_snapshot.synthetic, envelope_snapshot.synthetic, "snapshot file synthetic state"),
        (resolved_snapshot.synthetic, prediction.synthetic, "snapshot prediction synthetic state"),
    )
    for actual, expected, label in relationships:
        if actual != expected:
            raise ValueError(f"prediction and receipt {label} mismatch")
    _validate_prediction_receipt(prediction, receipt)

    directory.mkdir(parents=True, exist_ok=True)
    final_directory = directory / receipt.receipt_id
    bundle_directory = Path(
        tempfile.mkdtemp(dir=directory, prefix=f".bundle-{receipt.receipt_id}-")
    )
    committed = False
    try:
        bundle_prediction = bundle_directory / "prediction.json"
        bundle_receipt = bundle_directory / "receipt.json"
        for path, content in (
            (bundle_prediction, prediction_bytes(prediction)),
            (bundle_receipt, _canonical_bytes(receipt)),
        ):
            with path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            path.chmod(0o444)
        directory_descriptor = os.open(
            bundle_directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        bundle_directory.chmod(0o555)
        os.symlink(bundle_directory.name, final_directory, target_is_directory=True)
        committed = True
        return final_directory / "prediction.json", final_directory / "receipt.json"
    except FileExistsError:
        raise FileExistsError("refusing to overwrite published artifact bundle") from None
    finally:
        if not committed:
            bundle_directory.chmod(0o755)
            shutil.rmtree(bundle_directory, ignore_errors=True)
