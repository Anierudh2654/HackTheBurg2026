"""Document registration, canonical storage, metadata, and lexical search."""
from __future__ import annotations

from datetime import date
import json
import re
from .contracts_local.canon import to_canonical_text
from .contracts_local.models import DocHit, DocMeta, SourceRecord, Span
from .index.chunker import chunk_text
from .index.hybrid import cosine, lexical_rank, reciprocal_rank_fusion
from .index.embedder import embed_texts
from .storage import BlobStore, document_id


class DocumentRepository:
    def __init__(self, blob: BlobStore, graph=None, sessions=None, registry=None):
        self.blob = blob
        self.graph = graph
        self.sessions = sessions
        self.registry = registry
        self.meta: dict[str, DocMeta] = {}
        self.text: dict[str, str] = {}
        self.chunks: dict[str, list] = {}
        self.embeddings: dict[str, list[list[float]]] = {}
        if sessions is not None:
            self.load()

    def load(self) -> None:
        from sqlalchemy import text as sql_text
        with self.sessions() as session:
            documents = session.execute(sql_text("SELECT doc_id, source, title, doc_type, doc_date, canon_version, char_length, page_markers FROM documents")).mappings()
            for row in documents:
                source = SourceRecord.model_validate(row["source"])
                meta = DocMeta(doc_id=row["doc_id"], source=source, title=row["title"], doc_type=row["doc_type"],
                    doc_date=row["doc_date"], canon_version=row["canon_version"], char_length=row["char_length"],
                    page_markers=row["page_markers"], node_ids=[])
                self.meta[meta.doc_id] = meta
                hex_id = meta.doc_id.removeprefix("sha256:")
                self.text[meta.doc_id] = self.blob.get(f"canon/{hex_id}.v1.txt").decode("utf-8")
                rows = session.execute(sql_text("SELECT ordinal, start, \"end\", text, embedding FROM chunks WHERE doc_id=:doc_id ORDER BY ordinal"), {"doc_id": meta.doc_id}).mappings().all()
                self.chunks[meta.doc_id] = [type("ChunkRecord", (), {"ordinal": r["ordinal"], "start": r["start"], "end": r["end"], "text": r["text"]}) for r in rows]
                self.embeddings[meta.doc_id] = [list(r["embedding"]) if r["embedding"] is not None else [] for r in rows]
                linked_ids = session.execute(sql_text("SELECT node_id FROM node_documents WHERE doc_id=:doc_id ORDER BY node_id"),
                                             {"doc_id": meta.doc_id}).scalars().all()
                meta.node_ids = list(linked_ids)

    def register(self, source: SourceRecord) -> DocMeta:
        if source.registry_entry_id is None or self.registry is None:
            raise ValueError("SOURCE_NOT_IN_REGISTRY")
        try:
            entry = self.registry.require_url(source.registry_entry_id, source.url)
        except ValueError as exc:
            raise ValueError("URL_NOT_IN_REGISTRY") from exc
        from .config import get_settings
        if get_settings().gba_env == "prod" and not entry.data.get("terms_verified", False):
            raise ValueError("TERMS_UNVERIFIED")
        if source.canon_version not in (None, "1"):
            raise ValueError("CANON_VERSION_UNSUPPORTED")
        raw_key = "raw/" + source.doc_id.removeprefix("sha256:")
        if not self.blob.exists(raw_key):
            raise FileNotFoundError("raw document is missing from the blob store")
        raw = self.blob.get(raw_key)
        if document_id(raw) != source.doc_id or len(raw) != source.byte_length:
            raise ValueError("HASH_MISMATCH")
        canon = to_canonical_text(raw, source.media_type)
        text_bytes = canon.text.encode("utf-8")
        hex_id = source.doc_id.removeprefix("sha256:")
        canon_key = f"canon/{hex_id}.v1.txt"
        pages_key = f"canon/{hex_id}.v1.pages.json"
        self.blob.put(canon_key, text_bytes, "text/plain; charset=utf-8")
        self.blob.put(pages_key, json.dumps(canon.markers, ensure_ascii=False, separators=(",", ":")).encode(), "application/json")
        title = next((line.strip()[:200] for line in canon.text.splitlines() if line.strip()), None)
        doc_date = derive_date(source, canon.text)
        current = self.meta.get(source.doc_id)
        if current:
            result = current
        else:
            result = DocMeta(doc_id=source.doc_id, source=source, title=title,
                             doc_type=source.expected_doc_type, doc_date=doc_date,
                             canon_version=source.canon_version or "1", char_length=len(canon.text),
                             page_markers=canon.markers, node_ids=[])
        self.meta[source.doc_id] = result
        self.text[source.doc_id] = canon.text
        self.chunks[source.doc_id] = chunk_text(canon.text)
        try:
            settings = __import__("gba_graph.config", fromlist=["get_settings"]).get_settings()
            self.embeddings[source.doc_id] = embed_texts([chunk.text for chunk in self.chunks[source.doc_id]], settings.embed_model)
            if any(len(vector) != settings.embed_dim for vector in self.embeddings[source.doc_id]):
                raise ValueError("embedding vector dimension does not match EMBED_DIM")
        except (OSError, RuntimeError, ValueError, ImportError):
            # The model is loaded from local cache only; lexical search remains available when absent.
            self.embeddings[source.doc_id] = []
        if self.graph is not None:
            from .ingest.linker import link_document
            node_ids = link_document(source.registry_entry_id, canon.text, source.version_label, self.graph, source.source_id)
            if node_ids:
                result = result.model_copy(update={"node_ids": node_ids})
                self.meta[source.doc_id] = result
        self.blob.put(f"source/{source.source_id}.json", source.model_dump_json().encode(), "application/json")
        if self.sessions is not None:
            self._persist(result, self.chunks[source.doc_id], self.embeddings[source.doc_id])
        return result

    def _persist(self, meta: DocMeta, chunks: list, embeddings: list[list[float]]) -> None:
        from sqlalchemy import text as sql_text
        source_json = meta.source.model_dump(mode="json")
        with self.sessions.begin() as session:
            session.execute(sql_text("""INSERT INTO documents (doc_id, source_id, registry_entry_id, url, media_type, title, doc_type, doc_date, version_label, canon_version, char_length, page_markers, source)
                VALUES (:doc_id,:source_id,:registry_entry_id,:url,:media_type,:title,:doc_type,:doc_date,:version_label,:canon_version,:char_length,CAST(:page_markers AS jsonb),CAST(:source AS jsonb))
                ON CONFLICT (doc_id) DO NOTHING"""), {"doc_id": meta.doc_id, "source_id": meta.source.source_id,
                    "registry_entry_id": meta.source.registry_entry_id, "url": meta.source.url, "media_type": meta.source.media_type,
                    "title": meta.title, "doc_type": meta.doc_type, "doc_date": meta.doc_date,
                    "version_label": meta.source.version_label, "canon_version": meta.canon_version,
                    "char_length": meta.char_length, "page_markers": json.dumps(meta.page_markers),
                    "source": json.dumps(source_json, ensure_ascii=False)})
            for index, chunk in enumerate(chunks):
                vector = embeddings[index] if index < len(embeddings) else None
                session.execute(sql_text("""INSERT INTO chunks (doc_id, ordinal, start, \"end\", text, tsv, embedding)
                    VALUES (:doc_id,:ordinal,:start,:end,:text,to_tsvector('english',:text),CAST(:embedding AS vector))
                    ON CONFLICT (doc_id, ordinal) DO NOTHING"""), {"doc_id": meta.doc_id, "ordinal": chunk.ordinal,
                    "start": chunk.start, "end": chunk.end, "text": chunk.text,
                    "embedding": "[" + ",".join(map(str, vector)) + "]" if vector else None})
            for node_id in meta.node_ids:
                session.execute(sql_text("INSERT INTO node_documents (node_id, doc_id) VALUES (:node_id,:doc_id) ON CONFLICT DO NOTHING"),
                                {"node_id": node_id, "doc_id": meta.doc_id})

    def search(self, query: str, as_of: date, top_k: int, registry_ids: list[str], doc_types: list[str], strict: bool) -> list[DocHit]:
        metas = list(self.meta.values())
        hits: list[DocHit] = []
        lexical_all: list[tuple[str, int, float]] = []
        dense_all: list[tuple[str, int, float]] = []
        eligible: dict[str, list] = {}
        for meta in metas:
            if registry_ids and meta.source.registry_entry_id not in registry_ids:
                continue
            if doc_types and meta.doc_type not in doc_types:
                continue
            if strict and (meta.doc_date is None or meta.doc_date > as_of):
                continue
            chunks = self.chunks[meta.doc_id]
            eligible[meta.doc_id] = chunks
            text_list = [chunk.text for chunk in chunks]
            lexical_all.extend((meta.doc_id, index, score) for index, score in lexical_rank(query, text_list, limit=50))
        lexical_all.sort(key=lambda row: (-row[2], row[0], row[1]))
        lexical_all = lexical_all[:50]
        if self.sessions is not None and eligible:
            from sqlalchemy import text as sql_text
            phrase_match = query.strip('"') if query.startswith('"') and query.endswith('"') else ""
            if not phrase_match:
                statute_match = re.search(r"\b\d+\s*(?:Del\.|DGCL|§)", query, re.I)
                phrase_match = statute_match.group(0) if statute_match else ""
            with self.sessions() as session:
                rows = session.execute(sql_text("""SELECT doc_id, ordinal,
                    ts_rank_cd(tsv, plainto_tsquery('english', :query)) +
                    CASE WHEN :phrase <> '' AND text ILIKE :phrase_pattern THEN 2.0 ELSE 0 END AS score
                    FROM chunks WHERE doc_id = ANY(CAST(:doc_ids AS text[]))
                    AND (tsv @@ plainto_tsquery('english', :query) OR (:phrase <> '' AND text ILIKE :phrase_pattern))
                    ORDER BY score DESC, doc_id, ordinal LIMIT 50"""),
                    {"query": query, "phrase": phrase_match,
                     "phrase_pattern": "%" + phrase_match + "%", "doc_ids": list(eligible)}).mappings().all()
            if rows:
                lexical_all = [(row["doc_id"], row["ordinal"], float(row["score"]))
                               for row in rows if row["doc_id"] in eligible and row["ordinal"] < len(eligible[row["doc_id"]])]
        try:
            settings = __import__("gba_graph.config", fromlist=["get_settings"]).get_settings()
            query_vector = embed_texts([query], settings.embed_model)[0]
            for doc_id, chunks in eligible.items():
                for index, vector in enumerate(self.embeddings.get(doc_id, [])):
                    if vector:
                        dense_all.append((doc_id, index, cosine(query_vector, vector)))
        except (OSError, RuntimeError, ValueError, ImportError, IndexError):
            dense_all = []
        dense_all.sort(key=lambda row: (-row[2], row[0], row[1]))
        dense_all = dense_all[:50]
        identities = list(dict.fromkeys([(doc_id, index) for doc_id, index, _ in lexical_all] + [(doc_id, index) for doc_id, index, _ in dense_all]))
        identity_idx = {identity: index for index, identity in enumerate(identities)}
        bm25_order = [identity_idx[(doc_id, idx)] for doc_id, idx, _ in sorted(lexical_all, key=lambda row: (-row[2], row[0], row[1]))]
        dense_order = [identity_idx[(doc_id, idx)] for doc_id, idx, _ in sorted(dense_all, key=lambda row: (-row[2], row[0], row[1]))]
        fused = reciprocal_rank_fusion([bm25_order, dense_order])
        per_doc: dict[str, list[tuple[int, float]]] = {}
        for (doc_id, index), fused_index in identity_idx.items():
            per_doc.setdefault(doc_id, []).append((index, fused.get(fused_index, 0.0)))
        for doc_id, ranked in per_doc.items():
            meta = self.meta[doc_id]
            ranked.sort(key=lambda row: (-row[1], row[0]))
            spans = []
            for index, _score in ranked[:3]:
                chunk = eligible[doc_id][index]
                end = min(chunk.end, chunk.start + 500)
                spans.append(Span(doc_id=doc_id, start=chunk.start, end=end,
                                  quote=self.text[doc_id][chunk.start:end]))
            hits.append(DocHit(doc_id=doc_id, source_id=meta.source.source_id,
                               title=meta.title or "", doc_type=meta.doc_type or "", doc_date=meta.doc_date,
                               score=ranked[0][1], spans=spans))
        hits.sort(key=lambda hit: (-hit.score, hit.doc_id))
        rerank_model = __import__("gba_graph.config", fromlist=["get_settings"]).get_settings().rerank_model
        if rerank_model and hits:
            from .index.reranker import rerank
            passages = [eligible[hit.doc_id][per_doc[hit.doc_id][0][0]].text for hit in hits[:30]]
            try:
                scores = rerank(query, passages, rerank_model)
                reranked = {index: score for index, score in scores}
                hits = [hit.model_copy(update={"score": reranked.get(index, hit.score)})
                        for index, hit in enumerate(hits[:30])] + hits[30:]
            except (OSError, RuntimeError, ValueError, ImportError):
                pass
        return sorted(hits, key=lambda hit: (-hit.score, hit.doc_id))[:top_k]


def derive_date(source: SourceRecord, canonical_text: str = "") -> date | None:
    label = source.version_label or ""
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", label)
    if match:
        return date.fromisoformat(match.group(1))
    if source.registry_entry_id in {"de_courts", "courtlistener"}:
        match = re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b", canonical_text[:12000], re.I)
        if match:
            from datetime import datetime
            return datetime.strptime(match.group(0), "%B %d, %Y").date()
        return None
    if source.registry_entry_id == "sec_edgar":
        match = re.search(r"filing\s+date\s*[:\s]+(20\d{2}-\d{2}-\d{2})", canonical_text[:12000], re.I)
        if match:
            return date.fromisoformat(match.group(1))
        return None
    if source.registry_entry_id == "de_code_online":
        return source.retrieved_at.date()
    if source.registry_entry_id == "de_legislature":
        match = re.search(r"enacted\s+(?:on\s+)?(20\d{2}-\d{2}-\d{2})", canonical_text[:12000], re.I)
        if match:
            return date.fromisoformat(match.group(1))
    return None
