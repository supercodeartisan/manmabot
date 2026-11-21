"""Purple UIA contract — the frozen P0 contract.

Loads scripts/purple_contract.json (or a path passed in) and exposes typed
accessors. Nothing here talks to the live UI; this is pure configuration.

The contract is the single source of truth for the elements the engine drives.
All geometry is *relative to the owning window's client origin* and is used
only as a sanity reference — the engine never clicks a stored coordinate; it
re-discovers elements live and clicks their current rectangles.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CONTRACT = (
    Path(__file__).resolve().parents[2] / "scripts" / "purple_contract.json"
)


class ContractError(RuntimeError):
    pass


class PurpleContract:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    @classmethod
    def load(cls, path: str | Path = "") -> "PurpleContract":
        p = Path(path) if path else DEFAULT_CONTRACT
        if not p.exists():
            raise ContractError("contract file not found: %s" % p)
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(data)

    # -- seeds --------------------------------------------------------------
    @property
    def elements(self) -> dict[str, Any]:
        return self.data.get("elements", {})

    def element(self, state: str, seed: str) -> dict[str, Any]:
        el = dict(self.elements.get(state, {}).get(seed, {}))
        if el and "automation_id" not in el:
            el["automation_id"] = seed
        return el

    @property
    def gate_button(self) -> dict[str, Any]:
        return self.element("gate", "NcSignInButton")

    @property
    def email_field(self) -> dict[str, Any]:
        return self.element("login_email", "current-account")

    @property
    def email_submit(self) -> dict[str, Any]:
        return self.element("login_email", "btn-login-email")

    @property
    def password_field(self) -> dict[str, Any]:
        return self.element("login_password", "current-password")

    @property
    def password_submit(self) -> dict[str, Any]:
        return self.element("login_password", "btn-login-email")

    @property
    def game_card(self) -> dict[str, Any]:
        return self.element("launcher", "game_card")

    @property
    def play_button(self) -> dict[str, Any]:
        return self.element("launcher", "PlayButton")

    @property
    def playing_button(self) -> dict[str, Any]:
        return self.element("launcher", "PlayingButton")

    # -- discovery ----------------------------------------------------------
    @property
    def discovery(self) -> dict[str, Any]:
        return self.data.get("discovery", {})

    @property
    def process_images(self) -> list[str]:
        return self.discovery.get("process_images", [])

    @property
    def max_uia_depth(self) -> int:
        return int(self.discovery.get("max_uia_depth", 24))

    # -- budget / state machine --------------------------------------------
    @property
    def states(self) -> list[str]:
        return self.data.get("states", [])

    @property
    def budgets_sec(self) -> dict[str, int]:
        return self.data.get("budgets_sec", {})

    @property
    def retries_per_action(self) -> int:
        return int(self.data.get("retries_per_action", 2))

    # -- game ---------------------------------------------------------------
    @property
    def game(self) -> dict[str, Any]:
        return self.data.get("game", {})
