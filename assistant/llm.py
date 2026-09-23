"""Optional, cached LLM client used by the assistant.

The public surface deliberately returns None on configuration or network errors so
the graph-backed templates remain available offline.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except (ImportError, OSError, ValueError):
    pass

DEFAULT_NVIDIA_MODEL = "meta/llama-3.3-70b-instruct"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_TIMEOUT = 20


def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


def _positive(value: Any, default: float, maximum: float) -> float:
    try:
        number = float(value)
        return min(number, maximum) if math.isfinite(number) and number > 0 else default
    except (TypeError, ValueError, OverflowError):
        return default


def _valid_response(value: Any) -> bool:
    return (isinstance(value, dict) and isinstance(value.get("content"), str)
            and isinstance(value.get("tool_calls"), list)
            and all(isinstance(call, dict) and isinstance(call.get("name"), str)
                    and isinstance(call.get("arguments"), dict)
                    for call in value["tool_calls"]))


def _cache_path(key: str) -> Path:
    return Path(__file__).resolve().parent.parent / ".cache" / "assistant" / (key + ".json")


def _tool_result(name: str, arguments: Any, call_id: str = "") -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (TypeError, ValueError):
            arguments = {}
    return {"id": call_id, "name": name, "arguments": arguments if isinstance(arguments, dict) else {}}


def _openai_call(provider: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                 model: str, timeout: float) -> dict[str, Any] | None:
    try:
        from openai import OpenAI

        if provider == "nvidia":
            api_key = _setting("NVIDIA_API_KEY")
            base_url = _setting("NVIDIA_BASE_URL", DEFAULT_NVIDIA_BASE_URL)
        else:
            api_key = _setting("OPENAI_API_KEY")
            base_url = _setting("OPENAI_BASE_URL") or None
        if not api_key:
            return None
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "timeout": timeout,
            "max_tokens": int(_positive(_setting("LLM_MAX_TOKENS"), 700, 2000)),
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            response = client.chat.completions.create(**kwargs)
        finally:
            client.close()
        message = response.choices[0].message
        calls = []
        for item in (getattr(message, "tool_calls", None) or []):
            calls.append(_tool_result(item.function.name, item.function.arguments, item.id))
        return {"content": message.content or "", "tool_calls": calls, "source": provider}
    except Exception:
        return None


def _anthropic_call(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                    model: str, timeout: float) -> dict[str, Any] | None:
    api_key = _setting("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    system_parts = [str(m.get("content", "")) for m in messages if m.get("role") == "system"]
    converted: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def flush_tool_results() -> None:
        if pending_tool_results:
            converted.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results.clear()

    for message in messages:
        role = message.get("role")
        if role == "tool":
            pending_tool_results.append({
                "type": "tool_result",
                "tool_use_id": str(message.get("tool_call_id", "")),
                "content": str(message.get("content", "")),
            })
            continue
        flush_tool_results()
        if role == "assistant" and message.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": str(message["content"])})
            for call in message["tool_calls"]:
                function = call.get("function", {})
                try:
                    arguments = json.loads(function.get("arguments", "{}"))
                except (TypeError, ValueError):
                    arguments = {}
                blocks.append({
                    "type": "tool_use",
                    "id": str(call.get("id", "")),
                    "name": str(function.get("name", "")),
                    "input": arguments if isinstance(arguments, dict) else {},
                })
            converted.append({"role": "assistant", "content": blocks})
        elif role in {"user", "assistant"}:
            converted.append({"role": role, "content": message.get("content", "")})
    flush_tool_results()
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": int(_positive(_setting("LLM_MAX_TOKENS"), 700, 2000)),
        "messages": converted,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if tools:
        payload["tools"] = [
            {
                "name": item["function"]["name"],
                "description": item["function"].get("description", ""),
                "input_schema": item["function"].get("parameters", {"type": "object", "properties": {}}),
            }
            for item in tools if item.get("type") == "function"
        ]
    request = Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        text_parts = []
        calls = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(_tool_result(block.get("name", ""), block.get("input", {}), block.get("id", "")))
        return {"content": "\n".join(text_parts), "tool_calls": calls, "source": "anthropic"}
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None


def _call_model(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                *, timeout: float | None = None) -> dict[str, Any] | None:
    """Call the configured provider, or return None for none/unavailable/failure.

    Results are cached on disk by provider, model, messages, and tool schema. API
    credentials are never included in the cache key or stored in cache files.
    """
    provider = _setting("LLM_PROVIDER", "none").lower()
    if provider not in {"nvidia", "openai", "anthropic"}:
        return None
    timeout_value = _positive(_setting("LLM_TIMEOUT"), DEFAULT_TIMEOUT, DEFAULT_TIMEOUT)
    if timeout is not None:
        timeout_value = min(timeout_value, _positive(timeout, DEFAULT_TIMEOUT, DEFAULT_TIMEOUT))
    defaults = {"nvidia": DEFAULT_NVIDIA_MODEL, "openai": "gpt-4o-mini",
                "anthropic": "claude-haiku-4-5-20251001"}
    model = _setting("LLM_MODEL", defaults[provider])
    key_name = {"nvidia": "NVIDIA_API_KEY", "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY"}[provider]
    if not _setting(key_name):
        return None

    cache_payload = {
        "provider": provider,
        "model": model,
        "messages": messages,
        "tools": tools or [],
        "version": 2,
        "base_url": (_setting("NVIDIA_BASE_URL", DEFAULT_NVIDIA_BASE_URL) if provider == "nvidia"
                     else _setting("OPENAI_BASE_URL") if provider == "openai" else "anthropic"),
        "max_tokens": int(_positive(_setting("LLM_MAX_TOKENS"), 700, 2000)),
    }
    cache_key = hashlib.sha256(
        json.dumps(cache_payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    path = _cache_path(cache_key)
    try:
        if path.is_file():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if _valid_response(cached):
                return cached
    except (OSError, ValueError):
        pass

    if provider == "anthropic":
        result = _anthropic_call(messages, tools, model, timeout_value)
    else:
        result = _openai_call(provider, messages, tools, model, timeout_value)
    if not _valid_response(result):
        return None
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            json.dump(result, handle, ensure_ascii=False)
        temp_path.replace(path)
    except OSError:
        pass
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
    return result


def call_model(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
               *, timeout: float | None = None) -> dict[str, Any] | None:
    """Provider, configuration and cache failures never escape this boundary."""
    try:
        return _call_model(messages, tools, timeout=timeout)
    except Exception:
        return None
