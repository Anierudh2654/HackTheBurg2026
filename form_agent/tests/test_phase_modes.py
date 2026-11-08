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
