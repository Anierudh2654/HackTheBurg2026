"""Command-line entry point for Graph API operations."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from .config import get_settings
from .graph.seed_loader import export_seed_yaml, load_seed
from .graph.store import GraphStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="gba-graph")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    sub.add_parser("migrate")
    sub.add_parser("seed")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--entry", required=True)
    ingest.add_argument("--plan", type=Path, required=True)
    ingest.add_argument("--live", action="store_true")
    train = sub.add_parser("train")
    train.add_argument("--model", default="baseline-text-v0")
    train.add_argument("--dataset", type=Path)
    train.add_argument("--cutoff", type=__import__("datetime").date.fromisoformat)
    train.add_argument("--validation-start", type=__import__("datetime").date.fromisoformat)
    train.add_argument("--test-start", type=__import__("datetime").date.fromisoformat)
    audit = sub.add_parser("audit")
    audit.add_argument("--gold", type=Path, required=True)
    extract_eval = sub.add_parser("extract-eval")
    extract_eval.add_argument("--gold", type=Path, required=True)
    extract_eval.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("gba_graph.api.main:app", host="0.0.0.0", port=8101)
    elif args.command == "migrate":
        subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], check=True)
    elif args.command == "seed":
        graph = load_seed(GraphStore())
        payload = {"nodes": [n.model_dump(mode="json") for n in graph.nodes.values()],
                   "edges": [e.model_dump(mode="json") for e in graph.edges.values()]}
        output = Path("seed/seed_graph.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        export_seed_yaml(graph)
        print(f"wrote {len(graph.nodes)} nodes and {len(graph.edges)} edges to {output}")
    elif args.command == "ingest":
        if not args.live:
            parser.error("ingestion requires explicit --live; source terms and registry must be reviewed first")
        asyncio.run(_ingest(args.entry, args.plan))
    elif args.command == "train":
        if args.model == "baseline-text-v0":
            print("baseline-text-v0 is always available and requires no training")
        elif args.model == "text-only-v1" and args.dataset and args.cutoff:
            from .gnn.train import train_text_model
            dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
            metadata = train_text_model(dataset["pairs"], dataset["labels"], args.cutoff, Path("models/text-only-v1"))
            print(json.dumps(metadata, indent=2))
        elif args.model == "rgcn-v1" and args.dataset and args.validation_start and args.test_start:
            from .contracts_local.models import Edge, Node
            from .gnn.train import train_rgcn_graph
            payload = json.loads(args.dataset.read_text(encoding="utf-8"))
            nodes = [Node.model_validate(item) for item in payload["nodes"]]
            edges = [Edge.model_validate(item) for item in payload["edges"]]
            metadata = train_rgcn_graph(nodes, edges, args.validation_start, args.test_start,
                                        Path("models/rgcn-v1"))
            print(json.dumps(metadata, indent=2))
        else:
            parser.error("text-only-v1 needs --dataset and --cutoff; rgcn-v1 needs a separate nodes/edges graph JSON and --validation-start/--test-start")
    elif args.command == "audit":
        _audit(args.gold)
    elif args.command == "extract-eval":
        _extract_eval(args.gold, args.predictions)


async def _ingest(entry: str, plan_path: Path) -> None:
    from .api.state import state
    from .ingest.bulk import BulkIngestor, PoliteHttp
    state.initialise()
    settings = get_settings()
    http = PoliteHttp(settings.ingest_user_agent)
    try:
        result = await BulkIngestor(state.registry, state.blob, state.documents, http).ingest_plan(entry, plan_path)
        print(json.dumps(result, default=str, indent=2))
    finally:
        await http.close()


def _audit(gold_path: Path) -> None:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    items = gold if isinstance(gold, list) else gold.get("items", [])
    if len(items) < 50:
        raise SystemExit(f"audit requires at least 50 reviewed items; found {len(items)}")
    report = {"items_reviewed": len(items), "status": "needs-human-scoring",
              "note": "No accuracy score is emitted until each sampled node, edge, and frame is adjudicated."}
    Path("reports").mkdir(exist_ok=True)
    Path("reports/graph_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path("reports/graph_audit.md").write_text(f"# Graph audit\n\n- Items reviewed: {len(items)}\n- Status: needs human scoring\n", encoding="utf-8")


def _extract_eval(gold_path: Path, prediction_path: Path) -> None:
    gold_payload = json.loads(gold_path.read_text(encoding="utf-8"))
    predicted_payload = json.loads(prediction_path.read_text(encoding="utf-8"))
    gold = gold_payload if isinstance(gold_payload, list) else gold_payload.get("facts", [])
    predicted = predicted_payload if isinstance(predicted_payload, list) else predicted_payload.get("facts", [])

    def identity(item: dict) -> tuple[str, str]:
        return item["key"], json.dumps(item.get("value"), sort_keys=True, ensure_ascii=False)

    gold_ids = {identity(item) for item in gold if item.get("status", "known") == "known"}
    pred_known = [item for item in predicted if item.get("status") == "known"]
    pred_ids = {identity(item) for item in pred_known}
    true_positive = len(gold_ids & pred_ids)
    precision = true_positive / len(pred_ids) if pred_ids else 0.0
    recall = true_positive / len(gold_ids) if gold_ids else 0.0
    gold_spans = {(identity(item), span["doc_id"], span["start"], span["end"])
                  for item in gold for span in item.get("spans", [])}
    predicted_spans = {(identity(item), span["doc_id"], span["start"], span["end"])
                       for item in pred_known for span in item.get("spans", [])}
    span_exactness = len(gold_spans & predicted_spans) / len(predicted_spans) if predicted_spans else 0.0
    report = {"precision": precision, "recall": recall, "span_exactness": span_exactness,
              "known_gold_facts": len(gold_ids), "known_predictions": len(pred_ids)}
    Path("reports").mkdir(exist_ok=True)
    Path("reports/extract_eval.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path("reports/extract_eval.md").write_text("# Fact extraction evaluation\n\n" + "\n".join(
        f"- {key}: {value}" for key, value in report.items()) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
