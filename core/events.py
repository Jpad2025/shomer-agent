"""Eventos estructurados para triage y catálogo autónomo."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class ShomerEvent:
    """Evento crudo emitido por un monitor — no envía Telegram directo."""

    origen: str
    entidad: str
    metrica: str
    valor: str
    severity: str = "info"  # info | warn | critical
    lines: List[str] = field(default_factory=list)
    reply_markup: Any = None
    bypass_buffer: bool = False

    def entity_key(self) -> str:
        return self.entidad
