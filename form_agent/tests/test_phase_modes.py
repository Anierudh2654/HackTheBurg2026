import pytest
from types import SimpleNamespace

from form_agent.modes import (
    retain_pdf_grounded_answers,
    should_fill_form,
    validate_model_config,
    validate_run_mode,
)
from form_agent.validation import field_value_matches


def test_navigation_only_is_non_mutating_mode():
    validate_run_mode("navigate_only", "https://www.example.org/form", False)
    assert should_fill_form("navigate_only") is False


def test_sec_pdf_assist_requires_pdf_and_sec_destination():
    with pytest.raises(ValueError, match="Attach at least one"):
        validate_run_mode("sec_pdf_assist", "https://www.sec.gov/", False)
    with pytest.raises(ValueError, match="limited to SEC.gov"):
        validate_run_mode("sec_pdf_assist", "https://example.org/form", True)
    validate_run_mode("sec_pdf_assist", "https://www.sec.gov/", True)
    validate_run_mode("sec_pdf_assist", "https://tcr.sec.gov/form", True)
    assert should_fill_form("sec_pdf_assist") is True


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="Mode must be"):
        validate_run_mode("crawl", "https://www.sec.gov/", True)


def test_navigation_only_does_not_require_llm_credentials():
    validate_model_config("navigate_only", "", "")



def test_sec_assistance_requires_llm_credentials():
    with pytest.raises(ValueError, match="Configure NEBIUS_MODEL"):
        validate_model_config("sec_pdf_assist", "", "")
    validate_model_config("sec_pdf_assist", "model-id", "token")


def test_sec_assist_keeps_only_pdf_sourced_answers():
    answers = {
        "from_pdf": {"value": "Acme", "source": {"type": "pdf", "document_id": "d1", "page": 2}},
        "from_prompt": {"value": "Beta", "source": {"type": "prompt"}},
        "without_source": {"value": "Gamma"},
    }
    accepted, rejected = retain_pdf_grounded_answers(answers)
    assert list(accepted) == ["from_pdf"]
    assert rejected == ["from_prompt", "without_source"]


def test_field_readback_requires_matching_scalar_or_complete_choice_set():
    text_field = SimpleNamespace(tag="input", field_type="text", multiple=False)
    assert field_value_matches(text_field, "Acme, Inc.", "Acme, Inc.")
    assert not field_value_matches(text_field, "Acme, Inc.", "Other Inc.")

    checkbox_field = SimpleNamespace(tag="choice_group", field_type="checkbox", multiple=False)
    assert field_value_matches(checkbox_field, ["A", "B"], ["B", "A"])
    assert not field_value_matches(checkbox_field, ["A", "B"], ["A"])


@pytest.mark.parametrize("url,has_documents,expected", [
    ("https://www.sec.gov/form", True, "assist"),
    ("https://tcr.sec.gov/form", True, "assist"),
    ("https://www.sec.gov/form", False, "assist"),
    ("https://example.org/form", True, "assist"),
    ("https://sec.gov.example.org/form", True, "assist"),
])
def test_dashboard_chooses_supported_mode(url, has_documents, expected):
    from form_agent.modes import choose_run_mode
    assert choose_run_mode(url, has_documents) == expected


@pytest.mark.parametrize("document_ids,expected", [(["pdf1"], "assist"), ([], "assist")])
def test_dashboard_start_without_mode_uses_general_assistance(monkeypatch, document_ids, expected):
    import form_agent.app as dashboard

    class Request:
        async def json(self):
            return {"prompt": "go to SEC TCR", "document_ids": document_ids}

    calls = []
    def start(prompt, document_ids, mode):
        calls.append((prompt, document_ids, mode))
        return SimpleNamespace(public=lambda: {"status": "starting"})

    monkeypatch.setattr(dashboard, "start_run", start)
    # The request stub resolves immediately; no socket-based Windows event loop is needed.
    with pytest.raises(StopIteration) as completed:
        dashboard.start(Request()).send(None)
    assert completed.value.value == {"status": "starting"}
    assert calls == [("go to SEC TCR", document_ids, expected)]


def test_sec_prompt_assistance_needs_neither_pdf_nor_model():
    validate_run_mode("sec_prompt_assist", "https://www.sec.gov/", False)
    validate_model_config("sec_prompt_assist", "", "")
    assert should_fill_form("sec_prompt_assist")
    with pytest.raises(ValueError, match="limited to SEC.gov"):
        validate_run_mode("sec_prompt_assist", "https://example.org/", False)


@pytest.mark.parametrize("url,has_documents", [
    ("https://example.org/form", False),
    ("https://example.org/form", True),
    ("https://www.sec.gov/form", False),
])
def test_general_assistance_supports_prompt_and_optional_documents(url, has_documents):
    validate_run_mode("assist", url, has_documents)
    assert should_fill_form("assist")
    with pytest.raises(ValueError, match="Configure NEBIUS_MODEL"):
        validate_model_config("assist", "", "")
    validate_model_config("assist", "model", "token")
