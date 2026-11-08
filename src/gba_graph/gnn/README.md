# Track B legal GNN data and evaluation

## Role

The model is an advisory relation scorer and missing-authority ranker. It does not encode authoritative law or overrule deterministic source, quote, temporal, jurisdiction, or scope checks. The serving graph and training graph are separate. `seed/seed_graph.json` is illustrative and must not be used as training or evaluation gold.

The R-GCN uses no node-ID embeddings. `features.py` builds inductive node features from text, node type, jurisdiction, addressee class, transaction type, validity interval, as-of treatment-edge counts, audit status, and degree. New graph nodes can therefore be scored without retraining an ID vocabulary. `message_edges` masks both directions between a probed pair. Training candidates are restricted to audited or high-confidence `cites`/`addresses`/`applies_to` edges, with degree-matched negatives drawn from the training-time graph and known positives excluded.

## Training graph JSON

Pass a standalone export with this shape (each item follows the local Doc 00 Pydantic model):

```json
{
  "nodes": [{"node_id": "Case:example", "node_type": "Case", "label": "Example v. Example", "props": {}, "known_from": "2024-01-01", "origin": "human", "audited": true}],
  "edges": [{"edge_id": "...", "src": "Case:example", "dst": "Case:authority", "edge_type": "cites", "known_from": "2024-01-01", "origin": "human", "audited": true}]
}
```

The export must include stable provenance and legally meaningful `known_from`, `valid_from`, `valid_to`, and `scope_frame` values. Never infer an edge as gold solely because an LLM extracted it. The current trainer is a minimal R-GCN fitting path; before claiming benchmark performance, add repeated-seed evaluation, validation-only calibration/threshold selection, bootstrap confidence intervals, and trajectory-distribution recalibration. `evaluation.py` reports typed link metrics and tagged error miss/false-alarm/coverage counts for that evaluation layer.

## Failure benchmark protocol

Store each reviewed case with `failure_type`, `jurisdiction`, `as_of`, `query_or_claim`, `expected_flag`, `predicted_flag`, `covered`, `source_ids`, and reviewer provenance. Include fabricated or malformed citation, wrong caption/court, unsupported quote/holding, stale or superseded authority, wrong actor/entity scope, false premise, and missing relevant authority patterns. Pair each negative with valid controls. A missing graph node is `unverified/coverage gap`, never automatically `fabricated`.

Cross-jurisdiction papers and public challenge sets are useful for constructing failure patterns, but must not be merged into Delaware gold without domain review. Report per-failure-type recall/miss rate, false alarms on valid controls, source coverage, temporal split, sample size, and confidence interval. Use “observed benchmark miss rate” wording; do not claim immunity.

## Training invocation

After the separate graph export and gold review are ready:

```powershell
uv sync --extra gnn
uv run gba-graph train --model rgcn-v1 --dataset path/to/training_graph.json --validation-start YYYY-MM-DD --test-start YYYY-MM-DD
```

This writes model weights and metadata under `models/rgcn-v1`. Inspect and evaluate the artifact before selecting it with `GNN_ACTIVE_MODEL=rgcn-v1`. Do not use the test set for model, threshold, or calibration choices. The present implementation does not yet emit the full research report described above; that remains an explicit pre-integration deliverable.
