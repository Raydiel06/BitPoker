"""
api/main.py
API FastAPI — sirve al frontend de la Mini App durante el juego.
Todos los endpoints validan el initData de Telegram para
verificar que la petición viene de un usuario real.
"""

from contextlib import asynccontextmanager
from typing import Optional
import hashlib
import hmac
import json
import time
from urllib.parse import unquote, parse_qsl

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from db.database import get_db, init_db
from services import game_service, user_service


# ══════════════════════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate()
    with get_db() as db:
        init_db()
    yield

app = FastAPI(title="Casino Poker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # En producción limitar a MINI_APP_URL
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════
#  VALIDACIÓN DE TELEGRAM initData
# ══════════════════════════════════════════════════════

def verify_telegram_init_data(init_data: str) -> dict:
    """
    Verifica la firma del initData que envía la Mini App.
    Devuelve los datos del usuario si es válido.
    Lanza HTTPException 401 si es inválido o expirado.
    Documentación: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    try:
        parsed = dict(parse_qsl(unquote(init_data), keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            raise ValueError("hash ausente")

        # Verificar expiración (24h)
        auth_date = int(parsed.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            raise ValueError("initData expirado")

        # Construir data_check_string
        data_check = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        # HMAC-SHA256
        secret_key = hmac.new(
            b"WebAppData",
            config.BOT_TOKEN.encode(),
            hashlib.sha256,
        ).digest()
        expected = hmac.new(
            secret_key,
            data_check.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, received_hash):
            raise ValueError("firma inválida")

        user_data = json.loads(parsed["user"])
        return user_data

    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Unauthorized: {e}")


def get_current_user(x_init_data: str = Header(...)) -> dict:
    """Dependency — extrae el usuario validado del header."""
    return verify_telegram_init_data(x_init_data)


# ══════════════════════════════════════════════════════
#  SCHEMAS
# ══════════════════════════════════════════════════════

class ActionRequest(BaseModel):
    action: str           # fold | check | call | raise
    amount: int = 0       # solo relevante en raise


# ══════════════════════════════════════════════════════
#  ENDPOINTS
# ══════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": int(time.time())}


# ── USUARIO ────────────────────────────────────────────

@app.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    """Perfil del usuario autenticado."""
    with get_db() as db:
        profile = user_service.register_or_update(
            db,
            user_id=user["id"],
            display_name=user.get("first_name", ""),
            username=user.get("username"),
            language_code=user.get("language_code", "es"),
        )
    return profile


@app.get("/me/balance")
def get_balance(user: dict = Depends(get_current_user)):
    with get_db() as db:
        balance = user_service.get_balance(db, user["id"])
    return {"balance": balance}


@app.get("/me/history")
def get_history(user: dict = Depends(get_current_user)):
    with get_db() as db:
        history = user_service.get_history(db, user["id"])
    return {"transactions": history}


# ── PARTIDA ────────────────────────────────────────────

@app.post("/game/create")
def create_game(user: dict = Depends(get_current_user)):
    """Crea una nueva partida y devuelve el link de invitación."""
    try:
        with get_db() as db:
            result = game_service.create_game(db, user["id"])
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/game/{game_id}/join")
def join_game(game_id: str, user: dict = Depends(get_current_user)):
    """El segundo jugador se une a la partida."""
    try:
        with get_db() as db:
            result = game_service.join_game(db, user["id"], game_id)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/game/{game_id}/state")
def get_state(game_id: str, user: dict = Depends(get_current_user)):
    """Estado actual de la partida filtrado para el jugador."""
    try:
        with get_db() as db:
            state = game_service.get_state(db, game_id, user["id"])
        return state
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/game/{game_id}/action")
def process_action(
    game_id: str,
    body: ActionRequest,
    user: dict = Depends(get_current_user),
):
    """Procesa una acción del jugador: fold, check, call o raise."""
    try:
        with get_db() as db:
            result = game_service.process_action(
                db, game_id, user["id"],
                body.action, body.amount,
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.post("/game/{game_id}/abandon")
def abandon_game(game_id: str, user: dict = Depends(get_current_user)):
    """El jugador abandona voluntariamente desde el modal."""
    try:
        with get_db() as db:
            result = game_service.abandon_game(db, game_id, user["id"])
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/game/{game_id}/timeout/{user_id}")
def process_timeout(game_id: str, user_id: int):
    """
    Llamado internamente por el scheduler cuando expira un turno.
    No requiere autenticación — es una llamada interna del servidor.
    En producción proteger con un secret interno.
    """
    with get_db() as db:
        result = game_service.process_timeout(db, game_id, user_id)
    return result
