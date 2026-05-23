-- ============================================================
--  POKER BOT — ESQUEMA DE BASE DE DATOS
--  Motor: SQLite
--  Notación: snake_case, timestamps en Unix epoch (INTEGER)
-- ============================================================


-- ============================================================
--  USUARIOS
--  Fuente de verdad del jugador. Se crea automáticamente
--  la primera vez que el usuario interactúa con el bot.
-- ============================================================
CREATE TABLE users (
    id                  INTEGER PRIMARY KEY,        -- Telegram user_id (no autoincrementar, viene de Telegram)
    username            TEXT,                       -- @username de Telegram (puede ser NULL si no tiene)
    display_name        TEXT    NOT NULL,           -- first_name de Telegram como fallback
    avatar_url          TEXT,                       -- URL de foto de perfil (actualizable)
    balance             INTEGER NOT NULL DEFAULT 0, -- Saldo interno en centavos (evita decimales flotantes)
    language_code       TEXT    NOT NULL DEFAULT 'es', -- Código ISO del idioma tomado de Telegram

    -- Estado de sesión
    active_game_id      TEXT,                       -- FK a games.id — NULL si no está en partida
    is_banned           INTEGER NOT NULL DEFAULT 0, -- 0 = libre, 1 = baneado temporalmente
    banned_until        INTEGER,                    -- Unix timestamp de fin de ban (NULL si no baneado)

    -- Sistema de abandonos
    abandon_count       INTEGER NOT NULL DEFAULT 0, -- Contador de abandonos en la ventana activa
    last_abandon_at     INTEGER,                    -- Unix timestamp del último abandono
    -- Nota: el reset se evalúa en runtime comparando (NOW - last_abandon_at) > 86400 segundos

    created_at          INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    updated_at          INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

-- Índices de usuarios
CREATE INDEX idx_users_active_game ON users(active_game_id);
CREATE INDEX idx_users_banned      ON users(is_banned, banned_until);


-- ============================================================
--  PARTIDAS
--  Una partida = una mesa 1v1 completa desde creación
--  hasta que termina. Contiene el estado serializado
--  del juego para sobrevivir desconexiones y reinicios.
-- ============================================================
CREATE TABLE games (
    id              TEXT    PRIMARY KEY,            -- UUID generado en el backend (ej: "a3f9c1b2")
    creator_id      INTEGER NOT NULL REFERENCES users(id),
    opponent_id     INTEGER REFERENCES users(id),   -- NULL hasta que alguien se una

    status          TEXT    NOT NULL DEFAULT 'waiting',
    -- Valores posibles:
    --   'waiting'   — creada, esperando segundo jugador
    --   'active'    — ambos jugadores conectados, mano en curso
    --   'finished'  — partida terminada normalmente
    --   'abandoned' — un jugador se rindió o fue expulsado por timeout

    -- Configuración de la mesa
    small_blind     INTEGER NOT NULL DEFAULT 10,    -- en centavos
    big_blind       INTEGER NOT NULL DEFAULT 20,    -- en centavos
    buy_in          INTEGER NOT NULL DEFAULT 1000,  -- stack inicial en centavos

    -- Estado serializado de la mano actual
    -- Se actualiza en CADA acción del juego
    game_state      TEXT,
    -- Estructura JSON del game_state:
    -- {
    --   "stage":          "preflop|flop|turn|river|showdown",
    --   "deck":           [...cartas restantes],
    --   "community":      [...hasta 5 cartas],
    --   "pot":            integer (centavos),
    --   "current_turn":   user_id,
    --   "turn_started_at": unix_timestamp,
    --   "players": {
    --     "<user_id>": {
    --       "hole_cards":  [carta1, carta2],
    --       "stack":       integer,
    --       "bet":         integer,
    --       "status":      "active|folded|all_in"
    --     }
    --   }
    -- }

    winner_id       INTEGER REFERENCES users(id),   -- NULL hasta que termine
    rake_amount     INTEGER NOT NULL DEFAULT 0,      -- rake cobrado en centavos

    -- Timestamps clave
    created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    started_at      INTEGER,                         -- cuando se unió el segundo jugador
    finished_at     INTEGER                          -- cuando terminó la partida
);

-- Índices de partidas
CREATE INDEX idx_games_status      ON games(status);
CREATE INDEX idx_games_creator     ON games(creator_id);
CREATE INDEX idx_games_opponent    ON games(opponent_id);


-- ============================================================
--  HISTORIAL DE ACCIONES
--  Registro inmutable de cada acción en cada mano.
--  Sirve para auditoría, replay y detección de trampas.
--  No se actualiza nunca, solo INSERT.
-- ============================================================
CREATE TABLE game_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT    NOT NULL REFERENCES games(id),
    user_id         INTEGER NOT NULL REFERENCES users(id),
    hand_number     INTEGER NOT NULL DEFAULT 1,      -- número de mano dentro de la partida (para futuras multi-manos)

    action_type     TEXT    NOT NULL,
    -- Valores posibles:
    --   'join'      — segundo jugador se unió
    --   'deal'      — mano repartida (sistema)
    --   'check'     — pasar sin apostar
    --   'call'      — igualar apuesta
    --   'raise'     — subir apuesta
    --   'fold'      — retirarse de la mano
    --   'auto_fold' — fold automático por timeout
    --   'surrender' — rendirse desde el menú
    --   'all_in'    — apostar todo el stack
    --   'showdown'  — mostrar cartas al final

    amount          INTEGER,                         -- centavos (NULL para acciones sin monto)
    stage           TEXT,                            -- etapa del juego al momento de la acción
    created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

-- Índices de acciones
CREATE INDEX idx_actions_game    ON game_actions(game_id, hand_number);
CREATE INDEX idx_actions_user    ON game_actions(user_id);


-- ============================================================
--  TRANSACCIONES DE SALDO
--  Registro inmutable de cada movimiento de dinero.
--  El saldo en users.balance es la suma de estas entradas.
--  Nunca se actualiza, solo INSERT.
-- ============================================================
CREATE TABLE transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),

    type            TEXT    NOT NULL,
    -- Valores posibles:
    --   'deposit'       — recarga de saldo (futuro: cripto)
    --   'withdrawal'    — retiro de saldo (futuro: cripto)
    --   'bet'           — apuesta en una mano
    --   'win'           — ganancia de una mano
    --   'rake'          — comisión cobrada por la plataforma
    --   'refund'        — devolución (ej: error del sistema)
    --   'bonus'         — saldo de bienvenida u otros bonos

    amount          INTEGER NOT NULL,                -- positivo = entrada, negativo = salida (centavos)
    balance_after   INTEGER NOT NULL,                -- snapshot del saldo tras la transacción
    game_id         TEXT    REFERENCES games(id),    -- NULL para depósitos y retiros
    description     TEXT,                            -- texto libre para auditoría

    created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

-- Índices de transacciones
CREATE INDEX idx_tx_user    ON transactions(user_id, created_at);
CREATE INDEX idx_tx_game    ON transactions(game_id);
CREATE INDEX idx_tx_type    ON transactions(type);


-- ============================================================
--  BANS
--  Historial completo de restricciones.
--  Permite escalar duración por reincidencia y auditar.
-- ============================================================
CREATE TABLE bans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),

    reason          TEXT    NOT NULL DEFAULT 'frequent_abandon',
    -- Valores posibles:
    --   'frequent_abandon' — abandono reiterado
    --   'manual'           — ban manual por administrador (futuro)

    abandon_count_at_ban INTEGER NOT NULL,           -- contador de abandonos que disparó el ban
    duration_minutes     INTEGER NOT NULL,           -- duración en minutos (90, 180, 360...)
    starts_at            INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    ends_at              INTEGER NOT NULL,           -- starts_at + (duration_minutes * 60)
    is_active            INTEGER NOT NULL DEFAULT 1  -- 0 cuando expires o se levanta manualmente
);

-- Índices de bans
CREATE INDEX idx_bans_user   ON bans(user_id, is_active);
CREATE INDEX idx_bans_active ON bans(is_active, ends_at);


-- ============================================================
--  LÓGICA DE NEGOCIO — RESUMEN
--
--  RAKE:
--    Se calcula al cierre de cada mano.
--    rate = 0.03 (3% por defecto, ajustable)
--    rake = MIN(pot * rate, pot * 0.05)  — cap en 5%
--    Se descuenta del pot antes de pagar al ganador.
--
--  SISTEMA DE ABANDONOS:
--    Al registrar un abandono (surrender o auto_fold por desconexión):
--      1. Verificar si (NOW - last_abandon_at) > 86400 → resetear abandon_count a 0
--      2. Incrementar abandon_count += 1
--      3. Actualizar last_abandon_at = NOW
--      4. Evaluar:
--           abandon_count == 2 → enviar advertencia por bot
--           abandon_count == 3 → ban 90 min,  INSERT en bans
--           abandon_count == 4 → ban 180 min, INSERT en bans
--           abandon_count == 5 → ban 360 min, INSERT en bans
--           abandon_count >  5 → ban 360 * (abandon_count - 4) min
--
--  UNA PARTIDA ACTIVA POR JUGADOR:
--    Antes de crear o unirse a una partida, verificar:
--      users.active_game_id IS NULL
--    Al terminar la partida, limpiar:
--      UPDATE users SET active_game_id = NULL WHERE id IN (creator_id, opponent_id)
--
--  TIMEOUT DE TURNO:
--    El backend evalúa (NOW - game_state.turn_started_at) > 30
--    Si expira: registrar auto_fold en game_actions y procesar como fold normal.
--    Cuenta como abandono solo si es la última acción de la mano (el jugador nunca actuó).
--    Un auto_fold mid-hand por mala conexión puntual NO penaliza.
--
-- ============================================================
