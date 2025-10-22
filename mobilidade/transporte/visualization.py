"""Utilities for broadcasting real-time visualization events."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque
from typing import Deque, Dict, Iterable, Optional


class VisualizationEventHub:
    """Simple in-memory pub/sub hub for visualization events.

    The hub keeps the most recent run history so that new subscribers receive
    context immediately after connecting. All methods are thread-safe.
    """

    def __init__(self, history_size: int = 512, cooldown_seconds: float = 5.0) -> None:
        self._lock = threading.Lock()
        self._listeners: Dict[int, "queue.Queue[Optional[Dict[str, object]]]"] = {}
        self._history: Deque[Dict[str, object]] = deque(maxlen=history_size)
        self._active_run_id: Optional[str] = None
        self._cooldown_seconds = cooldown_seconds
        self._cooldown_until = 0.0
        self._cooldown_timer: Optional[threading.Timer] = None

    def subscribe(self) -> "queue.Queue[Optional[Dict[str, object]]]":
        """Register a new listener and replay the last known history."""

        listener: "queue.Queue[Optional[Dict[str, object]]]" = queue.Queue()
        with self._lock:
            for event in self._history:
                listener.put(event)
            if not self._history:
                listener.put({"event": "idle"})
            self._listeners[id(listener)] = listener
        return listener

    def unsubscribe(self, listener: "queue.Queue[Optional[Dict[str, object]]]") -> None:
        """Remove a listener from the hub."""

        with self._lock:
            self._listeners.pop(id(listener), None)
        listener.put(None)

    def _broadcast(self, event: Dict[str, object]) -> None:
        listeners: Iterable["queue.Queue[Optional[Dict[str, object]]]"]
        with self._lock:
            listeners = list(self._listeners.values())
        for listener in listeners:
            listener.put(event)

    def start_run(self, metadata: Dict[str, object]) -> Optional[str]:
        """Reset history and announce a new visualization run.

        Returns the identifier of the accepted run. If a run is already in
        progress or the hub is cooling down, ``None`` is returned and no
        broadcast happens.
        """

        run_id = str(metadata.get("runId") or uuid.uuid4())
        start_event = {"event": "run_start", "runId": run_id, **metadata}
        with self._lock:
            now = time.monotonic()
            if self._active_run_id is not None or now < self._cooldown_until:
                return None
            if self._cooldown_timer is not None:
                self._cooldown_timer.cancel()
                self._cooldown_timer = None
            self._active_run_id = run_id
            self._history.clear()
            self._history.append(start_event)
        self._broadcast(start_event)
        return run_id

    def publish(self, payload: Dict[str, object]) -> None:
        """Publish an event that belongs to the current run."""

        with self._lock:
            if not self._active_run_id:
                return
            event = {"runId": self._active_run_id, **payload}
            self._history.append(event)
        self._broadcast(event)

    def cache_hit(self, metadata: Dict[str, object]) -> None:
        """Notify listeners that a request was fulfilled from cache."""

        event = {"event": "cache_hit", **metadata}
        with self._lock:
            now = time.monotonic()
            if self._active_run_id is not None or now < self._cooldown_until:
                return
            if self._cooldown_timer is not None:
                self._cooldown_timer.cancel()
                self._cooldown_timer = None
            self._active_run_id = None
            self._history.clear()
            self._history.append(event)
            self._cooldown_until = now + self._cooldown_seconds
            self._schedule_idle_locked()
        self._broadcast(event)

    def end_run(self, status: str, extra: Optional[Dict[str, object]] = None) -> None:
        """Finalize the active run and broadcast its conclusion."""

        with self._lock:
            if not self._active_run_id:
                return
            run_id = self._active_run_id
        payload: Dict[str, object] = {"event": "run_end", "runId": run_id, "status": status}
        if extra:
            payload.update(extra)
        with self._lock:
            self._history.append(payload)
            self._active_run_id = None
            self._cooldown_until = time.monotonic() + self._cooldown_seconds
            self._schedule_idle_locked()
        self._broadcast(payload)

    def _schedule_idle_locked(self) -> None:
        if self._cooldown_timer is not None:
            self._cooldown_timer.cancel()
        delay = max(0.0, self._cooldown_until - time.monotonic())
        timer = threading.Timer(delay, self._emit_idle_if_ready)
        timer.daemon = True
        self._cooldown_timer = timer
        timer.start()

    def _emit_idle_if_ready(self) -> None:
        with self._lock:
            if self._active_run_id is not None or time.monotonic() < self._cooldown_until:
                return
            idle_event = {"event": "idle"}
            self._history.clear()
            self._history.append(idle_event)
            self._cooldown_timer = None
        self._broadcast(idle_event)


visualization_hub = VisualizationEventHub()

