"""Fact prompt catalog loading and schema construction."""
from pathlib import Path
from typing import Any
import yaml


def load_prompts(path: Path) -> dict[str, dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("facts"), dict):
        raise ValueError("fact prompt catalog must use version 1")
    return payload["facts"]


def extraction_schema(key: str, fact_config: dict[str, Any]) -> dict[str, Any]:
    value_type = fact_config["value_type"]
    schema_type = {"bool": "boolean", "date": "string", "enum": "string", "string": "string", "number": "number"}[value_type]
    value_schema: dict[str, Any] = {"type": schema_type}
    if value_type == "date":
        value_schema["format"] = "date"
        if key == "litigation_commenced_on":
            value_schema = {"anyOf": [value_schema, {"type": "null"}]}
    if value_type == "enum":
        value_schema["enum"] = fact_config.get("allowed_values", [])
    return {"type": "object", "additionalProperties": False,
            "properties": {"key": {"const": key}, "value": value_schema,
                "status": {"enum": ["known", "unknown"]}, "quote": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
            "required": ["key", "value", "status", "quote", "confidence"]}
