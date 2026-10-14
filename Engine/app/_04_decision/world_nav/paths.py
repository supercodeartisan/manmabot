"""Engine-owned world-nav data + Extra_data-free planner package paths."""

from __future__ import annotations

from pathlib import Path

# world_nav/paths.py -> world_nav -> _04_decision -> app -> engine
ENGINE_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = ENGINE_ROOT.parent
WORLD_NAV_DATA = ENGINE_ROOT / "data" / "world_nav"
MANIFEST = WORLD_NAV_DATA / "manifest.json"
PROVIDERS = WORLD_NAV_DATA / "providers"
