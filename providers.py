#!/usr/bin/env python3
"""Provider-neutral model boundary with a stdlib OpenAI-compatible adapter."""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Protocol, Sequence
from urllib.parse import quote, urlparse

from process_runner import run_bounded_process


@dataclass(frozen=True)
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str = "unknown"
    model: str = "unknown"


class Provider(Protocol):
    model: str

    def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.1,
        max_output_tokens: Optional[int] = None,
    ) -> ModelResponse:
        ...


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        retryable: bool = False,
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        try:
            delay = float(retry_after_seconds) if retry_after_seconds is not None else None
        except (TypeError, ValueError):
            delay = None
        self.retry_after_seconds = (
            delay if delay is not None and math.isfinite(delay) and delay >= 0 else None
        )


_TRANSIENT_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def _validate_http_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.username or parsed.password:
        raise ValueError("credentials are not allowed in base_url")
    if not parsed.hostname:
        raise ValueError("provider endpoint requires a hostname")
    if parsed.query or parsed.fragment:
        raise ValueError("provider base_url must not contain a query or fragment")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in local_hosts
    ):
        raise ValueError("provider endpoint must use HTTPS unless it is localhost")
    return base_url.rstrip("/")


def _redact(value: object, secret: str) -> str:
    message = str(value or "provider request failed")
    if secret:
        message = message.replace(secret, "<redacted>")
    return message[:1000]


def _error_text(raw: bytes, secret: str) -> str:
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        error = payload.get("error", payload) if isinstance(payload, dict) else payload
        if isinstance(error, dict):
            return _redact(error.get("message") or error.get("detail") or error, secret)
        return _redact(error, secret)
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return _redact(raw.decode("utf-8", errors="replace"), secret)


def _post_json(
    *,
    endpoint: str,
    payload: Dict[str, object],
    headers: Dict[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
    secret: str,
) -> Dict[str, object]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(max_response_bytes + 1)
    except urllib.error.HTTPError as exc:
        raw = exc.read(max_response_bytes + 1)
        status = int(exc.code)
        if len(raw) > max_response_bytes:
            raw = b"provider error response exceeded the size limit"
        raise ProviderError(
            _error_text(raw, secret),
            status_code=status,
            retryable=status in _TRANSIENT_STATUS_CODES,
            retry_after_seconds=_parse_retry_after(exc.headers.get("Retry-After")),
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(
            _redact(getattr(exc, "reason", exc), secret),
            retryable=True,
        ) from None
    if len(raw) > max_response_bytes:
        raise ProviderError("provider response exceeded the size limit", retryable=False)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError("malformed provider JSON response", retryable=False) from None
    if not isinstance(data, dict):
        raise ProviderError("malformed provider JSON response", retryable=False)
    return data


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            return max(0.0, retry_at.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


class OpenAICompatibleProvider:
    """Call any OpenAI-compatible `/chat/completions` endpoint."""

    _TRANSIENT_STATUS_CODES = _TRANSIENT_STATUS_CODES

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
        extra_headers: Optional[Dict[str, str]] = None,
        max_response_bytes: int = 4_000_000,
    ) -> None:
        if not base_url or not model:
            raise ValueError("base_url and model are required")
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        if max_response_bytes < 1:
            raise ValueError("timeout_seconds and max_response_bytes must be positive")

        self.api_key = api_key or ""
        self.base_url = _validate_http_base_url(base_url)
        self.model = model
        self.timeout_seconds = float(timeout_seconds)
        self.extra_headers = dict(extra_headers or {})
        self.max_response_bytes = int(max_response_bytes)

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleProvider(base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key='<redacted>')"
        )

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _safe_message(self, value: str) -> str:
        message = value or "provider request failed"
        if self.api_key:
            message = message.replace(self.api_key, "<redacted>")
        return message[:1000]

    def _error_message_from_body(self, raw: bytes) -> str:
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            error = payload.get("error", payload)
            if isinstance(error, dict):
                return self._safe_message(str(error.get("message") or error.get("detail") or error))
            return self._safe_message(str(error))
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return self._safe_message(raw.decode("utf-8", errors="replace"))

    def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.1,
        max_output_tokens: Optional[int] = None,
    ) -> ModelResponse:
        if not messages:
            raise ValueError("messages must not be empty")
        payload: Dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_output_tokens is not None:
            payload["max_tokens"] = int(max_output_tokens)

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    raise ProviderError(
                        "provider response exceeded the size limit",
                        retryable=False,
                    )
        except urllib.error.HTTPError as exc:
            raw = exc.read(self.max_response_bytes + 1)
            status = int(exc.code)
            if len(raw) > self.max_response_bytes:
                raw = b"provider error response exceeded the size limit"
            raise ProviderError(
                self._error_message_from_body(raw),
                status_code=status,
                retryable=status in self._TRANSIENT_STATUS_CODES,
                retry_after_seconds=_parse_retry_after(exc.headers.get("Retry-After")),
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(
                self._safe_message(str(getattr(exc, "reason", exc))),
                retryable=True,
            ) from None

        try:
            data = json.loads(raw.decode("utf-8"))
            message = data["choices"][0]["message"]
            content = message["content"]
            if isinstance(content, list):
                content = "".join(
                    str(item.get("text", "")) for item in content if isinstance(item, dict)
                )
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
            output_tokens = int(
                usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(
                f"Malformed provider response: {type(exc).__name__}", retryable=False
            ) from None

        return ModelResponse(
            text=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider="openai-compatible",
            model=self.model,
        )


class AnthropicProvider:
    """Native adapter for Anthropic's Messages API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 120.0,
        default_max_output_tokens: int = 8192,
        anthropic_version: str = "2023-06-01",
        max_response_bytes: int = 4_000_000,
    ) -> None:
        if not api_key or not model:
            raise ValueError("api_key and model are required")
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        if default_max_output_tokens < 1 or max_response_bytes < 1:
            raise ValueError("timeouts, output limits, and response limits must be positive")
        self.api_key = api_key
        self.model = model
        self.base_url = _validate_http_base_url(base_url)
        self.timeout_seconds = float(timeout_seconds)
        self.default_max_output_tokens = int(default_max_output_tokens)
        self.anthropic_version = anthropic_version
        self.max_response_bytes = int(max_response_bytes)

    def __repr__(self) -> str:
        return (
            f"AnthropicProvider(base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key='<redacted>')"
        )

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/v1/messages"):
            return self.base_url
        return f"{self.base_url}/v1/messages"

    def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.1,
        max_output_tokens: Optional[int] = None,
    ) -> ModelResponse:
        if not messages:
            raise ValueError("messages must not be empty")
        system_parts = []
        api_messages = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if not isinstance(content, str):
                raise ValueError("message content must be text")
            if role == "system":
                system_parts.append(content)
            elif role in {"user", "assistant"}:
                api_messages.append({"role": role, "content": content})
            else:
                raise ValueError(f"unsupported message role: {role!r}")
        if not api_messages:
            raise ValueError("at least one user or assistant message is required")

        output_limit = max_output_tokens or self.default_max_output_tokens
        if output_limit < 1:
            raise ValueError("max_output_tokens must be positive")
        payload: Dict[str, object] = {
            "model": self.model,
            "max_tokens": int(output_limit),
            "messages": api_messages,
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        data = _post_json(
            endpoint=self.endpoint,
            payload=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": self.anthropic_version,
            },
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
            secret=self.api_key,
        )
        try:
            blocks = data["content"]
            text = "".join(
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if not text.strip():
                raise ValueError("empty content")
            usage = data.get("usage") or {}
            input_tokens = sum(
                int(usage.get(key, 0) or 0)
                for key in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                )
            )
            output_tokens = int(usage.get("output_tokens", 0) or 0)
        except (KeyError, TypeError, ValueError):
            raise ProviderError("malformed Anthropic response", retryable=False) from None
        return ModelResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider="anthropic",
            model=self.model,
        )


class GeminiProvider:
    """Native adapter for Google's Gemini generateContent API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: float = 120.0,
        default_max_output_tokens: int = 8192,
        max_response_bytes: int = 4_000_000,
    ) -> None:
        if not api_key or not model:
            raise ValueError("api_key and model are required")
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        if default_max_output_tokens < 1 or max_response_bytes < 1:
            raise ValueError("timeouts, output limits, and response limits must be positive")
        self.api_key = api_key
        self.model = model.removeprefix("models/")
        self.base_url = _validate_http_base_url(base_url)
        self.timeout_seconds = float(timeout_seconds)
        self.default_max_output_tokens = int(default_max_output_tokens)
        self.max_response_bytes = int(max_response_bytes)

    def __repr__(self) -> str:
        return (
            f"GeminiProvider(base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key='<redacted>')"
        )

    @property
    def endpoint(self) -> str:
        model = quote(self.model, safe="-_.")
        return f"{self.base_url}/models/{model}:generateContent"

    def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.1,
        max_output_tokens: Optional[int] = None,
    ) -> ModelResponse:
        if not messages:
            raise ValueError("messages must not be empty")
        system_parts = []
        contents = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if not isinstance(content, str):
                raise ValueError("message content must be text")
            if role == "system":
                system_parts.append(content)
            elif role in {"user", "assistant"}:
                contents.append(
                    {
                        "role": "model" if role == "assistant" else "user",
                        "parts": [{"text": content}],
                    }
                )
            else:
                raise ValueError(f"unsupported message role: {role!r}")
        if not contents:
            raise ValueError("at least one user or assistant message is required")

        output_limit = max_output_tokens or self.default_max_output_tokens
        if output_limit < 1:
            raise ValueError("max_output_tokens must be positive")
        payload: Dict[str, object] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": int(output_limit),
                "responseMimeType": "application/json",
            },
        }
        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }
        data = _post_json(
            endpoint=self.endpoint,
            payload=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-goog-api-key": self.api_key,
            },
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
            secret=self.api_key,
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(
                part.get("text", "") for part in parts if isinstance(part, dict)
            )
            if not text.strip():
                raise ValueError("empty content")
            usage = data.get("usageMetadata") or {}
            input_tokens = int(usage.get("promptTokenCount", 0) or 0)
            output_tokens = int(usage.get("candidatesTokenCount", 0) or 0) + int(
                usage.get("thoughtsTokenCount", 0) or 0
            )
        except (KeyError, IndexError, TypeError, ValueError):
            feedback = _redact(data.get("promptFeedback", "unknown response"), self.api_key)
            raise ProviderError(
                f"malformed or blocked Gemini response: {feedback}",
                retryable=False,
            ) from None
        return ModelResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider="gemini",
            model=self.model,
        )


class CommandProvider:
    """Bridge any local agent framework through JSON stdin/stdout."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        model: str,
        timeout_seconds: float = 120.0,
        cwd: Optional[str] = None,
        max_response_chars: int = 1_000_000,
    ) -> None:
        if isinstance(command, (str, bytes)) or not command or any(
            not isinstance(value, str) or not value for value in command
        ):
            raise ValueError("command provider requires a non-empty argument array")
        if not model:
            raise ValueError("model is required")
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("timeout must be positive and finite")
        if max_response_chars < 1:
            raise ValueError("timeout and response cap must be positive")
        self.command = list(command)
        self.model = model
        self.timeout_seconds = float(timeout_seconds)
        self.cwd = os.path.abspath(cwd) if cwd else None
        self.max_response_chars = int(max_response_chars)

    def __repr__(self) -> str:
        return (
            f"CommandProvider(executable={os.path.basename(self.command[0])!r}, "
            f"model={self.model!r})"
        )

    @staticmethod
    def _bridge_error(stderr: str, returncode: int) -> ProviderError:
        try:
            payload = json.loads(stderr)
            if not isinstance(payload, dict):
                raise ValueError
            return ProviderError(
                str(payload.get("error") or f"provider bridge exited {returncode}")[:1000],
                status_code=payload.get("status_code"),
                retryable=bool(payload.get("retryable", False)),
                retry_after_seconds=(
                    float(payload["retry_after_seconds"])
                    if payload.get("retry_after_seconds") is not None
                    else None
                ),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            detail = (stderr or f"provider bridge exited {returncode}").strip()
            return ProviderError(detail[:1000], retryable=False)

    def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.1,
        max_output_tokens: Optional[int] = None,
    ) -> ModelResponse:
        if not messages:
            raise ValueError("messages must not be empty")
        request_payload = {
            "schema_version": 1,
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        try:
            result = run_bounded_process(
                self.command,
                input_text=json.dumps(request_payload),
                cwd=self.cwd,
                timeout_seconds=self.timeout_seconds,
                max_stdout_chars=self.max_response_chars,
                max_stderr_chars=min(self.max_response_chars, 100_000),
            )
        except OSError as exc:
            raise ProviderError(f"provider bridge could not start: {exc}", retryable=False) from None

        if result.timed_out:
            raise ProviderError("provider bridge timed out", retryable=True)
        if result.returncode != 0:
            raise self._bridge_error(result.stderr, result.returncode)
        if result.stdout_truncated:
            raise ProviderError("provider bridge response exceeded the size limit", retryable=False)
        try:
            payload = json.loads(result.stdout)
            text = payload["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty text")
            input_tokens = int(payload.get("input_tokens", 0) or 0)
            output_tokens = int(payload.get("output_tokens", 0) or 0)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise ProviderError("malformed provider bridge response", retryable=False) from None
        return ModelResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider="command-bridge",
            model=self.model,
        )


__all__ = [
    "AnthropicProvider",
    "CommandProvider",
    "GeminiProvider",
    "ModelResponse",
    "OpenAICompatibleProvider",
    "Provider",
    "ProviderError",
]
