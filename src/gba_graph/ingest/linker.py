"""Best-effort source-to-graph linking using explicit headers and metadata."""
from __future__ import annotations

from datetime import date
import re
from ..contracts_local.models import Node
from ..graph.store import GraphStore


def link_document(entry_id: str | None, text: str, version_label: str | None, store: GraphStore,
                  source_id: str | None = None) -> list[str]:
    if entry_id in {"de_courts", "courtlistener"}:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        caption = next((line for line in lines[:50] if re.search(r"\bv\.?\s|^In re\b", line, re.I)), None)
        date_match = re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b", "\n".join(lines[:100]), re.I)
        if not caption or not date_match:
            return []
        from datetime import datetime
        decided = datetime.strptime(date_match.group(0), "%B %d, %Y").date()
        citation_match = re.search(r"\b\d+\s+A\.\s*\d+d?\s+\d+\b", "\n".join(lines[:150]))
        citation = citation_match.group(0) if citation_match else ""
        normalized_caption = re.sub(r"[^a-z0-9]+", " ", caption.casefold()).strip()
        matched = next((node for node in store.nodes.values() if node.node_type == "Case" and (
            node.props.get("citation_string") == citation and citation
            or node.props.get("decided_on") == decided.isoformat()
            and re.sub(r"[^a-z0-9]+", " ", str(node.props.get("case_name", "")).casefold()).strip() == normalized_caption)), None)
        if matched:
            if source_id and source_id not in matched.source_ids:
                matched.source_ids.append(source_id)
                if hasattr(store, "persist_node"):
                    store.persist_node(matched)
            return [matched.node_id]
        slug = re.sub(r"[^a-z0-9._@-]", "", re.sub(r"[ /]+", "-", caption.lower())).strip("-")
        node_id = f"Case:{slug}-{decided.year}"
        if node_id not in store.nodes:
            node = Node(node_id=node_id, node_type="Case", label=caption,
                props={"case_name": caption, "decided_on": decided.isoformat(), "court_id": "Court:delaware-supreme-court", "citation_string": citation},
                known_from=decided, source_ids=[source_id] if source_id else [], origin="registry", audited=False)
            store.add_node(node)
        return [node_id]
    if entry_id in {"de_code_online", "de_legislature"} and version_label:
        section = re.search(r"(?:DGCL\s*)?(?:§|section\s+)([0-9]+[A-Za-z]?)", version_label, re.I)
        effective = re.search(r"20\d{2}-\d{2}-\d{2}", version_label)
        if section and effective:
            slug = f"de.dgcl.{section.group(1).lower()}@{effective.group(0)}"
            node_id = "Provision:" + slug
            existing = next((node for node in store.nodes.values() if node.node_type == "Provision"
                and str(node.props.get("section", "")).casefold() == section.group(1).casefold()
                and node.valid_from == date.fromisoformat(effective.group(0))), None)
            if existing:
                if source_id and source_id not in existing.source_ids:
                    existing.source_ids.append(source_id)
                    if hasattr(store, "persist_node"):
                        store.persist_node(existing)
                return [existing.node_id]
            if node_id not in store.nodes:
                node = Node(node_id=node_id, node_type="Provision", label=version_label,
                    props={"code": "DGCL", "section": section.group(1), "version_label": version_label},
                    known_from=date.fromisoformat(effective.group(0)), valid_from=date.fromisoformat(effective.group(0)),
                    source_ids=[source_id] if source_id else [],
                    origin="registry", audited=False)
                store.add_node(node)
            return [node_id]
    return []
