"""Helper OpenAI — chat interactivo con tool calling (mismo schema que Groq).

Usado para conversación del técnico cuando LLM_PROVIDER_INTERACTIVE=openai.
Monitores background siguen en Groq (gratis).
"""
from __future__ import annotations

import json
import logging
import os
import time

from core import memory as _memory
from core import tools as _tools
from core.groq_helper import (
    _SYSTEM_TECNICO,
    _SYSTEM_DEVELOPER,
    _behavior_rules_text,
    get_doc_context_developer,
    technician_only_mode,
)

log = logging.getLogger("openai-helper")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

_client = None
_import_error: str | None = None


def _get_client():
    global _client, _import_error
    if _client is not None or _import_error is not None:
        return _client
    try:
        import httpx
        from openai import OpenAI  # type: ignore
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            _import_error = "OPENAI_API_KEY no configurada"
            return None
        bind_ip = os.environ.get("OPENAI_BIND_IP", "").strip()
        http_client = None
        if bind_ip:
            transport = httpx.HTTPTransport(local_address=bind_ip)
            http_client = httpx.Client(transport=transport, timeout=15.0)
            log.info("OpenAI salida por IP local %s (WiFi/alternativa)", bind_ip)
        _client = OpenAI(
            api_key=key,
            max_retries=1,
            timeout=15.0,
            http_client=http_client,
        )
        return _client
    except ImportError as e:
        _import_error = f"paquete openai no instalado: {e}"
        return None
    except Exception as e:
        _import_error = f"error inicializando OpenAI: {e}"
        return None


def is_available() -> bool:
    return _get_client() is not None


def availability_error() -> str:
    return _import_error or ""


def _record_usage(resp, user_id: int | str, endpoint: str) -> None:
    try:
        usage = getattr(resp, "usage", None)
        if usage:
            tokens = int(getattr(usage, "total_tokens", 0) or 0)
            if tokens > 0:
                _memory.record_tokens(
                    tokens,
                    model=OPENAI_MODEL,
                    endpoint=endpoint,
                    provider="openai",
                    user_id=user_id,
                )
    except Exception:
        pass


def chat(history: list[dict], level: str = "tecnico", user_id: int | str = "") -> str | None:
    """Chat con tools. Retorna None si OpenAI no está disponible (fallback a Groq)."""
    client = _get_client()
    if client is None:
        return None

    if not history:
        return "Sin pregunta para procesar."

    effective_dev = level == "developer" and not technician_only_mode()
    system = _SYSTEM_DEVELOPER if effective_dev else _SYSTEM_TECNICO
    max_tokens = 700 if effective_dev else 550

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "system", "content": "Reglas de comportamiento:\n" + _behavior_rules_text()},
    ]

    if effective_dev:
        dq = ""
        for m in reversed(history):
            if m.get("role") == "user" and (m.get("content") or "").strip():
                dq = str(m["content"]).strip()
                break
        dev_ctx = get_doc_context_developer(dq)
        if dev_ctx:
            messages.append({
                "role": "system",
                "content": "Contexto documentación desarrollador:\n" + dev_ctx,
            })

    messages.extend(history)

    def _create(msgs, use_tools: bool):
        kwargs: dict = dict(
            model=OPENAI_MODEL,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=0.1,
        )
        if use_tools:
            kwargs["tools"] = _tools.TOOLS
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False
        return client.chat.completions.create(**kwargs)

    t0 = time.time()
    try:
        resp = _create(messages, use_tools=True)
    except Exception as e:
        err = str(e).lower()
        if "rate_limit" in err or "429" in err:
            log.warning("OpenAI rate-limit — reintentando")
            time.sleep(3)
            try:
                resp = _create(messages, use_tools=True)
            except Exception as e2:
                log.warning("OpenAI error tras retry: %s", e2)
                return None
        elif "insufficient_quota" in err or "billing" in err:
            log.warning("OpenAI cuota/billing agotada: %s", e)
            return None
        else:
            log.warning("OpenAI chat error: %s", e)
            return None

    t1 = time.time()
    _record_usage(resp, user_id, endpoint="chat")
    choice = resp.choices[0]

    if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
        msg = choice.message
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })
        tool_names = []
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}") or {}
            except Exception:
                args = {}
            tool_names.append(tc.function.name)
            result = _tools.execute(tc.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        t2 = time.time()
        try:
            resp2 = _create(messages, use_tools=False)
            t3 = time.time()
            log.debug("PERF llm1=%.1fs tools=%.1fs llm2=%.1fs total=%.1fs tools_called=%s",
                      t1-t0, t2-t1, t3-t2, t3-t0, tool_names)
            _record_usage(resp2, user_id, endpoint="chat_tools")
            out = (resp2.choices[0].message.content or "").strip()
            return out or "Obtuve datos pero no pude redactar. Usa /salud o /estado."
        except Exception as e:
            log.warning("OpenAI segunda llamada error: %s", e)
            return None

    out = (choice.message.content or "").strip()
    return out or None
