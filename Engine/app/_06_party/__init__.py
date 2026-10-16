"""Party member brain — mirror a leader (human or solo bot).

Independent of ``_04_decision`` farming columns. Session calls
:class:`PartyMemberManager.decide` when the profile has party member on.

Enable path (single): Hunt tab → SettingsBag ``party`` → Profile → BotController.
"""
from .config import PartyMemberConfig
from .manager import PartyMemberManager
from .policy import MemberKind, decide_policy
from .state import MemberRuntime

__all__ = [
    "MemberKind",
    "MemberRuntime",
    "PartyMemberConfig",
    "PartyMemberManager",
    "decide_policy",
]
