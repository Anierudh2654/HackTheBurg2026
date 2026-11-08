from __future__ import annotations

import re
import unicodedata


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value)).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", value).strip().casefold()


def field_value_matches(field: object, expected: str | list[str], actual: str | list[str]) -> bool:
    """Compare a requested field value to an independent browser read-back."""
    field_tag = getattr(field, "tag", "")
    field_type = getattr(field, "field_type", "")
    multi = (field_tag == "choice_group" and field_type == "checkbox") or bool(
        getattr(field, "multiple", False)
    )
    expected_values = expected if isinstance(expected, list) else [expected]
    actual_values = actual if isinstance(actual, list) else [actual]
    expected_norm = {_normalize(value) for value in expected_values if str(value).strip()}
    actual_norm = {_normalize(value) for value in actual_values if str(value).strip()}
    if not expected_norm:
        return False
    if multi:
        return expected_norm == actual_norm
    return len(expected_norm) == 1 and expected_norm == actual_norm
