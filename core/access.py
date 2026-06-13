"""Control de acceso: un solo chat autorizado (TELEGRAM_CHAT_ID).

Puede ser DM del técnico, del instalador USB o un grupo. Todo el bot y las
alertas van al mismo destino.
"""
import os
import logging
from telegram import Update, Bot
from telegram.error import TelegramError

log = logging.getLogger("shomer-access")

_TECNICO_CHAT = str(os.environ.get("TELEGRAM_CHAT_ID", ""))


def technician_only_mode() -> bool:
    """Siempre un solo perfil operativo en Telegram."""
    return True


def get_level(update: Update) -> str:
    """Retorna 'tecnico' si el chat coincide con TELEGRAM_CHAT_ID, si no 'none'."""
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    if _TECNICO_CHAT and str(chat_id) == str(_TECNICO_CHAT):
        return "tecnico"
    return "none"


def is_authorized(update: Update) -> bool:
    return get_level(update) != "none"


def request_dev_auth(user_id: int) -> None:
    pass


def is_pending_auth(user_id: int) -> bool:
    return False


def clear_pending_dev_auth(user_id: int) -> None:
    pass


def verify_dev_password(user_id: int, text: str) -> bool:
    return False


def logout_dev(user_id: int) -> None:
    pass


async def send_developer(bot: Bot, text: str) -> None:
    """Compat: mismo destino que alertas operativas (TELEGRAM_CHAT_ID)."""
    if not _TECNICO_CHAT:
        return
    try:
        await bot.send_message(chat_id=_TECNICO_CHAT, text=text, parse_mode="HTML")
    except TelegramError as e:
        log.warning("Telegram send error: %s", e)
