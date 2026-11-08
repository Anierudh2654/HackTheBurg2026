# Track B · Corpus, graph, retrieval, extraction

This repository implements the Track B service (`graph-api`, port 8101) described in `02_Track_B_LLD_Corpus_Graph_Retrieval_GNN_Extraction.md`. It exposes the Graph API under `/graph/v1`, keeps all outbound ingestion restricted to the source registry, and marks the seeded legal content as illustrative pending lawyer review.

## Local development

Python 3.12 and `uv` are expected. Configure `SERVICE_TOKEN`, `AGENT_USER_AGENT` with a real contact email, `REGISTRY_PATH`, `BLOB_URL`, and `DATABASE_URL`. Local PostgreSQL/pgvector and MinIO are described in `docker/compose.dev.yml`.

```powershell
uv sync --extra dev
Copy-Item .env.example .env
# Edit .env: set SERVICE_TOKEN and an honest AGENT_USER_AGENT with your contact email.
$env:SERVICE_TOKEN = 'local-development-token'
$env:AGENT_USER_AGENT = 'GuardedLegalAgent/1.0 (contact: your-real-email@example.org)'
docker compose -f docker/compose.dev.yml up -d
uv run gba-graph migrate
uv run gba-graph seed
uv run gba-graph serve
```

When `DATABASE_URL` is empty, the graph and corpus use local in-memory repositories; configure PostgreSQL to persist them. Sentence-transformer retrieval runs only when the configured embedding model is already available in the local model cache. `GBA_ENV=prod` requires source terms verification before bulk fetches. No live source plans or legal gold labels are included.

## Modules

- `graph/`: deterministic graph store, point-in-time visibility, validity, scope and standard-of-review engine.
- `ingest/`, `index/`: registry-constrained bulk fetch, canonical text, chunking and hybrid retrieval.
- `extract/`: asynchronous extraction pipeline; live model calls require a configured `LLMClient`.
- `gnn/`: inductive feature builder, temporal and degree-matched graph training utilities, R-GCN serving, calibration, and failure-type evaluation helpers. See `src/gba_graph/gnn/README.md`.
- `api/`: authenticated FastAPI Graph API.

See `config/REGISTRY_NOTES.md`, `DECISIONS.md`, and `QUESTIONS.md` before connecting live sources or relying on legal outputs.

The GNN trainer requires an external, dated training graph and only fits audited/high-confidence `cites`, `addresses`, and `applies_to` relations. The current model utilities do not emit a complete evaluation pack or establish legal reliability; keep the baseline active until the separately reviewed Delaware benchmark passes predeclared comparisons.

