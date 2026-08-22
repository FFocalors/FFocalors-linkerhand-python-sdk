"""One-owner worker for all device calls."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class _Job:
    fn: Callable[[], Any]
    event: threading.Event
    result: Any = None
    error: BaseException | None = None


class CommandWorker:
    def __init__(self, name: str = "linkerhand-sdk-worker"):
        self._queue: queue.Queue[_Job | None] = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None: return
            try:
                job.result = job.fn()
            except BaseException as exc:  # deliver SDK failures to caller, never kill worker
                job.error = exc
            finally:
                job.event.set()

    def submit(self, fn: Callable[[], Any], timeout: float | None = None) -> Any:
        with self._lock:
            if self._closed: raise RuntimeError("worker is closed")
            job = _Job(fn=fn, event=threading.Event())
            self._queue.put(job)
        if not job.event.wait(timeout):
            raise TimeoutError("SDK command timed out")
        if job.error is not None: raise job.error
        return job.result

    def shutdown(self, timeout: float = 2.0) -> None:
        with self._lock:
            if self._closed: return
            self._closed = True
            self._queue.put(None)
        self._thread.join(timeout)
