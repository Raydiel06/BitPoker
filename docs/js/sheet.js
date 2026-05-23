/**
 * sheet.js
 * Manages the bottom sheet: open/close, tab switching,
 * surrender confirmation flow.
 */

const Sheet = (() => {
  const overlayEl = document.getElementById('sheet-overlay');
  const sheetEl   = document.getElementById('bottom-sheet');
  const closeBtn  = document.getElementById('sheet-close');
  const tabs      = document.querySelectorAll('.sheet-tab');
  const panels    = document.querySelectorAll('.tab-panel');

  // ── Open / Close ──────────────────────────────────────
  function open() {
    overlayEl.classList.add('open');
    sheetEl.classList.add('open');
  }

  function close() {
    sheetEl.classList.remove('open');
    overlayEl.classList.remove('open');
  }

  // ── Tab switching ──────────────────────────────────────
  function switchTab(targetId) {
    tabs.forEach(t => t.classList.remove('active'));
    panels.forEach(p => p.classList.remove('active'));

    const activeTab = document.querySelector(`.sheet-tab[data-tab="${targetId}"]`);
    const activePanel = document.getElementById('tab-' + targetId);
    if (activeTab)  activeTab.classList.add('active');
    if (activePanel) activePanel.classList.add('active');
  }

  // ── Surrender ──────────────────────────────────────────
  function onSurrenderConfirm() {
    close();
    // TODO: Game.surrender() — will send action to backend
    console.log('[Sheet] Surrender confirmed — pending backend integration');
  }

  // ── Events ────────────────────────────────────────────
  document.getElementById('menu-btn').addEventListener('click', open);
  closeBtn.addEventListener('click', close);
  overlayEl.addEventListener('click', close);

  tabs.forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  document.getElementById('btn-surrender-yes').addEventListener('click', onSurrenderConfirm);
  document.getElementById('btn-surrender-no').addEventListener('click', close);

  return { open, close, switchTab };
})();
