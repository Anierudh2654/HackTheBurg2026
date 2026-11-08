# Track B ingestion notes

Only explicit URL plans are accepted. Add reviewed records to `config/deals.yaml`, `config/statutes.yaml`, or `config/opinions.yaml`; do not crawl beyond those URLs. Live endpoints, robots policies, content types, and API fields have not been verified in this build. See `config/REGISTRY_NOTES.md`. The ingest client rejects URLs outside the selected registry entry, honors cached robots.txt, uses the configured honest user agent, and never falls back to a non-registry host.

The source adapter modules contain metadata parsing and allowlist helpers only. Cassette fixtures and the lawyer-approved source plan are still needed before validating live-site details. The `--live` CLI flag is deliberate, and production mode additionally refuses any entry whose terms remain unverified.
