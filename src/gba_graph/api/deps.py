"""Authentication and visibility dependencies."""
from datetime import date, datetime, timezone
from fastapi import Header, HTTPException, Request
from ..config import get_settings
from .state import state


def auth(request: Request, authorization: str | None = Header(default=None)) -> None:
    if request.url.path in {"/health", "/openapi.json"}:
        return
    token = get_settings().service_token
    if not token or authorization != f"Bearer {token}":
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "invalid bearer token"})


def get_node(node_id: str, as_of: date, request: Request):
    node = state.graph.nodes.get(node_id)
    if node is None:
        raise HTTPException(404, detail={"code": "NODE_NOT_FOUND", "message": "graph node does not exist"})
    mode = get_settings().as_of_leakage_mode
    if mode == "strict" and node.known_from > as_of:
        raise HTTPException(404, detail={"code": "NOT_KNOWN_AS_OF", "message": "node was not publicly known as of requested date"})
    return node


def default_as_of(value: date | None) -> date:
    return value or datetime.now(timezone.utc).date()
