"""Operator scheduler — wraps the controller for background or blocking execution."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional

from sre_loop.controller import OperatorController

logger = logging.getLogger(__name__)


class OperatorScheduler:
    """Manages the lifecycle of an OperatorController in a background thread.

    Usage::

        scheduler = OperatorScheduler(interval_secs=30)
        scheduler.start_background()        # non-blocking
        ...
        scheduler.stop()

        # Or blocking (e.g. from a CLI entrypoint):
        scheduler.start_blocking()
    """

    def __init__(
        self,
        interval_secs: int = 30,
        demo_mode: Optional[bool] = None,
        auto_remediate: bool = False,
        namespace_filter: str = "",
        on_cycle_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.controller = OperatorController(
            interval_secs=interval_secs,
            demo_mode=demo_mode,
            auto_remediate=auto_remediate,
            namespace_filter=namespace_filter,
        )
        self._thread: Optional[threading.Thread] = None
        self._on_cycle_complete = on_cycle_complete

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def start_background(self) -> None:
        """Start the operator loop in a daemon background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Scheduler is already running")
            return

        self._thread = threading.Thread(
            target=self._run_with_callback,
            name="sre-operator-loop",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "OperatorScheduler started in background thread (interval=%ds)",
            self.controller.interval_secs,
        )

    def start_blocking(self) -> None:
        """Start the operator loop in the calling thread (blocks until stop())."""
        logger.info("OperatorScheduler starting in blocking mode")
        self.controller.start()

    def stop(self) -> None:
        """Signal the controller to stop after the current cycle."""
        self.controller.stop()
        if self._thread:
            self._thread.join(timeout=self.controller.interval_secs + 5)
            if self._thread.is_alive():
                logger.warning("Background thread did not stop within timeout")
        logger.info("OperatorScheduler stopped")

    def is_running(self) -> bool:
        """Return True if the background thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def get_status(self) -> Dict[str, Any]:
        """Return scheduler + controller status."""
        status = self.controller.get_status()
        status["thread_alive"] = self.is_running()
        return status

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_with_callback(self) -> None:
        """Run the controller loop; invoke the on_cycle_complete callback after each cycle."""
        if self._on_cycle_complete is None:
            self.controller.start()
            return

        # Wrap the controller to inject a callback after each cycle
        original_run_once = self.controller.run_once

        def _patched_run_once():
            result = original_run_once()
            try:
                self._on_cycle_complete(result.to_dict())
            except Exception as exc:
                logger.warning("on_cycle_complete callback raised: %s", exc)
            return result

        self.controller.run_once = _patched_run_once
        self.controller.start()
