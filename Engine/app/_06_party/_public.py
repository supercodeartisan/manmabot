"""Party member brain — mirror a leader (human or solo bot).

Independent of ``_04_decision`` farming columns. Session calls
:class:`PartyMemberManager.decide` when the profile has party member on.

Enable path (single): Party tab → Run as party member → Profile → BotController.
Leader comes from ``party_listen`` after join (no typed leader name).
Solo Start leaves this package unused (no party sensor, no member decide).
"""
from .config import PartyMemberConfig
from .leader import LeaderView, resolve_leader
from .loot import party_loot_ownership_filter, party_may_loot
from .manager import PartyMemberManager
from .policy import MemberKind, decide_policy
from .state import MemberRuntime

__all__ = [
    "LeaderView",
    "MemberKind",
    "MemberRuntime",
    "PartyMemberConfig",
    "PartyMemberManager",
    "decide_policy",
    "party_loot_ownership_filter",
    "party_may_loot",
    "resolve_leader",
]
