"""Single catalog of party-shop scratch and flag key names."""
from __future__ import annotations

JOIN = "party_join_leader"
PIN = "party_pin_shop_behavior"
FLAG = "party_shopkeeper_arrow"
ATTEMPT = "party_supply_attempt"
PAUSE = "party_supply_pause"
SEEN = "party_supply_seen"
CARE_POSE = "party_care_pose"
APPROACH_GOAL = "party_approach_goal"
DROP_JOB = "party_supply_drop"
LEADER_HOLD_POSE = "party_leader_hold_pose"
SUPPLY_ITEM = "party_supply_item"
SUPPLY_CHAIN = "party_supply_chain"
SUPPLY_KEEP = "party_supply_keep"
SUPPLY_CONFIGURED = "party_supply_configured"
ARROW_BUY_QTY = "party_arrow_buy_qty"
NAV_GOAL = "party_nav_goal"

__all__ = [
    "APPROACH_GOAL",
    "ARROW_BUY_QTY",
    "ATTEMPT",
    "CARE_POSE",
    "DROP_JOB",
    "FLAG",
    "JOIN",
    "LEADER_HOLD_POSE",
    "NAV_GOAL",
    "PAUSE",
    "PIN",
    "SEEN",
    "SUPPLY_CHAIN",
    "SUPPLY_CONFIGURED",
    "SUPPLY_ITEM",
    "SUPPLY_KEEP",
]
