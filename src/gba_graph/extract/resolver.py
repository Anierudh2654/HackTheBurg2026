"""Resolve and verify extractor quotations against canonical text."""
from __future__ import annotations

import re
import unicodedata
from ..contracts_local.models import Span


def normalize_quote(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
    return re.sub(r"\s+", " ", text).strip()


def _normalized_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    text = unicodedata.normalize("NFC", text)
    output: list[str] = []
    offsets: list[tuple[int, int]] = []
    pending_space: tuple[int, int] | None = None
    quote_map = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
    for index, char in enumerate(text):
        normalized = char.translate(quote_map)
        if normalized.isspace():
            if output and pending_space is None:
                pending_space = (index, index + 1)
            elif pending_space is not None:
                pending_space = (pending_space[0], index + 1)
            continue
        if pending_space is not None:
            output.append(" ")
            offsets.append(pending_space)
            pending_space = None
        output.append(normalized)
        offsets.append((index, index + 1))
    return "".join(output), offsets


def resolve_quote(doc_id: str, canonical_text: str, quote: str, base_offset: int = 0) -> Span | None:
    target = normalize_quote(quote)
    if not target or len(target) > 500:
        return None
    normalized, offsets = _normalized_with_offsets(canonical_text)
    position = normalized.find(target)
    if position < 0 or not offsets:
        return None
    start = offsets[position][0]
    end = offsets[position + len(target) - 1][1]
    exact = canonical_text[start:end]
    if len(exact) > 500:
        return None
    return Span(doc_id=doc_id, start=base_offset + start, end=base_offset + end, quote=exact)
