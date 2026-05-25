"""
services/game_service.py
Orquesta las partidas conectando PokerEngine con la base de datos.
Es el único punto donde el motor toca la DB.
"""

import time
from sqlite3 import Connection
from typing import Optional

import config
from core.poker_engine import PokerEngine, HandOutcome, Stage
from db import models


# ══════════════════════════════════════════════════════
#  CREAR Y UNIRSE A PARTIDA
# ══════════════════════════════════════════════════════

def create_game(db: Connection, creator_id: int) -> dict:
    """
    Crea una partida nueva y devuelve el link de invitación.
    Valida que el usuario no esté baneado ni en otra partida.
    """
    # Validar ban
    banned, until = models.is_user_banned(db, creator_id)
    if banned:
        remaining = until - int(time.time())
        mins = remaining // 60
        raise PermissionError(
            f"Estás suspendido temporalmente. "
            f"Tiempo restante: {mins} minutos."
        )

    # Validar que no esté en otra partida activa
    user = models.get_user(db, creator_id)
    if user["active_game_id"]:
        raise PermissionError(
            "Ya tienes una partida activa. "
            "Termínala antes de crear una nueva."
        )

    # Validar saldo mínimo
    if user["balance"] < config.BUY_IN:
        raise ValueError(
            f"Saldo insuficiente. "
            f"Se necesitan {config.BUY_IN} fichas para entrar."
        )

    # Descontar buy-in
    models.record_transaction(
        db, creator_id, "buy_in", -config.BUY_IN,
        description="Buy-in partida",
    )

    game = models.create_game(db, creator_id)
    invite_link = f"{config.MINI_APP_URL}?startapp={game['id']}"

    return {
        "game_id": game["id"],
        "invite_link": invite_link,
    }


def join_game(db: Connection, joiner_id: int, game_id: str) -> dict:
    """
    El segundo jugador se une a la partida e inicia la mano.
    Devuelve el estado inicial para ambos jugadores.
    """
    game = models.get_game(db, game_id)

    if not game:
        raise ValueError("La partida no existe o el link es inválido.")
    if game["status"] != "waiting":
        raise ValueError("Esta partida ya no está disponible.")
    if game["creator_id"] == joiner_id:
        raise ValueError("No puedes unirte a tu propia partida.")

    # Validar ban y saldo del segundo jugador
    banned, until = models.is_user_banned(db, joiner_id)
    if banned:
        remaining = until - int(time.time())
        raise PermissionError(
            f"Estás suspendido. Tiempo restante: {remaining // 60} minutos."
        )

    user = models.get_user(db, joiner_id)
    if user["balance"] < config.BUY_IN:
        raise ValueError(
            f"Saldo insuficiente. Se necesitan {config.BUY_IN} fichas."
        )

    # Descontar buy-in
    models.record_transaction(
        db, joiner_id, "buy_in", -config.BUY_IN,
        description="Buy-in partida",
    )

    # Unir jugador y activar partida
    models.join_game(db, game_id, joiner_id)

    # Iniciar el motor — dealer aleatorio en la primera mano
    import random
    dealer_id = random.choice([game["creator_id"], joiner_id])

    engine = PokerEngine(
        player_a_id=game["creator_id"], stack_a=config.BUY_IN,
        player_b_id=joiner_id,          stack_b=config.BUY_IN,
        dealer_id=dealer_id,
        hand_number=1,
    )
    engine.start_hand()
    models.update_game_state(db, game_id, engine.to_dict())

    return {
        "game_id": game_id,
        "state_creator": engine.state_for_player(game["creator_id"]),
        "state_joiner":  engine.state_for_player(joiner_id),
    }


# ══════════════════════════════════════════════════════
#  OBTENER ESTADO
# ══════════════════════════════════════════════════════

def get_state(db: Connection, game_id: str, user_id: int) -> dict:
    """Devuelve el estado actual de la partida filtrado para el jugador."""
    game = models.get_game(db, game_id)
    if not game:
        raise ValueError("Partida no encontrada.")

    state = models.get_game_state(db, game_id)
    if not state:
        raise ValueError("Estado de partida no disponible.")

    engine = PokerEngine.from_dict(state)
    return engine.state_for_player(user_id)


# ══════════════════════════════════════════════════════
#  PROCESAR ACCIÓN
# ══════════════════════════════════════════════════════

def process_action(
    db: Connection, game_id: str, user_id: int,
    action: str, amount: int = 0
) -> dict:
    """
    Procesa una acción del jugador.
    Devuelve el nuevo estado y el outcome si la mano terminó.
    """
    game = models.get_game(db, game_id)
    if not game or game["status"] != "active":
        raise ValueError("Partida no activa.")

    state = models.get_game_state(db, game_id)
    engine = PokerEngine.from_dict(state)

    # Registrar acción en el log
    models.log_action(
        db, game_id, user_id, action,
        engine.current_stage, amount if amount else None,
        engine.hand_number,
    )

    outcome = engine.process_action(user_id, action, amount)

    if outcome:
        return _resolve_hand(db, game_id, game, engine, outcome)

    # La mano continúa — guardar estado
    models.update_game_state(db, game_id, engine.to_dict())

    opponent_id = (
        game["opponent_id"]
        if user_id == game["creator_id"]
        else game["creator_id"]
    )

    return {
        "finished": False,
        "state_actor":    engine.state_for_player(user_id),
        "state_opponent": engine.state_for_player(opponent_id),
    }


# ══════════════════════════════════════════════════════
#  TIMEOUT DE TURNO
# ══════════════════════════════════════════════════════

def process_timeout(db: Connection, game_id: str, user_id: int) -> dict:
    """
    Llamado por el scheduler cuando expira el tiempo de un turno.
    Hace fold automático al jugador que no actuó.
    """
    game = models.get_game(db, game_id)
    if not game or game["status"] != "active":
        return {"error": "Partida no activa"}

    state = models.get_game_state(db, game_id)
    engine = PokerEngine.from_dict(state)

    if engine.current_player_id != user_id:
        return {"error": "No es el turno de este jugador"}

    # Verificar que realmente expiró
    elapsed = time.time() - engine.turn_started_at
    if elapsed < config.TURN_TIMEOUT:
        return {"error": "El turno aún no ha expirado"}

    models.log_action(
        db, game_id, user_id, "fold_timeout",
        engine.current_stage, None, engine.hand_number,
    )

    outcome = engine.process_timeout(user_id)
    return _resolve_hand(db, game_id, game, engine, outcome)


# ══════════════════════════════════════════════════════
#  ABANDONO VOLUNTARIO
# ══════════════════════════════════════════════════════

def abandon_game(db: Connection, game_id: str, user_id: int) -> dict:
    """
    El jugador abandona la partida voluntariamente desde el modal.
    Aplica penalizaciones según el historial de abandonos.
    """
    game = models.get_game(db, game_id)
    if not game or game["status"] != "active":
        raise ValueError("Partida no activa.")

    state = models.get_game_state(db, game_id)
    engine = PokerEngine.from_dict(state)

    # Resolver como fold
    player   = engine._get_player(user_id)
    opponent = engine._get_opponent(user_id)
    outcome  = engine._resolve_fold(player, opponent)
    outcome.reason = "abandon"

    result = _resolve_hand(db, game_id, game, engine, outcome)

    # Registrar abandono y aplicar ban si corresponde
    abandon_count = models.register_abandon(db, user_id)
    ban_duration  = models.apply_ban(db, user_id, abandon_count)

    result["abandon_count"] = abandon_count
    result["ban_applied"]   = ban_duration  # None o minutos

    # Mensaje de advertencia en la segunda salida
    if abandon_count == 2:
        result["warning"] = (
            "⚠️ Segunda salida registrada. "
            "A la tercera serás suspendido temporalmente."
        )

    return result


# ══════════════════════════════════════════════════════
#  HELPER PRIVADO — CIERRE DE MANO
# ══════════════════════════════════════════════════════

def _resolve_hand(
    db: Connection, game_id: str, game,
    engine: PokerEngine, outcome: HandOutcome
) -> dict:
    """
    Aplica el resultado de una mano a la DB:
    devuelve fichas, cobra rake, cierra partida.
    """
    # Devolver fichas restantes + ganancias al ganador
    models.record_transaction(
        db, outcome.winner_id, "win",
        engine._get_player(outcome.winner_id).stack + outcome.winner_profit,
        game_id=game_id,
        description=f"Ganancia mano #{engine.hand_number}",
    )

    # Devolver fichas restantes al perdedor (si quedan)
    loser_stack = engine._get_player(outcome.loser_id).stack
    if loser_stack > 0:
        models.record_transaction(
            db, outcome.loser_id, "loss",
            loser_stack,
            game_id=game_id,
            description=f"Devolución fichas mano #{engine.hand_number}",
        )

    models.finish_game(db, game_id, outcome.winner_id, outcome.rake)
    models.update_game_state(db, game_id, engine.to_dict())

    return {
        "finished": True,
        "outcome": outcome.to_dict(),
        "state_winner": engine.state_for_player(outcome.winner_id),
        "state_loser":  engine.state_for_player(outcome.loser_id),
    }
