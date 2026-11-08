"""Track B Graph API application."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import time
import json
import re
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from fastapi.responses import JSONResponse
from ..config import get_settings
from ..ids import new_ulid
from ..contracts_local.models import (DocSearchReq, DocSearchResp, ExtractReq, PredictMissingReq,
    RegisterDocReq, RuleCandidatesReq, RuleCandidatesResp, ScopeFrameReq, ScopeFrameResp, ScoreEdgesReq,
    ScoreEdgesResp, StandardReq, ValidityReq, Node, EdgeType, EdgeList, ValidityResult, DocMeta,
    JobStatus, ExtractResp, PredictMissingResp, StandardResp)
from ..graph.seed_loader import load_seed
from ..graph.standard import standard_of_review
from ..graph.validity import validity
from .deps import auth, default_as_of
from .errors import http_error_handler, validation_error_handler
from .state import state

app = FastAPI(title="Guarded Browsing Agent Graph API", version="1.0.0", dependencies=[Depends(auth)])
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, http_error_handler)


@app.on_event("startup")
async def startup() -> None:
    settings = get_settings()
    if not settings.service_token:
        raise RuntimeError("SERVICE_TOKEN is required")
    if not re.search(r"\(contact:\s*[^\s()]+@[^\s()]+\)", settings.agent_user_agent, re.I):
        raise RuntimeError("AGENT_USER_AGENT with a contact email is required")
    state.initialise()
    if not state.graph.nodes:
        load_seed(state.graph)


@app.middleware("http")
async def tracing(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or new_ulid()
    if not re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", request_id):
        request_id = new_ulid()
    run_id = request.headers.get("X-Run-Id") or f"run_{new_ulid()}"
    if not re.fullmatch(r"run_[0-9A-HJKMNP-TV-Z]{26}", run_id):
        return _trace_error(422, "VALIDATION_ERROR", "invalid X-Run-Id", request_id, f"run_{new_ulid()}")
    version = request.headers.get("X-Contract-Version")
    if version and version.split(".", 1)[0] != "1":
        return _trace_error(400, "CONTRACT_VERSION_MISMATCH", "contract major version mismatch", request_id, run_id)
    request.state.request_id = request_id
    request.state.run_id = run_id
    started = time.perf_counter()
    request_body = await request.body()
    async def replay_body():
        return {"type": "http.request", "body": request_body, "more_body": False}
    request._receive = replay_body
    try:
        response = await call_next(request)
    except Exception:
        response = Response(status_code=500)
        raise
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Run-Id"] = run_id
    response.headers["X-Contract-Version"] = "1.0.0"
    if request.url.path not in {"/health", "/openapi.json"}:
        request_hash = sha256(f"{request.method}\n{request.url.path}?{request.url.query}\n".encode() + request_body).hexdigest()
        state.trajectory(run_id).emit("graph_query", {"endpoint": request.url.path, "request_hash": request_hash,
            "status": response.status_code, "ms": int((time.perf_counter() - started) * 1000)})
    return response


@app.get("/health")
def health():
    return {"status": "ok", "service": "graph-api", "version": "0.1.0", "contract_version": "1.0.0"}


@app.get("/graph/v1/nodes/{node_id}", response_model=Node)
def node_get(node_id: str, as_of: date | None = None) -> Node:
    return _node_visible(node_id, default_as_of(as_of))


@app.get("/graph/v1/nodes/{node_id}/edges", response_model=EdgeList)
def node_edges(node_id: str, as_of: date | None = None, edge_type: EdgeType | None = None,
               direction: str = Query(default="both", pattern="^(in|out|both)$")):
    when = default_as_of(as_of)
    _node_visible(node_id, when)
    visible_nodes = {n.node_id for n in state.graph.visible_nodes(when, get_settings().as_of_leakage_mode)}
    values = [edge for edge in state.graph.edges_for(node_id, direction, edge_type)
              if edge.src in visible_nodes and edge.dst in visible_nodes
              and (get_settings().as_of_leakage_mode == "off" or edge.known_from <= when)]
    return {"items": values}


@app.post("/graph/v1/query/scope_frame", response_model=ScopeFrameResp)
def scope_frame(body: ScopeFrameReq):
    node = _node_visible(body.node_id, body.as_of)
    return ScopeFrameResp(node_id=node.node_id, frame=node.scope_frame)


@app.post("/graph/v1/query/validity", response_model=ValidityResult)
def query_validity(body: ValidityReq):
    node = _node_visible(body.node_id, body.as_of)
    edges = state.graph.visible_edges(body.as_of, get_settings().as_of_leakage_mode)
    return validity(node, edges, body.as_of)


@app.post("/graph/v1/query/standard_of_review", response_model=StandardResp)
def query_standard(body: StandardReq):
    return standard_of_review(state.graph, body.as_of, body.facts, get_settings().as_of_leakage_mode)


@app.post("/graph/v1/query/rule_candidates", response_model=RuleCandidatesResp)
def rule_candidates(body: RuleCandidatesReq):
    from ..index.hybrid import lexical_rank
    visible = [node for node in state.graph.visible_nodes(body.as_of, get_settings().as_of_leakage_mode)
               if node.node_type in body.node_types]
    visible = [node for node in visible if node.node_type not in {"Provision", "Holding"} or node.scope_frame is not None]
    texts = [f"{node.label} {node.props.get('proposition', '')} {node.props.get('section', '')}" for node in visible]
    ranked = lexical_rank(body.query, texts, limit=max(body.top_k * 2, 50))
    scores = {index: score for index, score in ranked}
    values = []
    for index, node in enumerate(visible):
        score = scores.get(index, 0.0)
        spans = []
        linked: list[tuple[float, object, str, str]] = []
        for doc_id, meta in state.documents.meta.items():
            if node.node_id not in meta.node_ids:
                continue
            if get_settings().as_of_leakage_mode == "strict" and (meta.doc_date is None or meta.doc_date > body.as_of):
                continue
            chunks = state.documents.chunks.get(doc_id, [])
            for chunk_index, chunk_score in lexical_rank(body.query, [chunk.text for chunk in chunks], limit=3):
                linked.append((chunk_score, chunks[chunk_index], doc_id, state.documents.text[doc_id]))
        if linked:
            linked.sort(key=lambda item: (-item[0], item[2], item[1].ordinal))
            score = max(score, linked[0][0])
            for _chunk_score, chunk, doc_id, doc_text in linked[:3]:
                end = min(chunk.end, chunk.start + 500)
                from ..contracts_local.models import Span
                spans.append(Span(doc_id=doc_id, start=chunk.start, end=end, quote=doc_text[chunk.start:end]))
        if score <= 0:
            continue
        if body.facts.get("transaction_type") and node.scope_frame and node.scope_frame.transaction_types:
            fact = body.facts["transaction_type"]
            fact_value = fact.value if hasattr(fact, "value") else fact.get("value")
            fact_status = fact.status if hasattr(fact, "status") else fact.get("status")
            if fact_status == "known" and fact_value in node.scope_frame.transaction_types:
                score += 0.05
        values.append({"node": node, "score": score, "spans": spans})
    values.sort(key=lambda item: (-item["score"], item["node"].node_id))
    return {"items": values[:body.top_k]}


@app.post("/graph/v1/search/documents", response_model=DocSearchResp)
def search_documents(body: DocSearchReq):
    settings = get_settings()
    items = state.documents.search(body.query, body.as_of, body.top_k, body.registry_entry_ids,
                                   body.doc_types, settings.as_of_leakage_mode == "strict")
    return {"items": items}


@app.get("/graph/v1/documents/{doc_id:path}/meta", response_model=DocMeta)
def document_meta(doc_id: str):
    meta = state.documents.meta.get(doc_id)
    if meta is None or (get_settings().as_of_leakage_mode == "strict" and
                        (meta.doc_date is None or meta.doc_date > default_as_of(None))):
        raise HTTPException(404, detail={"code": "DOC_NOT_FOUND", "message": "document not found"})
    return meta


@app.get("/graph/v1/documents/{doc_id:path}/text", response_class=PlainTextResponse)
def document_text(doc_id: str):
    text = state.documents.text.get(doc_id)
    meta = state.documents.meta.get(doc_id)
    if text is None or meta is None or (get_settings().as_of_leakage_mode == "strict" and
                                        (meta.doc_date is None or meta.doc_date > default_as_of(None))):
        raise HTTPException(404, detail={"code": "DOC_NOT_FOUND", "message": "document not found"})
    return text


@app.post("/graph/v1/documents/register", status_code=201, response_model=DocMeta)
def register_document(body: RegisterDocReq, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    cached = _idempotent_result(idempotency_key, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    try:
        result = state.documents.register(body.source)
        _store_idempotent(idempotency_key, body.model_dump(mode="json"), result.model_dump(mode="json"))
        return result
    except FileNotFoundError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc), "details": {"reason": "RAW_NOT_FOUND"}}) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc), "details": {"reason": str(exc)}}) from exc


@app.post("/graph/v1/extract/facts", status_code=202, response_model=ExtractResp)
async def extract_facts(body: ExtractReq, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    cached = _idempotent_result(idempotency_key, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    if len(body.doc_ids) > get_settings().extract_max_docs_per_job:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "too many documents"})
    missing_docs = [doc_id for doc_id in body.doc_ids if doc_id not in state.documents.meta]
    if missing_docs:
        raise HTTPException(404, detail={"code": "DOC_NOT_FOUND", "message": "one or more documents are unknown"})
    if get_settings().as_of_leakage_mode == "strict" and any(
        state.documents.meta[doc_id].doc_date is None or state.documents.meta[doc_id].doc_date > body.as_of
        for doc_id in body.doc_ids
    ):
        raise HTTPException(404, detail={"code": "DOC_NOT_FOUND", "message": "one or more documents are not known as of the requested date"})
    job_id = state.jobs.submit(body, request.state.run_id)
    result = {"job_id": job_id}
    _store_idempotent(idempotency_key, body.model_dump(mode="json"), result)
    return result


@app.get("/graph/v1/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str):
    job = state.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "JOB_NOT_FOUND", "message": "extraction job not found"})
    return job


@app.post("/graph/v1/gnn/score_edges", response_model=ScoreEdgesResp)
def score_edges(body: ScoreEdgesReq):
    scores = []
    graph_nodes = state.graph.visible_nodes(body.as_of, get_settings().as_of_leakage_mode)
    graph_edges = state.graph.visible_edges(body.as_of, get_settings().as_of_leakage_mode)
    for probe in body.edges:
        src, dst = _node_visible(probe.src, body.as_of), _node_visible(probe.dst, body.as_of)
        scores.append(state.scorer.score(src, dst, probe.edge_type, get_settings().gnn_flag_threshold,
                                         graph_nodes, graph_edges, body.as_of))
    return {"model_version": state.scorer.model_version, "scores": scores}


@app.post("/graph/v1/gnn/predict_missing", response_model=PredictMissingResp)
def predict_missing_route(body: PredictMissingReq):
    anchors = [_node_visible(node_id, body.as_of) for node_id in body.anchor_node_ids]
    if any(node.node_type not in {"Element", "Standard"} for node in anchors):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "anchor nodes must be Element or Standard"})
    candidates = [node for node in state.graph.visible_nodes(body.as_of, get_settings().as_of_leakage_mode)
                  if node.node_type in {"Case", "Holding"}]
    graph_nodes = state.graph.visible_nodes(body.as_of, get_settings().as_of_leakage_mode)
    graph_edges = state.graph.visible_edges(body.as_of, get_settings().as_of_leakage_mode)
    items = state.scorer.predict_missing(anchors, candidates, set(body.exclude_node_ids), body.top_k,
                                         get_settings().gnn_flag_threshold, graph_nodes, graph_edges,
                                         body.as_of)
    return {"model_version": state.scorer.model_version, "items": items}


@app.get("/graph/v1/registry")
def registry():
    return state.registry.public_json()


@app.get("/registry")
def registry_compat():
    return state.registry.public_json()


def _node_visible(node_id: str, as_of: date):
    node = state.graph.nodes.get(node_id)
    if node is None:
        raise HTTPException(404, detail={"code": "NODE_NOT_FOUND", "message": "graph node does not exist"})
    if get_settings().as_of_leakage_mode == "strict" and node.known_from > as_of:
        raise HTTPException(404, detail={"code": "NOT_KNOWN_AS_OF", "message": "node was not publicly known as of requested date"})
    return node


def _idempotent_result(key: str | None, request_payload: dict):
    if not key:
        return None
    import json
    request_hash = sha256(json.dumps(request_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    cached = state.idempotency.get(key)
    if cached is None and state.sessions is not None:
        from sqlalchemy import text as sql_text
        with state.sessions() as session:
            row = session.execute(sql_text("SELECT request_hash, response, created_at FROM idempotency WHERE key=:key AND created_at > now() - interval '24 hours'"), {"key": key}).mappings().first()
        if row is not None:
            cached = (row["request_hash"], row["created_at"].timestamp() + 86400, row["response"])
            state.idempotency[key] = cached
    if cached is None:
        return None
    old_hash, expiry, response = cached
    if expiry < time.time():
        state.idempotency.pop(key, None)
        return None
    if old_hash != request_hash:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Idempotency-Key was already used with a different request"})
    return response


def _store_idempotent(key: str | None, request_payload: dict, response_payload: object) -> None:
    if not key:
        return
    import json
    request_hash = sha256(json.dumps(request_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    state.idempotency[key] = (request_hash, time.time() + 86400, response_payload)
    if state.sessions is not None:
        from sqlalchemy import text as sql_text
        with state.sessions.begin() as session:
            session.execute(sql_text("INSERT INTO idempotency (key, request_hash, response) VALUES (:key,:request_hash,CAST(:response AS jsonb)) ON CONFLICT (key) DO UPDATE SET request_hash=EXCLUDED.request_hash, response=EXCLUDED.response, created_at=now() WHERE idempotency.created_at <= now() - interval '24 hours'"),
                {"key": key, "request_hash": request_hash, "response": json.dumps(response_payload, ensure_ascii=False)})


def _trace_error(status: int, code: str, message: str, request_id: str, run_id: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message,
        "details": {}, "request_id": request_id}}, headers={"X-Request-Id": request_id,
        "X-Run-Id": run_id, "X-Contract-Version": "1.0.0"})
