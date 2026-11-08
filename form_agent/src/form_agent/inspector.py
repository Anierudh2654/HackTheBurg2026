from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from form_agent.validation import field_value_matches


SKIP_TYPES = {"hidden", "password", "file", "submit", "button", "reset", "image"}
SKIP_LABELS = re.compile(r"captcha|verification code|one.time.passcode|password|passphrase|security code", re.I)
HUMAN_GATES = {
    "captcha": re.compile(r"captcha|recaptcha|hcaptcha|turnstile|verify you are human", re.I),
    "authentication": re.compile(r"sign in|log in|create an account|register|password", re.I),
    "consent": re.compile(r"i accept|acceptance disclaimer|agree to these terms|consent to these terms", re.I),
    "legal_attestation": re.compile(r"under penalty of perjury|certif(y|ication)|declaration|electronic signature", re.I),
}
FINAL_ACTION = re.compile(r"^(submit|submit tip|file|send|sign|e-sign|certify|finish|complete|confirm)$", re.I)
FORWARD_ACTION = {"next", "continue", "review", "review answers", "review submission"}
START_ACTION = {"start your tip", "start", "begin"}


@dataclass
class FormField:
    field_id: str
    locator_by: str
    locator_value: str
    tag: str
    field_type: str
    label: str
    placeholder: str
    required: bool
    options: list[str]
    already_filled: bool
    manual_only: bool = False
    choices: list[dict] | None = None
    multiple: bool = False

    def for_model(self) -> dict:
        return {
            "field_id": self.field_id,
            "tag": self.tag,
            "type": self.field_type,
            "label": self.label[:300],
            "placeholder": self.placeholder[:200],
            "required": self.required,
            "options": self.options[:100],
            "already_filled": self.already_filled,
            "manual_only": self.manual_only,
            "multiple": self.multiple,
        }


def _label_for(soup: BeautifulSoup, node) -> str:
    parts: list[str] = []
    node_id = node.get("id")
    if node_id:
        for label in soup.find_all("label", attrs={"for": node_id}):
            parts.append(label.get_text(" ", strip=True))
    ancestor = node.find_parent("label")
    if ancestor:
        parts.append(ancestor.get_text(" ", strip=True))
    for label_id in str(node.get("aria-labelledby", "")).split():
        labelled = soup.find(id=label_id)
        if labelled:
            parts.append(labelled.get_text(" ", strip=True))
    for attr in ("aria-label", "title"):
        if node.get(attr):
            parts.append(str(node.get(attr)))
    return " ".join(dict.fromkeys(p for p in parts if p))[:500]


def _choice_group_label(soup: BeautifulSoup, group_nodes: list, name: str) -> str:
    first = group_nodes[0]
    fieldset = first.find_parent("fieldset")
    legend = fieldset.find("legend") if fieldset else None
    if legend and legend.get_text(" ", strip=True):
        return legend.get_text(" ", strip=True)[:500]
    for node in group_nodes:
        labelled_by = str(node.get("aria-labelledby", "")).split()
        labels = [soup.find(id=label_id) for label_id in labelled_by]
        text = " ".join(label.get_text(" ", strip=True) for label in labels if label)
        if text:
            return text[:500]
        if node.get("aria-label"):
            return str(node.get("aria-label"))[:500]
        for ancestor in node.parents:
            if getattr(ancestor, "name", None) in {"fieldset", "form", "body", "html"}:
                break
            if getattr(ancestor, "get", lambda *_: None)("role") == "group":
                label = ancestor.get("aria-label")
                if label:
                    return str(label)[:500]
                labelled_by = str(ancestor.get("aria-labelledby", "")).split()
                labels = [soup.find(id=label_id) for label_id in labelled_by]
                text = " ".join(item.get_text(" ", strip=True) for item in labels if item)
                if text:
                    return text[:500]
    option_labels = [_label_for(soup, node) for node in group_nodes]
    for ancestor in first.parents:
        if getattr(ancestor, "name", None) in {"fieldset", "form", "body", "html"}:
            break
        if getattr(ancestor, "name", None) not in {"div", "section", "li", "tr", "td"}:
            continue
        text = ancestor.get_text(" ", strip=True)
        for option_label in option_labels:
            if option_label:
                text = re.sub(re.escape(option_label), " ", text, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip(" \t\r\n:;-")
        if len(text) >= 6 and text.casefold() != name.casefold():
            return text[:500]
    return name or "Choose an option"


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in value.split("'")) + ")"


def _choice_click_mode(driver, element, node_id: str) -> str | None:
    try:
        if element.is_displayed():
            return "input"
    except Exception:
        pass
    if node_id:
        try:
            labels = driver.find_elements(By.XPATH, f"//label[@for={_xpath_literal(node_id)}]")
            if any(label.is_displayed() and label.is_enabled() for label in labels):
                return "label_for"
        except Exception:
            pass
    try:
        labels = element.find_elements(By.XPATH, "ancestor::label[1]")
        if any(label.is_displayed() and label.is_enabled() for label in labels):
            return "ancestor_label"
    except Exception:
        pass
    return None


def inspect_page(driver) -> tuple[list[FormField], list[dict], str, str, bool]:
    """Extract visible form metadata; never returns existing field values."""
    source = driver.page_source
    soup = BeautifulSoup(source, "html.parser")
    body_text = soup.body.get_text(" ", strip=True) if soup.body else ""
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    password_present = False
    for password_element in driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]'):
        try:
            if password_element.is_displayed():
                password_present = True
                break
        except Exception:
            pass
    fields: list[FormField] = []
    nodes = soup.select("input, textarea, select")
    for index, node in enumerate(nodes):
        tag = node.name.lower()
        field_type = str(node.get("type", "text" if tag == "input" else tag)).lower()
        if field_type in SKIP_TYPES or node.has_attr("disabled") or node.has_attr("readonly"):
            continue
        if field_type in {"radio", "checkbox"}:
            continue
        node_id = str(node.get("id", ""))
        name = str(node.get("name", ""))
        if node_id:
            locator_by, locator_value = "id", node_id
            field_id = f"id:{node_id}"
        elif name:
            same_name = soup.find_all(attrs={"name": name})
            if len(same_name) != 1:
                if field_type not in {"radio", "checkbox"}:
                    continue
                group_key = f"name:{name}"
                if any(existing.field_id == group_key for existing in fields):
                    continue
            locator_by, locator_value = "name", name
            field_id = f"name:{name}"
        else:
            continue
        label = _label_for(soup, node)
        placeholder = str(node.get("placeholder", ""))
        if SKIP_LABELS.search(f"{label} {placeholder} {name} {node_id}"):
            continue
        try:
            element = driver.find_element(By.ID if locator_by == "id" else By.NAME, locator_value)
            if not element.is_displayed():
                continue
            existing = str(element.get_attribute("value") or "").strip()
            if tag == "textarea":
                existing = str(element.get_property("value") or "").strip()
            if tag == "select":
                options = [
                    option.text.strip() for option in Select(element).options
                    if option.text.strip()
                    and not option.get_attribute("disabled")
                    and str(option.get_attribute("value") or "").strip()
                ]
                option_keys = [re.sub(r"\s+", " ", option).strip().casefold()
                               for option in options]
                manual_only = len(option_keys) != len(set(option_keys))
                selected_options = Select(element).all_selected_options
                if Select(element).is_multiple:
                    existing = "selected" if selected_options else ""
                else:
                    current = selected_options[0] if selected_options else None
                    existing = str(current.get_attribute("value") or "").strip() if current else ""
            else:
                options = []
                manual_only = False
        except Exception:
            continue
        fields.append(FormField(
            field_id=field_id,
            locator_by=locator_by,
            locator_value=locator_value,
            tag=tag,
            field_type=field_type,
            label=label or placeholder or name or node_id or f"Field {index + 1}",
            placeholder=placeholder,
            required=node.has_attr("required") or node.get("aria-required") == "true",
            options=options,
            already_filled=bool(existing),
            manual_only=manual_only,
            multiple=bool(node.has_attr("multiple")),
        ))

    # Represent radio/checkbox controls as a single decision with labeled options.
    choice_groups: dict[tuple, list] = {}
    for node in nodes:
        choice_type = str(node.get("type", "")).lower()
        if choice_type not in {"radio", "checkbox"} or node.has_attr("disabled"):
            continue
        name = str(node.get("name", ""))
        form = node.find_parent("form")
        fieldset = node.find_parent("fieldset")
        node_id = str(node.get("id", ""))
        if choice_type == "radio" and name:
            group_key = (choice_type, "name", id(form), name)
        elif fieldset:
            group_key = (choice_type, "fieldset", id(fieldset))
        elif name:
            group_key = (choice_type, "name", id(form), name)
        elif node_id:
            group_key = (choice_type, "id", node_id)
        else:
            continue
        choice_groups.setdefault(group_key, []).append(node)

    for group_key, group_nodes in choice_groups.items():
        choice_type = group_key[0]
        first = group_nodes[0]
        name = str(first.get("name", ""))
        group_label = _choice_group_label(soup, group_nodes, name)
        choices: list[dict] = []
        selected = False
        required = False
        for option_index, option_node in enumerate(group_nodes):
            option_id = str(option_node.get("id", ""))
            option_name = str(option_node.get("name", ""))
            locator_by = "id" if option_id else "name"
            locator_value = option_id or option_name
            if not locator_value:
                continue
            option_label = _label_for(soup, option_node)
            if not option_label:
                continue
            named_choices = [
                candidate for candidate in soup.find_all("input", attrs={"name": option_name})
                if str(candidate.get("type", "")).lower() == choice_type
            ] if option_name else [option_node]
            locator_index = next((idx for idx, candidate in enumerate(named_choices)
                                  if candidate is option_node), 0)
            try:
                elements = driver.find_elements(By.ID if locator_by == "id" else By.NAME, locator_value)
                if locator_by == "id":
                    element = elements[0] if elements else None
                else:
                    option_value = str(option_node.get("value", "on"))
                    element = next((candidate for candidate in elements
                                    if str(candidate.get_attribute("value") or "on") == option_value), None)
                if element is None:
                    continue
                click_mode = _choice_click_mode(driver, element, option_id)
                if click_mode is None:
                    continue
                selected = selected or element.is_selected()
            except Exception:
                continue
            required = required or option_node.has_attr("required") or option_node.get("aria-required") == "true"
            choices.append({
                "label": option_label,
                "locator_by": locator_by,
                "locator_value": locator_value,
                "locator_index": locator_index,
                "value": str(option_node.get("value", "on")),
                "click_mode": click_mode,
            })
        if not choices:
            continue
        normalized_labels = [re.sub(r"\s+", " ", choice["label"]).strip().casefold()
                             for choice in choices]
        ambiguous_labels = len(normalized_labels) != len(set(normalized_labels))
        group_id = ":".join(str(part) for part in group_key[1:])
        fields.append(FormField(
            field_id=f"choice:{choice_type}:{group_id}",
            locator_by="choice",
            locator_value=group_id,
            tag="choice_group",
            field_type=choice_type,
            label=group_label[:500],
            placeholder="",
            required=required,
            options=[choice["label"] for choice in choices],
            already_filled=selected,
            manual_only=ambiguous_labels,
            choices=choices,
        ))

    navs: list[dict] = []
    for index, element in enumerate(driver.find_elements(By.XPATH, "//button|//input|//a")):
        try:
            if not element.is_displayed() or not element.is_enabled():
                continue
            tag = element.tag_name.lower()
            kind = (element.get_attribute("type") or "").lower()
            label = (element.text or element.get_attribute("value") or element.get_attribute("aria-label") or "").strip()
            label = re.sub(r"\s+", " ", label)
            if label:
                navs.append({"index": index, "tag": tag, "type": kind, "label": label[:160]})
        except Exception:
            continue
    return fields, navs, title, body_text, password_present


def gate_reason(fields: list[FormField], navs: list[dict], title: str, body_text: str,
                password_present: bool = False) -> str | None:
    text = f"{title} {body_text} " + " ".join(n["label"] for n in navs)
    if HUMAN_GATES["captcha"].search(text):
        return "captcha"
    auth_action = re.compile(
        r"\b(sign[ -]?in|log[ -]?in|sign[ -]?up|register|create (?:an? )?account|"
        r"reset (?:your )?password|change (?:your )?password)\b", re.I,
    )
    # A mixed form can include an optional password without being a login flow.
    # Password inputs themselves remain excluded from inspection and autofill.
    identity_label = re.compile(r"^(?:user(?:name)?|user name|e-?mail(?: address)?|phone(?: number)?|remember me)$", re.I)
    only_identity_fields = all(identity_label.fullmatch(f.label.strip()) for f in fields)
    auth_context = auth_action.search(title) or ((password_present or (bool(fields) and only_identity_fields)) and any(auth_action.search(n["label"]) for n in navs))
    if auth_context or (password_present and only_identity_fields):
        return "authentication"
    if HUMAN_GATES["consent"].search(text):
        return "consent"
    interactive_text = " ".join(f"{f.label} {f.placeholder}" for f in fields if not f.already_filled)
    interactive_text += " " + " ".join(n["label"] for n in navs)
    if HUMAN_GATES["legal_attestation"].search(interactive_text):
        return "legal_attestation"
    return None


def find_forward_action(navs: list[dict]) -> dict | None:
    for nav in navs:
        label = re.sub(r"\s+", " ", nav["label"]).strip().casefold()
        if FINAL_ACTION.fullmatch(label):
            continue
        if label in FORWARD_ACTION or label in START_ACTION:
            return nav
    return None


def is_review_page(navs: list[dict], title: str, body_text: str, *, allow_final_action: bool = True) -> bool:
    if re.search(r"\breview (your|the|submission|answers|information)\b", f"{title} {body_text[:500]}", re.I):
        return True
    return allow_final_action and any(FINAL_ACTION.fullmatch(n["label"].strip()) for n in navs)


def read_field_value(driver, field: FormField) -> str | list[str]:
    if field.tag == "choice_group":
        selected = []
        for choice in field.choices or []:
            locator = By.ID if choice["locator_by"] == "id" else By.NAME
            candidates = driver.find_elements(locator, choice["locator_value"])
            if choice["locator_by"] == "name":
                candidates = [candidate for candidate in candidates
                              if str(candidate.get_attribute("type") or "").lower() == field.field_type]
                index = int(choice.get("locator_index", 0))
                element = candidates[index] if index < len(candidates) else None
            else:
                element = candidates[0] if candidates else None
            if element is not None and element.is_selected():
                selected.append(choice["label"])
        return selected
    locator = By.ID if field.locator_by == "id" else By.NAME
    element = driver.find_element(locator, field.locator_value)
    if field.tag == "select":
        options = [option.text.strip() for option in Select(element).all_selected_options]
        return options if Select(element).is_multiple else (options[0] if options else "")
    value = element.get_property("value")
    return str(value if value is not None else "")


def fill_values(driver, fields: list[FormField], values: dict[str, str | list[str]]) -> tuple[list[str], list[str], list[str]]:
    filled: list[str] = []
    skipped: list[str] = []
    verification_failed: list[str] = []
    by_id = {f.field_id: f for f in fields}
    for field_id, value in values.items():
        field = by_id.get(field_id)
        if field is None or field.already_filled or field.manual_only or not value:
            skipped.append(field_id)
            continue
        try:
            if field.tag == "choice_group":
                selected_labels = value if isinstance(value, list) else [value]
                selected_norm = {re.sub(r"\s+", " ", str(v)).strip().casefold() for v in selected_labels}
                if field.field_type == "radio" and len(selected_norm) != 1:
                    skipped.append(field_id)
                    continue
                group_filled = False
                for choice in field.choices or []:
                    label_norm = re.sub(r"\s+", " ", choice["label"]).strip().casefold()
                    if label_norm not in selected_norm:
                        continue
                    locator = By.ID if choice["locator_by"] == "id" else By.NAME
                    candidates = driver.find_elements(locator, choice["locator_value"])
                    if choice["locator_by"] == "name":
                        candidates = [candidate for candidate in candidates
                                      if str(candidate.get_attribute("type") or "").lower() == field.field_type]
                        index = int(choice.get("locator_index", 0))
                        element = candidates[index] if index < len(candidates) else None
                    else:
                        element = candidates[0] if candidates else None
                    if element is None or element.is_selected():
                        continue
                    click_target = element
                    if choice.get("click_mode") == "label_for":
                        labels = driver.find_elements(
                            By.XPATH,
                            f"//label[@for={_xpath_literal(choice['locator_value'])}]",
                        )
                        click_target = next((label for label in labels
                                             if label.is_displayed() and label.is_enabled()), None)
                    elif choice.get("click_mode") == "ancestor_label":
                        labels = element.find_elements(By.XPATH, "ancestor::label[1]")
                        click_target = next((label for label in labels
                                             if label.is_displayed() and label.is_enabled()), None)
                    if click_target is None:
                        skipped.append(field_id)
                        continue
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", click_target)
                    click_target.click()
                    group_filled = True
                if group_filled and field_value_matches(field, value, read_field_value(driver, field)):
                    filled.append(field_id)
                elif group_filled:
                    skipped.append(field_id)
                    verification_failed.append(field_id)
                else:
                    skipped.append(field_id)
                continue
            element = driver.find_element(By.ID if field.locator_by == "id" else By.NAME, field.locator_value)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            if field.tag == "select":
                select = Select(element)
                if select.is_multiple:
                    for option in select.all_selected_options:
                        select.deselect_by_visible_text(option.text)
                    selected_values = value if isinstance(value, list) else [value]
                    for option_value in selected_values:
                        select.select_by_visible_text(str(option_value))
                else:
                    select.select_by_visible_text(str(value))
            else:
                element.clear()
                element.send_keys(value)
            if field_value_matches(field, value, read_field_value(driver, field)):
                filled.append(field_id)
            else:
                skipped.append(field_id)
                verification_failed.append(field_id)
        except Exception:
            skipped.append(field_id)
    return filled, skipped, verification_failed


def required_missing(fields: list[FormField]) -> list[str]:
    out = []
    for field in fields:
        if field.required and not field.already_filled:
            out.append(field.label)
    return out


def click_navigation(driver, nav: dict) -> None:
    # Resolve the exact visible node by label at click time; never press Enter.
    nodes = driver.find_elements(By.XPATH, "//button|//input|//a")
    element = nodes[nav["index"]]
    label = (element.text or element.get_attribute("value") or element.get_attribute("aria-label") or "").strip()
    label = re.sub(r"\s+", " ", label)
    if label.casefold() != nav["label"].casefold() or FINAL_ACTION.fullmatch(label):
        raise RuntimeError("Navigation control changed; stopping for user review")
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    element.click()

