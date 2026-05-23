/**
 * timer.js
 * Manages the countdown timer for each player's turn.
 * Decoupled from UI: receives DOM element IDs, drives visual states.
 */

const Timer = (() => {
  const TOTAL = 30; // seconds — adjust when backend sends dynamic value
  let remaining = TOTAL;
  let intervalId = null;

  // DOM refs
  const fillEl    = document.getElementById('timer-fill');
  const secondsEl = document.getElementById('timer-seconds');
  const dotEl     = document.getElementById('turn-dot');

  function applyState(r) {
    const pct = (r / TOTAL) * 100;
    fillEl.style.width      = pct + '%';
    secondsEl.textContent   = r + 's';

    let color;
    if (r > 15) {
      color = 'var(--timer-safe)';
      dotEl.style.animation = 'pulse 1.4s ease-in-out infinite';
    } else if (r > 5) {
      color = 'var(--timer-warn)';
      dotEl.style.animation = 'pulse 0.8s ease-in-out infinite';
    } else {
      color = 'var(--timer-danger)';
      dotEl.style.animation = 'dangerPulse 0.4s ease-in-out infinite';
    }

    fillEl.style.background   = color;
    secondsEl.style.color     = color;
    dotEl.style.background    = color;
  }

  function start(seconds = TOTAL) {
    stop(); // clear any existing interval first
    remaining = seconds;
    applyState(remaining);

    intervalId = setInterval(() => {
      remaining--;
      applyState(remaining);

      if (remaining <= 0) {
        stop();
        secondsEl.textContent = '0s';
        fillEl.style.width    = '0%';
        onExpire();
      }
    }, 1000);
  }

  function stop() {
    if (intervalId) {
      clearInterval(intervalId);
      intervalId = null;
    }
  }

  function reset(seconds = TOTAL) {
    start(seconds);
  }

  // Called when time runs out.
  // In production this will trigger a fold action via the game module.
  function onExpire() {
    console.log('[Timer] Turn expired — auto fold pending backend integration');
    // TODO: Game.autoFold();
  }

  return { start, stop, reset };
})();

// Auto-start on load
Timer.start();
