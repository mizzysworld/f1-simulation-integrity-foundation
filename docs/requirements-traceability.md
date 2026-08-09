# Phase 0B.2 public requirements traceability

| Public invariant | Source | Behavioral evidence | Status |
|---|---|---|---|
| Strict dynamic event and entrant contracts | `src/f1sim/schemas/models.py` | `test_schemas.py`, `test_baselines.py` | Implemented |
| Separate physical, classification and regulatory axes | schemas and settlement modules | `test_schemas.py`, `test_settlement.py` | Implemented bounded contract |
| Cutoff-bound canonical snapshots | `src/f1sim/data/snapshots.py` | `test_snapshots.py` | Implemented |
| Future-data and tamper rejection | snapshot validation/loading | `test_snapshots.py` | Implemented |
| Three transparent deterministic baselines | `src/f1sim/models/baselines.py` | `test_baselines.py` | Implemented; not validated forecast models |
| Stable canonical input/output hashes | schemas and receipt modules | baseline/snapshot tests | Implemented |
| Synthetic identity cannot be published as real | schemas and receipt publication | `test_snapshots.py` | Implemented |
| Bounded deterministic settlement | `src/f1sim/settlement/core.py` | `test_settlement.py` | Implemented bounded subset |
| Unsupported settlement evidence fails closed | settlement and public classification validators | `test_settlement.py` | Implemented |
| Safe receipt IDs and non-overwriting publication | schemas and receipt modules | `test_snapshots.py` | Implemented |
| Locked clean verification | `pyproject.toml`, `uv.lock`, CI | 51 tests plus Ruff, strict MyPy and publication scan | Implemented |

## Deliberately deferred

- probabilistic DNS and predictive retirement timing;
- generalized or multiple-penalty precedence;
- final model parameterization, calibration and promotion;
- historical walk-forward evaluation;
- live data-provider integration;
- production deployment and external validation.
