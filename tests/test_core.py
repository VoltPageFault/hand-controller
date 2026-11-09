import numpy as np
import pytest

from hand_controller.backends.null import NullMouseBackend
from hand_controller.config import deep_merge, load_config
from hand_controller.filters import OneEuroFilter
from hand_controller.gamepad_mode import GamepadMapper, apply_deadzone
from hand_controller.gestures import HandAnalyzer, HandFeatures
from hand_controller.mouse_mode import MouseMapper

ASPECT = 1.0


def make_hand(open_hand=True, pinch=None, offset=(0.5, 0.6)):
    """Mano sintetica verticale: polso in basso, dita verso l'alto. Unità ~ dimensione mano 0.1."""
    s = 0.1
    lm = np.zeros((21, 3))
    lm[0] = [0, 0, 0]
    # MCP di indice, medio, anulare, mignolo
    xs = {"index": -0.3, "middle": 0.0, "ring": 0.3, "pinky": 0.6}
    mcp = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}
    for name, x in xs.items():
        m = mcp[name]
        lm[m] = [x, -1.0, 0]
        if open_hand:
            lm[m + 1] = [x, -1.4, 0]
            lm[m + 2] = [x, -1.7, 0]
            lm[m + 3] = [x, -2.0, 0]
        else:  # pugno: punte ripiegate verso il palmo
            lm[m + 1] = [x, -1.3, 0]
            lm[m + 2] = [x, -1.0, 0]
            lm[m + 3] = [x, -0.8, 0]
    lm[1:5] = [[-0.4, -0.3, 0], [-0.7, -0.5, 0], [-0.9, -0.8, 0], [-1.0, -1.1, 0]]
    if pinch:
        tip = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}[pinch]
        lm[4] = lm[tip] + [0.05, 0.0, 0]
    lm[:, :2] = lm[:, :2] * s + np.array(offset)
    return lm


def test_config_merge():
    cfg = load_config()
    assert cfg["mouse"]["bindings"]["index"] == "left"
    merged = deep_merge(cfg, {"mouse": {"hand": "left"}})
    assert merged["mouse"]["hand"] == "left"
    assert merged["mouse"]["bindings"]["index"] == "left"


def test_one_euro_smooths_noise():
    f = OneEuroFilter(min_cutoff=1.0, beta=0.0)
    rng = np.random.default_rng(0)
    out = [f(np.array([0.5 + rng.normal(0, 0.01)]), t / 30) for t in range(200)]
    assert np.std(out[50:]) < 0.005


def test_pinch_hysteresis_and_events():
    an = HandAnalyzer(load_config()["gestures"])
    f = an.update("Right", make_hand(pinch="index"), ASPECT)
    assert f.pinches["index"] and "index" in f.pressed
    f = an.update("Right", make_hand(pinch="index"), ASPECT)
    assert f.pinches["index"] and not f.pressed
    f = an.update("Right", make_hand(), ASPECT)
    assert not f.pinches["index"] and "index" in f.released


def test_curl_open_vs_fist():
    an = HandAnalyzer(load_config()["gestures"])
    assert an.update("Left", make_hand(open_hand=True), ASPECT).curl < 0.2
    assert an.update("Left", make_hand(open_hand=False), ASPECT).curl > 0.8


def test_deadzone():
    assert apply_deadzone(0.05, 0.0, 0.1) == (0.0, 0.0)
    x, y = apply_deadzone(1.0, 0.0, 0.1)
    assert x == pytest.approx(1.0) and y == 0.0


def _feat(label, palm, size=0.1, pinches=None, curl=0.0):
    return HandFeatures(label=label, palm=np.array(palm), size=size, curl=curl,
                        pinches=pinches or {})


def test_gamepad_stick_anchor_and_direction():
    m = GamepadMapper(load_config()["gamepad"], ASPECT)
    m.update({"Left": _feat("Left", [0.3, 0.5])})               # ancora
    s = m.update({"Left": _feat("Left", [0.3, 0.4])})           # mano verso l'alto
    assert s.ly > 0.9 and abs(s.lx) < 1e-6
    s = m.update({"Left": _feat("Left", [0.4, 0.5])})           # mano a destra
    assert s.lx > 0.9
    s = m.update({})                                            # mano persa -> ricentra
    m.update({"Left": _feat("Left", [0.4, 0.5])})
    assert m.update({"Left": _feat("Left", [0.4, 0.5])}).lx == 0.0


def test_gamepad_buttons_and_trigger():
    m = GamepadMapper(load_config()["gamepad"], ASPECT)
    s = m.update({"Right": _feat("Right", [0.6, 0.5], pinches={"index": True}, curl=1.0)})
    assert "A" in s.buttons and s.rt == pytest.approx(1.0)


def test_mouse_mapping_click_and_drag():
    mouse = NullMouseBackend((1000, 500))
    cfg = deep_merge(load_config()["mouse"], {"motion": "absolute"})
    mm = MouseMapper(cfg, mouse)
    x0, y0, x1, y1 = mm.region
    f = _feat("Right", [(x0 + x1) / 2, (y0 + y1) / 2])
    mm.update({"Right": f}, 0.0)
    assert mouse.position() == pytest.approx((500, 250), abs=1)

    f = _feat("Right", [x0, y0], pinches={"index": True})
    f.pressed = {"index"}
    mm.update({"Right": f}, 1.0)
    assert ("press", "left") in mouse.events
    assert mouse.position() == pytest.approx((500, 250), abs=1)   # congelato subito dopo il pinch

    mm.update({}, 2.0)                                          # mano persa -> rilascia
    assert mouse.events[-1] == ("release", "left")


def _anchor_mapper(size=(1600, 900)):
    mouse = NullMouseBackend(size)
    mouse.position_ = (300, 200)
    cfg = deep_merge(load_config()["mouse"], {"motion": "anchor"})
    return mouse, MouseMapper(cfg, mouse)


def _run(mm, palm, frames, t0=0.0, curl=0.0, fps=30):
    t = t0
    for _ in range(frames):
        mm.update({"Right": _feat("Right", palm, curl=curl)}, t)
        t += 1 / fps
    return t


def test_anchor_entry_keeps_cursor_in_place():
    mouse, mm = _anchor_mapper()
    _run(mm, [0.4, 0.6], 20)
    assert mouse.position() == pytest.approx((300, 200), abs=2)


def test_anchor_fist_centers_then_hand_size_rect_spans_screen():
    mouse, mm = _anchor_mapper()
    t = _run(mm, [0.5, 0.5], 5, curl=1.0)                     # pugno -> centro
    assert mouse.position() == (800, 450) and mm.recentering
    t = _run(mm, [0.5, 0.5], 10, t0=t)                        # mano aperta: resta al centro
    assert mouse.position() == pytest.approx((800, 450), abs=1)
    # mezza "mano" (size 0.1, span 1) a destra = bordo destro dello schermo
    _run(mm, [0.55, 0.5], 60, t0=t)
    x, y = mouse.position()
    assert x == pytest.approx(1599, abs=3) and y == pytest.approx(450, abs=1)
    x0, y0, x1, y1 = mm.current_region()
    assert x1 - x0 == pytest.approx(0.1) and (y1 - y0) == pytest.approx(0.1 * 900 / 1600)


def test_anchor_smoothing_holds_still_on_jitter():
    mouse, mm = _anchor_mapper()
    t = _run(mm, [0.5, 0.5], 5, curl=1.0)
    t = _run(mm, [0.5, 0.5], 10, t0=t)
    rng = np.random.default_rng(1)
    xs = []
    for _ in range(60):
        mm.update({"Right": _feat("Right", [0.5 + rng.normal(0, 0.0005), 0.5])}, t)
        t += 1 / 30
        xs.append(mouse.position()[0])
    assert np.std(xs[10:]) < 4          # senza filtro sarebbe ~8 px
