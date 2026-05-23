/**
 * js/api.js
 * Capa de comunicación con el backend.
 * Todos los requests pasan por aquí — nunca llamar fetch directamente.
 *
 * Responsabilidades:
 * - Adjuntar el initData de Telegram en cada request
 * - Reintentos automáticos en errores de red (hasta 3 veces)
 * - Normalizar errores para que Game.js los maneje de forma uniforme
 */

const API = (() => {
  // ── CONFIG ──────────────────────────────────────────
  const BASE_URL = 'https://bitpoker-production.up.railway.app';  // reemplazar en producción
  const MAX_RETRIES = 3;
  const RETRY_DELAY_MS = 1200;  // espera entre reintentos

  // initData que Telegram inyecta en la Mini App
  function getInitData() {
    return window.Telegram?.WebApp?.initData || '';
  }

  // ── REQUEST BASE ────────────────────────────────────

  async function request(method, path, body = null, attempt = 1) {
    const options = {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-Init-Data': getInitData(),
      },
    };

    if (body) options.body = JSON.stringify(body);

    try {
      const res = await fetch(BASE_URL + path, options);

      // Error del servidor — no reintentar en 4xx (son errores de lógica)
      if (res.status >= 400 && res.status < 500) {
        const data = await res.json().catch(() => ({}));
        throw new APIError(res.status, data.detail || 'Error del servidor');
      }

      // Error 5xx — reintentar
      if (!res.ok) {
        throw new NetworkError(`HTTP ${res.status}`);
      }

      return await res.json();

    } catch (err) {
      // Error de red (sin conexión, timeout, etc.)
      if (err instanceof NetworkError || !(err instanceof APIError)) {
        if (attempt < MAX_RETRIES) {
          console.warn(`[API] Reintento ${attempt}/${MAX_RETRIES} para ${path}`);
          await sleep(RETRY_DELAY_MS * attempt);
          return request(method, path, body, attempt + 1);
        }
      }
      throw err;
    }
  }

  // ── ENDPOINTS ───────────────────────────────────────

  const get  = (path)        => request('GET',  path);
  const post = (path, body)  => request('POST', path, body);

  return {
    // Usuario
    getMe:      ()           => get('/me'),
    getBalance: ()           => get('/me/balance'),
    getHistory: ()           => get('/me/history'),

    // Partida
    createGame: ()           => post('/game/create'),
    joinGame:   (gameId)     => post(`/game/${gameId}/join`),
    getState:   (gameId)     => get(`/game/${gameId}/state`),
    sendAction: (gameId, action, amount = 0) =>
      post(`/game/${gameId}/action`, { action, amount }),
    abandonGame:(gameId)     => post(`/game/${gameId}/abandon`),
  };

  // ── HELPERS ─────────────────────────────────────────
  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
})();

// ── TIPOS DE ERROR ───────────────────────────────────

class APIError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
    this.name = 'APIError';
  }
}

class NetworkError extends Error {
  constructor(message) {
    super(message);
    this.name = 'NetworkError';
  }
}
