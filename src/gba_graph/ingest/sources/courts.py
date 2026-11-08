"""Delaware opinions explicit plan validation helpers."""


def opinion_plan(url: str, citation: str) -> dict:
    if not url.startswith("https://courts.delaware.gov/"):
        raise ValueError("URL_NOT_IN_REGISTRY")
    return {"url": url, "doc_type": "opinion", "citation": citation}
