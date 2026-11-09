import numpy as np
import pytest

from hand_controller.actions import ActionExecutor, parse_keys, validate_action
from hand_controller.backends import PadState
from hand_controller.backends.null import NullMouseBackend
from hand_controller.config import (config_stamp, diff_config, load_config, load_default_config,
                                    reset_user_config, save_user_config)
from hand_controller.custom_gestures import GestureEngine, describe_pose
from hand_controller.gestures import HandAnalyzer, HandFeatures, matches_pose
from hand_controller.main import to_pynput_hotkey
from hand_controller.mouse_mode import MouseMapper
from test_core import make_hand

HORNS = {"thumb": "any", "index": "up", "middle": "down", "ring": "down", "pinky": "up"}


def feat(label="Right", ext=None, pinches=None, curl=0.0):
    ext = ext or {}
    full = {k: ext.get(k, False) for k in ("thumb", "index", "middle", "ring", "pinky")}
    return HandFeatures(label=label, palm=np.array([0.5, 0.5]), size=0.1, curl=curl,
                        pinches=pinches or {}, extended=full)


def horns(label="Right"):
    return feat(label, {"index": True, "pinky": True}, curl=0.5)


# ---- configurazione --------------------------------------------------------------------------
def test_save_diff_and_reset(isolated_user_config):
    cfg = load_config()
    assert cfg == load_default_config()
    cfg["mouse"]["anchor"]["span"] = 0.7
    cfg["auto_switch"]["game_processes"].append("gioco.exe")
    save_user_config(cfg)
    assert config_stamp() is not None
    saved = isolated_user_config.read_text(encoding="utf-8")
    assert "span: 0.7" in saved and "camera" not in saved          # solo le differenze
    again = load_config()
    assert again["mouse"]["anchor"]["span"] == 0.7
    assert "gioco.exe" in again["auto_switch"]["game_processes"]
    reset_user_config()
    assert config_stamp() is None and load_config() == load_default_config()


def test_diff_config_nested():
    base = {"a": {"b": 1, "c": [1, 2]}, "d": 3}
    assert diff_config(base, {"a": {"b": 1, "c": [1, 2]}, "d": 3}) == {}
    assert diff_config(base, {"a": {"b": 2, "c": [1, 2]}, "d": 3}) == {"a": {"b": 2}}


def test_default_gestures_are_valid_and_only_horns_enabled():
    gestures = load_default_config()["custom_gestures"]
    assert all(validate_action(g["action"]) is None for g in gestures)
    enabled = [g for g in gestures if g.get("enabled", True)]
    assert len(enabled) == 1 and enabled[0]["action"]["value"] == "toggle_mode"
    assert describe_pose(enabled[0]["fingers"]) == "Corna"


# ---- pose e motore dei gesti -----------------------------------------------------------------
def test_matches_pose_and_pinch_blocks():
    assert matches_pose(horns(), HORNS)
    assert not matches_pose(feat(ext={"index": True}), HORNS)
    f = horns()
    f.pinches = {"middle": True}
    assert not matches_pose(f, HORNS)


def test_analyzer_detects_extended_fingers():
    cfg = load_default_config()["gestures"]
    open_f = HandAnalyzer(cfg).update("Right", make_hand(open_hand=True), 1.0)
    assert all(open_f.extended[n] for n in ("index", "middle", "ring", "pinky"))
    assert not open_f.fist
    assert HandAnalyzer(cfg).update("Right", make_hand(open_hand=False), 1.0).fist


class Recorder(ActionExecutor):
    def __init__(self):
        super().__init__(NullMouseBackend(), {}, dry_run=True)
        self.log = []

    def fire(self, action, now):
        self.log.append(("fire", action["value"]))
        super().fire(action, now)

    def press(self, action, now):
        self.log.append(("press", action["value"]))
        super().press(action, now)

    def release(self, action):
        self.log.append(("release", action["value"]))
        super().release(action)


def _gesture(**kw):
    g = {"name": "t", "enabled": True, "hand": "any", "fingers": HORNS, "hold_s": 0.5,
         "trigger": "once", "modes": ["mouse"], "action": {"type": "app", "value": "toggle_mode"}}
    g.update(kw)
    return g


def test_engine_once_fires_after_hold_and_only_once():
    ex = Recorder()
    eng = GestureEngine([_gesture()], ex)
    eng.update({"Right": horns()}, "mouse", 0.0)
    prog, name = eng.update({"Right": horns()}, "mouse", 0.25)
    assert ex.log == [] and name == "t" and prog == pytest.approx(0.5)
    eng.update({"Right": horns()}, "mouse", 0.6)
    eng.update({"Right": horns()}, "mouse", 1.5)
    assert ex.log == [("fire", "toggle_mode")]
    eng.update({}, "mouse", 2.0)                       # posa persa -> si riarma
    eng.update({"Right": horns()}, "mouse", 2.1)
    eng.update({"Right": horns()}, "mouse", 2.7)
    assert ex.log.count(("fire", "toggle_mode")) == 2


def test_engine_respects_mode_hand_and_enabled():
    ex = Recorder()
    eng = GestureEngine([_gesture(hold_s=0), _gesture(hand="Left", hold_s=0),
                         _gesture(enabled=False, hold_s=0)], ex)
    eng.update({"Right": horns()}, "gamepad", 0.0)     # modalità non attiva
    assert ex.log == []
    eng.update({"Right": horns()}, "mouse", 1.0)
    assert ex.log == [("fire", "toggle_mode")]         # solo il primo: mano sx e disattivato no


def test_engine_hold_presses_pad_until_released_with_grace():
    ex = Recorder()
    eng = GestureEngine([_gesture(trigger="hold", hold_s=0, modes=["gamepad"],
                                  action={"type": "pad", "value": "RB"})], ex)
    eng.update({"Left": horns("Left")}, "gamepad", 0.0)
    assert "RB" in ex.merge_pad(PadState(), 0.0).buttons
    eng.update({}, "gamepad", 0.05)                    # perdita breve: resta premuto
    assert ("release", "RB") not in ex.log
    eng.update({}, "gamepad", 0.5)
    assert ("release", "RB") in ex.log
    assert "RB" not in ex.merge_pad(PadState(), 0.5).buttons


def test_pad_tap_lasts_briefly():
    ex = Recorder()
    ex.fire({"type": "pad", "value": "DPAD_UP"}, 1.0)
    assert "DPAD_UP" in ex.merge_pad(PadState(), 1.05).buttons
    assert "DPAD_UP" not in ex.merge_pad(PadState(), 1.5).buttons


# ---- azioni e tasti --------------------------------------------------------------------------
def test_parse_keys_and_validation():
    assert len(parse_keys("ctrl+shift+t")) == 3
    assert len(parse_keys("win+d")) == 2
    with pytest.raises(ValueError):
        parse_keys("ctrl+tastoinesistente")
    assert validate_action({"type": "key", "value": "alt+tab"}) is None
    assert validate_action({"type": "pad", "value": "ZZ"})
    assert validate_action({"type": "app", "value": "boh"})
    assert validate_action({"type": "run", "value": ""})


def test_hotkey_format():
    from pynput import keyboard
    assert to_pynput_hotkey("ctrl+F10") == "<ctrl>+<f10>"
    assert to_pynput_hotkey("f9") == "<f9>"
    keyboard.HotKey.parse(to_pynput_hotkey("alt+shift+h"))


# ---- mouse: il pugno vero ricentra, l'indice teso no -----------------------------------------
def test_pointing_does_not_recenter_mouse():
    mouse = NullMouseBackend((1600, 900))
    cfg = dict(load_default_config()["mouse"], motion="anchor")
    mm = MouseMapper(cfg, mouse)
    mm.update({"Right": feat(ext={"index": True}, curl=0.8)}, 0.0)
    assert not mm.recentering
    mm.update({"Right": feat(curl=0.9)}, 0.1)
    assert mm.recentering
    mm.request_recenter()
    mm.update({"Right": feat(ext={"index": True, "middle": True, "ring": True, "pinky": True})}, 0.2)
    assert mm.recentering
