"""Shared canonical text implementation, version 1."""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

CANON_VERSION = 1


@dataclass(frozen=True)
class CanonResult:
    text: str
    markers: list[dict[str, Any]]
    canon_version: str = "1"


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\t", " ")
    lines = [re.sub(r" +", " ", line).rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def to_canonical_text(raw: bytes, media_type: str) -> CanonResult:
    media = media_type.split(";", 1)[0].strip().lower()
    markers: list[dict[str, Any]] = []
    if media == "text/html":
        from lxml import html
        doc = html.fromstring(raw)
        for element in doc.xpath("//script|//style|//noscript|//head"):
            element.drop_tree()
        for element in doc.xpath("//br|//p|//div|//li|//tr|//h1|//h2|//h3|//h4|//h5|//h6|//table|//section|//article"):
            element.tail = "\n" + (element.tail or "")
        for cell in doc.xpath("//td|//th"):
            cell.tail = " " + (cell.tail or "")
        text = doc.text_content()
    elif media == "application/pdf":
        from pdfminer.high_level import extract_text
        text = extract_text(io.BytesIO(raw))
    elif media == "text/plain":
        text = raw.decode("utf-8", errors="replace")
    elif media == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        from docx import Document
        document = Document(io.BytesIO(raw))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    else:
        raise ValueError(f"unsupported media type: {media_type}")
    text = _normalise(text)
    if media == "application/pdf":
        offset = 0
        for page_no, page in enumerate(text.split("\f"), 1):
            markers.append({"label": str(page_no), "start": offset})
            offset += len(page) + 1
    else:
        markers = [{"label": m.group(1), "start": m.start()} for m in re.finditer(r"\[\*(\d+)\]", text)]
    return CanonResult(text=text, markers=markers)
