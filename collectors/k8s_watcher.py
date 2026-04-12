"""Kubernetes watch loop — continuously polls cluster state and feeds detectors."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from providers.kubernetes import get_k8s_client

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECS = int(os.getenv("WATCH_INTERVAL_SECS", "30"))


class K8sWatcher:
    """Periodically polls the Kubernetes API and invokes registered detector callbacks."""

    def __init__(
        self,
        interval_secs: int = WATCH_INTERVAL_SECS,
    ) -> None:
        """Initialise the watcher.

        Args:
            interval_secs: How often to poll the cluster (seconds).
        """
        self._interval = interval_secs
        self._client = get_k8s_client()
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_state: Optional[Dict[str, Any]] = None
        logger.info("K8sWatcher: interval=%ds", interval_secs)

    def register_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback to be called with the cluster state on each poll.

        Args:
            callback: Function that accepts a cluster_state dict.
        """
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start the background watch loop in a daemon thread."""
        if self._running:
            logger.warning("K8sWatcher already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info("K8sWatcher started")

    def stop(self) -> None:
        """Stop the background watch loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("K8sWatcher stopped")

    def poll_once(self) -> Dict[str, Any]:
        """Poll the cluster state once and invoke all callbacks.

        Returns:
            The current cluster state dict.
        """
        try:
            state = self._client.get_cluster_state()
            self._last_state = state
            for cb in self._callbacks:
                try:
                    cb(state)
                except Exception as exc:
                    logger.error("Watcher callback error: %s", exc)
            return state
        except Exception as exc:
            logger.error("K8sWatcher poll failed: %s", exc)
            return {}

    def get_last_state(self) -> Optional[Dict[str, Any]]:
        """Return the most recently polled cluster state.

        Returns:
            Last cluster state dict, or None if no poll has occurred.
        """
        return self._last_state

    def _watch_loop(self) -> None:
        """Internal background loop."""
        logger.info("K8sWatcher watch loop started")
        while self._running:
            self.poll_once()
            time.sleep(self._interval)
        logger.info("K8sWatcher watch loop exited")
