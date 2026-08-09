"""Immutable receipt persistence with integrity checks and rollback-safe publication."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from f1sim.data.snapshots import load_snapshot, validate_snapshot_integrity
from f1sim.schemas import CanonicalPrediction, PredictionReceipt


def prediction_bytes(prediction: CanonicalPrediction) -> bytes:
    return prediction.model_dump_json(indent=2).encode()


def prediction_hash(prediction: CanonicalPrediction) -> str:
    return hashlib.sha256(prediction_bytes(prediction)).hexdigest()


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
    if receipt.status != "complete":
        raise ValueError("only complete runs can be published")
    envelope_snapshot = prediction.baseline_input.snapshot
    if envelope_snapshot is None:
        raise ValueError("non-synthetic publication requires a snapshot")
    resolved_snapshot = load_snapshot(snapshot)
    validate_snapshot_integrity(resolved_snapshot)
    relationships = (
        (prediction.event_id, receipt.event_id, "event"),
        (prediction.model_id, receipt.model_id, "model"),
        (prediction.model_version, receipt.model_version, "model version"),
        (prediction.ruleset_id, receipt.ruleset_id, "ruleset"),
        (prediction.field_size, receipt.field_size, "field"),
        (prediction.input_hash, prediction.baseline_input.canonical_hash(), "envelope hash"),
        (prediction.input_hash, receipt.input_hash, "input hash"),
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
        (prediction_hash(prediction), receipt.output_hash, "output hash"),
    )
    for actual, expected, label in relationships:
        if actual != expected:
            raise ValueError(f"prediction and receipt {label} mismatch")

    directory.mkdir(parents=True, exist_ok=True)
    final_directory = directory / receipt.receipt_id
    if final_directory.exists():
        raise FileExistsError("refusing to overwrite published artifact bundle")

    bundle_directory = Path(
        tempfile.mkdtemp(dir=directory, prefix=f".bundle-{receipt.receipt_id}-")
    )
    try:
        bundle_prediction = bundle_directory / "prediction.json"
        bundle_receipt = bundle_directory / "receipt.json"
        for path, content in (
            (bundle_prediction, prediction_bytes(prediction)),
            (bundle_receipt, receipt.model_dump_json(indent=2).encode()),
        ):
            with path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        # The exclusive symlink creation is the single publication commit. It cannot
        # replace a competing file/directory/link, and its target bundle is already complete.
        os.symlink(bundle_directory.name, final_directory, target_is_directory=True)
        return final_directory / "prediction.json", final_directory / "receipt.json"
    except Exception:
        shutil.rmtree(bundle_directory, ignore_errors=True)
        raise
