"""CourtListener API request helpers; tokens are supplied only through environment."""


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Token {token}"} if token else {}
