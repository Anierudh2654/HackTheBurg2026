"""Polite, explicit-URL bulk ingestion guarded by the source registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio
from pathlib import Path
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
import yaml
from ..config import get_settings
from ..contracts_local.models import SourceRecord
from ..ids import new_ulid
from ..registry import Registry
from ..storage import BlobStore, document_id
from ..trajectory import TrajectoryWriter


class IngestRefused(RuntimeError):
    pass


@dataclass
class TokenBucket:
    rate: float
    capacity: int
    tokens: float = 0.0
    updated: float = field(default_factory=time.monotonic)

    async def acquire(self) -> None:
        if self.capacity <= 0 or self.rate <= 0:
            raise IngestRefused("SOURCE_DISABLED")
        now = time.monotonic()
        self.tokens = min(float(self.capacity), self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < 1:
            await asyncio.sleep((1 - self.tokens) / self.rate)
            self.tokens = 0
        else:
            self.tokens -= 1


class PoliteHttp:
    def __init__(self, user_agent: str, timeout: float = 30.0):
        if not user_agent or "configure-a-real-email" in user_agent:
            raise ValueError("INGEST_USER_AGENT with a real contact email is required")
        self.user_agent = user_agent
        self.timeout = timeout
        self._robots: dict[str, tuple[float, RobotFileParser]] = {}
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                                         headers={"User-Agent": user_agent, "Accept": "*/*"})

    async def allowed_by_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        cached = self._robots.get(origin)
        if cached and time.time() - cached[0] < 86400:
            return cached[1].can_fetch(self.user_agent, url)
        response = await self._client.get(origin + "/robots.txt")
        if response.status_code == 404:
            content = ""
        elif response.status_code >= 400:
            return False
        else:
            content = response.text
        parser = RobotFileParser()
        parser.set_url(origin + "/robots.txt")
        parser.parse(content.splitlines())
        self._robots[origin] = (time.time(), parser)
        return parser.can_fetch(self.user_agent, url)

    async def get(self, url: str) -> httpx.Response:
        return await self._client.get(url)

    async def close(self) -> None:
        await self._client.aclose()


class BulkIngestor:
    def __init__(self, registry: Registry, blob: BlobStore, documents, http: PoliteHttp):
        self.registry, self.blob, self.documents, self.http = registry, blob, documents, http
        self.buckets: dict[str, TokenBucket] = {}
        self.semaphores: dict[str, asyncio.Semaphore] = {}
        self.run_id = f"run_{new_ulid()}"

    async def ingest_url(self, entry_id: str, url: str, expected_doc_type: str,
                         version_label: str | None = None) -> dict:
        entry = self.registry.require_url(entry_id, url)  # URL rejection always precedes network access.
        limit = int(entry.data["rate_limit"]["max_concurrent"])
        semaphore = self.semaphores.setdefault(entry_id, asyncio.Semaphore(max(1, limit)))
        async with semaphore:
            return await self._ingest_url(entry_id, url, expected_doc_type, version_label, entry)

    async def _ingest_url(self, entry_id: str, url: str, expected_doc_type: str,
                          version_label: str | None, entry) -> dict:
        settings = get_settings()
        trajectory = TrajectoryWriter(settings.trajectory_dir, self.run_id)
        data = entry.data
        if settings.gba_env == "prod" and not data.get("terms_verified", False):
            raise IngestRefused("TERMS_UNVERIFIED")
        if expected_doc_type not in data.get("doc_types", []):
            raise IngestRefused("DOC_TYPE_NOT_IN_REGISTRY")
        if entry_id not in self.buckets:
            rate = float(data["rate_limit"]["requests_per_second"])
            self.buckets[entry_id] = TokenBucket(rate, int(data["rate_limit"]["burst"]), tokens=float(data["rate_limit"]["burst"]))
        bucket = self.buckets[entry_id]
        if data.get("robots_respect") and not await self.http.allowed_by_robots(url):
            trajectory.emit("block", {"url": url, "kind": "robots_disallowed", "attempt": 1, "action_taken": "mark_unretrievable"})
            raise IngestRefused("ROBOTS_DISALLOWED")
        source_id = f"src_{new_ulid()}"
        response = None
        for attempt in range(3):
            await bucket.acquire()
            try:
                response = await self.http.get(url)
            except httpx.TimeoutException:
                trajectory.emit("fetch", {"url": url, "registry_entry_id": entry_id, "status": "timeout",
                    "source_id": source_id, "bytes": 0, "from_cache": False})
                trajectory.emit("block", {"url": url, "kind": "timeout", "attempt": attempt + 1,
                    "action_taken": "mark_unretrievable" if attempt == 2 else "retry"})
                if attempt == 2:
                    raise IngestRefused("TIMEOUT")
                await asyncio.sleep(2 ** attempt)
                continue
            trajectory.emit("fetch", {"url": url, "registry_entry_id": entry_id,
                "status": response.status_code, "source_id": source_id, "bytes": len(response.content), "from_cache": False})
            if response.status_code in {403, 429}:
                trajectory.emit("block", {"url": url, "kind": f"http_{response.status_code}",
                    "attempt": attempt + 1, "action_taken": "retry" if attempt < 2 and response.status_code == 429 else "mark_unretrievable"})
                if attempt < 2 and response.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise IngestRefused(f"HTTP_{response.status_code}")
            if response.status_code >= 300:
                raise IngestRefused(f"HTTP_{response.status_code}")
            break
        if response is None:
            raise IngestRefused("FETCH_FAILED")
        content = response.content
        content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        text_sample = content[:10000].decode("utf-8", errors="ignore").casefold()
        if any(marker in text_sample for marker in ("captcha", "verify you are human")):
            trajectory.emit("block", {"url": url, "kind": "captcha", "attempt": 1, "action_taken": "mark_unretrievable"})
            raise IngestRefused("BLOCK_PAGE")
        if "sign in to continue" in text_sample or "log in to continue" in text_sample:
            trajectory.emit("block", {"url": url, "kind": "login_wall", "attempt": 1, "action_taken": "mark_unretrievable"})
            raise IngestRefused("BLOCK_PAGE")
        expects_pdf = urlparse(url).path.casefold().endswith(".pdf")
        if expects_pdf and content_type == "text/html" and len(content) < 20_000:
            trajectory.emit("block", {"url": url, "kind": "silent_content_change", "attempt": 1, "action_taken": "mark_unretrievable"})
            raise IngestRefused("SILENT_CONTENT_CHANGE")
        if expected_doc_type in {"opinion", "statute", "bill", "session_law"} and content_type == "text/html" and len(content) < 512:
            trajectory.emit("block", {"url": url, "kind": "silent_content_change", "attempt": 1, "action_taken": "mark_unretrievable"})
            raise IngestRefused("SILENT_CONTENT_CHANGE")
        doc_id = document_id(content)
        self.blob.put("raw/" + doc_id.removeprefix("sha256:"), content, content_type)
        source = SourceRecord(source_id=source_id, url=url, registry_entry_id=entry_id,
            retrieved_at=datetime.now(timezone.utc), session_id=None, doc_id=doc_id,
            media_type=content_type, byte_length=len(content), http_status=response.status_code,
            fetch_method="api" if data["access"] == "api" else "bulk",
            retrieved_by=f"track_b.bulk.{entry_id}", expected_doc_type=expected_doc_type,
            version_label=version_label)
        meta = self.documents.register(source)
        return {"doc_id": doc_id, "source_id": source.source_id, "meta": meta}

    async def ingest_plan(self, entry_id: str, plan_path: Path) -> dict:
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        items = plan if isinstance(plan, list) else plan.get("items", [])
        result = {"entry_id": entry_id, "fetched": [], "failed": [], "skipped": []}
        for item in items:
            try:
                result["fetched"].append(await self.ingest_url(entry_id, item["url"], item["doc_type"], item.get("version_label")))
            except Exception as exc:
                result["failed"].append({"url": item.get("url"), "error": str(exc)})
        return result
