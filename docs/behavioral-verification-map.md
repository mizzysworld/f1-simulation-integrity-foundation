# Behavioral verification map

The public suite contains exactly **51 collected tests**.

| Test module | Collected cases | Primary scope |
|---|---:|---|
| `tests/unit/test_baselines.py` | 15 | dynamic field sizes, three baselines, known-DNS handling, canonical parameter hashing, non-finite inputs |
| `tests/unit/test_schemas.py` | 6 | strict event/start/status schemas, finite values, scalar-to-physical and classification-to-regulatory probability coherence, JSON fixtures |
| `tests/unit/test_settlement.py` | 13 | threshold classification, DQ-inclusive `1..N` crossing and partial-known chronology, bounded penalties, DQ/DNS, forged-state rejection |
| `tests/unit/test_snapshots.py` | 17 | canonical snapshots, cutoff enforcement, tamper/symlink rejection, publisher/loader receipt parity, atomic publication |
| **Total** | **51** | Full Phase 0B.2 behavioral gate |

Additional non-pytest gates:

- Ruff lint/import policy;
- strict MyPy over 13 source/test files;
- fail-closed publication scan with a 7/7 adversarial self-test;
- wheel and source-distribution member inspection with an 11/11 adversarial self-test;
- Python 3.12, 3.13 and 3.14 CI matrix.
