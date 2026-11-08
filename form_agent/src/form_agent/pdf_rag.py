from __future__ import annotations

import hashlib
import io
import math
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 250
MAX_TEXT_CHARS = 2_000_000
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200
MAX_DOCUMENTS = 10


@dataclass
class PdfDocument:
    document_id: str
    filename: str
    sha256: str
    page_count: int
    chunks: list[dict]

    def metadata(self) -> dict:
        return {"document_id": self.document_id, "filename": self.filename,
                "sha256": self.sha256, "page_count": self.page_count,
                "chunk_count": len(self.chunks)}


_documents: dict[str, PdfDocument] = {}
_lock = threading.RLock()


def _chunks_for_page(text: str, document_id: str, filename: str, page: int) -> list[dict]:
    text = unicodedata.normalize("NFC", text).replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    out: list[dict] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            boundary = text.rfind("\n", start + CHUNK_CHARS // 2, end)
            if boundary > start:
                end = boundary
        chunk_text = text[start:end].strip()
        if chunk_text:
            out.append({
                "chunk_id": f"{document_id}:p{page}:c{len(out) + 1}",
                "document_id": document_id,
                "filename": filename,
                "page": page,
                "text": chunk_text,
            })
        if end >= len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    return out


def add_pdf(filename: str, content: bytes) -> dict:
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the 15 MB upload limit")
    if not content.startswith(b"%PDF-"):
        raise ValueError("Uploaded file is not a PDF")
    safe_name = Path(filename or "document.pdf").name[:200]
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported; export an unlocked copy locally")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDF exceeds the {MAX_PDF_PAGES}-page limit")
        document_id = f"pdf_{uuid.uuid4().hex[:12]}"
        chunks: list[dict] = []
        total_chars = 0
        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            total_chars += len(text)
            if total_chars > MAX_TEXT_CHARS:
                raise ValueError("Extracted PDF text exceeds the 2 million character limit")
            chunks.extend(_chunks_for_page(text, document_id, safe_name, page_num))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not read PDF: {type(exc).__name__}") from exc
    if not chunks:
        raise ValueError("No selectable text found. Scanned/image-only PDFs need OCR before upload")
    record = PdfDocument(document_id, safe_name, hashlib.sha256(content).hexdigest(), len(reader.pages), chunks)
    with _lock:
        if len(_documents) >= MAX_DOCUMENTS:
            raise ValueError(f"At most {MAX_DOCUMENTS} PDFs can be attached at once")
        _documents[document_id] = record
    return record.metadata()


def list_documents() -> list[dict]:
    with _lock:
        return [doc.metadata() for doc in _documents.values()]


def remove_document(document_id: str) -> bool:
    with _lock:
        return _documents.pop(document_id, None) is not None


def get_documents(document_ids: list[str]) -> list[PdfDocument]:
    with _lock:
        missing = [doc_id for doc_id in document_ids if doc_id not in _documents]
        if missing:
            raise ValueError(f"Unknown or expired PDF attachment(s): {', '.join(missing)}")
        return [_documents[doc_id] for doc_id in document_ids]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFC", text).casefold())


def _bm25(query: str, chunks: list[dict]) -> list[tuple[float, dict]]:
    if not chunks:
        return []
    docs = [_tokens(c["text"]) for c in chunks]
    query_terms = set(_tokens(query))
    if not query_terms:
        return []
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / max(n, 1)
    document_frequency: dict[str, int] = {}
    for terms in docs:
        for term in set(terms):
            document_frequency[term] = document_frequency.get(term, 0) + 1
    scores: list[tuple[float, dict]] = []
    for chunk, terms in zip(chunks, docs):
        frequencies: dict[str, int] = {}
        for term in terms:
            frequencies[term] = frequencies.get(term, 0) + 1
        score = 0.0
        dl = len(terms)
        for term in query_terms:
            tf = frequencies.get(term, 0)
            if not tf:
                continue
            df = document_frequency.get(term, 0)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            score += idf * (tf * 2.5) / (tf + 1.5 * (1 - 0.75 + 0.75 * dl / max(avgdl, 1)))
        scores.append((score, chunk))
    return sorted(scores, key=lambda item: item[0], reverse=True)


def retrieve_context(documents: list[PdfDocument], prompt: str, fields: list[dict],
                     max_chunks: int = 12) -> list[dict]:
    chunks = [chunk for doc in documents for chunk in doc.chunks]
    best: dict[str, tuple[float, dict]] = {}
    for field in fields:
        query = " ".join([
            prompt[:6000],
            str(field.get("label", "")),
            str(field.get("placeholder", "")),
            " ".join(str(x) for x in field.get("options", [])),
        ])
        for score, chunk in _bm25(query, chunks)[:3]:
            if score > 0 and (chunk["chunk_id"] not in best or score > best[chunk["chunk_id"]][0]):
                best[chunk["chunk_id"]] = (score, chunk)
    selected = sorted(best.values(), key=lambda item: item[0], reverse=True)[:max_chunks]
    return [{**chunk, "score": round(score, 4)} for score, chunk in selected]

