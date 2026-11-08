"""Small protocol-compatible replay cache used by Track B extraction."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any, Protocol
import httpx


class LLMCacheMiss(RuntimeError):
    pass


class LLMResult(dict):
    """JSON-compatible LLM response with the shared protocol fields."""


class LLMClient(Protocol):
    def complete(self, *, role: str, system: str, messages: list[dict[str, Any]],
                 tools: list[dict] | None = None, response_schema: dict | None = None,
                 images: list[bytes] | None = None, max_tokens: int = 4096,
                 temperature: float = 0.0) -> LLMResult: ...


class ReplayClient:
    def __init__(self, cache_dir: Path, model: str):
        self.cache_dir, self.model = cache_dir, model

    def complete(self, *, role: str, system: str, messages: list[dict[str, Any]],
                 tools: list[dict] | None = None, response_schema: dict | None = None,
                 images: list[bytes] | None = None, max_tokens: int = 4096,
                 temperature: float = 0.0) -> LLMResult:
        request = {"role": role, "model": self.model, "system": system, "messages": messages,
                   "tools": tools, "response_schema": response_schema, "temperature": temperature,
                   "max_tokens": max_tokens,
                   "image_sha256s": [sha256(image).hexdigest() for image in images or []]}
        request_hash = sha256(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        path = self.cache_dir / f"{request_hash}.json"
        if not path.exists():
            raise LLMCacheMiss(f"replay cache entry missing for {request_hash}")
        result = json.loads(path.read_text(encoding="utf-8"))
        return LLMResult(text=result["text"], tool_calls=result.get("tool_calls", []), model=self.model,
                         input_tokens=result.get("input_tokens", 0), output_tokens=result.get("output_tokens", 0),
                         request_hash=request_hash)


class ProviderClient:
    def __init__(self, *, provider: str, api_key: str, base_url: str, model: str):
        if provider not in {"anthropic", "openai_compatible"}:
            raise ValueError("LLM_PROVIDER must be anthropic or openai_compatible")
        if not api_key or not base_url or not model:
            raise ValueError("LLM_API_KEY, LLM_BASE_URL, and role model are required")
        self.provider, self.api_key, self.base_url, self.model = provider, api_key, base_url.rstrip("/"), model
        self.client = httpx.Client(timeout=120.0)

    def complete(self, *, role: str, system: str, messages: list[dict[str, Any]],
                 tools: list[dict] | None = None, response_schema: dict | None = None,
                 images: list[bytes] | None = None, max_tokens: int = 4096,
                 temperature: float = 0.0) -> LLMResult:
        if images:
            raise ValueError("image inputs are not supported by the Track B extractor adapter")
        request = {"role": role, "model": self.model, "system": system, "messages": messages,
                   "tools": tools, "response_schema": response_schema, "temperature": temperature,
                   "max_tokens": max_tokens, "image_sha256s": []}
        request_hash = sha256(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        if self.provider == "openai_compatible":
            body = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages],
                    "temperature": temperature, "max_tokens": max_tokens}
            if response_schema:
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": "extraction", "strict": True, "schema": response_schema}}
            if tools:
                body["tools"] = tools
            url = self.base_url if self.base_url.endswith("/chat/completions") else self.base_url + "/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}"}
        else:
            body = {"model": self.model, "system": system, "messages": messages,
                    "max_tokens": max_tokens, "temperature": temperature}
            if response_schema:
                body["tools"] = [{"name": "structured_output", "description": "Return the required structured extraction.",
                                  "input_schema": response_schema}]
                body["tool_choice"] = {"type": "tool", "name": "structured_output"}
            url = self.base_url if self.base_url.endswith("/messages") else self.base_url + "/v1/messages"
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        response = None
        for attempt in range(4):
            try:
                response = self.client.post(url, json=body, headers=headers)
                if response.status_code not in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    break
                if attempt == 3:
                    response.raise_for_status()
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 3:
                    raise
            time.sleep((1, 4, 16)[attempt] if attempt < 3 else 16)
        payload = response.json()
        if self.provider == "openai_compatible":
            choice = payload["choices"][0]["message"]
            text_value = choice.get("content") or ""
            if not text_value and choice.get("tool_calls"):
                text_value = choice["tool_calls"][0]["function"]["arguments"]
            usage = payload.get("usage", {})
            input_tokens, output_tokens = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            tool_calls = choice.get("tool_calls", [])
        else:
            content = payload.get("content", [])
            tool_block = next((block for block in content if block.get("type") == "tool_use"), None)
            text_value = json.dumps(tool_block["input"], ensure_ascii=False) if tool_block else "".join(block.get("text", "") for block in content)
            usage = payload.get("usage", {})
            input_tokens, output_tokens = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            tool_calls = []
        return LLMResult(text=text_value, tool_calls=tool_calls, model=self.model,
                         input_tokens=input_tokens, output_tokens=output_tokens, request_hash=request_hash)


class CachedClient:
    def __init__(self, inner: LLMClient, cache_dir: Path, model: str, mode: str):
        self.inner, self.cache_dir, self.model, self.mode = inner, cache_dir, model, mode

    def complete(self, **kwargs: Any) -> LLMResult:
        request = {"role": kwargs["role"], "model": self.model, "system": kwargs["system"],
                   "messages": kwargs["messages"], "tools": kwargs.get("tools"),
                   "response_schema": kwargs.get("response_schema"), "temperature": kwargs.get("temperature", 0.0),
                   "max_tokens": kwargs.get("max_tokens", 4096),
                   "image_sha256s": [sha256(image).hexdigest() for image in kwargs.get("images") or []]}
        request_hash = sha256(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        path = self.cache_dir / f"{request_hash}.json"
        if self.mode == "replay":
            if not path.exists():
                raise LLMCacheMiss(f"replay cache entry missing for {request_hash}")
            result = json.loads(path.read_text(encoding="utf-8"))
            return LLMResult(text=result["text"], tool_calls=result.get("tool_calls", []), model=self.model,
                             input_tokens=result.get("input_tokens", 0), output_tokens=result.get("output_tokens", 0), request_hash=request_hash)
        result = self.inner.complete(**kwargs)
        result["request_hash"] = request_hash
        if self.mode == "record":
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


def create_client(*, mode: str, provider: str, api_key: str, base_url: str,
                  model: str, cache_dir: Path) -> LLMClient:
    if mode == "replay":
        return ReplayClient(cache_dir, model)
    inner = ProviderClient(provider=provider, api_key=api_key, base_url=base_url, model=model)
    return CachedClient(inner, cache_dir, model, mode)
