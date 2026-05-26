/**
 * js/game.js
 * Cerebro del frontend. Maneja estados:
 * - waiting: partida creada, esperando oponente
 * - active:  partida en curso
 * - finished: partida terminada
 */

const Game = (() => {

  // ── ESTADO ───────────────────────────────────────────
  let gameId       = null;
  let myUserId     = null;
  let myName       = null;
  let currentState = null;
  let pollingId    = null;
  let gameStatus   = 'waiting'; // 'waiting' | 'active' | 'finished'

  const POLL_WAITING  = 3000;  // polling mientras espera oponente
  const POLL_OPPONENT = 2000;  // polling mientras es turno del oponente

  // ── REFS DOM ─────────────────────────────────────────
  const $ = id => document.getElementById(id);

  const dom = {
    // Pantallas
    waitingScreen:    $('waiting-screen'),
    gameScreen:       $('game-screen'),
    waitingInviteUrl: $('waiting-invite-url'),
    btnCopyInvite:    $('btn-copy-invite'),

    // Oponente
    opponentCards:   $('opponent-cards'),
    opponentAvatar:  $('opponent-avatar'),
    opponentName:    $('opponent-name'),
    opponentBalance: $('opponent-balance'),
    opponentBet:     $('opponent-bet'),
    opponentDealer:  $('opponent-dealer'),

    // Mesa
    communityCards:  $('community-cards'),
    potAmount:       $('pot-amount'),

    // Yo
    myAvatar:        $('my-avatar'),
    myName:          $('my-name'),
    myBalance:       $('my-balance'),
    myBet:           $('my-bet'),
    myCards:         $('my-cards'),

    // Acciones
    actionBtns:      $('action-btns'),
    btnFold:         $('btn-fold'),
    btnCall:         $('btn-call'),
    btnConfirm:      $('btn-confirm'),

    // Timer
    turnLabelText:   $('turn-label-text'),
    turnDot:         $('turn-dot'),
  };

  // ── INIT ─────────────────────────────────────────────

  async function init() {
    const tg = window.Telegram?.WebApp;
    if (tg) { tg.ready(); tg.expand(); }

    gameId = _getGameIdFromUrl();
    if (!gameId) {
      _showError('Link de partida inválido.');
      return;
    }

    // Obtener perfil del usuario
    try {
      const me = await API.getMe();
      myUserId = me.id;
      myName   = me.display_name || me.username || 'Tú';
      dom.myName.textContent   = myName;
      dom.myAvatar.textContent = '😎';
    } catch (e) {
      _showError('No se pudo autenticar. Abre el juego desde Telegram.');
      return;
    }

    await _joinOrReconnect();
  }

  async function _joinOrReconnect() {
    try {
      // Intentar obtener estado (reconexión o segundo jugador)
      const state = await API.getState(gameId);

      if (state.status === 'waiting' || !state.is_active) {
        // Partida existe pero aún no empezó — mostrar espera
        _showWaiting();
        return;
      }

      // Partida activa — mostrar mesa
      _showGame();
      render(state);
      _startPollingIfNeeded(state);

    } catch (e) {
      if (e instanceof APIError && e.status === 404) {
        // Primer intento del segundo jugador — unirse
        await _tryJoin();
      } else if (e instanceof APIError && e.status === 200) {
        // La partida está en waiting
        _showWaiting();
      } else {
        _showError('Error al conectar. Intenta cerrar y abrir de nuevo.');
      }
    }
  }

  async function _tryJoin() {
    try {
      const result = await API.joinGame(gameId);

      // El segundo jugador recibe el estado directamente
      const state = result.state_joiner || result.state_creator;
      if (state) {
        _showGame();
        render(state);
        _startPollingIfNeeded(state);
      } else {
        _showWaiting();
      }
    } catch (e) {
      if (e instanceof APIError) {
        if (e.message.includes('esperando') || e.status === 409) {
          _showWaiting();
        } else {
          _showError(e.message);
        }
      } else {
        _showError('Error de conexión.');
      }
    }
  }

  // ── PANTALLAS ─────────────────────────────────────────

    function _showWaiting() {
    gameStatus = 'waiting';

    // Construir invite link — usar t.me si viene de Telegram,
    // si no usar la URL actual como fallback
    const tg = window.Telegram?.WebApp;
    let inviteUrl;

    if (tg?.initDataUnsafe?.start_param) {
      // Viene de Telegram Mini App — construir link t.me
      // El bot username se puede hardcodear o leer del initData
      const botUsername = 'neonfuturescasino_bot'; // tu bot
      inviteUrl = `https://t.me/${botUsername}/poker?startapp=${gameId}`;
    } else {
      // Fallback para pruebas fuera de Telegram
      const url = new URL(window.location.href);
      url.searchParams.set('startapp', gameId);
      inviteUrl = url.toString();
    }

    dom.waitingInviteUrl.textContent = inviteUrl;
    dom.waitingScreen.classList.remove('hidden');
    dom.gameScreen.classList.remove('visible');

    dom.btnCopyInvite.onclick = () => {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(inviteUrl).then(() => {
          dom.btnCopyInvite.textContent = '✅ Copiado';
          setTimeout(() => {
            dom.btnCopyInvite.textContent = '📋 Copiar link';
          }, 2000);
        });
      } else {
        // Fallback para navegadores sin clipboard API
        const el = document.createElement('textarea');
        el.value = inviteUrl;
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        dom.btnCopyInvite.textContent = '✅ Copiado';
        setTimeout(() => {
          dom.btnCopyInvite.textContent = '📋 Copiar link';
        }, 2000);
      }
    };

    // Polling esperando oponente
    _stopPolling();
    pollingId = setInterval(_pollWaiting, POLL_WAITING);
  }


  function _showGame() {
    gameStatus = 'active';
    dom.waitingScreen.classList.add('hidden');
    dom.gameScreen.classList.add('visible');
  }

  // ── POLLING DE ESPERA ─────────────────────────────────

  async function _pollWaiting() {
    try {
      const state = await API.getState(gameId);
      // Si el estado ya tiene cartas, la partida comenzó
      if (state.your_cards && state.your_cards.length > 0) {
        _stopPolling();
        _showGame();
        render(state);
        _startPollingIfNeeded(state);
      }
    } catch (_) {}
  }

  // ── RENDER ───────────────────────────────────────────

  function render(state) {
    if (!state) return;
    currentState = state;

    _renderCommunityCards(state.community_cards || []);
    _renderPot(state.pot || 0);
    _renderMyInfo(state);
    _renderOpponentInfo(state);
    _renderActions(state);
    _renderTimer(state);
  }

  function _renderCommunityCards(cards) {
    dom.communityCards.innerHTML = '';
    for (let i = 0; i < 5; i++) {
      dom.communityCards.appendChild(
        cards[i] ? _buildCard(cards[i]) : _buildBackCard()
      );
    }
  }

  function _renderPot(pot) {
    dom.potAmount.textContent = `$${(pot / 100).toFixed(2)}`;
  }

  function _renderMyInfo(state) {
    dom.myBalance.textContent = `$${((state.your_stack || 0) / 100).toFixed(2)}`;
    dom.myBet.textContent     = `Apuesta $${((state.your_bet || 0) / 100).toFixed(2)}`;

    dom.myCards.innerHTML = '';
    (state.your_cards || []).forEach(c => {
      dom.myCards.appendChild(_buildCard(c));
    });
  }

  function _renderOpponentInfo(state) {
    dom.opponentBalance.textContent =
      `$${((state.opponent_stack || 0) / 100).toFixed(2)}`;
    dom.opponentBet.textContent =
      `Apuesta $${((state.opponent_bet || 0) / 100).toFixed(2)}`;

    dom.opponentCards.innerHTML = '';
    const revealCards = state.opponent_cards && state.opponent_cards.length > 0;
    if (revealCards) {
      state.opponent_cards.forEach(c =>
        dom.opponentCards.appendChild(_buildCard(c))
      );
    } else {
      [0,1].forEach(() => dom.opponentCards.appendChild(_buildBackCard()));
    }

    dom.opponentDealer.style.display =
      state.dealer_is_opponent ? 'flex' : 'none';
  }

  function _renderActions(state) {
    const isMyTurn = state.is_your_turn;
    const actions  = state.valid_actions || [];

    dom.actionBtns.style.opacity      = isMyTurn ? '1' : '0.4';
    dom.actionBtns.style.pointerEvents = isMyTurn ? 'auto' : 'none';

    dom.btnFold.style.display  =
      actions.includes('fold')  ? '' : 'none';
    dom.btnCall.style.display  =
      (actions.includes('call') || actions.includes('check')) ? '' : 'none';
    document.getElementById('raise-toggle').style.display =
      actions.includes('raise') ? '' : 'none';

    // Texto dinámico call/check
    if (actions.includes('check')) {
      dom.btnCall.textContent = 'Check';
    } else {
      const toCall = (state.current_bet || 0) - (state.your_bet || 0);
      dom.btnCall.textContent = toCall > 0
        ? `Call $${(toCall / 100).toFixed(2)}`
        : 'Check';
    }

    // Límites del raise
    const minRaise = (state.current_bet || 0) * 2;
    Raise.setLimits(minRaise, state.your_stack || 0);
  }

  function _renderTimer(state) {
    if (state.is_your_turn) {
      dom.turnLabelText.textContent = 'Tu turno';
      const elapsed    = Math.floor(Date.now() / 1000) - (state.turn_started_at || 0);
      const remaining  = Math.max(0, 30 - elapsed);
      Timer.start(remaining);
    } else {
      dom.turnLabelText.textContent = 'Turno del oponente';
      Timer.stop();
      document.getElementById('timer-fill').style.width    = '0%';
      document.getElementById('timer-seconds').textContent = '—';
      dom.turnDot.style.background = 'var(--text-muted)';
      dom.turnDot.style.animation  = 'none';
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
      Timer.start();
      _showToast(
        e instanceof APIError ? e.message : 'Error de red. Reintentando…',
        'error'
      );
    }
  }

  async function autoFold() {
    try {
      const state = await API.getState(gameId);
      if (state.is_finished) {
        _handleGameEnd({ finished: true, outcome: state });
      } else {
        render(state);
      }
    } catch (_) {}
  }

  async function surrender() {
    try {
      const result = await API.abandonGame(gameId);
      if (result.warning) _showToast(result.warning, 'warning', 4000);
      if (result.ban_applied) {
        _showToast(`⛔ Suspendido por ${result.ban_applied} minutos.`, 'error', 5000);
      }
      _handleGameEnd(result);
    } catch (e) {
      _showToast(e instanceof APIError ? e.message : 'Error al rendirse.', 'error');
    }
  }

  // ── POLLING ──────────────────────────────────────────

  function _startPollingIfNeeded(state) {
    _stopPolling();
    if (!state.is_your_turn && !state.is_finished) {
      pollingId = setInterval(_pollGame, POLL_OPPONENT);
    }
  }

  function _stopPolling() {
    if (pollingId) { clearInterval(pollingId); pollingId = null; }
  }

  async function _pollGame() {
    try {
      const state = await API.getState(gameId);
      render(state);
      if (state.is_your_turn || state.is_finished) {
        _stopPolling();
        if (state.is_finished) _handleGameEnd({ finished: true, outcome: state });
      }
    } catch (_) {}
  }

  // ── FIN DE PARTIDA ────────────────────────────────────

  function _handleGameEnd(result) {
    _stopPolling();
    Timer.stop();
    _disableActions();
    gameStatus = 'finished';

    const outcome = result.outcome;
    if (!outcome) return;

    const won = outcome.winner_id === myUserId;
    const profit = ((outcome.winner_profit || 0) / 100).toFixed(2);

    _showToast(
      won ? `🏆 ¡Ganaste! +$${profit}` : `💀 Perdiste esta mano.`,
      won ? 'success' : 'error',
      4000,
    );

    setTimeout(() => window.Telegram?.WebApp?.close(), 4500);
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
    dom.actionBtns.style.pointerEvents = 'none';
    dom.actionBtns.style.opacity = '0.4';
  }

  function _enableActions() {
    if (currentState?.is_your_turn) {
      dom.actionBtns.style.pointerEvents = 'auto';
      dom.actionBtns.style.opacity = '1';
    }
  }

  function _showError(msg) {
    // Mostrar en pantalla de espera si la mesa no está visible
    if (gameStatus !== 'active') {
      const desc = document.querySelector('.waiting-desc');
      if (desc) desc.textContent = msg;
      const icon = document.querySelector('.waiting-icon');
      if (icon) icon.textContent = '⚠️';
      const dots = document.querySelector('.waiting-dots');
      if (dots) dots.style.display = 'none';
    }
    _showToast(msg, 'error', 0);
  }

  function _showToast(msg, type = 'info', duration = 3000) {
    let toast = document.getElementById('game-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'game-toast';
      toast.style.cssText = `
        position:fixed; top:60px; left:50%; transform:translateX(-50%);
        padding:10px 20px; border-radius:12px;
        font-size:13px; z-index:999;
        backdrop-filter:blur(12px);
        border:1px solid rgba(255,255,255,0.12);
        max-width:80vw; text-align:center;
        transition:opacity 0.3s;
        font-family:'DM Sans',sans-serif;
        color:#f5f0e8;
      `;
      document.body.appendChild(toast);
    }
    const colors = {
      info:    'rgba(200,169,110,0.85)',
      success: 'rgba(60,140,100,0.85)',
      warning: 'rgba(200,150,50,0.85)',
      error:   'rgba(180,60,60,0.85)',
    };
    toast.style.background = colors[type] || colors.info;
    toast.style.opacity = '1';
    toast.textContent = msg;
    if (duration > 0) {
      setTimeout(() => { toast.style.opacity = '0'; }, duration);
    }
  }

  function _getGameIdFromUrl() {
    const tg = window.Telegram?.WebApp;
    if (tg?.initDataUnsafe?.start_param) return tg.initDataUnsafe.start_param;
    const params = new URLSearchParams(window.location.search);
    return params.get('startapp') || params.get('game_id') || null;
  }

  // ── WIRE EVENTS ──────────────────────────────────────

  function _wireEvents() {
    dom.btnFold.addEventListener('click', () => sendAction('fold'));
    dom.btnCall.addEventListener('click', () => {
      const action = currentState?.valid_actions?.includes('check')
        ? 'check' : 'call';
      sendAction(action);
    });
    dom.btnConfirm.addEventListener('click', () => {
      sendAction('raise', Raise.getValue());
    });
    $('btn-surrender-yes').addEventListener('click', () => {
      Sheet.close();
      surrender();
    });
  }

  // ── API PÚBLICA ───────────────────────────────────────

  return { init, render, autoFold, surrender, sendAction };

})();

// ── ARRANQUE ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Wire events después de que el DOM esté listo
  document.getElementById('btn-fold')
    ?.addEventListener('click', () => Game.sendAction('fold'));
  document.getElementById('btn-call')
    ?.addEventListener('click', () => {
      const action = window._currentState?.valid_actions?.includes('check')
        ? 'check' : 'call';
      Game.sendAction(action);
    });
  document.getElementById('btn-confirm')
    ?.addEventListener('click', () => {
      Game.sendAction('raise', Raise.getValue());
    });
  document.getElementById('btn-surrender-yes')
    ?.addEventListener('click', () => {
      Sheet.close();
      Game.surrender();
    });

  Game.init();
});
                                        
