import io
import time

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject

from form_agent import pdf_forms as forms
from form_agent import pdf_rag


@pytest.fixture(autouse=True)
def clear_pdf_cache():
    forms._templates.clear()
    forms._results.clear()
    pdf_rag._documents.clear()
    yield
    forms._templates.clear()
    forms._results.clear()
    pdf_rag._documents.clear()


def template_bytes(*, flat=False, existing=False, pages=2):
    doc = fitz.open()
    for number in range(pages):
        page = doc.new_page()
        page.insert_text((45, 40), "General application - page " + str(number + 1), fontsize=16)
        for index, (name, label) in enumerate([("name", "Full name"), ("company", "Employer"), ("signature", "Signature")]):
            name = name + str(number)
            y = 85 + index * 70
            page.insert_text((45, y), label)
            rect = fitz.Rect(170, y - 16, 490, y + 10)
            if flat:
                page.draw_rect(rect, color=(0, 0, 0))
            else:
                widget = fitz.Widget()
                widget.field_name, widget.field_label = name, label
                widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                widget.rect = rect
                widget.text_fontsize = 11
                if existing and index == 0:
                    widget.field_value = "Existing user answer"
                page.add_widget(widget)
    content = doc.tobytes()
    doc.close()
    return content


def answer(value, source="prompt"):
    return {"value": value, "source": {"type": source, "filename": "profile.pdf" if source == "pdf" else "User prompt",
            "page": 1 if source == "pdf" else None, "document_id": "ref" if source == "pdf" else None,
            "quote": value}}


@pytest.mark.parametrize("flat", [False, True])
def test_general_template_fills_all_pages_and_remains_editable(monkeypatch, flat):
    original = template_bytes(flat=flat)
    meta = forms.add_template("unrelated-application.pdf", original)
    assert meta["page_count"] == 2
    assert meta["field_count"] == 6
    ref = fitz.open()
    page = ref.new_page()
    page.insert_text((30, 40), "Employer: Acme Labs")
    source = pdf_rag.add_pdf("profile.pdf", ref.tobytes())
    ref.close()
    requests = []
    def model(prompt, fields, context):
        requests.append((fields, context))
        return {f["field_id"]: answer("Alex Morgan" if f["label"] == "Full name" else "Acme Labs",
                "prompt" if f["label"] == "Full name" else "pdf")
                for f in fields if f["label"] in {"Full name", "Employer"}}
    monkeypatch.setattr(forms, "map_prompt_to_fields", model)
    result = forms.fill_template(meta["template_id"], "Full name: Alex Morgan. Use the attached employer details.", [source["document_id"]])
    assert result["filled_count"] == 4
    assert [f["label"] for f in result["remaining_fields"]] == ["Signature", "Signature"]
    assert requests[0][1][0]["filename"] == "profile.pdf"
    data = forms.get_result(result["result_id"])["content"]
    fields = PdfReader(io.BytesIO(data)).get_fields()
    assert len(fields) == 6
    assert sum(f.get("/V") == "Alex Morgan" for f in fields.values()) == 2
    assert sum(f.get("/V") == "Acme Labs" for f in fields.values()) == 2
    assert sum(not f.get("/V") for f in fields.values()) == 2
    assert original != data
    # An independent PDF engine sees the same values and can continue editing.
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            widgets = list(page.widgets())
            assert len(widgets) == 3
            target = widgets[2]
            target.field_value = "Manual completion"
            target.update()
        manual = doc.tobytes()
    assert sum(f.get("/V") == "Manual completion" for f in PdfReader(io.BytesIO(manual)).get_fields().values()) == 2


def test_preserves_existing_answers_and_blocks_protected_fields(monkeypatch):
    source = template_bytes(existing=True, pages=1)
    meta = forms.add_template("form.pdf", source)
    monkeypatch.setattr(forms, "map_prompt_to_fields", lambda *a: {
        "name0": answer("Overwrite"), "signature0": answer("Sign for me"), "company0": answer("Acme")})
    result = forms.fill_template(meta["template_id"], "Employer: Acme")
    fields = PdfReader(io.BytesIO(forms.get_result(result["result_id"])["content"])).get_fields()
    assert fields["name0"]["/V"] == "Existing user answer"
    assert not fields["signature0"].get("/V")
    assert fields["company0"]["/V"] == "Acme"


def test_overlong_answers_remain_blank_with_reason(monkeypatch):
    meta = forms.add_template("form.pdf", template_bytes(pages=1))
    monkeypatch.setattr(forms, "map_prompt_to_fields", lambda *a: {"name0": answer("x" * 500)})
    result = forms.fill_template(meta["template_id"], "My name is " + "x" * 500)
    assert result["filled_count"] == 0
    assert result["skipped_fields"][0]["field"] == "Full name"
    assert "fit" in result["skipped_fields"][0]["reason"]


def test_no_model_answers_still_returns_editable_unmodified_fields(monkeypatch):
    meta = forms.add_template("form.pdf", template_bytes(pages=1))
    monkeypatch.setattr(forms, "map_prompt_to_fields", lambda *a: {})
    result = forms.fill_template(meta["template_id"], "Leave missing details blank")
    assert result["filled_count"] == 0
    assert len(result["remaining_fields"]) == 3
    assert forms.get_result(result["result_id"])["content"].startswith(b"%PDF-")


def test_checkbox_and_dropdown_export_values(monkeypatch):
    doc = fitz.open()
    page = doc.new_page()
    for name, kind, rect in [("contact", fitz.PDF_WIDGET_TYPE_COMBOBOX, (50, 50, 250, 80)),
                             ("resident", fitz.PDF_WIDGET_TYPE_CHECKBOX, (50, 110, 70, 130))]:
        widget = fitz.Widget()
        widget.field_name, widget.field_label, widget.field_type = name, name, kind
        widget.rect = fitz.Rect(rect)
        if name == "contact":
            widget.choice_values = [("EMAIL_CODE", "Email"), ("PHONE_CODE", "Phone")]
        page.add_widget(widget)
    meta = forms.add_template("choices.pdf", doc.tobytes())
    doc.close()
    monkeypatch.setattr(forms, "map_prompt_to_fields", lambda *a: {"contact": answer("Email"), "resident": answer("Yes")})
    result = forms.fill_template(meta["template_id"], "Use email. I am a resident.")
    assert result["filled_count"] == 2
    fields = PdfReader(io.BytesIO(forms.get_result(result["result_id"])["content"])).get_fields()
    assert fields["contact"]["/V"] == "EMAIL_CODE"
    assert str(fields["resident"]["/V"]) == "/Yes"


def test_orphan_widgets_are_recovered(monkeypatch):
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(io.BytesIO(template_bytes(pages=1))))
    writer.root_object["/AcroForm"][NameObject("/Fields")] = ArrayObject()
    buf = io.BytesIO()
    writer.write(buf)
    meta = forms.add_template("orphan.pdf", buf.getvalue())
    assert meta["field_count"] == 3
    monkeypatch.setattr(forms, "map_prompt_to_fields", lambda *a: {"name0": answer("Alex")})
    result = forms.fill_template(meta["template_id"], "Full name: Alex")
    assert result["filled_count"] == 1


def test_malformed_encrypted_and_expired_uploads():
    with pytest.raises(ValueError, match="Upload a PDF"):
        forms.add_template("not.pdf", b"not a PDF")
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(ValueError, match="Encrypted"):
        forms.add_template("locked.pdf", buf.getvalue())
    meta = forms.add_template("form.pdf", template_bytes(pages=1))
    forms._templates[meta["template_id"]]["created"] = time.monotonic() - forms.TTL - 1
    with pytest.raises(ValueError, match="expired"):
        forms.fill_template(meta["template_id"], "Fill it")
    assert forms.get_result("missing") is None


def test_scan_without_vision_returns_actionable_error():
    doc = fitz.open()
    doc.new_page()
    meta = forms.add_template("scan.pdf", doc.tobytes())
    doc.close()
    assert meta["field_count"] == 0
    with pytest.raises(ValueError, match="PDF_VISION_MODEL"):
        forms.fill_template(meta["template_id"], "Name: Alex")


def test_download_endpoint_returns_pdf_with_safe_filename(monkeypatch):
    from form_agent.app import download_pdf
    meta = forms.add_template("../unsafe\r\nfilename.pdf", template_bytes(pages=1))
    monkeypatch.setattr(forms, "map_prompt_to_fields", lambda *a: {})
    result = forms.fill_template(meta["template_id"], "Leave fields blank")
    response = download_pdf(result["result_id"])
    assert response.media_type == "application/pdf"
    assert response.body.startswith(b"%PDF-")
    assert "\r" not in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"


def test_scanned_template_can_use_configured_vision_discovery(monkeypatch):
    import json
    from types import SimpleNamespace
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 80), "Full name")
    image = page.get_pixmap().tobytes("png")
    scan = fitz.open()
    page = scan.new_page()
    page.insert_image(page.rect, stream=image)
    meta = forms.add_template("scanned-form.pdf", scan.tobytes())
    assert meta["field_count"] == 0
    monkeypatch.setenv("PDF_VISION_MODEL", "test-vision")
    monkeypatch.setattr(forms, "_config", lambda: ("https://test.invalid", "test-model", "test-key"))
    requests = []
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "choices": [{"message": {"content": json.dumps({"fields": [
                {"label": "Full name", "rect": [.3, .07, .8, .11]},
                {"label": "Invalid", "rect": [-1, 0, 2, 1]},
            ]})}}]})
    monkeypatch.setattr(forms.httpx, "post", post)
    monkeypatch.setattr(forms, "map_prompt_to_fields", lambda prompt,fields,ctx: {
        fields[0]["field_id"]: answer("Alex Morgan")})
    result = forms.fill_template(meta["template_id"], "Full name: Alex Morgan")
    assert result["filled_count"] == 1
    assert "visually" in result["warnings"][0]
    assert requests[0]["model"] == "test-vision"
    assert requests[0]["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    fields = PdfReader(io.BytesIO(forms.get_result(result["result_id"])["content"])).get_fields()
    assert next(iter(fields.values()))["/V"] == "Alex Morgan"
    doc.close()
    scan.close()


def test_signed_documents_and_ambiguous_root_widgets_are_rejected():
    from pypdf.generic import DictionaryObject, TextStringObject
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(io.BytesIO(template_bytes(pages=1))))
    root = writer.root_object["/AcroForm"]["/Fields"]
    first = root[0].get_object()
    first[NameObject("/FT")] = NameObject("/Sig")
    first[NameObject("/V")] = TextStringObject("signed")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(ValueError, match="digitally signed"):
        forms.add_template("signed.pdf", buf.getvalue())
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(io.BytesIO(template_bytes(pages=1))))
    root = writer.root_object["/AcroForm"]["/Fields"]
    duplicate = writer._add_object(DictionaryObject(root[0].get_object()))
    root.append(duplicate)
    writer.pages[0]["/Annots"].append(duplicate)
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(ValueError, match="Ambiguous duplicate"):
        forms.add_template("ambiguous.pdf", buf.getvalue())
