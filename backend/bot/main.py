"""
bot/main.py
Bot de Telegram con UX rediseñada y panel de administrador.
"""

import asyncio
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    MenuButtonCommands, BotCommand,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters,
)

import config
from db.database import get_db, init_db
from services import game_service, user_service
from services import admin_service

log = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)

# ── ESTADOS DE CONVERSACIÓN ADMIN ─────────────────────
(
    ADMIN_WAIT_ID,
    ADMIN_WAIT_AMOUNT,
    ADMIN_WAIT_BAN_ID,
    ADMIN_WAIT_BAN_DURATION,
    ADMIN_WAIT_UNBAN_ID,
    ADMIN_WAIT_CHECK_ID,
) = range(6)


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════

def _tg_user(update: Update):
    u = update.effective_user
    return u.id, u.full_name, u.username, u.language_code or "es"


async def _reply(update: Update, text: str, keyboard=None) -> None:
    kwargs = {"parse_mode": "HTML"}
    if keyboard:
        kwargs["reply_markup"] = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text(text, **kwargs)


def _main_menu(balance: int) -> list:
    return [
        [InlineKeyboardButton("🃏  Nueva partida", callback_data="new_game")],
        [
            InlineKeyboardButton("💰  Saldo", callback_data="balance"),
            InlineKeyboardButton("📋  Historial", callback_data="history"),
        ],
        [InlineKeyboardButton("❓  Cómo jugar", callback_data="how_to_play")],
    ]


def _admin_menu() -> list:
    return [
        [
            InlineKeyboardButton("➕ Añadir saldo",  callback_data="adm_add"),
            InlineKeyboardButton("➖ Retirar saldo", callback_data="adm_remove"),
        ],
        [
            InlineKeyboardButton("🔨 Banear",        callback_data="adm_ban"),
            InlineKeyboardButton("✅ Desbanear",      callback_data="adm_unban"),
        ],
        [
            InlineKeyboardButton("🔍 Ver usuario",   callback_data="adm_check"),
            InlineKeyboardButton("📊 Estadísticas",  callback_data="adm_stats"),
        ],
        [InlineKeyboardButton("👥 Listar usuarios",  callback_data="adm_list")],
        [InlineKeyboardButton("🔙 Menú principal",   callback_data="main_menu")],
    ]


# ══════════════════════════════════════════════════════
#  COMANDOS PÚBLICOS
# ══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, name, username, lang = _tg_user(update)

    with get_db() as db:
        profile = user_service.register_or_update(db, uid, name, username, lang)

    # Deep link de partida
    if context.args:
        await _handle_invite(update, context, uid, context.args[0])
        return

    ban = profile["ban"]
    if ban["is_banned"]:
        await _reply(
            update,
            f"⛔ <b>Acceso restringido</b>\n\n"
            f"Estás suspendido temporalmente.\n"
            f"⏱ Tiempo restante: <b>{ban['remaining_minutes']} min "
            f"{ban['remaining_seconds']} seg</b>"
        )
        return

    balance = profile["balance"]
    admin_row = []
    if config.is_admin(uid):
        admin_row = [[InlineKeyboardButton(
            "🛡  Panel de Admin", callback_data="admin_panel"
        )]]

    await _reply(
        update,
        f"♠️ <b>Bienvenido al Casino</b>, {name}!\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Saldo disponible: <b>{balance} fichas</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"¿Qué quieres hacer?",
        keyboard=_main_menu(balance) + admin_row,
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not config.is_admin(uid):
        await _reply(update, "⛔ No tienes permisos de administrador.")
        return
    await _reply(
        update,
        "🛡 <b>Panel de Administración</b>\n\n"
        "Selecciona una acción:",
        keyboard=_admin_menu(),
    )


# ══════════════════════════════════════════════════════
#  CALLBACKS — MENÚ PRINCIPAL
# ══════════════════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    # ── MENÚ PRINCIPAL ────────────────────────────────

    if data == "main_menu":
        with get_db() as db:
            balance = user_service.get_balance(db, uid)
        admin_row = []
        if config.is_admin(uid):
            admin_row = [[InlineKeyboardButton(
                "🛡  Panel de Admin", callback_data="admin_panel"
            )]]
        await query.message.edit_text(
            f"♠️ <b>Casino</b>\n\n"
            f"💰 Saldo: <b>{balance} fichas</b>\n\n"
            f"¿Qué quieres hacer?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(_main_menu(balance) + admin_row),
        )

    elif data == "new_game":
        with get_db() as db:
            try:
                result = game_service.create_game(db, uid)
            except (PermissionError, ValueError) as e:
                await query.message.reply_text(f"❌ {e}", parse_mode="HTML")
                return

        invite_url = result["invite_link"]
        await query.message.reply_text(
            f"🃏 <b>Partida creada</b>\n\n"
            f"Comparte este link con tu oponente.\n"
            f"La partida comenzará cuando él lo abra.\n\n"
            f"🔗 <code>{invite_url}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎮 Abrir mesa", url=invite_url),
                InlineKeyboardButton("🔙 Menú", callback_data="main_menu"),
            ]]),
        )

    elif data == "balance":
        with get_db() as db:
            balance = user_service.get_balance(db, uid)
        await query.message.reply_text(
            f"💰 <b>Tu saldo</b>\n\n"
            f"<b>{balance} fichas</b> disponibles",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Menú", callback_data="main_menu")
            ]]),
        )

    elif data == "history":
        with get_db() as db:
            history = user_service.get_history(db, uid, limit=10)

        if not history:
            text = "📋 <b>Historial</b>\n\nAún no tienes movimientos."
        else:
            lines = []
            for tx in history:
                sign  = "+" if tx["amount"] > 0 else ""
                emoji = "🟢" if tx["amount"] > 0 else "🔴"
                lines.append(
                    f"{emoji} {sign}{tx['amount']} — "
                    f"<i>{tx['description'] or tx['type']}</i>"
                )
            text = "📋 <b>Últimos movimientos</b>\n\n" + "\n".join(lines)

        await query.message.reply_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Menú", callback_data="main_menu")
            ]]),
        )

    elif data == "how_to_play":
        await query.message.reply_text(
            "❓ <b>Cómo jugar</b>\n\n"
            "1️⃣ Pulsa <b>Nueva partida</b> para crear una mesa\n"
            "2️⃣ Comparte el link con tu oponente\n"
            "3️⃣ Cuando él abra el link, la partida comienza\n"
            "4️⃣ Cada turno tiene <b>30 segundos</b> para actuar\n"
            "5️⃣ Si no actúas a tiempo, se hace <b>fold automático</b>\n\n"
            "♠️ <b>Texas Hold'em 1v1</b>\n"
            "El casino cobra un <b>3% de rake</b> sobre el pot ganado.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Menú", callback_data="main_menu")
            ]]),
        )

    # ── PANEL ADMIN ───────────────────────────────────

    elif data == "admin_panel":
        if not config.is_admin(uid):
            return
        await query.message.reply_text(
            "🛡 <b>Panel de Administración</b>\n\nSelecciona una acción:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(_admin_menu()),
        )

    elif data == "adm_stats":
        if not config.is_admin(uid):
            return
        with get_db() as db:
            stats = admin_service.get_stats(db)
        await query.message.reply_text(
            f"📊 <b>Estadísticas del Casino</b>\n\n"
            f"👥 Usuarios registrados: <b>{stats['total_users']}</b>\n"
            f"🎮 Partidas activas: <b>{stats['active_games']}</b>\n"
            f"✅ Partidas finalizadas: <b>{stats['finished_games']}</b>\n"
            f"💰 Rake total recaudado: <b>{stats['total_rake_collected']}</b>\n"
            f"⛔ Usuarios baneados: <b>{stats['banned_users']}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")
            ]]),
        )

    elif data == "adm_list":
        if not config.is_admin(uid):
            return
        with get_db() as db:
            result = admin_service.list_users(db, limit=10)
        lines = []
        for u in result["users"]:
            status = "⛔" if u["is_banned"] else "🟢"
            name   = u["display_name"]
            bal    = u["balance"]
            uid_u  = u["id"]
            lines.append(f"{status} <b>{name}</b> | {bal}f | <code>{uid_u}</code>")

        await query.message.reply_text(
            f"👥 <b>Usuarios</b> ({result['total']} total)\n\n"
            + "\n".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")
            ]]),
        )

    elif data in ("adm_add", "adm_remove", "adm_ban", "adm_unban", "adm_check"):
        if not config.is_admin(uid):
            return
        prompts = {
            "adm_add":    "➕ <b>Añadir saldo</b>\n\nEnvía el <b>ID del usuario</b>:",
            "adm_remove": "➖ <b>Retirar saldo</b>\n\nEnvía el <b>ID del usuario</b>:",
            "adm_ban":    "🔨 <b>Banear usuario</b>\n\nEnvía el <b>ID del usuario</b>:",
            "adm_unban":  "✅ <b>Desbanear</b>\n\nEnvía el <b>ID del usuario</b>:",
            "adm_check":  "🔍 <b>Ver usuario</b>\n\nEnvía el <b>ID del usuario</b>:",
        }
        context.user_data["adm_action"] = data
        await query.message.reply_text(
            prompts[data], parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancelar", callback_data="admin_panel")
            ]]),
        )
        return ADMIN_WAIT_ID


# ══════════════════════════════════════════════════════
#  CONVERSACIÓN ADMIN
# ══════════════════════════════════════════════════════

async def admin_got_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not config.is_admin(uid):
        return ConversationHandler.END

    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await _reply(update, "❌ ID inválido. Envía solo el número.")
        return ADMIN_WAIT_ID

    context.user_data["adm_target_id"] = target_id
    action = context.user_data.get("adm_action")

    if action == "adm_check":
        with get_db() as db:
            try:
                info = admin_service.check_user(db, target_id)
            except ValueError as e:
                await _reply(update, f"❌ {e}")
                return ConversationHandler.END

        ban_text = (
            f"⛔ Baneado hasta <code>{info['banned_until']}</code>"
            if info["is_banned"] else "🟢 Sin ban"
        )
        recent = "\n".join([
            f"  {'+'if t['amount']>0 else ''}{t['amount']} — {t['description'] or t['type']}"
            for t in info["recent_transactions"]
        ]) or "  Sin movimientos"

        await _reply(
            update,
            f"🔍 <b>Usuario</b>\n\n"
            f"👤 {info['display_name']} (@{info['username'] or 'sin username'})\n"
            f"🆔 <code>{info['id']}</code>\n"
            f"💰 Saldo: <b>{info['balance']} fichas</b>\n"
            f"🎮 Partida activa: <code>{info['active_game_id'] or 'ninguna'}</code>\n"
            f"🚪 Abandonos: <b>{info['abandon_count']}</b>\n"
            f"{ban_text}\n\n"
            f"📋 <b>Últimos movimientos:</b>\n{recent}",
            keyboard=[[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]],
        )
        return ConversationHandler.END

    elif action == "adm_unban":
        with get_db() as db:
            try:
                result = admin_service.unban_user(db, target_id)
            except ValueError as e:
                await _reply(update, f"❌ {e}")
                return ConversationHandler.END

        await _reply(
            update,
            f"✅ <b>Ban levantado</b>\n\n"
            f"Usuario <b>{result['display_name']}</b> desbaneado.",
            keyboard=[[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]],
        )
        return ConversationHandler.END

    elif action in ("adm_add", "adm_remove"):
        await _reply(update, "💵 ¿Cuántas fichas?")
        return ADMIN_WAIT_AMOUNT

    elif action == "adm_ban":
        await _reply(update, "⏱ ¿Duración del ban en minutos?")
        return ADMIN_WAIT_BAN_DURATION


async def admin_got_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not config.is_admin(uid):
        return ConversationHandler.END

    try:
        amount = int(update.message.text.strip())
    except ValueError:
        await _reply(update, "❌ Cantidad inválida. Envía solo el número.")
        return ADMIN_WAIT_AMOUNT

    target_id = context.user_data["adm_target_id"]
    action    = context.user_data["adm_action"]

    with get_db() as db:
        try:
            if action == "adm_add":
                result = admin_service.add_balance(db, target_id, amount)
                emoji, verb = "➕", "añadidas"
            else:
                result = admin_service.remove_balance(db, target_id, amount)
                emoji, verb = "➖", "retiradas"
        except (ValueError, Exception) as e:
            await _reply(update, f"❌ {e}")
            return ConversationHandler.END

    await _reply(
        update,
        f"{emoji} <b>Saldo actualizado</b>\n\n"
        f"Usuario: <b>{result['display_name']}</b>\n"
        f"Fichas {verb}: <b>{amount}</b>\n"
        f"Nuevo saldo: <b>{result['new_balance']} fichas</b>",
        keyboard=[[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]],
    )
    return ConversationHandler.END


async def admin_got_ban_duration(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    uid = update.effective_user.id
    if not config.is_admin(uid):
        return ConversationHandler.END

    try:
        minutes = int(update.message.text.strip())
    except ValueError:
        await _reply(update, "❌ Duración inválida. Envía solo el número.")
        return ADMIN_WAIT_BAN_DURATION

    target_id = context.user_data["adm_target_id"]

    with get_db() as db:
        try:
            result = admin_service.ban_user(db, target_id, minutes)
        except (ValueError, PermissionError) as e:
            await _reply(update, f"❌ {e}")
            return ConversationHandler.END

    hours = minutes // 60
    mins  = minutes % 60
    duration_text = f"{hours}h {mins}min" if hours else f"{mins} minutos"

    await _reply(
        update,
        f"🔨 <b>Usuario baneado</b>\n\n"
        f"Usuario: <b>{result['display_name']}</b>\n"
        f"Duración: <b>{duration_text}</b>",
        keyboard=[[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]],
    )
    return ConversationHandler.END


async def cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await _reply(update, "❌ Acción cancelada.")
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
#  INVITE LINK
# ══════════════════════════════════════════════════════

async def _handle_invite(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    uid: int, game_id: str,
):
    invite_url = f"{config.MINI_APP_URL}?startapp={game_id}"
    await _reply(
        update,
        "🃏 <b>Te invitaron a una partida</b>\n\n"
        "Pulsa el botón para unirte a la mesa:",
        keyboard=[[InlineKeyboardButton("🎮 Unirse", url=invite_url)]],
    )


# ══════════════════════════════════════════════════════
#  NOTIFICACIONES
# ══════════════════════════════════════════════════════

async def notify_user(app: Application, user_id: int, text: str):
    try:
        await app.bot.send_message(
            chat_id=user_id, text=text, parse_mode="HTML"
        )
    except Exception as e:
        log.warning(f"No se pudo notificar a {user_id}: {e}")


async def notify_game_result(
    app: Application, outcome: dict,
    winner_id: int, loser_id: int,
):
    reason_map = {
        "fold":     "por fold del oponente",
        "timeout":  "por tiempo agotado",
        "abandon":  "por abandono del oponente",
        "showdown": "en el showdown",
    }
    reason = reason_map.get(outcome.get("reason", ""), "")
    profit = outcome["winner_profit"]
    rake   = outcome["rake"]

    await notify_user(
        app, winner_id,
        f"🏆 <b>¡Ganaste!</b> {reason}\n"
        f"💰 +{profit} fichas <i>(rake: {rake})</i>",
    )
    await notify_user(
        app, loser_id,
        f"💀 <b>Perdiste</b> la mano {reason}.\n"
        f"Mejor suerte en la próxima.",
    )


# ══════════════════════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════════════════════

async def post_init(app: Application):
    # Registrar comandos en el menú de Telegram
    await app.bot.set_my_commands([
        BotCommand("start",         "Menú principal"),
        BotCommand("admin",         "Panel de administrador"),
    ])
    # Arrancar scheduler
    from scheduler import run_scheduler_with_bot
    asyncio.create_task(run_scheduler_with_bot(app))
    log.info("[Bot] Scheduler iniciado.")


def main():
    config.validate()
    with get_db() as db:
        init_db()

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Conversación admin
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            handle_callback,
            pattern="^adm_(add|remove|ban|unban|check)$"
        )],
        states={
            ADMIN_WAIT_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_got_id)
            ],
            ADMIN_WAIT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_got_amount)
            ],
            ADMIN_WAIT_BAN_DURATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_got_ban_duration)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_admin),
            CallbackQueryHandler(cancel_admin, pattern="^admin_panel$"),
        ],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(admin_conv)
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Bot iniciado.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
            
