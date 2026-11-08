"""Registry loader and outbound URL policy."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import date
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml


class RateLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests_per_second: float = Field(ge=0)
    burst: int = Field(ge=0)
    max_concurrent: int = Field(ge=0)


class RegistryEntryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str
    role: str
    authoritative: bool
    base_domains: list[str]
    url_prefixes: list[str]
    doc_types: list[str]
    access: str
    requires_login: bool
    rate_limit: RateLimit
    robots_respect: bool
    allowed_action_classes: list[str]
    terms_verified: bool
    terms_url: str | None = None
    terms_checked_on: date | None = None
    phase: str

    @field_validator("role")
    @classmethod
    def role_value(cls, value: str) -> str:
        if value not in {"primary", "crosscheck"}:
            raise ValueError("role must be primary or crosscheck")
        return value

    @field_validator("access")
    @classmethod
    def access_value(cls, value: str) -> str:
        if value not in {"api", "bulk", "adapter", "operator"}:
            raise ValueError("invalid registry access")
        return value

    @field_validator("phase")
    @classmethod
    def phase_value(cls, value: str) -> str:
        if value not in {"MVP", "P6", "optional"}:
            raise ValueError("invalid registry phase")
        return value

    @model_validator(mode="after")
    def validate_terms_and_prefixes(self):
        if self.terms_verified and not (self.terms_url and self.terms_checked_on):
            raise ValueError("verified terms require terms_url and terms_checked_on")
        if not self.base_domains or not self.url_prefixes:
            raise ValueError("registry entry requires at least one domain and URL prefix")
        for prefix in self.url_prefixes:
            parsed = urlparse(prefix)
            if parsed.scheme != "https" or parsed.hostname not in self.base_domains:
                raise ValueError(f"URL prefix host must be listed in base_domains: {prefix}")
        return self


@dataclass(frozen=True)
class RegistryEntry:
    data: dict

    @property
    def entry_id(self) -> str:
        return str(self.data["entry_id"])

    def permits(self, url: str) -> bool:
        return any(url.startswith(prefix) for prefix in self.data["url_prefixes"])


class Registry:
    def __init__(self, entries: list[dict]):
        validated = [RegistryEntryModel.model_validate(entry).model_dump(mode="json") for entry in entries]
        self.entries = {str(e["entry_id"]): RegistryEntry(e) for e in validated}
        if len(self.entries) != len(entries):
            raise ValueError("registry entry_id values must be unique")

    @classmethod
    def load(cls, path: Path) -> "Registry":
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or not isinstance(payload.get("entries"), list):
            raise ValueError("registry.yaml must have version 1 and an entries list")
        return cls(payload["entries"])

    def require_url(self, entry_id: str, url: str) -> RegistryEntry:
        entry = self.entries.get(entry_id)
        if entry is None or not entry.permits(url):
            raise ValueError("URL_NOT_IN_REGISTRY")
        return entry

    def public_json(self) -> dict:
        return {"version": 1, "entries": [entry.data for entry in self.entries.values()]}
