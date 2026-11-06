"""One keyboard queue for party chat.

Automatic ``/초대`` and the monitor's Invite / Y+Enter buttons both run on the
game worker. A manual request is taken first on that tick, and the automatic
line is skipped so the two cannot type at once. The queue is ``queue.Queue``:
the UI thread only submits, the worker only runs.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class PartyChatJob:
    kind: str
    name: str
    job_id: str
    source: str = "manual"


class PartyChatQueue:
    def __init__(self) -> None:
        self._q: queue.Queue[PartyChatJob] = queue.Queue()
        self._lock = threading.Lock()
        self._latest: dict[str, Any] = {}

    def submit(self, kind: str, name: str = "") -> str:
        job_id = uuid.uuid4().hex[:8]
        self._q.put(
            PartyChatJob(
                kind=str(kind or "").strip().lower(),
                name=str(name or "").strip(),
                job_id=job_id,
            )
        )
        with self._lock:
            self._latest = {
                "id": job_id,
                "kind": str(kind or "").strip().lower(),
                "name": str(name or "").strip(),
                "state": "queued",
                "text": "queued",
                "ok": None,
                "at": time.time(),
            }
        return job_id

    def pop(self) -> Optional[PartyChatJob]:
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None

    def finish(self, job: PartyChatJob, text: str, *, ok: bool) -> None:
        with self._lock:
            self._latest = {
                "id": job.job_id,
                "kind": job.kind,
                "name": job.name,
                "state": "done" if ok else "failed",
                "text": text,
                "ok": bool(ok),
                "at": time.time(),
            }

    def note(self, text: str, *, state: str) -> None:
        with self._lock:
            current = dict(self._latest)
            current["state"] = state
            current["text"] = text
            current["at"] = time.time()
            self._latest = current

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            out = dict(self._latest)
        out["pending"] = int(self._q.qsize())
        return out
