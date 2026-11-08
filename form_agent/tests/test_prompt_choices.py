from dataclasses import replace

import pytest

from form_agent.mapper import map_explicit_prompt_choices


PROMPT = """Open the SEC TCR form and help me navigate it. I have not provided any
personal or report details, so do not fill any fields or guess information.
Pause for CAPTCHA, sign-in, and consent. Stop at review; do not submit, file,
sign, or certify anything. My complaint is about insider trading."""


def choice(**changes):
    field = {"field_id": "topic", "tag": "select", "type": "select",
             "label": "What is your complaint about?", "options": ["Insider Trading", "Market manipulation"],
             "already_filled": False, "manual_only": False}
    return dict(field, **changes)


@pytest.mark.parametrize("changes,expected", [
    ({}, "Insider Trading"),
    ({"tag": "choice_group", "type": "radio"}, "Insider Trading"),
    ({"tag": "choice_group", "type": "checkbox"}, ["Insider Trading"]),
    ({"multiple": True}, ["Insider Trading"]),
])
def test_literal_complaint_option_without_pdf_or_model(changes, expected):
    answers = map_explicit_prompt_choices(PROMPT, [choice(**changes)])
    assert answers["topic"]["value"] == expected
    assert answers["topic"]["source"]["type"] == "prompt"
    assert answers["topic"]["source"]["quote"] in PROMPT


@pytest.mark.parametrize("prompt,changes", [
    ("My complaint is not about insider trading.", {}),
    ("My complaint is about trading.", {}),
    ("I have no report details.", {}),
    ("My complaint is insider trading or market manipulation.", {}),
    ("My complaint is insider trading or fraud.", {"options": ["Insider Trading", "Fraud"]}),
    (PROMPT, {"already_filled": True}),
    (PROMPT, {"manual_only": True}),
    (PROMPT, {"label": "I certify this insider trading declaration"}),
    (PROMPT, {"label": "Consent to insider trading terms"}),
    (PROMPT, {"tag": "input", "type": "text"}),
    (PROMPT, {"tag": "textarea", "type": "textarea"}),
    ("Yes", {"options": ["Yes", "No"]}),
])
def test_unknown_ambiguous_protected_and_text_fields_stay_blank(prompt, changes):
    assert map_explicit_prompt_choices(prompt, [choice(**changes)]) == {}


@pytest.mark.parametrize("mode", ["sec_prompt_assist", "sec_pdf_assist", "assist"])
@pytest.mark.parametrize("gate", ["captcha", "authentication", "consent", "legal_attestation"])
def test_browser_selects_topic_pauses_for_missing_data_and_stops_at_review(monkeypatch, mode, gate):
    import form_agent.agent as agent
    from form_agent.inspector import FormField

    topic = FormField("topic", "id", "topic", "select", "select", "Complaint type", "", True,
                      ["Insider Trading", "Market manipulation"], False)
    name = FormField("name", "id", "name", "input", "text", "Your name", "", True, [], False)
    fields = [topic, name]
    handoffs = []
    writes = []
    clicks = []
    driver = type("Browser", (), {"current_url": "https://example.org/form" if mode == "assist" else "https://www.sec.gov/form",
                                  "set_page_load_timeout": lambda self, n: None,
                                  "get": lambda self, url: None})()
    run_prompt = "Fill known fields and ask me for missing data. My complaint is about insider trading." if mode == "assist" else PROMPT
    run = agent.AgentRun("test", run_prompt, driver.current_url, mode=mode)

    class StopAtReview:
        def is_set(self):
            return False
        def wait(self, timeout):
            assert run.status == "review_ready"
            return True

    run.stop_event = StopAtReview()
    monkeypatch.setattr(agent, "_chrome_driver", lambda: driver)
    monkeypatch.setattr(agent, "_bring_chrome_to_front", lambda d: True)
    monkeypatch.setattr(agent.time, "sleep", lambda n: None)
    monkeypatch.setattr(agent, "retrieve_context", lambda *args: [])
    # A prompt-sourced choice from the model must survive the PDF-only filter via
    # the independently matched explicit choice. Ordinary prompt text stays rejected.
    def model_answers(*args):
        if mode == "sec_prompt_assist":
            pytest.fail("Legacy literal-only path must not call the model")
        answers = {"topic": {"value": "Insider Trading", "source": {
            "type": "prompt", "filename": "User prompt", "page": None,
            "quote": "My complaint is about insider trading."}}}
        if mode == "sec_pdf_assist":
            answers["name"] = {"value": "invented", "source": {"type": "prompt"}}
        return answers
    monkeypatch.setattr(agent, "map_prompt_to_fields", model_answers)
    stage = {"gate": gate, "review": False}

    def inspect(d):
        navs = [{"label": "Submit"}] if stage["review"] else [{"label": "Next"}]
        return fields, navs, "Review your answers" if stage["review"] else "Complaint", "", False

    def wait(run, reason, message, *args):
        handoffs.append(reason)
        if reason == gate:
            stage["gate"] = None
        elif reason == "missing_required_fields":
            assert writes == [{"topic": "Insider Trading"}]
            fields[1] = replace(name, already_filled=True)  # user enters name in Chrome
        else:
            pytest.fail("Unexpected handoff: " + reason)
        return True

    def fill(d, current_fields, values):
        if values:
            writes.append(values)
            assert values == {"topic": "Insider Trading"}
            fields[0] = replace(topic, already_filled=True)
        return list(values), [], []

    def forward(d, nav, url):
        clicks.append(nav["label"])
        stage["review"] = True
        return True

    monkeypatch.setattr(agent, "inspect_page", inspect)
    monkeypatch.setattr(agent, "gate_reason", lambda *args: stage["gate"])
    monkeypatch.setattr(agent, "_wait_for_user", wait)
    monkeypatch.setattr(agent, "fill_values", fill)
    monkeypatch.setattr(agent, "_click_and_wait", forward)
    agent._run_browser(run)
    assert handoffs == [gate, "missing_required_fields"]
    assert writes == [{"topic": "Insider Trading"}]
    assert clicks == ["Next"]
    assert run.status == "review_ready"
    assert run.error is None
    assert run.field_sources[0]["source_type"] == "prompt"
