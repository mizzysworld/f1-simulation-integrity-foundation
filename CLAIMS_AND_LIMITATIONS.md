# Claims and limitations

## Supported claims

This reference supports claims about:

- strict deterministic schemas;
- content-addressed cutoff snapshots;
- three transparent deterministic baselines;
- stable input/output hashes;
- structured run receipts;
- synthetic-result publication denial;
- complete-first, non-overwriting snapshot publication;
- content-derived receipt identities and read-only atomic bundle publication;
- tamper-evident bundle loading with publisher/loader relationship parity through the supplied API;
- bounded settlement integrity with DQ-inclusive group-local `1..N` crossing order, partial-known elapsed chronology and fail-closed unsupported states;
- a locked, reproducible 51-test verification gate.

## Explicit non-claims

It does not provide or prove:

- a production F1 prediction service;
- live timing, telemetry or official-data ingestion;
- predictive accuracy or calibration;
- a validated or promoted forecast model;
- probabilistic DNS or retirement timing;
- generalized penalty precedence;
- historical walk-forward evaluation;
- betting advice, wagering integration or financial outcomes;
- deployment, users, adoption or third-party validation;
- FIA endorsement, affiliation or official rule certification.

The included rule-shaped fixtures are synthetic. No FIA document is distributed in this repository.

Read-only file modes are a local integrity guard, not protection against a filesystem owner or administrator who can deliberately change permissions. Integrity-sensitive consumers must use the supplied loaders, which revalidate content addresses, receipt identity, canonical hashes, regular-file types and publication relationships.
