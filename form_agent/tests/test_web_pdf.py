import io
import json
from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfReader

from form_agent import web_pdf


@pytest.mark.parametrize("prompt,expected", [
    ("Find and download Form X11 PDF, fill it and return a PDF.", True),
    ("Go to the authority. Find the application and return an editable PDF.", True),
    ("Fill the PDF using my details", True),
    ("Fill https://example.org/form.pdf using my details", True),
    ("Open the online application and use my attached PDF for reference", False),
    ("Fill the web form using the details in the attached PDF", False),
])
def test_pdf_output_intent_does_not_confuse_reference_attachments(prompt, expected):
    assert web_pdf.wants_pdf_output(prompt) == expected


def test_pdf_search_query_excludes_personal_details_and_filenames_are_not_sites():
    from form_agent.agent import resolve_destination
    url, query = resolve_destination("Find and download Form-X11.pdf.\nName: Alex Morgan\nEmail: alex@example.co.uk")
    assert "google.com/search" in url
    assert "Alex" not in query
    assert "email" not in query.lower()
    assert not url.startswith("https://Form-X11.pdf")


def test_collect_links_preserves_card_context_and_filters_irrelevant_actions():
    html = '<ul><li><h3>Form X11</h3>Claim form <a href="/media/123.pdf">PDF</a></li>' \
           '<li><h3>Form Y22</h3>Other form <a href="/media/456.pdf">PDF</a></li></ul>' \
           '<a href="/delete">Delete</a><a href="javascript:alert(1)">PDF</a>'
    links = web_pdf.collect_links(html, "https://example.org/forms", set())
    assert len(links) == 2
    assert "Form X11" in links[0]["context"]
    assert "Form Y22" not in links[0]["context"]
    assert links[0]["pdf"]


def test_model_selection_is_limited_to_known_links_and_query_tokens_are_not_sent(monkeypatch):
    links = [{"url": "https://example.org/form.pdf?token=private", "label": "Form X11", "context": "Application", "pdf": True}]
    sent = []
    monkeypatch.setattr(web_pdf, "_config", lambda: ("https://model.invalid", "model", "key"))
    def post(url, **kwargs):
        sent.append(kwargs["json"])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": {"content": '{"index":0}'}}]})
    monkeypatch.setattr(web_pdf.httpx, "post", post)
    assert web_pdf.choose_link("Download Form X11 PDF", "Forms", links) is links[0]
    assert "private" not in json.dumps(sent)
    monkeypatch.setattr(web_pdf.httpx, "post", lambda *a,**k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"choices": [{"message": {"content": '{"index":999}'}}]}))
    assert web_pdf.choose_link("Download Form X11 PDF", "Forms", links) is None


def client_transport(monkeypatch, handler):
    cls = httpx.Client
    monkeypatch.setattr(web_pdf.httpx, "Client", lambda **kwargs: cls(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(web_pdf.socket, "getaddrinfo", lambda *a,**k: [(2, 1, 6, "", ("8.8.8.8", 443))])


def test_download_approves_redirect_hosts_and_keeps_cookie_scope(monkeypatch):
    requests, approved = [], []
    def handler(request):
        requests.append(request)
        if request.url.host == "example.org":
            return httpx.Response(302, headers={"location": "https://cdn.example.net/download"})
        return httpx.Response(200, content=b"%PDF-test", headers={"content-disposition": 'attachment; filename="application.pdf"'})
    client_transport(monkeypatch, handler)
    content, name, url = web_pdf.download_pdf("https://example.org/document", approve=lambda u: approved.append(u) or True,
        cancelled=lambda: False, cookies=[{"name": "session", "value": "secret", "domain": "example.org"}], browser_host="example.org")
    assert content == b"%PDF-test"
    assert name == "application.pdf"
    assert len(approved) == 2
    assert "session=secret" in requests[0].headers["cookie"]
    assert "cookie" not in requests[1].headers


def test_unapproved_redirect_is_never_requested(monkeypatch):
    requested = []
    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://other.example.org/file.pdf"})
    client_transport(monkeypatch, handler)
    with pytest.raises(web_pdf.PdfDownloadCancelled):
        web_pdf.download_pdf("https://example.org/file.pdf", approve=lambda u: "other." not in u, cancelled=lambda: False)
    assert requested == ["https://example.org/file.pdf"]


@pytest.mark.parametrize("status,content", [(401,b"login"), (403,b"captcha"), (200,b"<html>Login</html>")])
def test_access_pages_pause_instead_of_becoming_pdf_templates(monkeypatch,status,content):
    client_transport(monkeypatch, lambda request: httpx.Response(status, content=content))
    with pytest.raises(web_pdf.PdfDownloadIntervention):
        web_pdf.download_pdf("https://example.org/file.pdf", approve=lambda u: True, cancelled=lambda: False)


def test_download_size_limit_and_private_network_restrictions(monkeypatch):
    client_transport(monkeypatch, lambda request: httpx.Response(200,content=b"%PDF-"+b"x"*200))
    monkeypatch.setattr(web_pdf,"MAX_PDF_BYTES",100)
    with pytest.raises(ValueError,match="limit"):
        web_pdf.download_pdf("https://example.org/file.pdf",approve=lambda u:True,cancelled=lambda:False)
    monkeypatch.setattr(web_pdf.socket,"getaddrinfo",lambda *a,**k:[(2,1,6,"",("127.0.0.1",443))])
    with pytest.raises(ValueError,match="private"):
        web_pdf.validate_download_url("https://example.org/file.pdf")
    assert web_pdf.validate_download_url("http://127.0.0.1:8000/test.pdf",local_origin="http://127.0.0.1:8000/forms")
    with pytest.raises(ValueError):
        web_pdf.validate_download_url("http://127.0.0.1:8001/test.pdf",local_origin="http://127.0.0.1:8000/forms")


def test_pending_pdf_approval_approves_target_not_current_browser_host(monkeypatch):
    from form_agent import agent
    run = agent.AgentRun("test","Download a PDF","https://source.example/forms")
    run.driver = SimpleNamespace(current_url=run.start_url)
    run.resume_event = SimpleNamespace(clear=lambda:None,wait=lambda timeout:True)
    monkeypatch.setattr(agent,"_bring_chrome_to_front",lambda d:True)
    assert agent._wait_for_user(run,"new_site","Review PDF host",approval_url="https://cdn.example/form.pdf?token=secret")
    assert "cdn.example" in run.approved_hosts
    assert "source.example" not in run.approved_hosts


@pytest.mark.parametrize("direct",[False,True])
def test_browser_discovers_downloads_fills_and_exposes_download_without_upload(monkeypatch,direct):
    from form_agent import agent,pdf_forms
    from test_pdf_forms import template_bytes,answer
    pdf_forms._templates.clear()
    pdf_forms._results.clear()
    start="https://example.org/form.pdf" if direct else "https://example.org/start"
    run=agent.AgentRun("test","Find and download the application PDF. Full name: Alex Morgan. Return the filled PDF.",start,mode="assist")
    class Driver:
        current_url="about:blank"
        closed=False
        visited=[]
        @property
        def page_source(self):
            return '<a href="/forms">Application forms</a>' if self.current_url.endswith('/start') else '<a href="/form.pdf">Application PDF</a>'
        def get(self,url):
            self.current_url=url
            self.visited.append(url)
        def get_cookies(self): return []
        def set_page_load_timeout(self,n): pass
        def quit(self): self.closed=True
    browser=Driver()
    class StopAfterReady:
        stopped=False
        def is_set(self): return self.stopped
        def wait(self,timeout):
            assert run.status=="pdf_ready"
            self.stopped=True
            return True
    run.stop_event=StopAfterReady()
    monkeypatch.setattr(agent,"_chrome_driver",lambda:browser)
    monkeypatch.setattr(agent,"inspect_page",lambda d:([],[],"Applications","",False))
    monkeypatch.setattr(agent,"choose_link",lambda prompt,title,links:links[0] if links else None)
    def download(url,**kwargs):
        assert kwargs['approve'](url)
        return template_bytes(pages=1),"application.pdf",url
    monkeypatch.setattr(agent,"download_pdf",download)
    monkeypatch.setattr(pdf_forms,"map_prompt_to_fields",lambda *a:{"name0":answer("Alex Morgan")})
    monkeypatch.setattr(agent,"map_prompt_to_fields",lambda *a:pytest.fail("PDF task must not fill the host website's inputs"))
    agent._run_browser(run)
    assert run.error is None
    assert run.status=="stopped"
    assert run.public()['pdf_result']['download_url'].startswith('/api/pdf/results/')
    result=pdf_forms.get_result(run.pdf_result['result_id'])
    assert PdfReader(io.BytesIO(result['content'])).get_fields()['name0']['/V']=='Alex Morgan'
    assert browser.closed
    if not direct:
        assert browser.visited==[start,'https://example.org/forms']
    assert not pdf_forms.list_templates()  # no template upload/selection required


def test_google_result_wrappers_and_extensionless_pdf_downloads():
    html = '<a href="/url?q=https%3A%2F%2Fissuer.example%2Fforms">Official application forms</a>' \
           '<a href="/search?q=other+form">Other form search</a>'
    links = web_pdf.collect_links(html, "https://www.google.com/search?q=application", set())
    assert [x["url"] for x in links] == ["https://issuer.example/forms"]
    html = '<div>Application form PDF <a download href="/download?id=123">Download</a></div>'
    links = web_pdf.collect_links(html, "https://issuer.example/forms", set())
    assert links[0]["pdf"]


def test_global_login_link_on_public_download_page_is_not_an_auth_gate():
    from form_agent.inspector import gate_reason
    assert gate_reason([], [{"label": "Sign in"}, {"label": "Download PDF"}], "Application forms", "", False) is None
