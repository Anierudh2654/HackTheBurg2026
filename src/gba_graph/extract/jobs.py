"""In-process async task queue for extraction jobs."""
from __future__ import annotations

import asyncio
import json
from ..ids import new_ulid
from ..contracts_local.models import ExtractReq, JobStatus, MatterFact
from .worker import extract_request
from sqlalchemy import text


class ExtractionJobs:
    def __init__(self):
        self.items: dict[str, JobStatus] = {}
        self.sessions = None

    def recover_running(self) -> None:
        if self.sessions is None:
            return
        with self.sessions.begin() as session:
            session.execute(text("UPDATE extraction_jobs SET status='failed', error='RESTART', updated_at=now() WHERE status IN ('queued','running')"))

    def submit(self, request: ExtractReq, run_id: str = "adhoc") -> str:
        job_id = f"job_{new_ulid()}"
        self.items[job_id] = JobStatus(job_id=job_id, status="queued")
        if self.sessions is not None:
            with self.sessions.begin() as session:
                session.execute(text("INSERT INTO extraction_jobs (job_id, request, status) VALUES (:job_id, CAST(:request AS jsonb), 'queued')"),
                    {"job_id": job_id, "request": request.model_dump_json()})
        asyncio.create_task(self._run(job_id, request, run_id))
        return job_id

    async def _run(self, job_id: str, request: ExtractReq, run_id: str) -> None:
        self.items[job_id] = JobStatus(job_id=job_id, status="running")
        self._persist_status(job_id, self.items[job_id])
        try:
            result = await asyncio.to_thread(extract_request, request, run_id)
            self.items[job_id] = JobStatus(job_id=job_id, status="done", result=result)
        except Exception as exc:
            self.items[job_id] = JobStatus(job_id=job_id, status="failed", error=str(exc))
        self._persist_status(job_id, self.items[job_id])

    def get(self, job_id: str) -> JobStatus | None:
        local = self.items.get(job_id)
        if local is not None or self.sessions is None:
            return local
        with self.sessions() as session:
            row = session.execute(text("SELECT status, result, error FROM extraction_jobs WHERE job_id=:job_id"), {"job_id": job_id}).mappings().first()
        if row is None:
            return None
        result = [MatterFact.model_validate(item) for item in row["result"]] if row["result"] else None
        return JobStatus(job_id=job_id, status=row["status"], result=result, error=row["error"])

    def _persist_status(self, job_id: str, status: JobStatus) -> None:
        if self.sessions is None:
            return
        result = [fact.model_dump(mode="json") for fact in status.result] if status.result else None
        with self.sessions.begin() as session:
            session.execute(text("UPDATE extraction_jobs SET status=:status, result=CAST(:result AS jsonb), error=:error, updated_at=now() WHERE job_id=:job_id"),
                {"job_id": job_id, "status": status.status, "result": json.dumps(result) if result is not None else None,
                 "error": status.error})
