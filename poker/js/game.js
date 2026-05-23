/**
 * js/game.js
 * Módulo principal del juego.
 * Conecta la API con el DOM — es el cerebro del frontend.
 *
 * Responsabilidades:
 * - Inicializar la partida al cargar la Mini App
 * - Mantener el estado local sincronizado con el backend
 * - Renderizar el estado en el DOM
 * - Manejar acciones del jugador (fold, call, raise)
 * - Polling cuando es el turno del oponente
 * - Manejar reconexión y errores de red
 */

const Game = (() => {

  // ── ESTADO LOCAL ────────────────────────────────────
  let gameId       = null;
  let myUserId     = null;
  let currentState = null;
  let pollingId    = null;
  const POLL_INTERVAL = 2000;  // ms — solo cuando es turno del oponente

  // ── REFS DOM ─────────────────────────────────────────

  const dom = {
    // Oponente
    opponentName:    document.querySelector('.opponent-block .player-name'),
    opponentBalance: document.querySelector('.opponent-block .player-balance'),
    opponentBet:     document.querySelector('.opponent-block .bet-tag'),
    opponentDealer:  document.querySelector('.opponent-block .dealer-badge'),
    opponentCards:   document.querySelector('.opponent-block .hand-cards'),

    // Mesa
    communityCards:  document.querySelector('.community-cards'),
    potAmount:       document.querySelector('.pot-amount'),

    // Yo
    myName:          document.querySelector('.self-left .player-name'),
    myBalance:       document.querySelector('.self-left .player-balance'),
    myBet:           document.querySelector('.self-left .bet-tag'),
    myCards:         document.querySelector('.self-left .hand-cards'),

    // Acciones
    btnFold:         document.querySelector('.btn-fold'),
    btnCall:         document.querySelector('.btn-call'),
    btnRaise:        document.getElementById('raise-toggle'),
    btnConfirm:      document.querySelector('.btn-confirm'),
    actionsArea:     document.querySelector('.action-btns'),

    // Timer
    timerBlock:      document.querySelector('.timer-block'),
    turnLabel:       document.querySelector('.turn-label span:nth-child(2)'),
  };

  // ── INIT ─────────────────────────────────────────────

  async function init() {
    // Inicializar Telegram Mini App
    const tg = window.Telegram?.WebApp;
    if (tg) {
      tg.ready();
      tg.expand();
    }

    // Obtener game_id del startapp parameter
    gameId = _getGameIdFromUrl();
    if (!gameId) {
      _showError('Link de partida inválido.');
      return;
    }

    // Obtener perfil del usuario
    try {
      const me = await API.getMe();
      myUserId = me.id;
    } catch (e) {
      _showError('No se pudo autenticar. Abre el juego desde Telegram.');
      return;
    }

    // Unirse o reconectar a la partida
    await _joinOrReconnect();
  }

  async function _joinOrReconnect() {
    try {
      // Intentar obtener estado primero (reconexión)
      const state = await API.getState(gameId);
      currentState = state;
      render(state);
      _startPollingIfNeeded(state);
    } catch (e) {
      if (e instanceof APIError && e.status === 404) {
        // La partida existe pero aún no empezó — intentar unirse
        await _tryJoin();
      } else {
        _showError('Error al conectar con la partida.');
      }
    }
  }

  async function _tryJoin() {
    try {
      const result = await API.joinGame(gameId);
      currentState = result[`state_joiner`] || result[`state_creator`];
      render(currentState);
      _startPollingIfNeeded(currentState);
    } catch (e) {
      if (e instanceof APIError) {
        _showError(e.message);
      } else {
        _showError('Error de conexión al unirse a la partida.');
      }
    }
  }

  // ── RENDER ───────────────────────────────────────────

  function render(state) {
    if (!state) return;
    currentState = state;

    _renderCommunityCards(state.community_cards || []);
    _renderPot(state.pot);
    _renderMyInfo(state);
    _renderOpponentInfo(state);
    _renderActions(state);
    _renderTimer(state);
  }

  function _renderCommunityCards(cards) {
    dom.communityCards.innerHTML = '';

    // Siempre 5 slots — rellenar con backs los que faltan
    for (let i = 0; i < 5; i++) {
      if (cards[i]) {
        dom.communityCards.appendChild(_buildCard(cards[i]));
      } else {
        dom.communityCards.appendChild(_buildBackCard());
      }
    }
  }

  function _renderPot(pot) {
    dom.potAmount.textContent = `$${(pot / 100).toFixed(2)}`;
  }

  function _renderMyInfo(state) {
    dom.myBalance.textContent = `$${(state.your_stack / 100).toFixed(2)}`;
    dom.myBet.textContent     = `Apuesta $${(state.your_bet / 100).toFixed(2)}`;

    dom.myCards.innerHTML = '';
    (state.your_cards || []).forEach(c => {
      dom.myCards.appendChild(_buildCard(c));
    });
  }

  function _renderOpponentInfo(state) {
    dom.opponentBalance.textContent = `$${(state.opponent_stack / 100).toFixed(2)}`;
    dom.opponentBet.textContent     = `Apuesta $${(state.opponent_bet / 100).toFixed(2)}`;

    // Cartas del oponente — backs hasta el showdown
    dom.opponentCards.innerHTML = '';
    if (state.opponent_cards && state.opponent_cards.length > 0) {
      state.opponent_cards.forEach(c => {
        dom.opponentCards.appendChild(_buildCard(c));
      });
    } else {
      [0, 1].forEach(() => dom.opponentCards.appendChild(_buildBackCard()));
    }

    // Badge de dealer
    dom.opponentDealer.style.display =
      state.dealer_is_opponent ? 'flex' : 'none';
  }

  function _renderActions(state) {
    const isMyTurn = state.is_your_turn;
    const actions  = state.valid_actions || [];

    dom.actionsArea.style.opacity      = isMyTurn ? '1' : '0.4';
    dom.actionsArea.style.pointerEvents = isMyTurn ? 'auto' : 'none';

    // Mostrar u ocultar botones según acciones válidas
    dom.btnFold.style.display  = actions.includes('fold')  ? '' : 'none';
    dom.btnCall.style.display  = actions.includes('call')  ? '' : 'none';
    dom.btnRaise.style.display = actions.includes('raise') ? '' : 'none';

    // Texto dinámico en Call
    if (state.current_bet > 0) {
      const toCall = state.current_bet - state.your_bet;
      dom.btnCall.textContent = toCall > 0
        ? `Call $${(toCall / 100).toFixed(2)}`
        : 'Check';
    }

    // Actualizar límites del raise
    const minRaise = state.current_bet * 2;
    Raise.setLimits(minRaise, state.your_stack);
  }

  function _renderTimer(state) {
    if (state.is_your_turn) {
      dom.turnLabel.textContent = 'Tu turno';
      // Calcular segundos restantes desde turn_started_at
      const elapsed   = Math.floor(Date.now() / 1000) - state.turn_started_at;
      const remaining = Math.max(0, 30 - elapsed);
      Timer.start(remaining);
    } else {
      dom.turnLabel.textContent = 'Turno del oponente';
      Timer.stop();
      // Limpiar visualmente la barra
      document.getElementById('timer-fill').style.width = '0%';
      document.getElementById('timer-seconds').textContent = '—';
    }
  }

  // ── ACCIONES ─────────────────────────────────────────

  async function sendAction(action, amount = 0) {
    if (!currentState?.is_your_turn) return;

    _disableActions();
    Timer.stop();

    try {
      const result = await API.sendAction(gameId, action, amount);

      if (result.finished) {
        _handleGameEnd(result);
      } else {
        render(result.state_actor);
        _startPollingIfNeeded(result.state_actor);
      }
    } catch (e) {
      _enableActions();
      Timer.start(); // reanudar timer si falló
      _showToast(e instanceof APIError ? e.message : 'Error de red. Reintentando…');
    }
  }

  async function autoFold() {
    // Llamado por Timer cuando expira — el backend ya hizo fold,
    // solo actualizamos el estado local
    try {
      const state = await API.getState(gameId);
      render(state);
    } catch (_) {}
  }

  async function surrender() {
    try {
      const result = await API.abandonGame(gameId);
      if (result.ban_applied) {
        _showToast(
          `Suspendido por ${result.ban_applied} minutos.`,
          'warning'
        );
      }
      if (result.warning) {
        _showToast(result.warning, 'warning');
      }
      _handleGameEnd(result);
    } catch (e) {
      _showToast(e instanceof APIError ? e.message : 'Error al rendirse.');
    }
  }

  // ── POLLING ──────────────────────────────────────────

  function _startPollingIfNeeded(state) {
    _stopPolling();
    if (!state.is_your_turn && !state.is_finished) {
      pollingId = setInterval(_poll, POLL_INTERVAL);
    }
  }

  function _stopPolling() {
    if (pollingId) {
      clearInterval(pollingId);
      pollingId = null;
    }
  }

  async function _poll() {
    try {
      const state = await API.getState(gameId);
      render(state);

      if (state.is_your_turn || state.is_finished) {
        _stopPolling();
        if (state.is_finished) _handleGameEnd({ finished: true, outcome: state });
      }
    } catch (_) {
      // Ignorar errores de red en polling — reintentará solo
    }
  }

  // ── FIN DE PARTIDA ────────────────────────────────────

  function _handleGameEnd(result) {
    _stopPolling();
    Timer.stop();
    _disableActions();

    const outcome = result.outcome;
    if (!outcome) return;

    const won = outcome.winner_id === myUserId;
    const msg = won
      ? `🏆 ¡Ganaste! +$${(outcome.winner_profit / 100).toFixed(2)}`
      : `💀 Perdiste esta mano.`;

    // Mostrar resultado brevemente antes de cerrar
    _showToast(msg, won ? 'success' : 'error', 4000);

    setTimeout(() => {
      window.Telegram?.WebApp?.close();
    }, 4000);
  }

  // ── BUILDERS DE CARTAS ────────────────────────────────

  function _buildCard(card) {
    const el = document.createElement('div');
    el.className = `card ${card.color}`;
    el.innerHTML = `
      <div class="tl">${card.rank}<br>${card.symbol}</div>
      <div class="center">${card.symbol}</div>
      <div class="br">${card.rank}<br>${card.symbol}</div>
    `;
    return el;
  }

  function _buildBackCard() {
    const el = document.createElement('div');
    el.className = 'card back';
    return el;
  }

  // ── UI HELPERS ────────────────────────────────────────

  function _disableActions() {
    dom.actionsArea.style.pointerEvents = 'none';
    dom.actionsArea.style.opacity = '0.4';
  }

  function _enableActions() {
    if (currentState?.is_your_turn) {
      dom.actionsArea.style.pointerEvents = 'auto';
      dom.actionsArea.style.opacity = '1';
    }
  }

  function _showError(msg) {
    _showToast(msg, 'error', 0);  // 0 = no desaparece solo
  }

  function _showToast(msg, type = 'info', duration = 3000) {
    // Crear toast simple si no existe
    let toast = document.getElementById('game-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'game-toast';
      toast.style.cssText = `
        position: fixed; top: 60px; left: 50%; transform: translateX(-50%);
        background: rgba(0,0,0,0.85); color: #f5f0e8;
        padding: 10px 20px; border-radius: 12px;
        font-size: 13px; z-index: 999;
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255,255,255,0.12);
        max-width: 80vw; text-align: center;
        transition: opacity 0.3s;
      `;
      document.body.appendChild(toast);
    }

    const colors = {
      info:    'rgba(200,169,110,0.3)',
      success: 'rgba(60,140,100,0.3)',
      warning: 'rgba(200,150,50,0.3)',
      error:   'rgba(180,60,60,0.3)',
    };
    toast.style.background = colors[type] || colors.info;
    toast.style.opacity = '1';
    toast.textContent = msg;

    if (duration > 0) {
      setTimeout(() => { toast.style.opacity = '0'; }, duration);
    }
  }

  // ── URL PARSING ──────────────────────────────────────

  function _getGameIdFromUrl() {
    // Telegram pasa el startapp como ?startapp=ID o en initDataUnsafe
    const tg = window.Telegram?.WebApp;
    if (tg?.initDataUnsafe?.start_param) {
      return tg.initDataUnsafe.start_param;
    }
    const params = new URLSearchParams(window.location.search);
    return params.get('startapp') || params.get('game_id') || null;
  }

  // ── EVENTS (conectar botones al módulo) ───────────────

  function _wireEvents() {
    dom.btnFold.addEventListener('click', () => sendAction('fold'));
    dom.btnCall.addEventListener('click', () => {
      const action = currentState?.current_bet > currentState?.your_bet
        ? 'call' : 'check';
      sendAction(action);
    });
    dom.btnConfirm.addEventListener('click', () => {
      sendAction('raise', Raise.getValue());
    });
  }

  // ── API PÚBLICA ───────────────────────────────────────

  return {
    init,
    render,
    autoFold,
    surrender,
    sendAction,
  };

})();

// ── INTEGRACIÓN CON OTROS MÓDULOS ────────────────────

// Timer llama a Game cuando expira
// (reemplaza el TODO en timer.js)
const _origOnExpire = Timer.onExpire;
Object.defineProperty(Timer, 'onExpire', {
  get: () => Game.autoFold,
});

// Sheet llama a Game cuando se confirma rendirse
// (reemplaza el TODO en sheet.js)
const _origSurrender = Sheet.onSurrenderConfirm;
document.getElementById('btn-surrender-yes')
  .addEventListener('click', Game.surrender, { once: false });

// ── ARRANQUE ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  _wireEvents = Game._wireEvents; // exponer para el init
  Game.init();
});

// Wire events inmediatamente si el DOM ya cargó
if (document.readyState !== 'loading') {
  Game.init();
}
