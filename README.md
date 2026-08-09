# F1 Simulation Integrity Foundation

**Deterministic simulation-integrity and publication-evidence reference**

> **Status:** public Phase 0B.2 reference candidate. The branch contains the bounded source, synthetic fixtures, locked dependencies, public CI, reproducibility instructions and fail-closed publication checks required for independent review.

This project demonstrates transferable engineering for traceable baseline runs, cutoff-bound data handling, deterministic artifacts and publication integrity in an F1 prediction context.

## What this reference demonstrates

- Strict typed event, entrant, ruleset, prediction, settlement and receipt contracts.
- Cutoff-bound, content-addressed snapshots with canonical JSON identity.
- Rejection of future-leaking records, non-finite values, unsupported objects, symlinks and tampered snapshot files.
- Three transparent deterministic baselines: equal strength, grid only and team-priority-then-grid.
- Stable canonical input and prediction hashes.
- Synthetic identity bound from event through snapshot, prediction and receipt.
- Synthetic-result publication rejected even when caller-controlled flags are forged.
- Receipt IDs restricted to safe path components.
- Atomic non-overwriting prediction/receipt bundle publication.
- Fail-closed settlement for unsupported evidence, impossible classifications and out-of-scope penalty combinations.

## Verify

Requires Python `3.12`, `3.13` or `3.14` and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run mypy src tests
uv run pytest -q
uv run python scripts/publication_scan.py
uv build
```

The behavioral suite contains **51 tests**. CI runs the complete gate on Python 3.12, 3.13 and 3.14 from the locked dependency graph.

See [Reproducibility](REPRODUCIBILITY.md), [requirements traceability](docs/requirements-traceability.md), [behavioral verification](docs/behavioral-verification-map.md), and [claims and limitations](CLAIMS_AND_LIMITATIONS.md).

## Boundary

This is a bounded synthetic reference, not a production prediction service, generalized experiment platform, validated forecasting model, betting system, live data integration or evidence of deployment, adoption, or external validation.

No FIA documents, internal strategy documents, credentials, private paths, generated office files, historical datasets or private implementation history are included.

## Rights

`UNLICENSED` — all rights reserved. No permission to copy, modify, distribute or use is granted except by written authorization from the rights holder.
