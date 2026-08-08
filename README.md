# F1 Simulation Integrity Foundation

**Reproducibility and Publication-Integrity Infrastructure**

> **Publication status:** Evidence landing page. A public-safe source package, public CI, reproducibility documentation, and a versioned evidence release are being prepared. This repository does not yet contain the public source package.

F1 Simulation Integrity Foundation is a bounded simulation-integrity project developed in an F1 prediction context. It demonstrates transferable engineering for traceable baseline runs, cutoff-bound data handling, deterministic artifacts, and publication integrity without disguising the project’s original domain.

## Locally verified scope being prepared for publication

- Canonical typed inputs and strict prediction/settlement contracts
- Cutoff-bound, content-addressed source snapshots
- Three deterministic baselines
- Stable input and output hashes
- Structured run receipts
- Rollback-safe, non-overwriting artifact publication
- Fail-closed checks for future-data leakage, snapshot tampering, impossible settlement states, synthetic-result publication, receipt/output mismatch, and competing publication destinations

The current publication candidate passed locked dependency sync, Ruff, strict MyPy across 13 source files, Hypothesis-backed property tests, and 51 tests during isolated local verification. Those results are not yet independently reproducible from this repository; source, locked dependencies, CI, commands, and verification receipts will be added before the public reference release.

## Claim boundary

This project is a bounded Phase 0B simulation-integrity foundation. It is not presented as a complete generalized experiment platform, production prediction service, or evidence of live deployment, adoption, or external validation.

## Planned public release gates

- Public-safe fresh-history package
- Rights, secret, private-path, and dependency review
- Clean locked setup
- Ruff, strict MyPy, complete test suite, and public CI
- Reproducibility and limitations documentation
- Versioned verification receipt and release snapshot
