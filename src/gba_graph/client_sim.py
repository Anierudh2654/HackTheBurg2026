"""Development client that exercises the Track B API as Track A would."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import httpx
from .config import get_settings
from .contracts_local.models import (DocMeta, DocSearchReq, DocSearchResp, ExtractReq, JobStatus,
    RegisterDocReq, RuleCandidatesReq, RuleCandidatesResp, ScopeFrameReq, ScopeFrameResp,
    ScoreEdgesReq, ScoreEdgesResp, StandardReq, StandardResp, ValidityReq, ValidityResult, SourceRecord)
from .ids import new_ulid
from .storage import BlobStore, document_id


class GraphClientSim:
    def __init__(self, base_url: str | None = None, service_token: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.graph_api_url).rstrip("/")
        self.service_token = service_token or settings.service_token
        self.client = httpx.Client(timeout=30.0)

    def headers(self, run_id: str = "adhoc", *, matter_id: str | None = None) -> dict[str, str]:
        if run_id == "adhoc":
            run_id = f"run_{new_ulid()}"
        values = {"Authorization": f"Bearer {self.service_token}", "X-Request-Id": new_ulid(),
                  "X-Run-Id": run_id, "X-Contract-Version": "1.0.0"}
        if matter_id:
            values["X-Matter-Id"] = matter_id
        return values

    def register_document(self, raw: bytes, *, url: str, registry_entry_id: str,
                          media_type: str, expected_doc_type: str, version_label: str | None = None,
                          run_id: str = "adhoc") -> DocMeta:
        doc_id = document_id(raw)
        BlobStore(get_settings().blob_url, get_settings().blob_s3_key, get_settings().blob_s3_secret).put(
            "raw/" + doc_id.removeprefix("sha256:"), raw, media_type)
        source = SourceRecord(source_id=f"src_{new_ulid()}", url=url, registry_entry_id=registry_entry_id,
            retrieved_at=datetime.now(timezone.utc), session_id=None, doc_id=doc_id, media_type=media_type,
            byte_length=len(raw), fetch_method="human", retrieved_by="track_b.client_sim",
            expected_doc_type=expected_doc_type, version_label=version_label)
        response = self.client.post(self.base_url + "/graph/v1/documents/register",
            json=RegisterDocReq(source=source).model_dump(mode="json"), headers=self.headers(run_id))
        response.raise_for_status()
        return DocMeta.model_validate(response.json())

    def post(self, path: str, model: Any, response_model: type, *, run_id: str = "adhoc"):
        response = self.client.post(self.base_url + path, json=model.model_dump(mode="json"), headers=self.headers(run_id))
        response.raise_for_status()
        payload = response.json()
        return response_model.model_validate(payload)

    def scope_frame(self, node_id: str, as_of, *, run_id: str = "adhoc") -> ScopeFrameResp:
        return self.post("/graph/v1/query/scope_frame", ScopeFrameReq(node_id=node_id, as_of=as_of), ScopeFrameResp, run_id=run_id)

    def validity(self, node_id: str, as_of, *, run_id: str = "adhoc") -> ValidityResult:
        return self.post("/graph/v1/query/validity", ValidityReq(node_id=node_id, as_of=as_of), ValidityResult, run_id=run_id)

    def standard(self, as_of, facts: dict, *, run_id: str = "adhoc") -> StandardResp:
        return self.post("/graph/v1/query/standard_of_review", StandardReq(as_of=as_of, facts=facts), StandardResp, run_id=run_id)

    def search(self, request: DocSearchReq, *, run_id: str = "adhoc") -> DocSearchResp:
        return self.post("/graph/v1/search/documents", request, DocSearchResp, run_id=run_id)

    def rule_candidates(self, request: RuleCandidatesReq, *, run_id: str = "adhoc") -> RuleCandidatesResp:
        return self.post("/graph/v1/query/rule_candidates", request, RuleCandidatesResp, run_id=run_id)

    def score_edges(self, request: ScoreEdgesReq, *, run_id: str = "adhoc") -> ScoreEdgesResp:
        return self.post("/graph/v1/gnn/score_edges", request, ScoreEdgesResp, run_id=run_id)

    def extract(self, request: ExtractReq, *, run_id: str = "adhoc") -> str:
        response = self.client.post(self.base_url + "/graph/v1/extract/facts",
            json=request.model_dump(mode="json"), headers=self.headers(run_id))
        response.raise_for_status()
        return response.json()["job_id"]

    def get_job(self, job_id: str, *, run_id: str = "adhoc") -> JobStatus:
        response = self.client.get(self.base_url + f"/graph/v1/jobs/{job_id}", headers=self.headers(run_id))
        response.raise_for_status()
        return JobStatus.model_validate(response.json())

    def close(self) -> None:
        self.client.close()
