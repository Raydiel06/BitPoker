/**
 * raise.js
 * Manages the raise panel: slider ↔ manual input sync,
 * validation, and toggle visibility.
 */

const Raise = (() => {
  const MIN = 80;   // minimum raise — will come from backend per game state
  const MAX = 760;  // player's current stack — will come from backend

  const panelEl  = document.getElementById('raise-panel');
  const toggleEl = document.getElementById('raise-toggle');
  const sliderEl = document.getElementById('raise-slider');
  const inputEl  = document.getElementById('raise-input');

  function clamp(v, min, max) {
    return Math.min(Math.max(v, min), max);
  }

  // Slider moved → update input
  function onSliderChange() {
    inputEl.value = clamp(parseInt(sliderEl.value) || MIN, MIN, MAX);
  }

  // User typing → update slider (loose, final clamp on blur)
  function onInputChange() {
    const n = parseInt(inputEl.value);
    if (!isNaN(n)) sliderEl.value = clamp(n, MIN, MAX);
  }

  // On blur or Enter → enforce valid range
  function onInputCommit() {
    const n = clamp(parseInt(inputEl.value) || MIN, MIN, MAX);
    inputEl.value = n;
    sliderEl.value = n;
  }

  function toggle() {
    panelEl.classList.toggle('open');
  }

  function getValue() {
    return parseInt(inputEl.value) || MIN;
  }

  // Update limits dynamically (called by game module after backend response)
  function setLimits(min, max) {
    sliderEl.min = min;
    sliderEl.max = max;
    inputEl.min  = min;
    inputEl.max  = max;
  }

  // Wire events
  sliderEl.addEventListener('input', onSliderChange);
  inputEl.addEventListener('input', onInputChange);
  inputEl.addEventListener('blur', onInputCommit);
  inputEl.addEventListener('keydown', e => { if (e.key === 'Enter') inputEl.blur(); });
  toggleEl.addEventListener('click', toggle);

  return { toggle, getValue, setLimits };
})();
