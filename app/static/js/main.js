/* =========================================================
   Bosco delle Kjxii – Main JS
   Handles the turn countdown clock in the navbar.
   ========================================================= */

(function () {
  'use strict';

  const dateEl  = document.getElementById('turn-date');
  const timerEl = document.getElementById('turn-timer');

  if (!dateEl || !timerEl) return;  // not logged in

  let remaining = 0;

  function pad(n) { return String(n).padStart(2, '0'); }

  function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${pad(m)}:${pad(s)}`;
  }

  function tick() {
    if (remaining > 0) {
      remaining--;
      timerEl.textContent = formatTime(remaining);
    }
  }

  async function fetchState() {
    try {
      const res  = await fetch('/api/gamestate');
      if (!res.ok) return;
      const data = await res.json();
      dateEl.textContent  = data.date_string;
      remaining           = data.remaining_seconds;
      timerEl.textContent = formatTime(remaining);
    } catch (e) {
      // silent fail
    }
  }

  // Initial fetch, then poll every 30 s
  fetchState();
  setInterval(fetchState, 30_000);

  // Countdown every second
  setInterval(tick, 1_000);
})();
