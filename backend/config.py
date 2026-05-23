import os
from dotenv import load_dotenv

load_dotenv()

# ── TELEGRAM ──────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
MINI_APP_URL: str = os.getenv("MINI_APP_URL", "")  # URL donde vive el frontend

# ── BASE DE DATOS ──────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "casino.db")

# ── POKER ──────────────────────────────────────────────
SMALL_BLIND: int = 10       # centavos
BIG_BLIND: int   = 20       # centavos
BUY_IN: int      = 1000     # centavos (stack inicial)
TURN_TIMEOUT: int = 30      # segundos por turno
RAKE_RATE: float  = 0.03    # 3%
RAKE_CAP: float   = 0.05    # máximo 5% del pot

# ── SISTEMA DE ABANDONOS ───────────────────────────────
ABANDON_RESET_SECONDS: int = 86400  # 1 día

# Duración de bans en minutos según abandon_count
BAN_DURATIONS: dict[int, int] = {
    3: 90,
    4: 180,
    5: 360,
}

def get_ban_duration(abandon_count: int) -> int:
    """Devuelve duración del ban en minutos según reincidencia."""
    if abandon_count in BAN_DURATIONS:
        return BAN_DURATIONS[abandon_count]
    if abandon_count > 5:
        return 360 * (abandon_count - 4)
    return 0  # sin ban

# ── VALIDACIONES AL ARRANCAR ───────────────────────────
def validate():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN no está definido en .env")
    if not MINI_APP_URL:
        raise ValueError("MINI_APP_URL no está definido en .env")
