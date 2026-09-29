from __future__ import annotations

import time
from app._03_world.inventory_listen_reader import LiveInventorySweep
from app._03_world.memory_inventory import inventory_state_from_snapshot


class _SlowReader:
    def __init__(self, delay_s: float, snap: dict) -> None:
        self.delay_s = delay_s
        self.snap = snap
        self.calls = 0
        self.dll_loaded = True

    def _snapshot_file(self):
        return {
            "source": "inv.json",
            "items": [{"id": 80, "count": 3, "name": "체력 회복제"}],
        }

    def snapshot(self):
        self.calls += 1
        time.sleep(self.delay_s)
        return self.snap


def test_poll_does_not_block_on_slow_dll():
    live = {
        "cmd": "inventory",
        "items": [
            {"id": 80, "count": 26, "name": "체력 회복제"},
            {"id": 7, "count": 2477, "name": "화살"},
        ],
    }
    sweep = LiveInventorySweep(interval_s=2.0, reader=_SlowReader(0.4, live))
    t0 = time.perf_counter()
    first = sweep.poll(force=True)
    waited = time.perf_counter() - t0
    assert waited < 0.15
    assert first is not None
    assert first.get("source") == "inv.json"
    seed = inventory_state_from_snapshot(first)
    assert seed.hp_potion == 3
    deadline = time.time() + 2.0
    latest = first
    while time.time() < deadline:
        latest = sweep.poll()
        if latest is not None and latest.get("source") != "inv.json":
            break
        time.sleep(0.02)
    assert latest.get("items")[1]["count"] == 2477
    parsed = inventory_state_from_snapshot(latest)
    assert parsed.hp_potion == 26
    assert parsed.arrows == 2477
    sweep.close()


def test_close_does_not_wait_for_scan():
    sweep = LiveInventorySweep(
        interval_s=2.0,
        reader=_SlowReader(1.0, {"items": [{"id": 7, "count": 1}]}),
    )
    sweep.poll(force=True)
    t0 = time.perf_counter()
    sweep.close()
    assert time.perf_counter() - t0 < 0.15


def test_inv_json_seed_parses_shop_counts():
    snap = {
        "source": "inv.json",
        "items": [
            {"id": 80, "count": 26, "name": "체력 회복제"},
            {"id": 7, "count": 477, "name": "화살"},
            {"id": 5, "count": 1100, "name": "아데나"},
        ],
    }
    state = inventory_state_from_snapshot(snap)
    assert state.bag_ready is True
    assert state.hp_potion == 26
    assert state.arrows == 477
    assert state.silver_arrows == 0
    assert state.adena == 1100


def test_red_potion_counts_as_hp_potion():
    state = inventory_state_from_snapshot(
        {
            "items": [
                {"id": 14, "count": 8, "name": "紅色藥水"},
                {"id": 15, "count": 2, "name": "橙色藥水"},
            ]
        }
    )
    assert state.hp_potion == 10
