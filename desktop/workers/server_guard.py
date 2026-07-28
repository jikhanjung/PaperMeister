"""Resilience state machine for serialized, server-dependent batch queues.

Extracted from the references batch so biblio (and any future server-backed
queue) can share it. The QUEUE stays in the caller — this only decides *when* to
pause and polls for recovery. Wire it up by:

  * calling `record_ok()` when an item finishes in a way that proves the server
    responded (parsed, or nothing-to-do), and `record_fail()` when an item
    failed in a way that could mean the server is down;
  * gating the caller's drain with `if guard.paused(): return`;
  * calling `cancel()` when the batch is cancelled.

On the Nth consecutive failure it confirms with one blocking health ping (a
transient blip that still answers just resets the streak). If the server is
really down it invokes `on_pause(remaining)`, then polls off the UI thread every
`poll_ms`; when the server answers it invokes `on_resume(remaining)` then
`on_drain()` to continue.
"""
import logging
import time

from PyQt6.QtCore import QObject, QTimer

from desktop.workers.background import BackgroundTask

# Share the biblio logger: these decisions belong beside the extraction lines
# they interrupt, in the same daily file. Until this existed the guard only
# talked to the UI, so an overnight batch left no record of whether it had been
# paused — the morning log showed failures stopping and resuming with no reason
# given.
logger = logging.getLogger('biblio')


class ServerGuard(QObject):
    def __init__(self, *, health_check, on_pause, on_resume, on_drain,
                 remaining, parent=None, fail_stop=3, poll_ms=60_000):
        super().__init__(parent)
        self._health = health_check      # () -> bool  (blocking, short)
        self._on_pause = on_pause        # (remaining: int) -> None
        self._on_resume = on_resume      # (remaining: int) -> None
        self._on_drain = on_drain        # () -> None  (resume the queue)
        self._remaining = remaining      # () -> int
        self._fail_stop = fail_stop
        self._poll_ms = poll_ms
        self._streak = 0
        self._paused = False
        self._timer = None
        self._poll_task = None
        self._paused_at = 0.0

    def paused(self) -> bool:
        return self._paused

    def record_ok(self):
        """The server responded (item parsed, or no work needed)."""
        self._streak = 0

    def record_fail(self) -> bool:
        """An item failed in a way that could mean the server is down. Returns
        True if this crossed the threshold and paused the batch."""
        self._streak += 1
        if (self._paused or self._streak < self._fail_stop
                or self._remaining() == 0):
            return False
        if self._health():           # transient blip — server still answers
            logger.info('ServerGuard: %d consecutive failures but the server '
                        'still answers — treating as a blip, continuing',
                        self._fail_stop)
            self._streak = 0
            return False
        self._paused = True
        self._streak = 0
        self._paused_at = time.monotonic()
        logger.warning('ServerGuard: server is down after %d consecutive '
                       'failures — PAUSING with %d item(s) queued, polling '
                       'every %ds', self._fail_stop, self._remaining(),
                       self._poll_ms // 1000)
        self._on_pause(self._remaining())
        self._start_poll()
        return True

    def cancel(self):
        """The batch was cancelled — stop polling and clear paused state."""
        if self._paused:
            logger.info('ServerGuard: cancelled while paused (%s down)',
                        _duration(time.monotonic() - self._paused_at))
        self._stop_poll()
        self._paused = False
        self._streak = 0

    # ── recovery polling ─────────────────────────────────────────

    def _start_poll(self):
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(self._poll_ms)
            self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _stop_poll(self):
        if self._timer is not None:
            self._timer.stop()

    def _poll(self):
        if not self._paused:
            self._stop_poll()
            return
        if self._poll_task and self._poll_task.isRunning():
            return   # previous ping still in flight — wait for the next tick
        task = BackgroundTask(self._health)
        task.done.connect(self._on_poll_result)
        self._poll_task = task
        task.start()

    def _on_poll_result(self, alive):
        if not alive or not self._paused:
            return   # still down (or cancelled) — keep polling
        self._stop_poll()
        self._paused = False
        self._streak = 0
        logger.warning('ServerGuard: server recovered after %s — RESUMING '
                       '%d item(s)', _duration(time.monotonic() - self._paused_at),
                       self._remaining())
        self._on_resume(self._remaining())
        self._on_drain()


def _duration(seconds: float) -> str:
    """Human-readable outage length — the number you want when reading back a
    batch that ran unattended overnight."""
    seconds = int(seconds)
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m {seconds % 60}s'
    return f'{seconds // 3600}h {(seconds % 3600) // 60}m'
