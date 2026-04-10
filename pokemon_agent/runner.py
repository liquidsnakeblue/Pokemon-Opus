"""
EmulatorRunner — drives the emulator on a dedicated thread at real-time 60 FPS.

Problem this solves
-------------------
The original pokemon-agent server only ticked PyBoy inside `/action` handlers,
so the Game Boy was frozen whenever the agent was thinking. From a viewer's
perspective the game looked chunky: text scrolls stalled mid-letter for
seconds, then snapped forward when the next action burst executed.

Fix
---
Own the PyBoy instance from a single background thread and tick it at a
steady 60 FPS regardless of whether the agent is sending actions. External
code (FastAPI handlers) submits work to the runner and blocks until it
completes. All PyBoy access is serialized through this thread, so there
are no concurrent-memory races.

Contract
--------
- `start()` spins up the thread; `stop()` joins it.
- `with_emu(fn)` runs `fn(emu)` on the runner thread under its lock.
  Use this for memory reads, screenshots, save/load — anything that
  needs atomic access to the emulator but does not want to advance time.
- `press_button(btn, hold, wait)` schedules a frame-accurate button press
  into the tick loop. Blocks until the press+wait window completes, so
  real-time pacing comes for free — a 20-frame press takes 333 ms wallclock.
- `tick(frames)` blocks the caller until the runner has advanced that
  many frames of real-time emulator time.
- `get_frame_bytes()` returns the most recently captured PNG bytes.
  No lock is held, no encoding is done on the caller's thread — it just
  reads the cached buffer.

Safety
------
- The runner holds its lock ONLY during the work portion of each frame
  (apply inputs + tick + capture). It releases the lock before the
  wallclock sleep, so external callers can grab the lock in the gap
  between frames without stalling the tick loop.
- External submissions always schedule their inputs one frame in the
  future, so there's no race with the current iteration.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple, TypeVar

from PIL import Image

from .emulator import Emulator, PyBoyEmulator

logger = logging.getLogger(__name__)

T = TypeVar("T")


class EmulatorRunner:
    """Runs an Emulator in a dedicated thread at real-time 60 FPS."""

    def __init__(
        self,
        emulator: Emulator,
        target_fps: int = 60,
        capture_every_n_frames: int = 2,
        png_compress_level: int = 1,
    ) -> None:
        self.emu = emulator
        self.target_fps = target_fps
        self.frame_dt = 1.0 / target_fps
        self.capture_every = capture_every_n_frames
        self.png_compress_level = png_compress_level

        # Protects: the emulator object, _frame, _scheduled_inputs, _deadlines
        self._lock = threading.Lock()

        # Monotonic frame counter. Incremented after every emulator tick.
        self._frame: int = 0

        # Input schedule: frame_number -> list of (op, button) where op is
        # 'press' or 'release'. Applied before ticking that frame.
        self._scheduled_inputs: Dict[int, List[Tuple[str, str]]] = defaultdict(list)

        # Frame-number -> list of threading.Events to set after ticking
        # that frame. Used by callers blocking on `press_button` / `tick`.
        self._deadlines: Dict[int, List[threading.Event]] = defaultdict(list)

        # Cached latest frame PNG bytes. Written by the runner thread under
        # _frame_bytes_lock, read by external threads for /screenshot.
        self._frame_bytes: Optional[bytes] = None
        self._frame_bytes_lock = threading.Lock()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="EmulatorRunner",
        )
        self._thread.start()
        logger.info(f"EmulatorRunner started at {self.target_fps} FPS")

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("EmulatorRunner stopped")

    # ── Public operations ────────────────────────────────────────────

    def with_emu(self, fn: Callable[[Emulator], T], timeout: float = 5.0) -> T:
        """Run `fn(emu)` under the runner's lock.

        The runner releases the lock during wallclock sleeps (most of each
        frame period), so this rarely waits more than ~1 ms. The function
        should not tick the emulator itself — use `tick()` instead.
        """
        acquired = self._lock.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError(f"EmulatorRunner.with_emu: lock timeout after {timeout}s")
        try:
            return fn(self.emu)
        finally:
            self._lock.release()

    def press_button(
        self,
        button: str,
        hold_frames: int = 8,
        wait_frames: int = 12,
        timeout: float = 10.0,
    ) -> None:
        """Press a button, hold it for `hold_frames`, then wait `wait_frames`.

        Blocks until (hold + wait) frames have been emulated in real time.
        This matches Pokemon Red's expected input timing and stays at
        real-time 60 FPS pacing.
        """
        done = threading.Event()

        with self._lock:
            # Schedule inputs one frame in the future so we don't race the
            # loop's own frame-processing step for the current iteration.
            press_frame = self._frame + 1
            release_frame = press_frame + hold_frames
            done_frame = release_frame + wait_frames
            self._scheduled_inputs[press_frame].append(("press", button))
            self._scheduled_inputs[release_frame].append(("release", button))
            self._deadlines[done_frame].append(done)

        if not done.wait(timeout=timeout):
            raise TimeoutError(
                f"press_button({button!r}, hold={hold_frames}, wait={wait_frames}) "
                f"timed out after {timeout}s"
            )

    def tick(self, frames: int = 1, timeout: Optional[float] = None) -> None:
        """Block the caller until the runner has emulated `frames` more frames.

        Real-time: `frames=60` takes ~1 second wallclock.
        """
        if frames <= 0:
            return
        done = threading.Event()
        with self._lock:
            target = self._frame + frames
            self._deadlines[target].append(done)
        effective_timeout = timeout if timeout is not None else max(2.0, frames * self.frame_dt * 2)
        if not done.wait(timeout=effective_timeout):
            raise TimeoutError(f"tick({frames}) timed out")

    def get_frame_bytes(self) -> Optional[bytes]:
        """Return the most recently captured frame as PNG bytes, or None."""
        with self._frame_bytes_lock:
            return self._frame_bytes

    def get_frame_number(self) -> int:
        with self._lock:
            return self._frame

    # ── Runner thread ────────────────────────────────────────────────

    def _run(self) -> None:
        # Capture an initial frame immediately so /screenshot never 404s
        self._capture_frame()

        next_tick_time = time.monotonic()

        while not self._stop_event.is_set():
            # === Work portion of the frame (lock held) ===
            with self._lock:
                current_frame = self._frame

                # Apply any inputs scheduled for this frame
                pending_inputs = self._scheduled_inputs.pop(current_frame, None)
                if pending_inputs:
                    for op, btn in pending_inputs:
                        try:
                            if op == "press":
                                self.emu._pyboy.button_press(btn)  # type: ignore[union-attr]
                            else:
                                self.emu._pyboy.button_release(btn)  # type: ignore[union-attr]
                        except Exception as e:
                            logger.warning(f"input {op} {btn} failed: {e}")

                # Advance the emulator by exactly one frame
                try:
                    self.emu.tick(1)
                except Exception as e:
                    logger.error(f"emulator tick failed: {e}")

                self._frame += 1

                # Signal any deadlines that have now been reached
                ready = self._deadlines.pop(self._frame, None)

                # Capture a frame every N iterations (default N=2 → 30 FPS capture)
                should_capture = (self._frame % self.capture_every) == 0

            # Signal waiters OUTSIDE the lock to avoid holding it while they wake
            if ready:
                for evt in ready:
                    evt.set()

            # Capture OUTSIDE the lock — but we need to take it briefly
            # inside _capture_frame() because PIL needs to read the screen.
            if should_capture:
                self._capture_frame()

            # === Real-time pacing (lock NOT held) ===
            next_tick_time += self.frame_dt
            sleep = next_tick_time - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            else:
                # Fell behind schedule — reset target to now so we don't
                # burn CPU trying to catch up in a tight loop.
                next_tick_time = time.monotonic()

    # ── Frame capture ────────────────────────────────────────────────

    def _capture_frame(self) -> None:
        """Snapshot the current screen into the cached PNG buffer.

        Briefly acquires the emulator lock to read the PIL Image. PNG
        encoding happens outside the lock.
        """
        try:
            acquired = self._lock.acquire(timeout=0.1)
            if not acquired:
                return
            try:
                img = self.emu.get_screen()
                # PyBoy returns a PIL Image directly; copy it so we can
                # release the lock before encoding.
                if isinstance(img, Image.Image):
                    img_copy = img.copy()
                else:
                    import numpy as np  # noqa: F401 — type check only
                    img_copy = Image.fromarray(img)
            finally:
                self._lock.release()

            buf = io.BytesIO()
            img_copy.save(buf, format="PNG", compress_level=self.png_compress_level)
            data = buf.getvalue()

            with self._frame_bytes_lock:
                self._frame_bytes = data
        except Exception as e:
            logger.debug(f"frame capture failed: {e}")
