"""my-mods ShowBlindspot: render the indicator off-screen and check the pixels at each screen edge."""
from types import SimpleNamespace

import pyray as rl
import pytest

from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.ui_state import ui_state
import openpilot.selfdrive.ui.widgets.blindspot_indicator as bsi

W, H = 400, 200
AMBER = bsi.BSM_AMBER
RED = bsi.BSM_RED


@pytest.fixture(scope="module")
def target():
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_NONE)
  if not rl.is_window_ready():
    gui_app.init_window("test_blindspot_indicator")
  tex = rl.load_render_texture(W, H)
  yield tex
  rl.unload_render_texture(tex)


def draw(target, monkeypatch, show=True, frames=30, **car):
  cs = dict(leftBlindspot=False, rightBlindspot=False, leftBlinker=False, rightBlinker=False)
  cs.update(car)
  monkeypatch.setattr(bsi, "get_bool_safe", lambda key, params=None: show)
  monkeypatch.setattr(ui_state, "started", True)
  monkeypatch.setattr(ui_state, "sm", {"carState": SimpleNamespace(**cs)})
  ind = bsi.BlindspotIndicator()
  ind._last_t -= 1.0  # pretend time has passed so the fade-in completes
  for _ in range(frames):
    rl.begin_texture_mode(target)
    rl.clear_background(rl.BLACK)
    ind._last_t -= 0.05
    ind.render(rl.Rectangle(0, 0, W, H))
    rl.end_texture_mode()
  img = rl.load_image_from_texture(target.texture)
  # render textures are stored upside down; only x matters here
  left = rl.get_image_color(img, 1, H // 2)
  right = rl.get_image_color(img, W - 2, H // 2)
  middle = rl.get_image_color(img, W // 2, H // 2)
  rl.unload_image(img)
  return (left.r, left.g, left.b), (right.r, right.g, right.b), (middle.r, middle.g, middle.b)


def tinted(px, color):
  # dominated by the indicator colour: each channel within 60 of the expected (blended over black, alpha ~200)
  return all(abs(p - c * bsi.BSM_MAX_ALPHA / 255) < 60 for p, c in zip(px, color, strict=True))


def test_left_amber(target, monkeypatch):
  left, right, middle = draw(target, monkeypatch, leftBlindspot=True)
  assert tinted(left, AMBER)
  assert right == (0, 0, 0) and middle == (0, 0, 0)


def test_right_red_with_blinker(target, monkeypatch):
  left, right, _ = draw(target, monkeypatch, rightBlindspot=True, rightBlinker=True)
  assert tinted(right, RED)
  assert left == (0, 0, 0)


def test_nothing_when_clear(target, monkeypatch):
  assert draw(target, monkeypatch) == ((0, 0, 0),) * 3


def test_nothing_when_toggle_off(target, monkeypatch):
  assert draw(target, monkeypatch, show=False, leftBlindspot=True, rightBlindspot=True) == ((0, 0, 0),) * 3
