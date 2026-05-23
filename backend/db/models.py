"""
db/models.py
Todas las operaciones de base de datos del proyecto.
Cada función recibe una conexión activa (db) y opera dentro
de la transacción del llamador — nunca abre su propia transacción.
"""

import json
import time
import uuid
from sqlite3 import Connection, Row
from typing import Optional

import config


# ══════════════════════════════════════════════════════
#  USUARIOS
# ══════════════════════════════════════════════════════

def get_user(db: Connection, user_id: int) -> Optional[Row]:
    return db.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def create_user(db: Connection, user_id: int, display_name: str,
                username: Optional[str], language_code: str = "es") -> Row:
    db.execute(
        """
        INSERT INTO users (id, display_name, username, language_code)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, display_name, username, language_code),
    )
    return get_user(db, user_id)


def get_or_create_user(db: Connection, user_id: int, display_name: str,
                       username: Optional[str], language_code: str = "es") -> Row:
    """Crea el usuario si no existe. Actualiza nombre y username si ya existe."""
    user = get_user(db, user_id)
    if user is None:
        return create_user(db, user_id, display_name, username, language_code)

    # Actualizar datos que pueden cambiar en Telegram
    db.execute(
        """
        UPDATE users
        SET display_name = ?, username = ?, updated_at = ?
        WHERE id = ?
        """,
        (display_name, username, int(time.time()), user_id),
    )
    return get_user(db, user_id)


def update_user_balance(db: Connection, user_id: int, new_balance: int) -> None:
    db.execute(
        "UPDATE users SET balance = ?, updated_at = ? WHERE id = ?",
        (new_balance, int(time.time()), user_id),
    )


def set_user_active_game(db: Connection, user_id: int,
                         game_id: Optional[str]) -> None:
    db.execute(
        "UPDATE users SET active_game_id = ?, updated_at = ? WHERE id = ?",
        (game_id, int(time.time()), user_id),
    )


def is_user_banned(db: Connection, user_id: int) -> tuple[bool, Optional[int]]:
    """
    Devuelve (baneado, banned_until).
    Limpia el ban automáticamente si ya expiró.
    """
    user = get_user(db, user_id)
    if not user or not user["is_banned"]:
        return False, None

    now = int(time.time())
    if user["banned_until"] and user["banned_until"] <= now:
        # Ban expirado — limpiar
        db.execute(
            "UPDATE users SET is_banned = 0, banned_until = NULL, updated_at = ? WHERE id = ?",
            (now, user_id),
        )
        db.execute(
            "UPDATE bans SET is_active = 0 WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )
        return False, None

    return True, user["banned_until"]


# ══════════════════════════════════════════════════════
#  SISTEMA DE ABANDONOS
# ══════════════════════════════════════════════════════

def register_abandon(db: Connection, user_id: int) -> int:
    """
    Registra un abandono y devuelve el abandon_count actualizado.
    Aplica el reset de 24h si corresponde.
    """
    user = get_user(db, user_id)
    now = int(time.time())

    # Resetear si pasó más de 1 día desde el último abandono
    count = user["abandon_count"]
    last = user["last_abandon_at"]
    if last and (now - last) > config.ABANDON_RESET_SECONDS:
        count = 0

    count += 1
    db.execute(
        """
        UPDATE users
        SET abandon_count = ?, last_abandon_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (count, now, now, user_id),
    )
    return count


def apply_ban(db: Connection, user_id: int, abandon_count: int) -> Optional[int]:
    """
    Aplica ban si corresponde según abandon_count.
    Devuelve duración en minutos o None si no hubo ban.
    """
    duration = config.get_ban_duration(abandon_count)
    if duration == 0:
        return None

    now = int(time.time())
    ends_at = now + duration * 60

    db.execute(
        """
        UPDATE users
        SET is_banned = 1, banned_until = ?, updated_at = ?
        WHERE id = ?
        """,
        (ends_at, now, user_id),
    )
    db.execute(
        """
        INSERT INTO bans (user_id, reason, abandon_count_at_ban, duration_minutes, ends_at)
        VALUES (?, 'frequent_abandon', ?, ?, ?)
        """,
        (user_id, abandon_count, duration, ends_at),
    )
    return duration


# ══════════════════════════════════════════════════════
#  PARTIDAS
# ══════════════════════════════════════════════════════

def create_game(db: Connection, creator_id: int) -> Row:
    game_id = uuid.uuid4().hex[:8]  # ID corto legible
    db.execute(
        """
        INSERT INTO games (id, creator_id, small_blind, big_blind, buy_in)
        VALUES (?, ?, ?, ?, ?)
        """,
        (game_id, creator_id, config.SMALL_BLIND, config.BIG_BLIND, config.BUY_IN),
    )
    set_user_active_game(db, creator_id, game_id)
    return get_game(db, game_id)


def get_game(db: Connection, game_id: str) -> Optional[Row]:
    return db.execute(
        "SELECT * FROM games WHERE id = ?", (game_id,)
    ).fetchone()


def join_game(db: Connection, game_id: str, opponent_id: int) -> Row:
    now = int(time.time())
    db.execute(
        """
        UPDATE games
        SET opponent_id = ?, status = 'active', started_at = ?
        WHERE id = ?
        """,
        (opponent_id, now, game_id),
    )
    set_user_active_game(db, opponent_id, game_id)
    return get_game(db, game_id)


def update_game_state(db: Connection, game_id: str, state: dict) -> None:
    db.execute(
        "UPDATE games SET game_state = ? WHERE id = ?",
        (json.dumps(state), game_id),
    )


def finish_game(db: Connection, game_id: str, winner_id: int,
                rake_amount: int) -> None:
    now = int(time.time())
    db.execute(
        """
        UPDATE games
        SET status = 'finished', winner_id = ?, rake_amount = ?, finished_at = ?
        WHERE id = ?
        """,
        (winner_id, rake_amount, now, game_id),
    )
    # Liberar a ambos jugadores
    game = get_game(db, game_id)
    set_user_active_game(db, game["creator_id"], None)
    if game["opponent_id"]:
        set_user_active_game(db, game["opponent_id"], None)


def abandon_game(db: Connection, game_id: str) -> None:
    now = int(time.time())
    db.execute(
        """
        UPDATE games
        SET status = 'abandoned', finished_at = ?
        WHERE id = ?
        """,
        (now, game_id),
    )
    game = get_game(db, game_id)
    set_user_active_game(db, game["creator_id"], None)
    if game["opponent_id"]:
        set_user_active_game(db, game["opponent_id"], None)


def get_game_state(db: Connection, game_id: str) -> Optional[dict]:
    game = get_game(db, game_id)
    if not game or not game["game_state"]:
        return None
    return json.loads(game["game_state"])


# ══════════════════════════════════════════════════════
#  ACCIONES
# ══════════════════════════════════════════════════════

def log_action(db: Connection, game_id: str, user_id: int,
               action_type: str, stage: str,
               amount: Optional[int] = None,
               hand_number: int = 1) -> None:
    db.execute(
        """
        INSERT INTO game_actions
            (game_id, user_id, hand_number, action_type, amount, stage)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (game_id, user_id, hand_number, action_type, amount, stage),
    )


# ══════════════════════════════════════════════════════
#  TRANSACCIONES
# ══════════════════════════════════════════════════════

def record_transaction(db: Connection, user_id: int, tx_type: str,
                       amount: int, game_id: Optional[str] = None,
                       description: Optional[str] = None) -> None:
    """
    Registra un movimiento de saldo y actualiza users.balance.
    amount positivo = entrada, negativo = salida.
    """
    user = get_user(db, user_id)
    new_balance = user["balance"] + amount

    if new_balance < 0:
        raise ValueError(
            f"Saldo insuficiente: balance={user['balance']}, amount={amount}"
        )

    update_user_balance(db, user_id, new_balance)
    db.execute(
        """
        INSERT INTO transactions
            (user_id, type, amount, balance_after, game_id, description)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, tx_type, amount, new_balance, game_id, description),
    )


def get_balance(db: Connection, user_id: int) -> int:
    user = get_user(db, user_id)
    return user["balance"] if user else 0


def get_transaction_history(db: Connection, user_id: int,
                            limit: int = 20) -> list[Row]:
    return db.execute(
        """
        SELECT * FROM transactions
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
