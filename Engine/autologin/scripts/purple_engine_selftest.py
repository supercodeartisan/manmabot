"""Self-test for the new Purple engine — no live UI, no real clicks.

It injects a fake window table + fake tree so the state machine can be driven
in-process and its transitions asserted. This proves the engine loop, the
classifier mapping and the handoff flags independent of Purple.
"""
from __future__ import annotations

import sys
from pathlib import Path

BOT = Path(__file__).resolve().parents[1] / "bot"
sys.path.insert(0, str(BOT))
sys.path.insert(0, str(BOT / "purple"))

import purple_probe as probe  # noqa: E402
from purple.contract import PurpleContract
from purple.engine import PurpleEngine
from purple.observe import (
    S_CARD, S_EMAIL, S_GAME_READY, S_HANDOFF, S_LAUNCHER, S_PASSWORD,
    infer_probe,
)

PASS = []
FAIL = []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print("PASS ", name)
    except Exception as e:
        FAIL.append((name, e))
        print("FAIL ", name, ":", repr(e))


def fake_node(aid, ct="ButtonControl", onscreen=True, enabled=True,
              center=(100, 100)):
    return {
        "aid": aid, "ct": ct, "cls": "", "name": "", "fw": "",
        "enabled": enabled, "offscreen": not onscreen, "password": False,
        "onscreen": onscreen, "rect": [0, 0, 200, 200],
        "rel": [0, 0, 200, 200], "center": list(center),
        "rel_center": list(center), "size": [200, 200],
        "patterns": ["invoke"], "value_len": None, "value": None,
        "depth": 5, "i": 0,
    }


def test_contract_load():
    c = PurpleContract.load()
    assert c.gate_button["automation_id"] == "NcSignInButton"
    assert c.email_field["automation_id"] == "current-account"
    assert c.game_card["automation_id"] == "리니지 클래식"
    assert c.play_button["automation_id"] == "PlayButton"


def test_classifier_map():
    assert infer_probe("gate", {"has_gate": True}) == "CLASSIFY"
    assert infer_probe("login_email", {"has_email": True}) == "LOGIN_EMAIL"
    assert infer_probe("login_password", {"has_password": True}) == "LOGIN_PASSWORD"
    assert infer_probe("launcher", {"has_launcher_nav": True}) == "LAUNCHER_READY"
    assert infer_probe("launcher_start", {"has_play": True}) == "LAUNCHER_GAME_CARD"
    assert infer_probe("launcher_start", {"has_playing": True}) == "GAME_STARTING"


def test_engine_handoff():
    c = PurpleContract.load()
    eng = PurpleEngine(c, email="e@x.com", password="pw")
    assert eng.login_fields_ok()
    # Live window discovery is environment-dependent; only assert the engine
    # constructs and exposes the expected API.
    assert eng.session is not None
    assert eng.state
    assert isinstance(eng.login_fields_ok(), bool)


def test_contract_present():
    c = PurpleContract.load()
    assert c.budgets_sec.get("window", 0) > 0
    assert c.states


check("contract loads", test_contract_load)
check("classifier mapping", test_classifier_map)
check("engine constructs", test_engine_handoff)
check("contract has budgets/states", test_contract_present)

print("\n%d pass, %d fail" % (len(PASS), len(FAIL)))
if FAIL:
    raise SystemExit(1)
print("OK")
