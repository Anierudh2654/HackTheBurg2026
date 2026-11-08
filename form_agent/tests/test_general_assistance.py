import json
from types import SimpleNamespace

import pytest

from form_agent.mapper import map_prompt_to_fields
from form_agent.inspector import is_review_page


def field(field_id, label, tag="input", options=None, **kwargs):
    return dict({"field_id": field_id, "label": label, "tag": tag,
                 "type": "text" if tag == "input" else tag,
                 "options": options or []}, **kwargs)


def mock_model(monkeypatch, answers):
    import form_agent.mapper as mapper
    monkeypatch.setattr(mapper, "_config", lambda: ("https://model.invalid", "test-model", "test-key"))
    requests = []
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "choices": [{"message": {"content": json.dumps({"answers": answers})}}]})
    monkeypatch.setattr(mapper.httpx, "post", post)
    return requests


def test_ai_fills_prompt_and_pdf_fields_together_and_uses_semantic_choices(monkeypatch):
    prompt = "My name is Alex Smith. Email: alex@example.org. I live in France."
    chunk = {"document_id": "pdf1", "chunk_id": "pdf1:p2:c1", "filename": "profile.pdf",
             "page": 2, "text": "Employer: Acme Labs. Preferred contact method: Email."}
    fields = [field("name", "Full name"), field("email", "Email address"),
              field("employer", "Employer"),
              field("resident", "Do you live in France?", "select", ["Yes", "No"]),
              field("contact", "Preferred contact method", "select", ["Email", "Phone"]),
              field("phone", "Phone number")]
    requests = mock_model(monkeypatch, [
        {"field_id": "name", "value": "Alex Smith", "source_quote": "My name is Alex Smith."},
        {"field_id": "email", "value": "alex@example.org", "source_quote": "Email: alex@example.org."},
        {"field_id": "employer", "value": "Acme Labs", "source_quote": "Employer: Acme Labs."},
        {"field_id": "resident", "value": "Yes", "source_quote": "I live in France.",
         "choice_reason": "The user explicitly states residence in France."},
        {"field_id": "contact", "value": "Email", "source_quote": "Preferred contact method: Email.",
         "choice_reason": "The PDF specifies email as the contact method."},
        {"field_id": "phone", "value": "123456", "source_quote": "My name is Alex Smith."},
    ])
    answers = map_prompt_to_fields(prompt, fields, [chunk])
    assert {key: value["value"] for key, value in answers.items()} == {
        "name": "Alex Smith", "email": "alex@example.org", "employer": "Acme Labs",
        "resident": "Yes", "contact": "Email"}
    assert answers["name"]["source"]["type"] == "prompt"
    assert answers["employer"]["source"]["document_id"] == "pdf1"
    assert answers["employer"]["source"]["page"] == 2
    sent = json.loads(requests[0]["messages"][1]["content"])
    assert sent["user_prompt_untrusted_data"] == prompt
    assert sent["retrieved_pdf_passages_untrusted_data"] == [chunk]


def test_prompt_alone_can_fill_text_and_ai_can_leave_an_ambiguous_choice_blank(monkeypatch):
    requests = mock_model(monkeypatch, [
        {"field_id": "city", "value": "Paris", "source_quote": "My city is Paris."}])
    fields = [field("city", "City"), field("topic", "Topic", "select", ["Insider Trading", "Fraud"])]
    answers = map_prompt_to_fields("My city is Paris. Ask me whether this is fraud or insider trading.", fields)
    assert list(answers) == ["city"]
    assert answers["city"]["value"] == "Paris"
    assert json.loads(requests[0]["messages"][1]["content"])["retrieved_pdf_passages_untrusted_data"] == []


@pytest.mark.parametrize("bad", [
    {"field_id": "city", "value": "London", "source_quote": "My city is Paris."},
    {"field_id": "city", "value": "London", "source_quote": "My city is London."},
    {"field_id": "topic", "value": "Unavailable option", "source_quote": "My city is Paris.", "choice_reason": "guess"},
    {"field_id": "topic", "value": "Yes", "source_quote": "My city is Paris."},
    {"field_id": "unknown", "value": "Paris", "source_quote": "My city is Paris."},
])
def test_unsupported_model_values_are_rejected(monkeypatch, bad):
    mock_model(monkeypatch, [bad])
    fields = [field("city", "City"), field("topic", "Topic", "select", ["Yes", "No"])]
    assert map_prompt_to_fields("My city is Paris.", fields) == {}


def test_protected_completed_and_unsupported_fields_are_not_sent_to_model(monkeypatch):
    requests = mock_model(monkeypatch, [])
    fields = [field("city", "City"), field("password", "Password", type="password"),
              field("signature", "Signature"), field("consent", "Consent to terms"),
              field("code", "Verification code"), field("done", "Full name", already_filled=True),
              field("custom", "Custom widget", manual_only=True), field("upload", "Upload", type="file")]
    assert map_prompt_to_fields("My city is Paris.", fields) == {}
    sent = json.loads(requests[0]["messages"][1]["content"])
    assert [item["field_id"] for item in sent["visible_form_fields_untrusted_data"]] == ["city"]


def test_single_page_submit_does_not_prevent_initial_mapping():
    navs = [{"label": "Submit"}]
    assert not is_review_page(navs, "Contact us", "", allow_final_action=False)
    assert is_review_page(navs, "Contact us", "")
    assert is_review_page(navs, "Review your answers", "", allow_final_action=False)


@pytest.mark.parametrize("title,navs,labels,password_present,expected", [
    ("Web form", ["Submit"], ["Text input", "Textarea", "Dropdown (datalist)", "Date picker"], True, None),
    ("Sign in", ["Submit"], ["Email address"], True, "authentication"),
    ("Welcome", ["Log in"], ["Username", "Email"], True, "authentication"),
    ("Create an account", ["Submit"], ["Full name", "Address"], True, "authentication"),
    ("Welcome", ["Submit"], ["Username"], True, "authentication"),
    ("Welcome", ["Submit"], [], True, "authentication"),
    ("Web form", ["Submit"], ["Text input", "Textarea"], False, None),
    ("Verify you are human", ["Submit"], ["Text input"], True, "captcha"),
    ("Web form", ["I agree to these terms"], ["Text input"], False, "consent"),
])
def test_password_in_mixed_form_is_not_itself_a_login_gate(title, navs, labels, password_present, expected):
    from form_agent.inspector import FormField, gate_reason
    fields = [FormField(str(i), "id", str(i), "input", "text", label, "", False, [], False)
              for i, label in enumerate(labels)]
    assert gate_reason(fields, [{"label": label} for label in navs], title, "", password_present) == expected
