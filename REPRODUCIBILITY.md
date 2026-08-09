# Reproducibility

## Supported runtimes

- Python 3.12
- Python 3.13
- Python 3.14

## Clean verification

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run mypy src tests
uv run pytest -q
uv run python scripts/publication_scan.py
uv build
```

Expected behavioral result:

```text
51 passed
```

## Determinism boundary

Determinism applies when event, snapshot, baseline parameters, source code, lockfile and runtime inputs are fixed. The baseline input envelope is canonical JSON and SHA-256-addressed. Snapshot identity includes event, cutoff, creation time, synthetic state and records.

The project does not claim byte-identical wheel or source-distribution archives across different build-tool versions or operating systems. The build backend is pinned and CI records the exact source commit and runtime matrix.

## Clean-room rule

Verification must use synthetic fixtures and temporary output directories. Tests must not write into the source tree or depend on private files, credentials, network access, FIA documents or machine-specific paths.
