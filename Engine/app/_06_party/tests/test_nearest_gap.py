"""Leader stands only when the nearest member is past the tile limit."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from settings.profile import Profile, party_near_limit  # noqa: E402
from app._06_party.formation import (  # noqa: E402
    OTHER_MAP,
    nearest_follower_gap,
    nearest_gap_hold,
)


def test_nearest_gap_hold() -> None:
    assert party_near_limit(profile=Profile()) == 5
    chosen = Profile()
    chosen.party_near_tiles = 12
    assert party_near_limit(profile=chosen) == 12
    assert nearest_gap_hold(6, 0, party_near_limit(profile=chosen)) is False
    assert nearest_gap_hold(13, 0, party_near_limit(profile=chosen)) is True

    leader = (10, 10)
    nearest, other = nearest_follower_gap(leader, [(14, 10), (30, 10)])
    assert nearest == 4 and other == 0
    assert nearest_gap_hold(nearest, other, 5) is False

    nearest, other = nearest_follower_gap(leader, [(15, 10)])
    assert nearest == 5
    assert nearest_gap_hold(nearest, other, 5) is False

    nearest, other = nearest_follower_gap(leader, [(16, 10), (40, 10)])
    assert nearest == 6
    assert nearest_gap_hold(nearest, other, 5) is True

    nearest, other = nearest_follower_gap(leader, [(19, 10), (12, 10)])
    assert nearest == 2
    assert nearest_gap_hold(nearest, other, 5) is False

    nearest, other = nearest_follower_gap(leader, [])
    assert nearest is None and other == 0
    assert nearest_gap_hold(nearest, other, 5) is False

    nearest, other = nearest_follower_gap(leader, [OTHER_MAP, OTHER_MAP])
    assert nearest is None and other == 2
    assert nearest_gap_hold(nearest, other, 5) is True

    nearest, other = nearest_follower_gap(leader, [(12, 10), OTHER_MAP])
    assert nearest == 2 and other == 1
    assert nearest_gap_hold(nearest, other, 5) is False


if __name__ == "__main__":
    test_nearest_gap_hold()
    print("ok")
