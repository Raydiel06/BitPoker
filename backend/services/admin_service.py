"""
services/admin_service.py
Operaciones exclusivas de administrador.
"""

import time
from sqlite3 import Connection
from typing import Optional

from db import models
import config


def add_balance(db: Connection, target_id: int, amount: int,
                reason: str = "Ajuste manual") -> dict:
    """Añade fichas a un usuario."""
    user = models.get_user(db, target_id)
    if not user:
        raise ValueError(f"Usuario {target_id} no encontrado.")
    if amount <= 0:
        raise ValueError("El monto debe ser positivo.")

    models.record_transaction(
        db, target_id, "admin_add", amount,
        description=reason,
    )
    new_balance = models.get_balance(db, target_id)
    return {
        "user_id": target_id,
        "display_name": user["display_name"],
        "added": amount,
        "new_balance": new_balance,
    }


def remove_balance(db: Connection, target_id: int, amount: int,
                   reason: str = "Ajuste manual") -> dict:
    """Retira fichas de un usuario."""
    user = models.get_user(db, target_id)
    if not user:
        raise ValueError(f"Usuario {target_id} no encontrado.")
    if amount <= 0:
        raise ValueError("El monto debe ser positivo.")
    if user["balance"] < amount:
        raise ValueError(
            f"Saldo insuficiente. Balance actual: {user['balance']}."
        )

    models.record_transaction(
        db, target_id, "admin_remove", -amount,
        description=reason,
    )
    new_balance = models.get_balance(db, target_id)
    return {
        "user_id": target_id,
        "display_name": user["display_name"],
        "removed": amount,
        "new_balance": new_balance,
    }


def ban_user(db: Connection, target_id: int,
             duration_minutes: int, reason: str = "Ban manual") -> dict:
    """Banea a un usuario por X minutos."""
    user = models.get_user(db, target_id)
    if not user:
        raise ValueError(f"Usuario {target_id} no encontrado.")
    if config.is_admin(target_id):
        raise PermissionError("No puedes banear a un administrador.")

    now = int(time.time())
    ends_at = now + duration_minutes * 60

    db.execute(
        """
        UPDATE users
        SET is_banned = 1, banned_until = ?, updated_at = ?
        WHERE id = ?
        """,
        (ends_at, now, target_id),
    )
    db.execute(
        """
        INSERT INTO bans (user_id, reason, abandon_count_at_ban,
                          duration_minutes, ends_at)
        VALUES (?, ?, 0, ?, ?)
        """,
        (target_id, reason, duration_minutes, ends_at),
    )
    return {
        "user_id": target_id,
        "display_name": user["display_name"],
        "banned_until": ends_at,
        "duration_minutes": duration_minutes,
    }


def unban_user(db: Connection, target_id: int) -> dict:
    """Levanta el ban de un usuario."""
    user = models.get_user(db, target_id)
    if not user:
        raise ValueError(f"Usuario {target_id} no encontrado.")

    now = int(time.time())
    db.execute(
        """
        UPDATE users
        SET is_banned = 0, banned_until = NULL, abandon_count = 0,
            updated_at = ?
        WHERE id = ?
        """,
        (now, target_id),
    )
    db.execute(
        "UPDATE bans SET is_active = 0 WHERE user_id = ? AND is_active = 1",
        (target_id,),
    )
    return {
        "user_id": target_id,
        "display_name": user["display_name"],
        "unbanned": True,
    }


def check_user(db: Connection, target_id: int) -> dict:
    """Devuelve información completa de un usuario."""
    user = models.get_user(db, target_id)
    if not user:
        raise ValueError(f"Usuario {target_id} no encontrado.")

    banned, until = models.is_user_banned(db, target_id)
    history = models.get_transaction_history(db, target_id, limit=5)

    return {
        "id": user["id"],
        "display_name": user["display_name"],
        "username": user["username"],
        "balance": user["balance"],
        "abandon_count": user["abandon_count"],
        "active_game_id": user["active_game_id"],
        "is_banned": banned,
        "banned_until": until,
        "created_at": user["created_at"],
        "recent_transactions": [dict(h) for h in history],
    }


def list_users(db: Connection, limit: int = 20,
               offset: int = 0) -> dict:
    """Lista usuarios ordenados por fecha de registro."""
    rows = db.execute(
        """
        SELECT id, display_name, username, balance,
               is_banned, active_game_id, created_at
        FROM users
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()

    total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    return {
        "total": total,
        "users": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


def get_stats(db: Connection) -> dict:
    """Estadísticas generales del casino."""
    total_users = db.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    active_games = db.execute(
        "SELECT COUNT(*) FROM games WHERE status = 'active'"
    ).fetchone()[0]

    total_games = db.execute(
        "SELECT COUNT(*) FROM games WHERE status = 'finished'"
    ).fetchone()[0]

    total_rake = db.execute(
        "SELECT COALESCE(SUM(rake_amount), 0) FROM games WHERE status = 'finished'"
    ).fetchone()[0]

    banned_users = db.execute(
        "SELECT COUNT(*) FROM users WHERE is_banned = 1"
    ).fetchone()[0]

    return {
        "total_users": total_users,
        "active_games": active_games,
        "finished_games": total_games,
        "total_rake_collected": total_rake,
        "banned_users": banned_users,
                     }
                     
