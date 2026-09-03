"""In-process coordination for idempotent translation requests."""

import threading
import time
from collections import OrderedDict


class TranslationCoordinator:
    def __init__(self, max_keys: int = 10_000, cache_seconds: int = 300) -> None:
        self.max_keys = max_keys
        self.cache_seconds = cache_seconds
        self.lock = threading.Lock()
        self.events: OrderedDict[tuple[int, str], threading.Event] = OrderedDict()
        self.outcomes: OrderedDict[tuple[int, str], tuple[float, object]] = OrderedDict()

    def _cached_outcome(self, key: tuple[int, str]):
        with self.lock:
            cached = self.outcomes.get(key)
            if cached is None:
                return None
            stored_at, outcome = cached
            if time.monotonic() - stored_at > self.cache_seconds:
                self.outcomes.pop(key, None)
                return None
            self.outcomes.move_to_end(key)
            return outcome

    def _store_outcome(self, key: tuple[int, str], outcome: object) -> None:
        with self.lock:
            self.outcomes[key] = (time.monotonic(), outcome)
            if len(self.outcomes) > self.max_keys:
                self.outcomes.popitem(last=False)

    def execute(self, device_id: int, request_id: str, callback, timeout_seconds: float = 10.0):
        key = (device_id, request_id)
        cached = self._cached_outcome(key)
        if cached is not None:
            return cached

        with self.lock:
            event = self.events.get(key)
            if event is None:
                event = threading.Event()
                self.events[key] = event
                if len(self.events) > self.max_keys:
                    self.events.popitem(last=False)
                owner = True
            else:
                owner = False

        if not owner:
            completed = event.wait(timeout=timeout_seconds)
            if not completed:
                return "ai_unavailable"
            return self._cached_outcome(key)

        try:
            outcome = callback()
            if isinstance(outcome, Exception):
                result = "ai_unavailable"
            else:
                result = outcome
        except Exception:
            result = "ai_unavailable"
        finally:
            self._store_outcome(key, result)
            event.set()
            with self.lock:
                self.events.pop(key, None)
        return result

    def clear(self) -> None:
        with self.lock:
            self.events.clear()
            self.outcomes.clear()
