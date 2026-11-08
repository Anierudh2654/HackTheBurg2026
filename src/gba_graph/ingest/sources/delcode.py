"""Delaware Code explicit plan validation helpers."""


def section_plan(url: str, section: str, version_label: str) -> dict:
    if not url.startswith("https://delcode.delaware.gov/"):
        raise ValueError("URL_NOT_IN_REGISTRY")
    return {"url": url, "doc_type": "statute", "section": section, "version_label": version_label}
