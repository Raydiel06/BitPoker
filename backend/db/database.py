import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import config

# Una conexión por hilo — SQLite no es thread-safe por defecto
_local = threading.local()


def _get_raw_connection() -> sqlite3.Connection:
    """Devuelve la conexión del hilo actual, creándola si no existe."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(
            config.DB_PATH,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        _local.conn.row_factory = sqlite3.Row   # acceso por nombre de columna
        _local.conn.execute("PRAGMA journal_mode=WAL")   # mejor concurrencia
        _local.conn.execute("PRAGMA foreign_keys=ON")    # integridad referencial
    return _local.conn


@contextmanager
def get_db():
    """
    Context manager para operaciones de base de datos.

    Uso:
        with get_db() as db:
            db.execute("SELECT ...")

    Hace commit automático si no hubo excepciones.
    Hace rollback y relanza si hubo error.
    """
    conn = _get_raw_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    """
    Inicializa la base de datos ejecutando el schema.sql.
    Solo crea tablas si no existen — seguro de ejecutar siempre al arrancar.
    """
    schema_path = Path(__file__).parent / "schema.sql"
    if not schema_path.exists():
        raise FileNotFoundError(f"schema.sql no encontrado en {schema_path}")

    with get_db() as db:
        db.executescript(schema_path.read_text())

    print(f"[DB] Base de datos lista en: {config.DB_PATH}")


def close_db():
    """Cierra la conexión del hilo actual. Útil al apagar el servidor."""
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None
