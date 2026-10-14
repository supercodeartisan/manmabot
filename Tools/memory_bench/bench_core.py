"""Memory-read timing helpers for the Memory Bench tool.

Each unit is a named callable that performs one live sensor read and returns
a short summary string (counts / ok). Timing is owned by ``run_samples``.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

# print_state SLOW_MS is 100; wait a little over so each sample forces sweep.
ENTITY_SLOW_GAP_S = 0.15


@dataclass(frozen=True)
class UnitSpec:
    key: str
    label: str
    blurb: str


UNITS: tuple[UnitSpec, ...] = (
    UnitSpec(
        "entities_compare",
        "Entities (print_state) — fast vs slow",
        "Same DLL: consecutive snaps ≈ fast PRES_B; 0.15s gap ≈ slow cell sweep + fast.",
    ),
    UnitSpec(
        "entities_fast",
        "Entities — fast only",
        "Back-to-back print_state snapshots (roster already warm).",
    ),
    UnitSpec(
        "entities_slow",
        "Entities — slow+fast (forced sweep)",
        "Wait 0.15s between snaps so each call re-walks the cell map.",
    ),
    UnitSpec("buff", "Buffs (buff_listen)", "Active buff list JSON."),
    UnitSpec(
        "uidialog",
        "UI dialogs (uidialog scan)",
        "Each poll walks the UI graph (layouts + WINDOW vft). Not the bot header cache.",
    ),
    UnitSpec("hotbar", "Hotbar (hotbar_listen)", "F-key slot snapshot."),
    UnitSpec("inventory", "Inventory (poll, no force)", "Return last bag / idle poll."),
    UnitSpec("inventory_force", "Inventory (force scan)", "Start a bag scan if idle."),
    UnitSpec("shop", "Shop lists (shop_listen)", "Buy/Sell memory lists (shop UI open)."),
    UnitSpec("attacks_me", "Attacks me", "Who is attacking the local player."),
    UnitSpec("contested", "Contested mobs", "Mobs claimed by other players."),
    UnitSpec("player", "Player monitor", "realtime_monitor player snapshot."),
    UnitSpec(
        "capture_tick",
        "Full capture_tick",
        "player+print_state+attacks+contested+buff+uidialog (+inv idle).",
    ),
    UnitSpec(
        "capture_tick_full",
        "Full capture_tick + hotbar + force bag",
        "Same as capture_tick with hotbar refresh and force inventory.",
    ),
)


def unit_choices() -> list[tuple[str, str]]:
    return [(u.key, u.label) for u in UNITS]


def unit_by_key(key: str) -> UnitSpec:
    for u in UNITS:
        if u.key == key:
            return u
    raise KeyError(key)


@dataclass
class SampleStats:
    times_ms: list[float]
    ok: int = 0
    fail: int = 0
    last_detail: str = ""

    @property
    def n(self) -> int:
        return len(self.times_ms)

    def summary_lines(self, title: str) -> list[str]:
        lines = [f"━━ {title} ━━"]
        if not self.times_ms:
            lines.append("  (no samples)")
            return lines
        xs = sorted(self.times_ms)
        avg = statistics.fmean(xs)
        p50 = statistics.median(xs)
        p95 = xs[max(0, int(round(0.95 * (len(xs) - 1))))]
        lines.append(
            f"  samples {self.n}  |  ok {self.ok}  fail {self.fail}"
        )
        lines.append(
            f"  min {min(xs):7.2f} ms   avg {avg:7.2f} ms   "
            f"max {max(xs):7.2f} ms"
        )
        lines.append(f"  p50 {p50:7.2f} ms   p95 {p95:7.2f} ms")
        if self.last_detail:
            lines.append(f"  last → {self.last_detail}")
        return lines


def _ms(dt: float) -> float:
    return float(dt) * 1000.0


def run_samples(
    once: Callable[[], tuple[bool, str]],
    *,
    iterations: int,
    warmup: int = 1,
    gap_s: float = 0.0,
    progress: Optional[Callable[[str], None]] = None,
) -> SampleStats:
    """Time ``once`` for warmup + iterations. ``gap_s`` sleeps between samples."""
    stats = SampleStats(times_ms=[])
    total = max(0, int(warmup)) + max(1, int(iterations))
    for i in range(total):
        is_warm = i < max(0, int(warmup))
        if progress:
            phase = "warmup" if is_warm else "sample"
            progress(f"{phase} {i + 1}/{total}")
        if gap_s > 0 and i > 0:
            time.sleep(gap_s)
        t0 = time.perf_counter()
        try:
            ok, detail = once()
        except Exception as exc:
            ok, detail = False, f"error: {exc}"
        elapsed = _ms(time.perf_counter() - t0)
        if is_warm:
            continue
        stats.times_ms.append(elapsed)
        if ok:
            stats.ok += 1
        else:
            stats.fail += 1
        stats.last_detail = detail
    return stats


def _sensors():
    from app._01_perception.sensors import shared_sensors

    return shared_sensors()


def _print_reader():
    sensors = _sensors()
    # Prefer the shared print_state handle used by capture_tick.
    reader = getattr(sensors, "_print_reader", None)
    if reader is not None and hasattr(reader, "snapshot"):
        return reader
    from app._01_perception.print_state_reader import PrintStateReader

    return PrintStateReader()


def _detail_entities(snap: Any) -> str:
    if not isinstance(snap, dict):
        return "no snapshot"
    ents = snap.get("entities")
    n = len(ents) if isinstance(ents, list) else 0
    bait = 0
    if isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict) and e.get("bait"):
                bait += 1
    return f"entities={n} bait={bait}"


def _once_entities() -> tuple[bool, str]:
    snap = _print_reader().snapshot()
    ok = isinstance(snap, dict)
    return ok, _detail_entities(snap)


def _once_buff() -> tuple[bool, str]:
    snap = _sensors().capture_buff()
    ok = isinstance(snap, dict)
    n = len(snap.get("buffs") or []) if ok else 0
    return ok, f"buffs={n}"


def _once_uidialog() -> tuple[bool, str]:
    snap = _sensors().capture_uidialog()
    ok = isinstance(snap, dict)
    n_open = int(snap.get("n_open") or 0) if ok else 0
    open_list = snap.get("open") if ok else None
    return ok, f"n_open={n_open} open={open_list}"


def _once_hotbar() -> tuple[bool, str]:
    snap = _sensors().capture_hotbar(force=True)
    ok = isinstance(snap, dict)
    n = len(snap.get("slots") or []) if ok else 0
    return ok, f"slots={n}"


def _once_inventory(*, force: bool) -> tuple[bool, str]:
    snap = _sensors().capture_inventory(force=force)
    ok = isinstance(snap, dict)
    n = len(snap.get("items") or []) if ok else 0
    return ok, f"items={n} force={force}"


def _once_shop() -> tuple[bool, str]:
    snap = _sensors().capture_shop()
    ok = isinstance(snap, dict)
    buy = len(snap.get("buy") or []) if ok else 0
    sell = len(snap.get("sell") or []) if ok else 0
    return ok, f"buy={buy} sell={sell}"


def _once_attacks() -> tuple[bool, str]:
    sensors = _sensors()
    reader = getattr(sensors, "_attacks_reader", None)
    if reader is None:
        return False, "attacks_me reader missing"
    snap = reader.snapshot()
    ok = snap is not None
    n = 0
    if isinstance(snap, dict):
        rows = snap.get("attackers") or snap.get("rows") or snap.get("ents")
        if isinstance(rows, list):
            n = len(rows)
        elif isinstance(snap.get("n"), int):
            n = int(snap["n"])
    return ok, f"rows={n}"


def _once_contested() -> tuple[bool, str]:
    sensors = _sensors()
    reader = getattr(sensors, "_contested_reader", None)
    if reader is None:
        return False, "contested reader missing"
    snap = reader.snapshot()
    ok = snap is not None
    n = 0
    if isinstance(snap, dict):
        rows = snap.get("mobs") or snap.get("rows") or snap.get("ents")
        if isinstance(rows, list):
            n = len(rows)
        elif isinstance(snap.get("n"), int):
            n = int(snap["n"])
    return ok, f"rows={n}"


def _once_player() -> tuple[bool, str]:
    snap = _sensors().pull_player(fresh=False)
    ok = isinstance(snap, dict)
    if not ok:
        return False, "no player"
    p = snap.get("player") if isinstance(snap.get("player"), dict) else snap
    x = p.get("x") if isinstance(p, dict) else None
    y = p.get("y") if isinstance(p, dict) else None
    mid = p.get("mapId") if isinstance(p, dict) else None
    return True, f"xy=({x},{y}) mapId={mid}"


def _once_tick(*, force_inventory: bool, hotbar: bool) -> tuple[bool, str]:
    buf = _sensors().capture_tick(force_inventory=force_inventory, hotbar=hotbar)
    bits = []
    if buf.player_ok:
        bits.append("player")
    if buf.print_state_ok:
        ents = (buf.print_state or {}).get("entities") if buf.print_state else None
        bits.append(f"print({len(ents) if isinstance(ents, list) else 0})")
    if buf.buff_ok:
        bits.append("buff")
    if buf.uidialog_ok:
        bits.append("uidialog")
    if buf.hotbar_ok:
        bits.append("hotbar")
    if buf.inventory_ok:
        bits.append("inv")
    if buf.errors:
        bits.append(f"err={len(buf.errors)}")
    return bool(bits), " ".join(bits) or "empty"


def format_report(
    *,
    unit: UnitSpec,
    iterations: int,
    warmup: int,
    blocks: list[tuple[str, SampleStats]],
    note: str = "",
) -> str:
    lines = [
        "Memory Read Bench",
        f"unit   : {unit.label}",
        f"key    : {unit.key}",
        f"about  : {unit.blurb}",
        f"iters  : {iterations}  warmup={warmup}",
        f"when   : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for title, stats in blocks:
        lines.extend(stats.summary_lines(title))
        lines.append("")
    if len(blocks) == 2 and all(b[1].times_ms for b in blocks):
        a = statistics.fmean(blocks[0][1].times_ms)
        b = statistics.fmean(blocks[1][1].times_ms)
        if a > 0:
            lines.append("━━ Compare ━━")
            lines.append(
                f"  {blocks[1][0]} / {blocks[0][0]}  ≈  {b / a:5.2f}×"
            )
            lines.append(
                f"  Δ avg  {b - a:+7.2f} ms"
            )
            lines.append("")
    if note:
        lines.append(note)
        lines.append("")
    lines.append("Tip: run while LC is in-world. Elevate if SignedDriver is required.")
    return "\n".join(lines)


def bench_unit(
    key: str,
    *,
    iterations: int = 20,
    warmup: int = 2,
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """Run the selected unit and return a human-readable report."""
    unit = unit_by_key(key)
    # Touch sensors early so DLL load cost is outside timed samples where possible.
    if progress:
        progress("loading sensors…")
    _sensors()

    if key == "entities_compare":
        if progress:
            progress("entities: warm slow sweep…")
        # One slow-forcing pause so roster exists, then fast batch.
        time.sleep(ENTITY_SLOW_GAP_S)
        _once_entities()
        fast = run_samples(
            _once_entities,
            iterations=iterations,
            warmup=warmup,
            gap_s=0.0,
            progress=progress,
        )
        if progress:
            progress("entities: slow sweeps…")
        slow = run_samples(
            _once_entities,
            iterations=iterations,
            warmup=0,
            gap_s=ENTITY_SLOW_GAP_S,
            progress=progress,
        )
        return format_report(
            unit=unit,
            iterations=iterations,
            warmup=warmup,
            blocks=[
                ("FAST  (back-to-back PRES_B poll)", fast),
                ("SLOW+FAST  (0.15s gap → cell-map sweep each time)", slow),
            ],
            note=(
                "Slow samples include the forced wait outside the timer; "
                "only the snapshot() call is measured."
            ),
        )

    if key == "entities_fast":
        # Warm with a slow gap once so roster is filled, then fast.
        time.sleep(ENTITY_SLOW_GAP_S)
        _once_entities()
        stats = run_samples(
            _once_entities,
            iterations=iterations,
            warmup=warmup,
            gap_s=0.0,
            progress=progress,
        )
        return format_report(
            unit=unit,
            iterations=iterations,
            warmup=warmup,
            blocks=[("FAST print_state", stats)],
        )

    if key == "entities_slow":
        stats = run_samples(
            _once_entities,
            iterations=iterations,
            warmup=max(1, warmup),
            gap_s=ENTITY_SLOW_GAP_S,
            progress=progress,
        )
        return format_report(
            unit=unit,
            iterations=iterations,
            warmup=warmup,
            blocks=[("SLOW+FAST print_state (forced sweep)", stats)],
        )

    once_map: dict[str, Callable[[], tuple[bool, str]]] = {
        "buff": _once_buff,
        "uidialog": _once_uidialog,
        "hotbar": _once_hotbar,
        "inventory": lambda: _once_inventory(force=False),
        "inventory_force": lambda: _once_inventory(force=True),
        "shop": _once_shop,
        "attacks_me": _once_attacks,
        "contested": _once_contested,
        "player": _once_player,
        "capture_tick": lambda: _once_tick(force_inventory=False, hotbar=False),
        "capture_tick_full": lambda: _once_tick(
            force_inventory=True, hotbar=True
        ),
    }
    once = once_map.get(key)
    if once is None:
        raise KeyError(key)
    stats = run_samples(
        once,
        iterations=iterations,
        warmup=warmup,
        gap_s=0.0,
        progress=progress,
    )
    return format_report(
        unit=unit,
        iterations=iterations,
        warmup=warmup,
        blocks=[(unit.label, stats)],
    )


__all__ = [
    "UNITS",
    "UnitSpec",
    "unit_choices",
    "unit_by_key",
    "bench_unit",
    "ENTITY_SLOW_GAP_S",
]
