# Track B decisions

| Date (UTC) | Decision | Reason |
|---|---|---|
| 2026-11-07 | Build the Track B repository contents at this project root; defer package imports to `contracts_local` until `gba_contracts` is published. | The supplied folder contains the specifications only and the request selects LLD 002. |
| 2026-11-07 | Use a deterministic local graph repository for the development/default mode, with a PostgreSQL repository boundary and migration for deployment. | Keeps the graph API usable before the integration database is provisioned. |
| 2026-11-07 | Treat seeded legal propositions and dates as illustrative and unaudited. | Doc 00 and Doc 02 require lawyer review before legal reliance. |
| 2026-11-07 | Keep the embedding and LLM integrations lazy and fail closed when live assets/configuration are absent; use lexical retrieval and replay-only extraction in offline development. | Avoids implicit network access and preserves deterministic local operation. |
| 2026-11-07 | Generate ULID-formatted IDs with a local implementation instead of adding a runtime dependency. | Preserves the contract format while keeping Track B's development install self-contained. |
| 2026-11-07 | No canonical shared fixture package or integration README was supplied; use Doc 00 scenario IDs and record the local seed as a candidate that must be reconciled with `gba_contracts/fixtures/seed_graph.json`. | Avoid asserting byte-level fixture compatibility without the package. |
| 2026-11-07 | Keep the audited serving graph separate from an explicit training graph export; use inductive text, scope, jurisdiction, time, and graph-context features without learned node-ID embeddings. | Newly browsed nodes must be scoreable; a tiny seed graph must not be treated as training data. |
| 2026-11-07 | Treat the GNN as advisory ranking/triage for typed legal relations; source existence, quotation support, temporal validity, jurisdiction, and scope remain deterministic/evidence-backed gates. | Prior legal hallucination benchmarks show retrieval and citation existence do not establish claim support or applicability. |
| 2026-11-07 | Map opinion-to-elements only through reviewer-labelled `addresses`/`applies_to` relations; citation edges are structural pretraining and are not the authority-recall gold label. | Prevents a mismatch between citation prediction and the agent's missing-authority task. |

