import os
from dotenv import load_dotenv

load_dotenv()

# ── TELEGRAM ──────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
MINI_APP_URL: str = os.getenv("MINI_APP_URL", "")

# ── ADMINISTRADORES ────────────────────────────────────
ADMIN_IDS: set[int] = {1519654469}  # añadir más IDs aquí cuando escale

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ── BASE DE DATOS ──────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "casino.db")

# ── POKER ──────────────────────────────────────────────
SMALL_BLIND: int  = 10
BIG_BLIND: int    = 20
BUY_IN: int       = 1000
TURN_TIMEOUT: int = 30
RAKE_RATE: float  = 0.03
RAKE_CAP: float   = 0.05

# ── USUARIOS NUEVOS ────────────────────────────────────
WELCOME_BONUS: int = 1000  # fichas al registrarse

# ── SISTEMA DE ABANDONOS ───────────────────────────────
ABANDON_RESET_SECONDS: int = 86400

BAN_DURATIONS: dict[int, int] = {
    3: 90,
    4: 180,
    5: 360,
}

def get_ban_duration(abandon_count: int) -> int:
    if abandon_count in BAN_DURATIONS:
        return BAN_DURATIONS[abandon_count]
    if abandon_count > 5:
        return 360 * (abandon_count - 4)
    return 0

# ── VALIDACIONES ───────────────────────────────────────
def validate():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN no está definido en .env")
    if not MINI_APP_URL:
        raise ValueError("MINI_APP_URL no está definido en .env")
                     
