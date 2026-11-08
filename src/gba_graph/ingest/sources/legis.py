"""Delaware Legislature explicit bill plan validation helpers."""


def bill_plan(url: str, bill_id: str) -> dict:
    if not url.startswith("https://legis.delaware.gov/"):
        raise ValueError("URL_NOT_IN_REGISTRY")
    return {"url": url, "doc_type": "bill", "bill_id": bill_id}
