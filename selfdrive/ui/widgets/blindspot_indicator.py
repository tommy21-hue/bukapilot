"""Blind spot indicators on the onroad screen (my-mods, Param ShowBlindspot, off by default).

Draws a glow on the left/right edge of the camera view while the car's own blind spot monitor (BSM)
reports a vehicle on that side: amber normally, red if the blinker is on toward that side.
Display only: reads carState.leftBlindspot / rightBlindspot, changes nothing else.
"""
import time

import pyray as rl

from openpilot.common.mod_params import get_bool_safe
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import Widget

BSM_AMBER = (255, 170, 0)
BSM_RED = (230, 40, 40)
BSM_MAX_ALPHA = 200
BSM_WIDTH_FRAC = 0.09     # glow width as a fraction of the camera view width
BSM_FADE_PER_S = 6.0      # alpha 0->1 in ~0.17 s, so a flickering signal doesn't strobe
PARAM_REFRESH_S = 1.0


class BlindspotIndicator(Widget):
  def __init__(self):
    super().__init__()
    self.set_enabled(False)  # display only: never takes touches meant for the road view
    self._show = get_bool_safe("ShowBlindspot", ui_state.params)
    self._last_param_t = time.monotonic()
    self._last_t = time.monotonic()
    self._alpha = {"left": 0.0, "right": 0.0}

  def _update_state(self):
    now = time.monotonic()
    if now - self._last_param_t > PARAM_REFRESH_S:
      self._show = get_bool_safe("ShowBlindspot", ui_state.params)
      self._last_param_t = now

  def _render(self, rect: rl.Rectangle):
    now = time.monotonic()
    dt, self._last_t = min(now - self._last_t, 0.1), now
    if not self._show or not ui_state.started:
      self._alpha = {"left": 0.0, "right": 0.0}
      return

    cs = ui_state.sm['carState']
    for side, detected, blinker in (("left", cs.leftBlindspot, cs.leftBlinker), ("right", cs.rightBlindspot, cs.rightBlinker)):
      target = 1.0 if detected else 0.0
      step = BSM_FADE_PER_S * dt
      a = self._alpha[side]
      self._alpha[side] = min(a + step, target) if target > a else max(a - step, target)
      if self._alpha[side] <= 0.0:
        continue

      r, g, b = BSM_RED if (detected and blinker) else BSM_AMBER
      solid = rl.Color(r, g, b, int(BSM_MAX_ALPHA * self._alpha[side]))
      clear = rl.Color(r, g, b, 0)
      w = int(rect.width * BSM_WIDTH_FRAC)
      if side == "left":
        rl.draw_rectangle_gradient_h(int(rect.x), int(rect.y), w, int(rect.height), solid, clear)
      else:
        rl.draw_rectangle_gradient_h(int(rect.x + rect.width - w), int(rect.y), w, int(rect.height), clear, solid)
