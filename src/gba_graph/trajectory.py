"""Append-only hash-chained Track B trajectory events."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import Lock
from .ids import new_ulid


def canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _ensure_secret_free(value) -> None:
    secret_name = re.compile(r"(?:api[_-]?key|access[_-]?token|authorization|password|secret|cookie)", re.I)
    secret_values = [os.getenv(name, "") for name in ("SERVICE_TOKEN", "LLM_API_KEY", "COURTLISTENER_TOKEN", "BLOB_S3_SECRET")]
    secret_values = [secret for secret in secret_values if len(secret) >= 8]
    if isinstance(value, dict):
        for key, item in value.items():
            if secret_name.search(str(key)):
                raise ValueError("trajectory payload may not contain secret fields")
            _ensure_secret_free(item)
    elif isinstance(value, list):
        for item in value:
            _ensure_secret_free(item)
    elif isinstance(value, str):
        if any(secret in value for secret in secret_values) or re.search(r"[?&](?:api[_-]?key|access[_-]?token|token|password)=", value, re.I):
            raise ValueError("trajectory payload may not contain secrets")


class TrajectoryWriter:
    _locks: dict[str, Lock] = {}

    def __init__(self, root: Path, run_id: str):
        if run_id != "adhoc" and not re.fullmatch(r"run_[0-9A-HJKMNP-TV-Z]{26}", run_id):
            raise ValueError("invalid run id")
        self.path = root / run_id / "graph-api.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self._locks.setdefault(str(self.path.resolve()), Lock())

    def emit(self, event_type: str, payload: dict, *, matter_id: str | None = None) -> None:
        _ensure_secret_free(payload)
        with self.lock:
            previous = "0" * 64
            seq = 1
            if self.path.exists():
                with self.path.open("rb") as stream:
                    for line in stream:
                        if line.strip():
                            last = json.loads(line)
                            previous = last["event_hash"]
                            seq = int(last["seq"]) + 1
            body = {"event_id": f"evt_{new_ulid()}", "run_id": self.path.parent.name,
                    "matter_id": matter_id, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "seq": seq, "component": "graph", "type": event_type, "payload": payload,
                    "parent_event_id": None, "session_id": None, "prev_hash": previous}
            body["event_hash"] = sha256(canonical_json(body).encode("utf-8")).hexdigest()
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical_json(body) + "\n")
                stream.flush()


def verify_chain(path: Path) -> int | None:
    previous = "0" * 64
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            event = json.loads(line)
            expected_prev = event.pop("event_hash")
            if event.get("prev_hash") != previous or sha256(canonical_json(event).encode("utf-8")).hexdigest() != expected_prev:
                return number
            previous = expected_prev
    return None
