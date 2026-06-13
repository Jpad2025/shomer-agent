"""
Estado global del bot: modo mantenimiento y rate-limit por usuario.
"""
import time
import logging

log = logging.getLogger("shomer-maintenance")

# Cuánto tiempo pausar cuando se agota la cuota Groq (segundos)
COOLDOWN_SECS = 90

# Timestamp hasta el cual el bot está en pausa (0 = activo)
_paused_until: float = 0

# Timestamp del último mensaje procesado por user_id
_user_last_msg: dict[int, float] = {}

# Segundos mínimos entre mensajes del mismo usuario
USER_RATE_LIMIT_SECS = 5


def is_paused() -> bool:
    global _paused_until
    if _paused_until and time.time() < _paused_until:
        return True
    if _paused_until and time.time() >= _paused_until:
        _paused_until = 0
        log.info("Modo mantenimiento finalizado — bot activo")
    return False


def pause(secs: int = COOLDOWN_SECS) -> None:
    global _paused_until
    _paused_until = time.time() + secs
    log.warning("Bot pausado por %d segundos (cuota agotada o forzado)", secs)


def resume() -> None:
    global _paused_until
    _paused_until = 0
    log.info("Bot reactivado manualmente")


def paused_until_str() -> str:
    if not _paused_until:
        return "activo"
    remaining = max(0, int(_paused_until - time.time()))
    return f"pausado ~{remaining}s"


def check_user_rate(user_id: int) -> bool:
    """Retorna True si el usuario puede enviar (respetó el cooldown)."""
    now = time.time()
    last = _user_last_msg.get(user_id, 0)
    if now - last < USER_RATE_LIMIT_SECS:
        return False
    _user_last_msg[user_id] = now
    return True


def reset_user_rate(user_id: int) -> None:
    _user_last_msg.pop(user_id, None)
