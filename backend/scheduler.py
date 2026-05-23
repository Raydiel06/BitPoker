"""
scheduler.py
Monitorea los turnos activos y dispara fold automático
cuando un jugador agota su tiempo.
Corre como tarea de fondo junto al bot o la API.
Sin dependencias externas adicionales — usa asyncio puro.
"""

import asyncio
import logging
import time
from typing import Optional

import config
from db.database import get_db
from db import models
from services import game_service

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════

CHECK_INTERVAL = 5   # segundos entre cada revisión de turnos


# ══════════════════════════════════════════════════════
#  SCHEDULER PRINCIPAL
# ══════════════════════════════════════════════════════

class TurnScheduler:
    """
    Revisa cada CHECK_INTERVAL segundos si algún turno expiró.
    Si expiró, llama a game_service.process_timeout() y
    notifica a ambos jugadores via bot.
    """

    def __init__(self, notify_callback=None) -> None:
        """
        notify_callback: función async opcional para notificar
        resultado al bot. Firma: async (outcome, winner_id, loser_id)
        """
        self._running = False
        self._notify  = notify_callback

    async def start(self) -> None:
        self._running = True
        log.info("[Scheduler] Iniciado. Revisando cada %ds.", CHECK_INTERVAL)
        while self._running:
            try:
                await self._check_expired_turns()
            except Exception as e:
                log.error("[Scheduler] Error en ciclo: %s", e)
            await asyncio.sleep(CHECK_INTERVAL)

    def stop(self) -> None:
        self._running = False
        log.info("[Scheduler] Detenido.")

    # ── CICLO DE REVISIÓN ──────────────────────────────

    async def _check_expired_turns(self) -> None:
        """Busca partidas activas con turno expirado y las resuelve."""
        now = int(time.time())
        deadline = now - config.TURN_TIMEOUT

        with get_db() as db:
            # Obtener partidas activas cuyo turno_started_at ya expiró
            rows = db.execute(
                """
                SELECT id, creator_id, opponent_id, game_state
                FROM games
                WHERE status = 'active'
                  AND game_state IS NOT NULL
                """,
            ).fetchall()

        for row in rows:
            await self._evaluate_game(row, deadline)

    async def _evaluate_game(self, row, deadline: int) -> None:
        """Evalúa si el turno de una partida expiró."""
        import json

        game_id = row["id"]
        try:
            state = json.loads(row["game_state"])
        except Exception:
            return

        # Verificar si el turno expiró
        turn_started = state.get("turn_started_at", 0)
        if turn_started > deadline:
            return   # Aún tiene tiempo

        current_player = state.get("current_player_id")
        if not current_player:
            return

        is_finished = state.get("is_finished", False)
        if is_finished:
            return

        log.info(
            "[Scheduler] Timeout en partida %s, jugador %s",
            game_id, current_player,
        )

        await self._apply_timeout(game_id, current_player, row)

    async def _apply_timeout(
        self, game_id: str, user_id: int, row
    ) -> None:
        """Aplica el fold automático y notifica."""
        try:
            with get_db() as db:
                result = game_service.process_timeout(db, game_id, user_id)

            if "error" in result:
                log.warning(
                    "[Scheduler] No se pudo aplicar timeout en %s: %s",
                    game_id, result["error"],
                )
                return

            outcome = result.get("outcome", {})
            winner_id = outcome.get("winner_id")
            loser_id  = outcome.get("loser_id")

            log.info(
                "[Scheduler] Timeout resuelto. Partida %s — ganador: %s",
                game_id, winner_id,
            )

            # Notificar via bot si hay callback registrado
            if self._notify and winner_id and loser_id:
                await self._notify(outcome, winner_id, loser_id)

        except Exception as e:
            log.error(
                "[Scheduler] Error aplicando timeout en %s: %s",
                game_id, e,
            )


# ══════════════════════════════════════════════════════
#  INTEGRACIÓN CON EL BOT
# ══════════════════════════════════════════════════════

def create_scheduler_for_bot(bot_app) -> TurnScheduler:
    """
    Crea el scheduler configurado para notificar
    resultados a través del bot de Telegram.
    """
    from bot.main import notify_game_result

    async def notify(outcome: dict, winner_id: int, loser_id: int):
        await notify_game_result(bot_app, outcome, winner_id, loser_id)

    return TurnScheduler(notify_callback=notify)


async def run_scheduler_with_bot(bot_app) -> None:
    """
    Punto de entrada para correr el scheduler
    junto al bot en el mismo proceso.
    """
    scheduler = create_scheduler_for_bot(bot_app)
    await scheduler.start()


# ══════════════════════════════════════════════════════
#  ARRANQUE INDEPENDIENTE (para pruebas)
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    scheduler = TurnScheduler()
    asyncio.run(scheduler.start())
