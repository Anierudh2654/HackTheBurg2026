from urllib.parse import urlparse


RUN_MODES = {"navigate_only", "sec_pdf_assist"}


def validate_run_mode(mode: str, url: str, has_documents: bool) -> None:
    if mode not in RUN_MODES:
        raise ValueError("Mode must be navigate_only or sec_pdf_assist")
    host = (urlparse(url).hostname or "").lower()
    if mode == "sec_pdf_assist":
        if not has_documents:
            raise ValueError("Attach at least one text-readable PDF for SEC PDF-assisted mode")
        if not (host == "sec.gov" or host.endswith(".sec.gov")):
            raise ValueError("SEC PDF-assisted mode is limited to SEC.gov destinations")


def should_fill_form(mode: str) -> bool:
    """Only explicit SEC PDF-assist mode may write values into page fields."""
    return mode == "sec_pdf_assist"


def validate_model_config(mode: str, model: str, api_key: str) -> None:
    if should_fill_form(mode) and (not model or not api_key):
        raise ValueError("Configure NEBIUS_MODEL and NEBIUS_API_KEY in form_agent/.env for SEC PDF assistance")


def retain_pdf_grounded_answers(answers: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """SEC PDF-assist mode only writes answers whose validated quote came from a PDF chunk."""
    accepted = {}
    rejected = []
    for field_id, answer in answers.items():
        source = answer.get("source", {}) if isinstance(answer, dict) else {}
        if source.get("type") == "pdf" and source.get("document_id") and source.get("page"):
            accepted[field_id] = answer
        else:
            rejected.append(field_id)
    return accepted, rejected
