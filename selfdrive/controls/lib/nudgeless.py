"""Nudgeless lane change (my-mods, Param NudgelessLaneChange, off by default).

With the toggle on and the existing Auto Lane Change (IsAlcEnabled) on:
  * at or above 60 km/h, a lane change starts without a steering-wheel nudge once the blinker has
    been on for 1 s with the car's own blind spot monitor (BSM) clear on that side the whole time;
  * below 60 km/h the stock behaviour is unchanged (a nudge is still needed);
  * if BSM sees a car on that side while the car is moving across, the lane change is cancelled and
    a take-over alert is shown. It won't restart until the blinker is switched off and on again.

Steering still goes through the stock lateral controller and the car port's steering limits; this
only decides when the model is asked to change lanes.
One automatic lane change per blinker: holding the blinker after a lane change needs a nudge for the next.

Idea from FrogPilot's nudgeless lane change (../ref-frogpilot, selfdrive/controls/lib/desire_helper.py),
Copyright (c) 2018, Comma.ai, Inc., MIT licensed. Written fresh for bukapilot; no code copied.
"""
from cereal import log
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

NUDGELESS_MIN_SPEED = 60 * CV.KPH_TO_MS
NUDGELESS_DELAY = 1.0  # s of blinker with BSM clear before the lane change starts


def nudgeless_eligible(enabled: bool, v_ego: float) -> bool:
  return enabled and v_ego >= NUDGELESS_MIN_SPEED


class NudgelessTimer:
  """Counts how long the blinker has been on with BSM clear and speed high enough. Runs at model rate."""
  def __init__(self, dt: float = DT_MDL):
    self.frames = 0
    self.delay_frames = round(NUDGELESS_DELAY / dt)

  def reset(self):
    self.frames = 0

  def update(self, enabled: bool, v_ego: float, blindspot: bool) -> bool:
    """Returns True once the lane change may start without a nudge."""
    if nudgeless_eligible(enabled, v_ego) and not blindspot:
      self.frames += 1
    else:
      self.frames = 0  # BSM must be clear for the whole delay, not just at the end
    return self.frames >= self.delay_frames


class NudgelessMonitor:
  """selfdrived side (100 Hz). Mirrors DesireHelper's nudgeless state for the on-screen alerts:
  - aborted: True on the frame DesireHelper cancels a lane change because of BSM
  - used: a lane change already started during this blinker, so the next one needs a nudge
  """
  def __init__(self):
    self.prev_state = LaneChangeState.off
    self.prev_direction = LaneChangeDirection.none
    self.used = False

  def update(self, enabled: bool, one_blinker: bool, lc_state, lc_direction,
             left_blindspot: bool, right_blindspot: bool) -> bool:
    blindspot = ((self.prev_direction == LaneChangeDirection.left and left_blindspot) or
                 (self.prev_direction == LaneChangeDirection.right and right_blindspot))
    aborted = (enabled and blindspot and
               self.prev_state == LaneChangeState.laneChangeStarting and
               lc_state == LaneChangeState.off)

    if not one_blinker:
      self.used = False
    elif lc_state == LaneChangeState.laneChangeStarting:
      self.used = True

    self.prev_state = lc_state
    self.prev_direction = lc_direction
    return aborted

  def show_nudgeless_alert(self, enabled: bool, v_ego: float) -> bool:
    """While waiting in preLaneChange: will this lane change start by itself?"""
    return nudgeless_eligible(enabled, v_ego) and not self.used
