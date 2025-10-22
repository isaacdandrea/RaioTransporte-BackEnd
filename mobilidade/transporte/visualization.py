"""Utilities for broadcasting real-time visualization events."""

from __future__ import annotations

import queue
import threading
import uuid
from collections import deque
from typing import Deque, Dict, Iterable, Optional


class VisualizationEventHub:
    """Simple in-memory pub/sub hub for visualization events.

    The hub keeps the most recent run history so that new subscribers receive
    context immediately after connecting. All methods are thread-safe.
    """

    def __init__(self, history_size: int = 512) -> None:
        self._lock = threading.Lock()
        self._listeners: Dict[int, "queue.Queue[Optional[Dict[str, object]]]"] = {}
        self._history: Deque[Dict[str, object]] = deque(maxlen=history_size)
        self._active_run_id: Optional[str] = None

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

    def start_run(self, metadata: Dict[str, object]) -> str:
        """Reset history and announce a new visualization run."""

        run_id = str(metadata.get("runId") or uuid.uuid4())
        start_event = {"event": "run_start", "runId": run_id, **metadata}
        with self._lock:
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
            self._active_run_id = None
            self._history.clear()
            self._history.append(event)
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
        self._broadcast(payload)


visualization_hub = VisualizationEventHub()

