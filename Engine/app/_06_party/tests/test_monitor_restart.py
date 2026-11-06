"""Stop while the party monitor is polling must not stack lcapi_run."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from app._01_perception import lc_session as lc
from app._01_perception.lc_session import LcSession


def test_ensure_waits_until_the_stopped_thread_leaves() -> None:
    session = LcSession()
    inside = threading.Event()
    leave = threading.Event()
    lock = threading.Lock()
    current = 0
    peak = 0
    starts = 0

    def fake_run(name, dll, spec, slot, run_id):
        del name, dll, spec, slot, run_id
        nonlocal current, peak, starts
        with lock:
            current += 1
            starts += 1
            peak = max(peak, current)
        inside.set()
        leave.wait(3.0)
        with lock:
            current -= 1

    session._run = fake_run  # type: ignore[method-assign]
    real_is_file = Path.is_file
    Path.is_file = lambda self: True  # type: ignore[method-assign]
    lc._MODULES["slot_b"] = lc._MODULES["party"]
    try:
        session.ensure("party")
        session.ensure("slot_b")
        assert inside.wait(2.0)
        deadline = time.monotonic() + 2.0
        while starts < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert starts == 2

        session.stop()
        for _ in range(20):
            session.ensure("party")
            session.ensure("slot_b")
        assert starts == 2
        assert peak == 2
    finally:
        lc._MODULES.pop("slot_b", None)
        Path.is_file = real_is_file  # type: ignore[method-assign]

    leave.set()
    deadline = time.monotonic() + 2.0
    while current and time.monotonic() < deadline:
        time.sleep(0.01)
    assert current == 0

    session.ensure("party")
    deadline = time.monotonic() + 2.0
    while starts < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert starts == 3
    assert peak == 2
    leave.set()


if __name__ == "__main__":
    test_ensure_waits_until_the_stopped_thread_leaves()
    print("OK")
