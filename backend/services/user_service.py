"""
services/user_service.py
Gestión de usuarios, saldo y consultas de perfil.
"""

import time
from sqlite3 import Connection
from typing import Optional

from db import models
import config


def register_or_update(
    db: Connection,
    user_id: int,
    display_name: str,
    username: Optional[str],
    language_code: str = "es",
) -> dict:
    """
    Registra un usuario nuevo o actualiza sus datos.
    Devuelve el perfil completo.
    """
    user = models.get_or_create_user(
        db, user_id, display_name, username, language_code
    )
    return _build_profile(db, user)


def get_profile(db: Connection, user_id: int) -> dict:
    user = models.get_user(db, user_id)
    if not user:
        raise ValueError("Usuario no encontrado.")
    return _build_profile(db, user)


def get_balance(db: Connection, user_id: int) -> int:
    return models.get_balance(db, user_id)


def get_history(db: Connection, user_id: int, limit: int = 20) -> list[dict]:
    rows = models.get_transaction_history(db, user_id, limit)
    return [dict(r) for r in rows]


def check_ban_status(db: Connection, user_id: int) -> dict:
    banned, until = models.is_user_banned(db, user_id)
    if not banned:
        return {"is_banned": False}
    remaining = until - int(time.time())
    return {
        "is_banned": True,
        "banned_until": until,
        "remaining_minutes": remaining // 60,
        "remaining_seconds": remaining % 60,
    }


# ── HELPER ─────────────────────────────────────────────

def _build_profile(db: Connection, user) -> dict:
    ban = check_ban_status(db, user["id"])
    return {
        "id": user["id"],
        "display_name": user["display_name"],
        "username": user["username"],
        "balance": user["balance"],
        "abandon_count": user["abandon_count"],
        "active_game_id": user["active_game_id"],
        "ban": ban,
        "created_at": user["created_at"],
    }
