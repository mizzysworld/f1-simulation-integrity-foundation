# Phase 0B.2 public requirements traceability

| Public invariant | Source | Behavioral evidence | Status |
|---|---|---|---|
| Strict dynamic event and entrant contracts | `src/f1sim/schemas/models.py` | `test_schemas.py`, `test_baselines.py` | Implemented |
| Separate physical, classification and regulatory axes | schemas and settlement modules | `test_schemas.py`, `test_settlement.py` | Implemented bounded contract |
| Cutoff-bound canonical snapshots | `src/f1sim/data/snapshots.py` | incomplete-visibility and content-address regressions in `test_snapshots.py` | Complete-first atomic publication |
| Future-data, symlink-race and tamper rejection | descriptor-based snapshot validation/loading | `test_snapshots.py` | Implemented |
| Three transparent deterministic baselines | `src/f1sim/models/baselines.py` | `test_baselines.py` | Implemented; not validated forecast models |
| Stable canonical input/output hashes | schemas and receipt modules | reordered-map baseline/receipt regression | Implemented |
| Coherent probability marginals and exclusive position columns | prediction schemas | schema/baseline adversarial regressions | Implemented |
| Synthetic identity cannot be published as real | schemas and receipt publication | `test_snapshots.py` | Implemented |
| Bounded deterministic settlement | `src/f1sim/settlement/core.py` | `test_settlement.py` | Implemented bounded subset |
| Unsupported or contradictory settlement evidence fails closed | settlement and public classification validators | crossing/timing and forged-output regressions | Implemented |
| Settlement evidence survives into public classification | classification schema and settlement core | equal-lap swap regression | Implemented |
| Content-bound receipt IDs and non-overwriting publication | receipt module | identity, mutation and concurrency regressions | Implemented |
| Read-only receipt bundles with tamper-evident loading | receipt module | post-publication mutation regression | Implemented within local trust boundary |
| Locked clean verification | `pyproject.toml`, `uv.lock`, CI | 51 tests plus Ruff, strict MyPy and publication scan | Implemented |

## Deliberately deferred

- probabilistic DNS and predictive retirement timing;
- generalized or multiple-penalty precedence;
- final model parameterization, calibration and promotion;
- historical walk-forward evaluation;
- live data-provider integration;
- production deployment and external validation.
