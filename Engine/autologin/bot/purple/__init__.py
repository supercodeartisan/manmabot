"""Purple package — the new UIA-based login engine (replaces fixed S1-S3).

Modules:
- contract.py    frozen P0 UIA contract (source of truth)
- uia_session.py window discovery + read-only tree observation ("eyes")
- observe.py     state classifier (probe labels -> engine states)
- act.py         live clicks / typing ("hands")
- engine.py      state machine driving Purple gate -> login -> game card -> Play
- handoff.py     S4+ handoff contract (set bot.game / phase / flags)

The old fixed-coordinate path (bot.tick / _fixed_purple_login /
_normalize_purple_shell_size) is intentionally NOT used here. Run the engine
with `purple_engine=v2` (or an explicit flag) and keep the legacy path for
rollback via the existing flags.
"""
from .contract import PurpleContract
from .engine import PurpleEngine
from .uia_session import PurpleSession

__all__ = ["PurpleContract", "PurpleEngine", "PurpleSession"]
