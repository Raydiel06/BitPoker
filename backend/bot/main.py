"""
bot/main.py
Bot de Telegram — punto de entrada conversacional.
Maneja registro, creación de partidas, saldo e historial.
El juego en sí ocurre en la Mini App (frontend + API).
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import config
from db.database import get_db, init_db
from services import game_service, user_service

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════

def _tg_user(update: Update) -> tuple[int, str, str | None, str]:
    u = update.effective_user
    return (
        u.id,
        u.full_name,
        u.username,
        u.language_code or "es",
    )


async def _reply(update: Update, text: str, **kwargs) -> None:
    await update.effective_message.reply_text(
        text, parse_mode="HTML", **kwargs
    )


# ══════════════════════════════════════════════════════
#  COMANDOS
# ══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start — registro y bienvenida.
    También maneja el deep link cuando viene de un invite link.
    """
    uid, name, username, lang = _tg_user(update)

    with get_db() as db:
        profile = user_service.register_or_update(db, uid, name, username, lang)

    # Si viene con parámetro startapp (link de partida)
    args = context.args
    if args:
        game_id = args[0]
        await _handle_invite(update, context, uid, game_id)
        return

    ban = profile["ban"]
    if ban["is_banned"]:
        await _reply(
            update,
            f"⛔ Estás suspendido.\n"
            f"Tiempo restante: <b>{ban['remaining_minutes']} min</b>."
        )
        return

    keyboard = [
        [InlineKeyboardButton("🃏 Nueva partida", callback_data="new_game")],
        [InlineKeyboardButton("💰 Mi saldo",      callback_data="balance")],
        [InlineKeyboardButton("📋 Historial",     callback_data="history")],
    ]
    await _reply(
        update,
        f"👋 Hola, <b>{name}</b>.\n\n"
        f"💰 Saldo: <b>{profile['balance']}</b> fichas\n\n"
        f"¿Qué quieres hacer?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/balance — saldo actual."""
    uid, name, username, lang = _tg_user(update)
    with get_db() as db:
        user_service.register_or_update(db, uid, name, username, lang)
        balance = user_service.get_balance(db, uid)
    await _reply(update, f"💰 Tu saldo: <b>{balance}</b> fichas.")


async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/historial — últimas 10 transacciones."""
    uid, name, username, lang = _tg_user(update)
    with get_db() as db:
        user_service.register_or_update(db, uid, name, username, lang)
        history = user_service.get_history(db, uid, limit=10)

    if not history:
        await _reply(update, "📋 Aún no tienes movimientos.")
        return

    lines = []
    for tx in history:
        sign = "+" if tx["amount"] > 0 else ""
        lines.append(
            f"{sign}{tx['amount']} — {tx['type']} "
            f"<i>({tx['description'] or ''})</i>"
        )

    await _reply(update, "📋 <b>Últimos movimientos:</b>\n\n" + "\n".join(lines))


async def cmd_nueva_partida(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/nueva_partida — crea partida y envía link."""
    uid, name, username, lang = _tg_user(update)
    with get_db() as db:
        user_service.register_or_update(db, uid, name, username, lang)
        try:
            result = game_service.create_game(db, uid)
        except (PermissionError, ValueError) as e:
            await _reply(update, f"❌ {e}")
            return

    game_id    = result["game_id"]
    invite_url = result["invite_link"]

    keyboard = [[
        InlineKeyboardButton("🎮 Abrir partida", url=invite_url)
    ]]
    await _reply(
        update,
        f"✅ Partida creada.\n\n"
        f"🔗 Comparte este link con tu oponente:\n"
        f"<code>{invite_url}</code>\n\n"
        f"La partida comienza cuando el oponente abra el link.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ══════════════════════════════════════════════════════
#  CALLBACK BUTTONS (menú inline)
# ══════════════════════════════════════════════════════

async def handle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data == "new_game":
        # Reusar lógica del comando
        context.args = []
        await cmd_nueva_partida(update, context)

    elif data == "balance":
        with get_db() as db:
            balance = user_service.get_balance(db, uid)
        await query.message.reply_text(
            f"💰 Tu saldo: <b>{balance}</b> fichas.",
            parse_mode="HTML",
        )

    elif data == "history":
        with get_db() as db:
            history = user_service.get_history(db, uid, limit=10)
        if not history:
            await query.message.reply_text("📋 Aún no tienes movimientos.")
            return
        lines = []
        for tx in history:
            sign = "+" if tx["amount"] > 0 else ""
            lines.append(f"{sign}{tx['amount']} — {tx['type']}")
        await query.message.reply_text(
            "📋 <b>Últimos movimientos:</b>\n\n" + "\n".join(lines),
            parse_mode="HTML",
        )


# ══════════════════════════════════════════════════════
#  INVITE LINK HANDLER
# ══════════════════════════════════════════════════════

async def _handle_invite(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    uid: int, game_id: str,
) -> None:
    """
    El usuario abrió un link de invitación.
    Muestra botón para abrir la Mini App directamente en la partida.
    """
    invite_url = f"{config.MINI_APP_URL}?startapp={game_id}"
    keyboard = [[
        InlineKeyboardButton("🎮 Unirse a la partida", url=invite_url)
    ]]
    await _reply(
        update,
        "🃏 Te invitaron a una partida de poker.\n\n"
        "Pulsa el botón para unirte:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ══════════════════════════════════════════════════════
#  NOTIFICACIONES (llamadas desde services)
# ══════════════════════════════════════════════════════

async def notify_user(app: Application, user_id: int, text: str) -> None:
    """Envía un mensaje proactivo a un usuario."""
    try:
        await app.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning(f"No se pudo notificar a {user_id}: {e}")


async def notify_game_result(
    app: Application, outcome: dict,
    winner_id: int, loser_id: int,
) -> None:
    """Notifica el resultado de la mano a ambos jugadores."""
    reason_map = {
        "fold":     "por fold",
        "timeout":  "por tiempo agotado",
        "abandon":  "por abandono",
        "showdown": "en el showdown",
    }
    reason = reason_map.get(outcome.get("reason", ""), "")
    profit = outcome["winner_profit"]
    rake   = outcome["rake"]

    await notify_user(
        app, winner_id,
        f"🏆 ¡Ganaste la mano {reason}!\n"
        f"💰 +{profit} fichas (rake: {rake})",
    )
    await notify_user(
        app, loser_id,
        f"💀 Perdiste la mano {reason}.\n"
        f"Mejor suerte en la próxima.",
    )


# ══════════════════════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════════════════════

def main() -> None:
    config.validate()

    # Inicializar DB
    with get_db() as db:
        init_db()

    log.info("Iniciando bot...")

    app = Application.builder().token(config.BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start",          cmd_start))
    app.add_handler(CommandHandler("balance",        cmd_balance))
    app.add_handler(CommandHandler("historial",      cmd_historial))
    app.add_handler(CommandHandler("nueva_partida",  cmd_nueva_partida))

    # Callbacks del menú inline
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Bot corriendo. Presiona Ctrl+C para detener.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()


# ══════════════════════════════════════════════════════
#  ARRANQUE CON SCHEDULER
# ══════════════════════════════════════════════════════

async def post_init(app: Application) -> None:
    """Arranca el scheduler como tarea de fondo cuando el bot inicia."""
    from scheduler import run_scheduler_with_bot
    asyncio.create_task(run_scheduler_with_bot(app))
    log.info("[Bot] Scheduler de turnos iniciado.")


def main_with_scheduler() -> None:
    """
    Versión de main() que incluye el scheduler.
    Usar esta en producción.
    """
    import asyncio
    config.validate()

    with get_db() as db:
        init_db()

    log.info("Iniciando bot con scheduler...")

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("balance",       cmd_balance))
    app.add_handler(CommandHandler("historial",     cmd_historial))
    app.add_handler(CommandHandler("nueva_partida", cmd_nueva_partida))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Bot corriendo con scheduler. Presiona Ctrl+C para detener.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main_with_scheduler()
