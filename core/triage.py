"""Capa C — Triage: buffer de eventos → un mensaje Telegram por entidad."""
from __future__ import annotations

import asyncio
import html as _html
import logging
import os
from typing import Callable, Dict, List, Optional

from telegram import Bot

from core.events import ShomerEvent

log = logging.getLogger("shomer-triage")

_SEV_ORDER = {"info": 0, "warn": 1, "critical": 2}


def is_enabled() -> bool:
    return os.environ.get("BOT_TRIAGE_ENABLED", "0").strip().lower() in ("1", "true", "yes")


def _window_sec() -> float:
    try:
        return float(os.environ.get("BOT_TRIAGE_WINDOW_SEC", "15"))
    except ValueError:
        return 15.0


def _critical_sec() -> float:
    try:
        return float(os.environ.get("BOT_TRIAGE_CRITICAL_SEC", "5"))
    except ValueError:
        return 5.0


def _use_groq() -> bool:
    return os.environ.get("BOT_TRIAGE_USE_GROQ", "0").strip().lower() in ("1", "true", "yes")


class TriageManager:
    def __init__(self, bot: Bot, send_fn: Callable):
        self._bot = bot
        self._send = send_fn
        self._buffer: Dict[str, List[ShomerEvent]] = {}
        self._timers: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def emit(self, event: ShomerEvent) -> None:
        if not is_enabled():
            text = "\n".join(event.lines) if event.lines else f"{event.metrica}: {event.valor}"
            await self._send(self._bot, text, reply_markup=event.reply_markup)
            return

        key = event.entity_key()
        async with self._lock:
            self._buffer.setdefault(key, []).append(event)

        if event.bypass_buffer:
            await self._flush(key)
            return

        delay = _critical_sec() if event.severity == "critical" else _window_sec()
        if key in self._timers:
            self._timers[key].cancel()
        self._timers[key] = asyncio.create_task(self._delayed_flush(key, delay))

    async def _delayed_flush(self, key: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._flush(key)
        except asyncio.CancelledError:
            pass

    async def _flush(self, key: str) -> None:
        async with self._lock:
            events = self._buffer.pop(key, [])
            self._timers.pop(key, None)
        if not events:
            return

        text, markup = self._merge(key, events)
        try:
            await self._send(self._bot, text, reply_markup=markup)
        except Exception as e:
            log.warning("triage flush send error: %s", e)

    def _merge(self, entity_key: str, events: List[ShomerEvent]) -> tuple[str, Optional[object]]:
        events = sorted(events, key=lambda e: _SEV_ORDER.get(e.severity, 0))
        lines: List[str] = []
        seen: set[str] = set()
        for ev in events:
            for line in ev.lines:
                if line not in seen:
                    seen.add(line)
                    lines.append(line)
            if not ev.lines and ev.valor:
                stub = f"{ev.metrica}: {ev.valor}"
                if stub not in seen:
                    seen.add(stub)
                    lines.append(stub)

        raw = "\n".join(lines)
        if _use_groq() and len(events) > 1:
            try:
                from core.groq_helper import explain

                prompt = (
                    "Consolidá estos avisos en líneas cortas para Telegram. "
                    "Cada línea: emoji + <b>evento</b> — detalle. "
                    "Ejemplo: 🔴 Equipo Infra caído — Cámara (192.168.1.57). "
                    "Sin párrafos largos ni ➡️.\n\n"
                    + raw
                )
                summarized = explain(prompt, level="tecnico")
                if summarized and len(summarized) > 20:
                    raw = summarized
            except Exception as e:
                log.debug("triage groq merge skip: %s", e)

        severity = events[-1].severity if events else "info"
        from core import fmt

        raw = fmt.triage_digest(entity_key, raw, severity)

        # reply_markup del evento más severo que lo tenga; si no, botón Entendido
        markup = None
        for ev in reversed(events):
            if ev.reply_markup is not None:
                markup = ev.reply_markup
                break
        if markup is None and is_enabled():
            from core.fmt import btn, kb

            markup = kb([btn("✅ Entendido", "dismiss:ok")])

        return raw, markup


_manager: Optional[TriageManager] = None


def init(bot: Bot, send_fn: Callable) -> TriageManager:
    global _manager
    _manager = TriageManager(bot, send_fn)
    if is_enabled():
        log.info(
            "Triage activo — ventana %.0fs, crítico %.0fs, groq=%s",
            _window_sec(),
            _critical_sec(),
            _use_groq(),
        )
    return _manager


def get_manager() -> Optional[TriageManager]:
    return _manager


async def notify(bot: Bot, event: ShomerEvent, send_fn: Callable) -> None:
    mgr = get_manager()
    if mgr is None:
        text = "\n".join(event.lines) if event.lines else f"{event.metrica}: {event.valor}"
        await send_fn(bot, text, reply_markup=event.reply_markup)
        return
    await mgr.emit(event)
