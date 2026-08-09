# Security

## Supported scope

Security review applies to the exact public source commit, lockfile, CI run and any versioned release derived from them.

## Publication boundary

Runtime modules do not execute shell commands, evaluate dynamic code, open network connections, access credentials or ingest arbitrary external archives. Local publication is restricted to validated snapshot, prediction and receipt objects and refuses competing destinations.

## Reporting

Report security issues privately to the repository owner. Do not include live credentials, private datasets or personal information in public issues.
