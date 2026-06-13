"""
Memoria de conversación persistente por usuario — SQLite en /app/data/.
Sobrevive reinicios del contenedor (volumen montado).
"""
import os
import sqlite3
import time
import logging

log = logging.getLogger("shomer-memory")

DB_PATH = os.environ.get("MEMORY_DB", "/app/data/conversations.db")
MAX_STORED  = 30   # mensajes guardados por usuario
GROQ_LIMIT  = 10   # cuántos se pasan a Groq como historial

# Umbral diario global de tokens (todos los proveedores sumados) antes de degradar
TOKEN_WARN_DAILY  = int(os.environ.get("TOKEN_WARN_DAILY",  "80000"))   # aviso al developer
TOKEN_LIMIT_DAILY = int(os.environ.get("TOKEN_LIMIT_DAILY", "120000"))  # modo mantenimiento

# Hard caps OpenAI (proveedor pago — cinturón de seguridad en el servidor)
OPENAI_LIMIT_PER_MESSAGE    = int(os.environ.get("OPENAI_LIMIT_PER_MESSAGE",    "4000"))
OPENAI_LIMIT_PER_USER_DAILY = int(os.environ.get("OPENAI_LIMIT_PER_USER_DAILY", "20000"))
OPENAI_LIMIT_DAILY          = int(os.environ.get("OPENAI_LIMIT_DAILY",          "80000"))

# Costo estimado USD por 1M tokens — para /tokens
_COST_PER_M_TOKENS = {
    "gpt-4o-mini":              0.30,
    "gpt-4o":                   5.00,
    "llama-3.3-70b-versatile":  0.00,
}


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT    NOT NULL,
            role    TEXT    NOT NULL,
            content TEXT    NOT NULL,
            level   TEXT    DEFAULT 'tecnico',
            ts      INTEGER NOT NULL
        )
    """)
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_ts ON messages(user_id, ts)"
    )
    con.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            date      TEXT    NOT NULL,
            tokens    INTEGER NOT NULL DEFAULT 0,
            model     TEXT    NOT NULL DEFAULT '',
            endpoint  TEXT    NOT NULL DEFAULT 'chat',
            ts        INTEGER NOT NULL
        )
    """)
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_token_date ON token_usage(date)"
    )
    # Migración: columnas provider y user_id (idempotente)
    cols = {r[1] for r in con.execute("PRAGMA table_info(token_usage)").fetchall()}
    if "provider" not in cols:
        con.execute("ALTER TABLE token_usage ADD COLUMN provider TEXT NOT NULL DEFAULT 'groq'")
    if "user_id" not in cols:
        con.execute("ALTER TABLE token_usage ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    con.commit()
    return con


def add_message(user_id: int | str, role: str, content: str,
                level: str = "tecnico") -> None:
    try:
        con = _conn()
        con.execute(
            "INSERT INTO messages (user_id, role, content, level, ts) VALUES (?,?,?,?,?)",
            (str(user_id), role, content[:3000], level, int(time.time())),
        )
        # Mantener solo los últimos MAX_STORED por usuario
        con.execute("""
            DELETE FROM messages
            WHERE user_id = ?
              AND id NOT IN (
                  SELECT id FROM messages
                  WHERE user_id = ?
                  ORDER BY ts DESC
                  LIMIT ?
              )
        """, (str(user_id), str(user_id), MAX_STORED))
        con.commit()
        con.close()
    except Exception as e:
        log.warning("memory.add_message error: %s", e)


def get_history(user_id: int | str, limit: int = GROQ_LIMIT) -> list[dict]:
    """Retorna lista [{role, content}] en orden cronológico para Groq."""
    try:
        con = _conn()
        rows = con.execute(
            "SELECT role, content FROM messages WHERE user_id=? "
            "ORDER BY ts DESC LIMIT ?",
            (str(user_id), limit),
        ).fetchall()
        con.close()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
    except Exception as e:
        log.warning("memory.get_history error: %s", e)
        return []


def clear_history(user_id: int | str) -> None:
    try:
        con = _conn()
        con.execute("DELETE FROM messages WHERE user_id=?", (str(user_id),))
        con.commit()
        con.close()
    except Exception as e:
        log.warning("memory.clear_history error: %s", e)


# ── Contador de tokens ────────────────────────────────────────────────────────

def record_tokens(
    tokens: int,
    model: str = "",
    endpoint: str = "chat",
    provider: str = "groq",
    user_id: int | str = "",
) -> None:
    """Registra tokens consumidos en una llamada a la IA."""
    try:
        today = time.strftime("%Y-%m-%d")
        con = _conn()
        con.execute(
            "INSERT INTO token_usage (date, tokens, model, endpoint, ts, provider, user_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (today, tokens, model, endpoint, int(time.time()), provider, str(user_id)),
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("memory.record_tokens error: %s", e)


def get_tokens_today(provider: str | None = None) -> int:
    """Total de tokens consumidos hoy (filtrable por proveedor)."""
    try:
        today = time.strftime("%Y-%m-%d")
        con = _conn()
        if provider:
            row = con.execute(
                "SELECT COALESCE(SUM(tokens),0) FROM token_usage WHERE date=? AND provider=?",
                (today, provider),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT COALESCE(SUM(tokens),0) FROM token_usage WHERE date=?", (today,)
            ).fetchone()
        con.close()
        return int(row[0]) if row else 0
    except Exception as e:
        log.warning("memory.get_tokens_today error: %s", e)
        return 0


def get_user_tokens_today(user_id: int | str, provider: str | None = None) -> int:
    """Tokens consumidos hoy por un usuario específico (filtrable por proveedor)."""
    try:
        today = time.strftime("%Y-%m-%d")
        con = _conn()
        if provider:
            row = con.execute(
                "SELECT COALESCE(SUM(tokens),0) FROM token_usage "
                "WHERE date=? AND user_id=? AND provider=?",
                (today, str(user_id), provider),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT COALESCE(SUM(tokens),0) FROM token_usage WHERE date=? AND user_id=?",
                (today, str(user_id)),
            ).fetchone()
        con.close()
        return int(row[0]) if row else 0
    except Exception as e:
        log.warning("memory.get_user_tokens_today error: %s", e)
        return 0


def get_token_stats(days: int = 7) -> list[dict]:
    """Estadísticas de consumo por día (últimos N días) — total global."""
    try:
        con = _conn()
        rows = con.execute(
            "SELECT date, SUM(tokens) as total FROM token_usage "
            "GROUP BY date ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        con.close()
        return [{"date": r[0], "tokens": r[1]} for r in rows]
    except Exception as e:
        log.warning("memory.get_token_stats error: %s", e)
        return []


def get_provider_stats_today() -> dict:
    """Desglose por proveedor del consumo de hoy."""
    try:
        today = time.strftime("%Y-%m-%d")
        con = _conn()
        rows = con.execute(
            "SELECT provider, SUM(tokens) FROM token_usage WHERE date=? GROUP BY provider",
            (today,),
        ).fetchall()
        con.close()
        return {r[0] or "groq": int(r[1] or 0) for r in rows}
    except Exception as e:
        log.warning("memory.get_provider_stats_today error: %s", e)
        return {}


def estimate_cost_usd(tokens: int, model: str) -> float:
    """Estima costo en USD según tabla de precios por 1M tokens."""
    rate = _COST_PER_M_TOKENS.get(model, 0.0)
    return (tokens / 1_000_000.0) * rate


def check_token_budget() -> str:
    """
    Verifica si se acerca o supera el presupuesto diario GLOBAL.
    Retorna: 'ok' | 'warn' | 'exceeded'
    """
    used = get_tokens_today()
    if used >= TOKEN_LIMIT_DAILY:
        return "exceeded"
    if used >= TOKEN_WARN_DAILY:
        return "warn"
    return "ok"


def check_openai_caps(user_id: int | str) -> tuple[bool, str]:
    """Hard caps OpenAI antes de llamar. (allowed, reason)."""
    daily = get_tokens_today(provider="openai")
    if daily >= OPENAI_LIMIT_DAILY:
        return False, f"openai_daily ({daily:,}/{OPENAI_LIMIT_DAILY:,})"
    user_daily = get_user_tokens_today(user_id, provider="openai")
    if user_daily >= OPENAI_LIMIT_PER_USER_DAILY:
        return False, f"openai_user_daily ({user_daily:,}/{OPENAI_LIMIT_PER_USER_DAILY:,})"
    return True, "ok"
