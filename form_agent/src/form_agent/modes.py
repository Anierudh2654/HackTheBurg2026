from urllib.parse import urlparse


RUN_MODES = {"assist", "navigate_only", "sec_prompt_assist", "sec_pdf_assist"}


def choose_run_mode(url: str, has_documents: bool) -> str:
    """Use prompt/PDF assistance for any requested destination by default."""
    return "assist"


def validate_run_mode(mode: str, url: str, has_documents: bool) -> None:
    if mode not in RUN_MODES:
        raise ValueError("Mode must be assist, navigate_only, sec_prompt_assist, or sec_pdf_assist")
    host = (urlparse(url).hostname or "").lower()
    if mode == "sec_prompt_assist" and not (host == "sec.gov" or host.endswith(".sec.gov")):
        raise ValueError("SEC prompt assistance is limited to SEC.gov destinations")
    if mode == "sec_pdf_assist":
        if not has_documents:
            raise ValueError("Attach at least one text-readable PDF for SEC PDF-assisted mode")
        if not (host == "sec.gov" or host.endswith(".sec.gov")):
            raise ValueError("SEC PDF-assisted mode is limited to SEC.gov destinations")


def should_fill_form(mode: str) -> bool:
    """Assistance may write supported answers; navigation-only never writes."""
    return mode in {"assist", "sec_prompt_assist", "sec_pdf_assist"}


def validate_model_config(mode: str, model: str, api_key: str) -> None:
    if mode in {"assist", "sec_pdf_assist"} and (not model or not api_key):
        raise ValueError("Configure NEBIUS_MODEL and NEBIUS_API_KEY in form_agent/.env for AI form assistance")


def retain_pdf_grounded_answers(answers: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """Keep model answers grounded in PDF chunks; literal prompt choices are merged separately."""
    accepted = {}
    rejected = []
    for field_id, answer in answers.items():
        source = answer.get("source", {}) if isinstance(answer, dict) else {}
        if source.get("type") == "pdf" and source.get("document_id") and source.get("page"):
            accepted[field_id] = answer
        else:
            rejected.append(field_id)
    return accepted, rejected
