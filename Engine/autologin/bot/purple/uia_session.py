"""Purple UIA session — window discovery and tree observation.

This is the "eyes". It reuses the read-only walker from the P0 probe and
exposes the state classifier. No input is ever sent here.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import win32gui

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import purple_probe as probe  # noqa: E402

from .contract import PurpleContract  # noqa: E402


class PurpleSession:
    def __init__(self, contract: PurpleContract):
        self.contract = contract
        self._uia = None
        import uiautomation as uia
        self._uia = uia
        uia.SetGlobalSearchTimeout(0.8)

    # -- window discovery ---------------------------------------------------
    def windows(self) -> list[dict]:
        return probe.sampleable_windows(probe.enumerate_purple_windows())

    def attach(self, hwnd: int) -> Any:
        return self._uia.ControlFromHandle(int(hwnd))

    # -- one-shot observation ----------------------------------------------
    def observe(self, hwnd: int, max_depth: int | None = None,
                max_controls: int = 2000) -> tuple[str, dict, list[dict]]:
        root = self.attach(hwnd)
        if root is None:
            return "unknown", {}, []
        rect = win32gui.GetWindowRect(hwnd)
        nodes, _ = probe.walk_tree(
            root, tuple(rect) if rect else None,
            max_depth or self.contract.max_uia_depth, max_controls, False)
        label, flags = probe.classify_probe(nodes)
        return label, flags, nodes

    def find(self, nodes: list[dict], seed: str) -> dict | None:
        for n in nodes:
            if n["aid"] == seed and n["onscreen"]:
                return n
        return None

    def find_enabled(self, nodes: list[dict], seed: str) -> dict | None:
        for n in nodes:
            if n["aid"] == seed and n["onscreen"] and n["enabled"]:
                return n
        return None

    def scan_all(self) -> list[tuple[dict, str, dict, list[dict]]]:
        """(row, state, flags, nodes) for every sampleable window."""
        out = []
        for row in self.windows():
            state, flags, nodes = self.observe(row["hwnd"])
            out.append((row, state, flags, nodes))
        return out

    def find_in_all(self, seed: str, require_enabled: bool = False):
        for row, state, flags, nodes in self.scan_all():
            node = (self.find_enabled if require_enabled else self.find)(
                nodes, seed)
            if node is not None:
                return row, node
        return None
