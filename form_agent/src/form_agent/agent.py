from __future__ import annotations

import os
import re
import threading
import time
import uuid
import ctypes
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from form_agent.inspector import (
    click_navigation,
    find_forward_action,
    gate_reason,
    inspect_page,
    is_review_page,
    fill_values,
    required_missing,
)
from form_agent.mapper import map_prompt_to_fields
from form_agent.modes import (
    retain_pdf_grounded_answers,
    should_fill_form,
    validate_model_config,
    validate_run_mode,
)
from form_agent.pdf_rag import PdfDocument, get_documents, retrieve_context

load_dotenv()

PROFILE_DIR = Path(os.getenv("CHROME_PROFILE_DIR", ".browser_profile")).resolve()
MAX_PAGES = max(1, min(int(os.getenv("MAX_FORM_PAGES", "20")), 50))
SECRET_LIKE = re.compile(
    r"(?im)\b(password|passwd|passphrase|api[_ -]?key|access[_ -]?token|otp|one[- ]time code)\b\s*[:=]\s*\S+"
)
FICTIONAL_MARKERS = re.compile(r"\bfictional\b|\bsynthetic\b|\bdemo[- ]only\b|northwind media", re.I)
SEC_TCR_URL = "https://www.sec.gov/welcome-tips-complaints-and-referrals"
EXPLICIT_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
DOMAIN_URL = re.compile(
    r"(?<![@\w])(?:www\.)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
    r"(?:/[^\s<>\"']*)?",
    re.I,
)


def resolve_destination(prompt: str) -> tuple[str, str | None]:
    """Resolve a prompt-provided site; use a browser search for named sites."""
    if re.search(r"\bSEC\b", prompt, re.I) and re.search(
        r"\b(TCR|tips?|complaints?|referrals?|securities and exchange commission)\b",
        prompt, re.I,
    ):
        return SEC_TCR_URL, None
    explicit = EXPLICIT_URL.search(prompt)
    if explicit:
        return explicit.group(0).rstrip(".,;:!?)]}"), None
    domain = DOMAIN_URL.search(prompt)
    if domain:
        value = domain.group(0).rstrip(".,;:!?)]}")
        return (value if value.startswith(("http://", "https://")) else f"https://{value}"), None
    directive = re.search(
        r"\b(?:navigate|go|open|visit|browse)\s+to\s+(?:the\s+)?([^,;.!?\n]+)",
        prompt, re.I,
    )
    if directive:
        query = directive.group(1).strip().strip("'\"")
        query = re.split(r"\b(?:and then|then fill|using my|with my|using the attached)\b",
                         query, maxsplit=1, flags=re.I)[0].strip()
        if query:
            return f"https://www.google.com/search?q={quote_plus(query)}", query
    site_hint = re.search(
        r"\b(?:on|at|through|using)\s+(?:the\s+)?"
        r"([a-z0-9][a-z0-9&'. -]{0,50}?)\s+(?:website|site|portal|online form)\b",
        prompt, re.I,
    )
    if site_hint:
        query = site_hint.group(1).strip()
        if query and query.casefold() not in {"this", "that", "the", "a"}:
            return f"https://www.google.com/search?q={quote_plus(query)}", query
    raise ValueError("Tell the agent which site to open: include its URL/domain or say 'go to [site name]' in the prompt.")
def validate_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Enter a full http(s) form URL")
    if parsed.username or parsed.password:
        raise ValueError("Do not put credentials in the URL")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Only HTTPS websites are allowed")
    return url.strip()


def safe_display_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    try:
        if parsed.port:
            host = f"{host}:{parsed.port}"
    except ValueError:
        pass
    return f"{parsed.scheme}://{host}{parsed.path}"


@dataclass
class AgentRun:
    run_id: str
    prompt: str
    start_url: str
    target_query: str | None = None
    mode: str = "navigate_only"
    documents: list[PdfDocument] = field(default_factory=list, repr=False)
    status: str = "starting"
    message: str = "Starting visible Chrome"
    current_url: str = ""
    page_number: int = 0
    fields_seen: list[str] = field(default_factory=list)
    filled_fields: list[str] = field(default_factory=list)
    skipped_fields: list[str] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    retrieved_sources: list[dict] = field(default_factory=list)
    field_sources: list[dict] = field(default_factory=list)
    handoff_reason: str | None = None
    handoff_context: dict | None = None
    error: str | None = None
    events: list[dict] = field(default_factory=list)
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    resume_event: threading.Event = field(default_factory=threading.Event, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    driver: object | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)
    approved_hosts: set[str] = field(default_factory=set, repr=False)
    resolved_gates: set[tuple[str, str]] = field(default_factory=set, repr=False)

    def record(self, event: str, message: str) -> None:
        with self.lock:
            self.events.append({"time": time.strftime("%H:%M:%S"), "event": event, "message": message})
            self.events = self.events[-100:]
            self.message = message

    def public(self) -> dict:
        with self.lock:
            return {
                "run_id": self.run_id,
                "status": self.status,
                "message": self.message,
                "current_url": safe_display_url(self.current_url) if self.current_url else "",
                "destination_url": safe_display_url(self.start_url),
                "mode": self.mode,
                "page_number": self.page_number,
                "fields_seen": list(self.fields_seen),
                "filled_fields": list(self.filled_fields),
                "skipped_fields": list(self.skipped_fields),
                "required_missing": list(self.required_missing),
                "retrieved_sources": list(self.retrieved_sources),
                "field_sources": list(self.field_sources),
                "handoff_reason": self.handoff_reason,
                "handoff_context": dict(self.handoff_context) if self.handoff_context else None,
                "error": self.error,
                "events": list(self.events),
            }


_state_lock = threading.RLock()
_active: AgentRun | None = None


def active_run() -> AgentRun | None:
    with _state_lock:
        return _active


def start_run(prompt: str, document_ids: list[str] | None = None,
              mode: str = "navigate_only") -> AgentRun:
    global _active
    if not prompt.strip():
        raise ValueError("Enter a user prompt")
    if len(prompt) > 40000:
        raise ValueError("Prompt is too long (maximum 40,000 characters)")
    if SECRET_LIKE.search(prompt):
        raise ValueError("Remove passwords, API keys, tokens, OTPs, and other login secrets from the prompt")
    model = (os.getenv("LLM_MODEL") or os.getenv("NEBIUS_MODEL") or "").strip()
    key = (os.getenv("NEBIUS_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    url, target_query = resolve_destination(prompt)
    url = validate_url(url)
    documents = get_documents(document_ids or [])
    validate_run_mode(mode, url, bool(documents))
    validate_model_config(mode, model, key)
    with _state_lock:
        if _active and _active.status not in {"finished", "stopped", "error"}:
            raise ValueError("A browser run is already active")
        run = AgentRun(run_id=f"run_{uuid.uuid4().hex[:12]}", prompt=prompt,
                       start_url=url, target_query=target_query, mode=mode,
                       documents=documents)
        _active = run
    run.thread = threading.Thread(target=_run_browser, args=(run,), daemon=True, name=run.run_id)
    run.thread.start()
    return run


def resume_run() -> AgentRun:
    run = active_run()
    if not run or run.status != "waiting_user":
        raise ValueError("There is no user handoff waiting to resume")
    with run.lock:
        run.handoff_reason = None
        run.status = "running"
    run.resume_event.set()
    return run


def stop_run() -> AgentRun:
    run = active_run()
    if not run:
        raise ValueError("No browser run exists")
    run.stop_event.set()
    run.resume_event.set()
    with run.lock:
        run.status = "stopping"
        run.message = "Stopping the browser session"
    if not run.thread or not run.thread.is_alive():
        if run.driver:
            try:
                run.driver.quit()
            except WebDriverException:
                pass
        with run.lock:
            run.status = "stopped"
            run.message = "Browser session stopped"
    return run


def _bring_chrome_to_front(driver) -> bool:
    if not driver:
        return False
    try:
        driver.switch_to.window(driver.current_window_handle)
        driver.execute_script("window.focus();")
    except WebDriverException:
        pass
    if os.name != "nt":
        return True
    try:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        page_title = str(driver.title or "").strip().casefold()
        if not page_title:
            return False
        matches: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.AttachThreadInput.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.BOOL
        ]
        user32.AttachThreadInput.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        def visit(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if user32.IsWindowVisible(hwnd) and page_title in title.value.casefold():
                matches.append(hwnd)
                return False
            return True

        callback = callback_type(visit)
        user32.EnumWindows(callback, 0)
        if matches:
            target = matches[0]
            foreground = user32.GetForegroundWindow()
            process_id = wintypes.DWORD()
            foreground_thread = user32.GetWindowThreadProcessId(
                foreground, ctypes.byref(process_id)
            ) if foreground else 0
            target_thread = user32.GetWindowThreadProcessId(
                target, ctypes.byref(process_id)
            )
            current_thread = kernel32.GetCurrentThreadId()
            attached: list[int] = []
            for thread_id in {foreground_thread, target_thread} - {0, current_thread}:
                if user32.AttachThreadInput(current_thread, thread_id, True):
                    attached.append(thread_id)
            try:
                if user32.IsIconic(target):
                    user32.ShowWindow(target, 9)  # SW_RESTORE only when minimized
                else:
                    user32.ShowWindow(target, 5)  # SW_SHOW preserves its size/state
                user32.BringWindowToTop(target)
                user32.SetForegroundWindow(target)
                user32.SetActiveWindow(target)
                user32.SetFocus(target)
            finally:
                for thread_id in attached:
                    user32.AttachThreadInput(current_thread, thread_id, False)
            return user32.GetForegroundWindow() == target
        return False
    except Exception:
        # OS foreground-window policies can prevent focus changes; keep the
        # Selenium tab selected and let the dashboard identify the handoff.
        return False


def _wait_for_user(run: AgentRun, reason: str, message: str,
                   fields=None, navs=None, title: str = "") -> bool:
    chrome_focused = _bring_chrome_to_front(run.driver)
    if not chrome_focused:
        message += " Chrome could not be confirmed in front; use Alt+Tab to switch to its window."
    current_url = getattr(run.driver, "current_url", "") if run.driver else run.current_url
    context_fields = []
    for item in fields or []:
        context_fields.append({
            "label": item.label,
            "required": item.required,
            "options": list(item.options),
            "already_filled": item.already_filled,
            "manual_only": item.manual_only,
        })
    with run.lock:
        run.status = "waiting_user"
        run.handoff_reason = reason
        run.handoff_context = {
            "url": safe_display_url(current_url) if current_url else "",
            "title": title,
            "inspected": fields is not None,
            "chrome_focused": chrome_focused,
            "fields": context_fields,
            "missing_required": [item.label for item in fields or []
                                 if item.required and not item.already_filled],
            "controls": [item.get("label", "") for item in (navs or []) if item.get("label")][:30],
        }
        run.record("handoff", message)
        run.resume_event.clear()
    while not run.stop_event.is_set():
        if run.resume_event.wait(timeout=1):
            run.resume_event.clear()
            current = getattr(run.driver, "current_url", "") if run.driver else ""
            host = (urlparse(current).hostname or "").lower()
            if host:
                run.approved_hosts.add(host)
            if current:
                run.resolved_gates.add((current, reason))
            with run.lock:
                run.status = "running"
                run.handoff_reason = None
                run.handoff_context = None
            run.record("resumed", "Continuing after user intervention")
            return True
    return False


def _host_is_approved(run: AgentRun, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in run.approved_hosts:
        return True
    # SEC's official welcome page can move to an SEC subdomain for its TCR portal.
    if urlparse(run.start_url).hostname in {"www.sec.gov", "sec.gov"}:
        return host == "sec.gov" or host.endswith(".sec.gov")
    return False


def _chrome_driver():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--no-first-run")
    # Visible Chrome is intentional: the user must handle consent and access gates.
    return webdriver.Chrome(options=options)


def _click_and_wait(driver, nav: dict, old_url: str) -> bool:
    old_source = driver.page_source
    old_handles = set(driver.window_handles)
    click_navigation(driver, nav)
    try:
        WebDriverWait(driver, 30).until(
            lambda d: d.current_url != old_url
            or set(d.window_handles) != old_handles
            or d.page_source != old_source
        )
    except TimeoutException:
        return False
    new_handles = set(driver.window_handles) - old_handles
    if new_handles:
        driver.switch_to.window(sorted(new_handles)[-1])
    return True


def _open_best_search_result(driver, query: str) -> str | None:
    """Open the highest-overlap external Google result for a user-named site."""
    words = {word for word in re.findall(r"[a-z0-9]+", query.casefold())
             if len(word) > 2 and word not in {"the", "and", "for", "form", "website", "site"}}
    candidates = []
    try:
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href^='http']")
        for index, anchor in enumerate(anchors):
            if not anchor.is_displayed() or not anchor.is_enabled():
                continue
            href = str(anchor.get_attribute("href") or "")
            parsed = urlparse(href)
            host = (parsed.hostname or "").lower()
            if host in {"google.com", "www.google.com"} and parsed.path == "/url":
                target = parse_qs(parsed.query).get("q", [""])[0]
                if target:
                    href = target
                    parsed = urlparse(href)
                    host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not host or host == "google.com" or host.endswith(".google.com"):
                continue
            label = re.sub(r"\s+", " ", (anchor.text or "").strip())
            if not label:
                try:
                    heading = anchor.find_element(By.CSS_SELECTOR, "h3")
                    label = re.sub(r"\s+", " ", heading.text.strip())
                except Exception:
                    continue
            haystack = f"{label} {host} {parsed.path}".casefold()
            overlap = len(words & set(re.findall(r"[a-z0-9]+", haystack)))
            if words and overlap == 0:
                continue
            score = overlap * 10 - index * 0.01
            if host.endswith(".gov"):
                score += 1
            candidates.append((score, index, anchor, href, label, host))
    except WebDriverException:
        return None
    if not candidates:
        return None
    _, _, chosen, href, label, host = max(candidates, key=lambda item: item[0])
    old_url = driver.current_url
    old_source = driver.page_source
    old_handles = set(driver.window_handles)
    try:
        chosen.click()
        WebDriverWait(driver, 20).until(
            lambda d: d.current_url != old_url
            or set(d.window_handles) != old_handles
            or d.page_source != old_source
        )
        new_handles = set(driver.window_handles) - old_handles
        if new_handles:
            driver.switch_to.window(sorted(new_handles)[-1])
        return f"{safe_display_url(driver.current_url)} · {label} ({host})"
    except (TimeoutException, WebDriverException):
        try:
            driver.get(href)
            return f"{safe_display_url(driver.current_url)} · {label} ({host})"
        except WebDriverException:
            return None


def _find_task_navigation(navs: list[dict], prompt: str) -> dict | None:
    prompt_words = set(re.findall(r"[a-z0-9]+", prompt.casefold()))
    ignored = {"the", "and", "for", "with", "from", "that", "this", "please", "form",
               "site", "website", "page", "open", "navigate", "go", "fill", "complete",
               "help", "using", "information", "details"}
    prompt_terms = prompt_words - ignored
    form_intent = bool(re.search(
        r"\b(form|application|apply|complaint|tip|report|claim|permit|request|filing)\b",
        prompt, re.I,
    ))
    action_terms = {"start", "begin", "apply", "application", "form", "complaint",
                    "report", "request", "continue", "get", "started", "file"}
    ranked = []
    for nav in navs:
        label = re.sub(r"\s+", " ", str(nav.get("label", ""))).strip()
        folded = label.casefold()
        if not label or FINAL_ACTION.fullmatch(label):
            continue
        words = set(re.findall(r"[a-z0-9]+", folded))
        overlap = len(words & prompt_terms)
        action_match = bool(words & action_terms)
        score = overlap * 3
        if form_intent and action_match:
            score += 3
        if folded in {"start", "begin", "get started", "start now", "apply now"} and form_intent:
            score += 2
        if score >= 3:
            ranked.append((score, nav))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def _run_browser(run: AgentRun) -> None:
    driver = None
    try:
        run.record("browser", "Launching visible Chrome through Selenium Manager")
        driver = _chrome_driver()
        run.driver = driver
        driver.set_page_load_timeout(60)
        if run.stop_event.is_set():
            with run.lock:
                run.status = "stopped"
                run.message = "Browser session stopped before navigation"
            return
        driver.get(run.start_url)
        run.approved_hosts.add((urlparse(run.start_url).hostname or "").lower())

        for page_no in range(1, MAX_PAGES + 1):
            if run.stop_event.is_set():
                break
            run.page_number = page_no
            url = driver.current_url
            run.current_url = url
            host = (urlparse(url).hostname or "").lower()
            if not _host_is_approved(run, url):
                if not _wait_for_user(run, "new_site", f"Chrome opened {host}. Review the destination and press Resume to authorize this site for this run."):
                    break
                continue
            if run.mode == "sec_pdf_assist" and (host == "sec.gov" or host.endswith(".sec.gov")) and FICTIONAL_MARKERS.search(run.prompt):
                raise RuntimeError("Refusing to enter fictional/demo facts into the live SEC TCR system. Test only with truthful information on a live government form.")

            fields, navs, title, body, password_present = inspect_page(driver)
            reason = gate_reason(fields, navs, title, body, password_present)
            if reason and (url, reason) not in run.resolved_gates:
                messages = {
                    "captcha": "CAPTCHA detected. Solve it yourself in Chrome, then press Resume.",
                    "authentication": "Login or account setup detected. Complete it yourself in Chrome, then press Resume.",
                    "consent": "Site terms or consent detected. Read and accept/reject it yourself in Chrome, then press Resume.",
                    "legal_attestation": "A legal declaration or certification is present. Review and complete it yourself, then press Resume.",
                }
                if not _wait_for_user(run, reason, messages[reason], fields, navs, title):
                    break
                continue

            if run.target_query and host in {"google.com", "www.google.com"} and urlparse(url).path == "/search":
                result = _open_best_search_result(driver, run.target_query)
                if not result:
                    if not _wait_for_user(
                        run, "search_result",
                        "I couldn't identify a matching search result. Choose the intended site in Chrome, then press Resume.",
                        fields, navs, title,
                    ):
                        break
                    run.target_query = None
                    continue
                run.target_query = None
                run.record("navigation", f"Opened the closest search result: {result}")
                time.sleep(0.6)
                continue

            if is_review_page(navs, title, body):
                chrome_focused = _bring_chrome_to_front(driver)
                with run.lock:
                    run.status = "review_ready"
                    run.handoff_reason = "review"
                    run.handoff_context = {
                        "url": safe_display_url(url), "title": title,
                        "inspected": True,
                        "chrome_focused": chrome_focused,
                        "fields": [{"label": f.label, "required": f.required,
                                    "options": list(f.options), "already_filled": f.already_filled,
                                    "manual_only": f.manual_only} for f in fields],
                        "controls": [n["label"] for n in navs if n.get("label")][:30],
                    }
                review_message = "Review/final-action page reached. Chrome is paused; no final action was clicked."
                if not chrome_focused:
                    review_message += " Use Alt+Tab to switch to the Chrome window."
                run.record("review", review_message)
                while not run.stop_event.wait(0.5):
                    pass
                break

            if "welcome-tips-complaints-and-referrals" in url:
                start_action = next((n for n in navs if n["label"].strip().casefold() == "start your tip"), None)
                if start_action:
                    if not _click_and_wait(driver, start_action, url):
                        if not _wait_for_user(run, "start_navigation", "The Start Your Tip link did not advance. Inspect Chrome and continue manually, then press Resume.", fields, navs, title):
                            break
                        continue
                    time.sleep(0.6)
                    continue

            if not fields:
                start_action = next((n for n in navs if n["label"].strip().casefold() in {"start your tip", "start", "begin"}), None)
                if not start_action:
                    start_action = _find_task_navigation(navs, run.prompt)
                if start_action:
                    if not _click_and_wait(driver, start_action, url):
                        if not _wait_for_user(run, "start_navigation", f"Couldn't open “{start_action['label']}” automatically. Inspect Chrome and continue manually, then press Resume.", fields, navs, title):
                            break
                        continue
                    time.sleep(0.6)
                    continue
                if not _wait_for_user(run, "page_action", "No supported form fields were found. Inspect Chrome and navigate to the form, then press Resume.", fields, navs, title):
                    break
                continue

            run.fields_seen = [
                f"{item.label}{' [required]' if item.required else ''}"
                + (f" — options: {', '.join(item.options)}" if item.options else "")
                for item in fields
            ]
            run.record("inspect", f"Inspected {len(fields)} visible text/select fields on page {page_no}")
            if not should_fill_form(run.mode):
                chrome_focused = _bring_chrome_to_front(driver)
                with run.lock:
                    run.status = "form_ready"
                    run.handoff_reason = "form_found"
                    run.handoff_context = {
                        "url": safe_display_url(url), "title": title,
                        "inspected": True, "chrome_focused": chrome_focused,
                        "fields": [{"label": f.label, "required": f.required,
                                    "options": list(f.options), "already_filled": f.already_filled,
                                    "manual_only": f.manual_only} for f in fields],
                        "controls": [n["label"] for n in navs if n.get("label")][:30],
                    }
                message = "Relevant form reached. Navigation-only mode has not changed any fields. Review the page; stop the run when finished."
                if not chrome_focused:
                    message += " Use Alt+Tab to switch to the Chrome window."
                run.record("form_ready", message)
                while not run.stop_event.wait(0.5):
                    pass
                break

            model_fields = [f.for_model() for f in fields if not f.already_filled and not f.manual_only]
            try:
                retrieved = retrieve_context(run.documents, run.prompt, model_fields)
                run.retrieved_sources = [
                    {"filename": c["filename"], "page": c["page"], "score": c["score"],
                     "excerpt": c["text"][:220]}
                    for c in retrieved
                ]
                answers = map_prompt_to_fields(run.prompt, model_fields, retrieved)
            except Exception as exc:
                raise RuntimeError(f"Field mapping failed: {exc}") from exc
            ungrounded_ids: list[str] = []
            if run.mode == "sec_pdf_assist":
                answers, ungrounded_ids = retain_pdf_grounded_answers(answers)
            values = {field_id: answer["value"] for field_id, answer in answers.items()}
            filled_ids, skipped_ids, verification_failed_ids = fill_values(driver, fields, values)
            skipped_ids = list(dict.fromkeys([*skipped_ids, *ungrounded_ids]))
            field_by_id = {f.field_id: f for f in fields}
            filled = [field_by_id[field_id].label for field_id in filled_ids if field_id in field_by_id]
            skipped = [field_by_id.get(field_id).label if field_id in field_by_id else field_id
                       for field_id in skipped_ids]
            run.filled_fields.extend(label for label in filled if label not in run.filled_fields)
            run.skipped_fields = skipped
            for field_id in filled_ids:
                field = field_by_id.get(field_id)
                answer = answers.get(field_id)
                if field and answer:
                    source = answer["source"]
                    run.field_sources = [item for item in run.field_sources if item["field"] != field.label]
                    run.field_sources.append({
                        "field": field.label, "filename": source["filename"],
                        "page": source["page"], "source_type": source["type"],
                        "value": answer["value"],
                        "quote": source["quote"][:220],
                        "choice_reason": answer.get("choice_reason", ""),
                    })
            run.record("fill", f"Filled {len(filled)} field(s) from prompt/PDF excerpts; left unsupported fields unchanged")

            # Reinspect after fill: reaching the final review page always halts here.
            fields_after, navs_after, title_after, body_after, _ = inspect_page(driver)
            if verification_failed_ids:
                failed_labels = [field_by_id[field_id].label for field_id in verification_failed_ids
                                 if field_id in field_by_id]
                run.record("write_verification_failed", f"Browser read-back did not match requested values for: {', '.join(failed_labels)}")
                if not _wait_for_user(run, "write_verification", "A field value did not match its requested value when independently read back. Inspect the page and correct or clear it, then press Resume.", fields_after, navs_after, title_after):
                    break
                continue
            if is_review_page(navs_after, title_after, body_after):
                chrome_focused = _bring_chrome_to_front(driver)
                with run.lock:
                    run.status = "review_ready"
                    run.handoff_reason = "review"
                    run.handoff_context = {
                        "url": safe_display_url(driver.current_url), "title": title_after,
                        "inspected": True,
                        "chrome_focused": chrome_focused,
                        "fields": [{"label": f.label, "required": f.required,
                                    "options": list(f.options), "already_filled": f.already_filled,
                                    "manual_only": f.manual_only} for f in fields_after],
                        "controls": [n["label"] for n in navs_after if n.get("label")][:30],
                    }
                review_message = "Review/final-action page reached. Chrome is paused; no final action was clicked."
                if not chrome_focused:
                    review_message += " Use Alt+Tab to switch to the Chrome window."
                run.record("review", review_message)
                while not run.stop_event.wait(0.5):
                    pass
                break

            missing = required_missing(fields_after)
            run.required_missing = missing
            forward = find_forward_action(navs_after)
            if missing:
                run.record("required_fields", f"Required fields left blank: {', '.join(missing[:10])}")
                if not _wait_for_user(run, "missing_required_fields", "Fill any missing required fields in Chrome, then press Resume. Missing values were not guessed.", fields_after, navs_after, title_after):
                    break
                continue
            if forward:
                if not _click_and_wait(driver, forward, url):
                    if not _wait_for_user(run, "forward_navigation", "The page did not advance. Resolve the page's validation message or continue manually, then press Resume.", fields_after, navs_after, title_after):
                        break
                    continue
                time.sleep(0.6)
                continue
            if not _wait_for_user(run, "manual_navigation", "No safe Next/Continue/Review control was found. Use the site's own forward navigation in Chrome, then press Resume.", fields_after, navs_after, title_after):
                break

        with run.lock:
            if run.status != "review_ready":
                run.status = "stopped" if run.stop_event.is_set() else "finished"
                if run.status == "finished":
                    run.message = "Page limit reached; browser session closed without submitting."
    except Exception as exc:
        with run.lock:
            run.status = "error"
            safe_error = str(exc)
            for unsafe_url in (run.start_url, getattr(driver, "current_url", "") if driver else ""):
                if unsafe_url:
                    safe_error = safe_error.replace(unsafe_url, safe_display_url(unsafe_url))
            run.error = f"{type(exc).__name__}: {safe_error[:500]}"
            run.record("error", run.error)
    finally:
        # Keep Chrome open at review or error so the user can inspect the state.
        if driver and run.status not in {"review_ready", "form_ready", "error"}:
            try:
                driver.quit()
            except WebDriverException:
                pass

