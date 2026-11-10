"""Search knobs for live farm search (``mode_ticks`` / ``search_hop``)."""
from __future__ import annotations

# Anti-spam: the character is screen-centered, so movement cannot be read
# from its position. A waypoint (leg) is held (emitted with ``mid_act=True``)
# while its age counter is below LEG_TICKS; once the counter reaches
# LEG_TICKS, search rolls the next leg. Each new leg is a real click.
# Another action that skips search for more than one tick drops the hop.
# The next search tick plans a new point and clicks immediately.
LEG_TICKS = 60

__all__ = [
    "LEG_TICKS",
]
