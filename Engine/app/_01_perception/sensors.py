"""Fill :class:`PerceptionBuffer` from live memory DLLs.

All product memory reads go through :class:`PerceptionSensors`. Schedules
differ per sensor; not every field is filled every call (partial buffer).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from app._01_perception.buffer import PerceptionBuffer
from app._01_perception.memory_client import open_monitor_from_config

_LOCK = threading.Lock()
_SHARED: Optional["PerceptionSensors"] = None


def _resolve_sensor_config(
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Prefer an explicit config; otherwise load Engine/config (memory.yaml)."""
    if isinstance(config, dict):
        return config
    try:
        from tool.utils import load_config

        loaded = load_config()
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    return {}


def shared_sensors(config: Optional[dict[str, Any]] = None) -> "PerceptionSensors":
    """Process-wide sensors. Loads ``Engine/config`` when no config is passed.

    UI probes / Start gates call this without config. If the first call used an
    empty dict, player memory stayed disabled forever — recreate when config
    enables memory.
    """
    global _SHARED
    with _LOCK:
        cfg = _resolve_sensor_config(config)
        want_memory = bool((cfg.get("memory") or {}).get("enabled", False))
        if _SHARED is None:
            _SHARED = PerceptionSensors(cfg)
        elif want_memory and not getattr(_SHARED, "_memory_enabled", False):
            try:
                _SHARED.close()
            except Exception:
                pass
            _SHARED = PerceptionSensors(cfg)
        return _SHARED


def set_shared_sensors(sensors: "PerceptionSensors") -> None:
    global _SHARED
    with _LOCK:
        _SHARED = sensors


def clear_shared_sensors() -> None:
    global _SHARED
    with _LOCK:
        if _SHARED is not None:
            try:
                _SHARED.close()
            except Exception:
                pass
            _SHARED = None


class PerceptionSensors:
    """Owns sensor handles and the latest :class:`PerceptionBuffer`."""

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self._config = config if isinstance(config, dict) else {}
        self.buffer = PerceptionBuffer()
        self._monitor = open_monitor_from_config(self._config, quiet=True)
        self._print_reader = None
        self._attacks_reader = None
        self._contested_reader = None
        self._inventory = None
        self._hotbar = None
        self._shop = None
        self._buff = None
        self._uidialog = None
        self._party = None
        self._party_init_tried = False
        self._entity_sweep = None
        self._last_hotbar_at = 0.0
        self._hotbar_interval_s = 1.0
        self._memory_enabled = bool(
            (self._config.get("memory") or {}).get("enabled", False)
        )
        self._reconnect_interval_s = float(
            ((self._config.get("memory") or {}).get("reconnect_interval_s", 2.5))
        )
        self._last_reconnect_at = 0.0
        self._init_print()
        self._init_combat_readers()
        self._init_inventory()
        self._init_hotbar()
        self._init_shop()
        self._init_buff()
        self._init_uidialog()
        # Party DLL loads only when capture_tick(party=True) / capture_party().

    def _init_print(self) -> None:
        try:
            from app._01_perception.print_state_reader import PrintStateReader

            self._print_reader = PrintStateReader()
        except Exception as exc:
            self._print_reader = None
            self.buffer.errors.append(f"print_state: {exc}")

    def _init_combat_readers(self) -> None:
        try:
            from app._01_perception.attacks_me_reader import AttacksMeReader

            self._attacks_reader = AttacksMeReader()
        except Exception as exc:
            self._attacks_reader = None
            self.buffer.errors.append(f"attacks_me: {exc}")
        try:
            from app._01_perception.contested_mobs_reader import ContestedMobsReader

            self._contested_reader = ContestedMobsReader()
        except Exception as exc:
            self._contested_reader = None
            self.buffer.errors.append(f"contested_mobs: {exc}")

    def _init_inventory(self) -> None:
        try:
            from app._01_perception.inventory_listen_reader import LiveInventorySweep

            self._inventory = LiveInventorySweep()
        except Exception as exc:
            self._inventory = None
            self.buffer.errors.append(f"inventory: {exc}")

    def _init_hotbar(self) -> None:
        try:
            from app._01_perception.hotbar_listen_reader import HotbarListenReader

            self._hotbar = HotbarListenReader()
        except Exception as exc:
            self._hotbar = None
            self.buffer.errors.append(f"hotbar: {exc}")

    def _init_shop(self) -> None:
        try:
            from app._01_perception.shop_listen_reader import ShopListenReader

            self._shop = ShopListenReader()
        except Exception as exc:
            self._shop = None
            self.buffer.errors.append(f"shop: {exc}")

    def _init_buff(self) -> None:
        try:
            from app._01_perception.buff_listen_reader import BuffListenReader

            self._buff = BuffListenReader()
        except Exception as exc:
            self._buff = None
            self.buffer.errors.append(f"buff: {exc}")

    def _init_uidialog(self) -> None:
        try:
            from app._01_perception.uidialog_listen_reader import UiDialogListenReader

            self._uidialog = UiDialogListenReader()
        except Exception as exc:
            self._uidialog = None
            self.buffer.errors.append(f"uidialog: {exc}")

    def _init_party(self) -> None:
        """Lazy: only party-member sessions need this reader."""
        if self._party_init_tried:
            return
        self._party_init_tried = True
        try:
            from app._01_perception.party_listen_reader import (
                PartyListenReader,
                default_dll_path,
            )

            self._party = PartyListenReader()
            if not getattr(self._party, "dll_loaded", False):
                self.buffer.errors.append(
                    f"party: DLL missing ({default_dll_path().name})"
                )
        except Exception as exc:
            self._party = None
            self.buffer.errors.append(f"party: {exc}")

    @property
    def monitor(self) -> Any:
        return self._monitor

    @property
    def inventory_sweep(self) -> Any:
        return self._inventory

    @property
    def shop_ready(self) -> bool:
        shop = self._shop
        return shop is not None and bool(getattr(shop, "dll_loaded", False))

    def ensure_entity_sweep(self, *, log_interval_s: float = 30.0) -> Any:
        """Tools-only print_state entity poller (not used by the live bot tick)."""
        if self._entity_sweep is None:
            from app._01_perception.entity_sweep import LiveEntitySweep

            self._entity_sweep = LiveEntitySweep(log_interval_s=log_interval_s)
        return self._entity_sweep

    def release_entity_sweep(self) -> None:
        sweep = self._entity_sweep
        self._entity_sweep = None
        if sweep is None:
            return
        try:
            sweep.close()
        except Exception:
            pass

    def inventory_scanning(self) -> bool:
        inv = self._inventory
        if inv is None:
            return False
        return bool(inv.scanning())

    def close(self) -> None:
        if self._monitor is not None:
            try:
                self._monitor.close()
            except Exception:
                pass
            self._monitor = None
        if self._print_reader is not None:
            try:
                self._print_reader.close()
            except Exception:
                pass
            self._print_reader = None
        for attr in (
            "_attacks_reader",
            "_contested_reader",
            "_shop",
            "_buff",
            "_uidialog",
            "_party",
        ):
            reader = getattr(self, attr)
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        if self._inventory is not None:
            try:
                self._inventory.close()
            except Exception:
                pass
            self._inventory = None
        self._hotbar = None
        self.release_entity_sweep()

    def capture_tick(
        self,
        *,
        force_inventory: bool = False,
        hotbar: bool = False,
        party: bool = False,
    ) -> PerceptionBuffer:
        """Per-tick set: player, print_state, attacks, contested, buffs, uidialog; inventory/hotbar by schedule.

        Buff/uidialog are synchronous DLL reads each tick (uidialog poll; discover ~2s), run on
        two short-lived threads so they overlap each tick.
        Party memory is read only when ``party=True`` (party-member sessions).
        """
        buf = self.buffer
        buf.clear()
        buf.stamp()
        self._capture_player(buf)
        self._capture_print_state(buf)
        self._capture_attacks(buf)
        self._capture_contested(buf)
        if force_inventory:
            self._capture_inventory(buf, force=True)
        else:
            # Return last finished bag without starting a scan.
            self._capture_inventory(buf, force=False)
        if hotbar or (time.perf_counter() - self._last_hotbar_at) >= self._hotbar_interval_s:
            self._capture_hotbar(buf)
            self._last_hotbar_at = time.perf_counter()
        self._capture_buff_and_uidialog_sync(buf)
        if party:
            self._capture_party(buf)
        return buf

    def capture(
        self,
        *,
        force_inventory: bool = False,
        hotbar: bool = False,
        party: bool = False,
    ) -> PerceptionBuffer:
        """Alias for :meth:`capture_tick`."""
        return self.capture_tick(
            force_inventory=force_inventory, hotbar=hotbar, party=party
        )

    def capture_hotbar(self, *, force: bool = True) -> Optional[dict[str, Any]]:
        """On-demand hotbar slots. Also stamps ``self.buffer.hotbar`` when ok."""
        del force
        buf = self.buffer
        # Do not clear the whole tick buffer — only refresh hotbar fields.
        self._capture_hotbar(buf)
        if buf.hotbar_ok:
            return buf.hotbar
        return None

    def capture_inventory(self, *, force: bool = False) -> Optional[dict[str, Any]]:
        """On-demand bag. ``force=True`` starts a scan if idle."""
        buf = self.buffer
        self._capture_inventory(buf, force=force)
        if buf.inventory_ok:
            return buf.inventory
        return None

    def capture_shop(self) -> Optional[dict[str, Any]]:
        """On-demand shop Buy/Sell lists. Returns dict; not required every tick."""
        if self._shop is None:
            return None
        try:
            snap = self._shop.snapshot()
        except Exception as exc:
            self.buffer.errors.append(f"shop: {exc}")
            return None
        if not isinstance(snap, dict):
            return None
        self.buffer.shop = snap
        self.buffer.shop_ok = True
        return snap

    def capture_buff(self) -> Optional[dict[str, Any]]:
        """On-demand active buffs (synchronous DLL read, same as tick/tools)."""
        buf = self.buffer
        self._capture_buff(buf)
        if buf.buff_ok:
            return buf.buff
        return None

    def capture_uidialog(self) -> Optional[dict[str, Any]]:
        """On-demand UI dialog open/closed (synchronous DLL read, same as tick/tools)."""
        buf = self.buffer
        self._capture_uidialog(buf)
        if buf.uidialog_ok:
            return buf.uidialog
        return None

    def capture_party(self) -> Optional[dict[str, Any]]:
        """On-demand party roster / leader stats (synchronous DLL read)."""
        self._init_party()
        buf = self.buffer
        self._capture_party(buf)
        if buf.party_ok:
            return buf.party
        return None

    def capture_field(self) -> PerceptionBuffer:
        """Player pose and print_state only. Does not run the bot tick.

        Writes a fresh buffer so an idle field view can read memory without
        clearing inventory, hotbar, or the live tick buffer.
        """
        buf = PerceptionBuffer()
        buf.stamp()
        self._capture_player(buf)
        self._capture_print_state(buf)
        return buf

    def pull_player(self, *, fresh: bool = False) -> Optional[dict[str, Any]]:
        """On-demand monitor snapshot. For gate waits, Tools fill-from-memory, etc."""
        buf = PerceptionBuffer()
        buf.stamp()
        self._capture_player(buf, fresh=fresh)
        if buf.player_ok and isinstance(buf.player, dict):
            # Keep latest on the live buffer for apply callers.
            self.buffer.player = buf.player
            self.buffer.player_ok = True
            return buf.player
        return None

    def _capture_player(self, buf: PerceptionBuffer, *, fresh: bool = False) -> None:
        if self._monitor is None and self._memory_enabled:
            now = time.time()
            if now - self._last_reconnect_at >= self._reconnect_interval_s:
                self._last_reconnect_at = now
                self._monitor = open_monitor_from_config(
                    self._config, quiet=True, connect_retries=1
                )
        if self._monitor is None:
            return
        try:
            snap = self._monitor.snapshot(fresh=fresh)
        except Exception as exc:
            buf.errors.append(f"player: {exc}")
            try:
                self._monitor.close()
            except Exception:
                pass
            self._monitor = None
            self._last_reconnect_at = 0.0
            return
        if snap is None:
            return
        if isinstance(snap, dict) and isinstance(snap.get("player"), dict):
            buf.player = snap
            buf.player_ok = True

    def _capture_print_state(self, buf: PerceptionBuffer) -> None:
        if self._print_reader is None:
            return
        try:
            snap = self._print_reader.snapshot()
        except Exception as exc:
            buf.errors.append(f"print_state: {exc}")
            return
        if not isinstance(snap, dict):
            return
        buf.print_state = snap
        try:
            ok = float(snap.get("client_w") or 0) >= 1 and float(snap.get("client_h") or 0) >= 1
        except (TypeError, ValueError):
            ok = False
        buf.print_state_ok = bool(ok)

    def _capture_attacks(self, buf: PerceptionBuffer) -> None:
        if self._attacks_reader is None:
            return
        try:
            buf.attacks_me = self._attacks_reader.snapshot()
        except Exception as exc:
            buf.errors.append(f"attacks_me: {exc}")

    def _capture_contested(self, buf: PerceptionBuffer) -> None:
        if self._contested_reader is None:
            return
        try:
            buf.contested_mobs = self._contested_reader.snapshot()
        except Exception as exc:
            buf.errors.append(f"contested_mobs: {exc}")

    def _capture_inventory(self, buf: PerceptionBuffer, *, force: bool) -> None:
        if self._inventory is None:
            return
        try:
            snap = self._inventory.poll(force=force)
        except Exception as exc:
            buf.errors.append(f"inventory: {exc}")
            return
        if isinstance(snap, dict) and isinstance(snap.get("items"), list):
            buf.inventory = snap
            buf.inventory_ok = True

    def _capture_hotbar(self, buf: PerceptionBuffer) -> None:
        if self._hotbar is None:
            return
        try:
            snap = self._hotbar.snapshot()
        except Exception as exc:
            buf.errors.append(f"hotbar: {exc}")
            return
        if isinstance(snap, dict) and isinstance(snap.get("slots"), list):
            buf.hotbar = snap
            buf.hotbar_ok = True

    def _capture_buff(self, buf: PerceptionBuffer) -> None:
        if self._buff is None or not getattr(self._buff, "dll_loaded", False):
            return
        try:
            snap = self._buff.snapshot_fresh()
        except Exception as exc:
            buf.errors.append(f"buff: {exc}")
            return
        if isinstance(snap, dict) and isinstance(snap.get("buffs"), list):
            buf.buff = snap
            buf.buff_ok = True

    def _capture_uidialog(self, buf: PerceptionBuffer) -> None:
        if self._uidialog is None or not getattr(self._uidialog, "dll_loaded", False):
            return
        try:
            snap = self._uidialog.snapshot_fresh()
        except Exception as exc:
            buf.errors.append(f"uidialog: {exc}")
            return
        if isinstance(snap, dict) and isinstance(snap.get("windows"), dict):
            buf.uidialog = snap
            buf.uidialog_ok = True

    def _capture_party(self, buf: PerceptionBuffer) -> None:
        self._init_party()
        if self._party is None or not getattr(self._party, "dll_loaded", False):
            return
        try:
            snap = self._party.snapshot()
        except Exception as exc:
            buf.errors.append(f"party: {exc}")
            return
        if isinstance(snap, dict) and "leader" in snap:
            buf.party = snap
            buf.party_ok = True

    def _capture_buff_and_uidialog_sync(self, buf: PerceptionBuffer) -> None:
        """Fresh buff + uidialog DLL reads on separate threads (join before return)."""
        errors: list[str] = []
        buff_snap: Optional[dict[str, Any]] = None
        ui_snap: Optional[dict[str, Any]] = None

        def _buff() -> None:
            nonlocal buff_snap
            if self._buff is None or not getattr(self._buff, "dll_loaded", False):
                return
            try:
                buff_snap = self._buff.snapshot_fresh()
            except Exception as exc:
                errors.append(f"buff: {exc}")

        def _ui() -> None:
            nonlocal ui_snap
            if self._uidialog is None or not getattr(self._uidialog, "dll_loaded", False):
                return
            try:
                ui_snap = self._uidialog.snapshot_fresh()
            except Exception as exc:
                errors.append(f"uidialog: {exc}")

        t_buff = threading.Thread(target=_buff, name="buff-sync", daemon=True)
        t_ui = threading.Thread(target=_ui, name="uidialog-sync", daemon=True)
        t_buff.start()
        t_ui.start()
        t_buff.join(timeout=5.0)
        t_ui.join(timeout=5.0)
        for err in errors:
            buf.errors.append(err)
        if isinstance(buff_snap, dict) and isinstance(buff_snap.get("buffs"), list):
            buf.buff = buff_snap
            buf.buff_ok = True
        if isinstance(ui_snap, dict) and isinstance(ui_snap.get("windows"), dict):
            buf.uidialog = ui_snap
            buf.uidialog_ok = True


__all__ = [
    "PerceptionSensors",
    "clear_shared_sensors",
    "set_shared_sensors",
    "shared_sensors",
]
