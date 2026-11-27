"""Turn desires (my-mods, Params TurnDesires + TurnDesireSpeed, off by default).

Below a set low speed (default 25 km/h, adjustable 20-30 km/h) the blinker asks the driving model to
take the turn (Desire.turnLeft / turnRight) instead of starting a lane change, and steering stays on
while the blinker is on (stock bukapilot switches steering off with the blinker below 32 km/h).

Steering still goes through the stock lateral controller and the car port's steering limits, which
are NOT changed. On the BYD Seal those allow at most 120 deg of steering-wheel angle, roughly a 22 m
turn radius, so many intersection turns are too tight: TooTightDetector raises a take-over alert.

Idea from sunnypilot's lane turn desire; written fresh for bukapilot, no sunnypilot code copied.
"""
from cereal import log
from openpilot.common.constants import CV

TURN_DESIRE_SPEED_DEFAULT = 25  # km/h
TURN_DESIRE_SPEED_MIN = 20
TURN_DESIRE_SPEED_MAX = 30
TURN_DESIRE_SPEED_OPTIONS = (20, 22, 25, 28, 30)
TURN_DESIRE_HYSTERESIS = 5 * CV.KPH_TO_MS  # keep turning until this much above the set speed (accelerating out)

# "Too tight": the car port is limiting the steering we asked for. Angle cars only (BYD).
TOO_TIGHT_ANGLE_MARGIN = 5.      # deg below the car's max steering angle
TOO_TIGHT_LIMITED_DEG = 5.       # deg between requested and allowed angle
TOO_TIGHT_TIME = 0.3             # s it must last before alerting
TOO_TIGHT_MIN_SPEED = 1.0        # m/s; steering is inactive at standstill


def clamp_turn_speed(kph) -> int:
  try:
    kph = int(kph)
  except (TypeError, ValueError):
    return TURN_DESIRE_SPEED_DEFAULT
  return max(TURN_DESIRE_SPEED_MIN, min(TURN_DESIRE_SPEED_MAX, kph))


class TurnDesire:
  """Decides whether the blinker means "turn" right now. Same logic runs in modeld and selfdrived."""
  def __init__(self):
    self.active = False

  def update(self, enabled: bool, set_speed_kph, left_blinker: bool, right_blinker: bool, v_ego: float):
    """Returns log.Desire.turnLeft / turnRight, or log.Desire.none."""
    one_blinker = left_blinker != right_blinker
    if not enabled or not one_blinker:
      self.active = False
      return log.Desire.none

    set_speed = clamp_turn_speed(set_speed_kph) * CV.KPH_TO_MS
    if v_ego < set_speed:
      self.active = True
    elif v_ego > set_speed + TURN_DESIRE_HYSTERESIS:
      self.active = False

    if not self.active:
      return log.Desire.none
    return log.Desire.turnLeft if left_blinker else log.Desire.turnRight


class TooTightDetector:
  """selfdrived side (100 Hz): during a turn desire, is the car port capping the steering we want?"""
  def __init__(self, max_angle_deg: float | None, dt: float):
    self.max_angle = max_angle_deg  # None for cars without an angle limit we know: never alert
    self.frames = 0
    self.on_frames = round(TOO_TIGHT_TIME / dt)

  def update(self, turning: bool, lat_active: bool, v_ego: float, requested_deg: float, allowed_deg: float) -> bool:
    limited = False
    if self.max_angle is not None and turning and lat_active and v_ego > TOO_TIGHT_MIN_SPEED:
      at_max = abs(requested_deg) >= self.max_angle - TOO_TIGHT_ANGLE_MARGIN
      capped = abs(requested_deg - allowed_deg) > TOO_TIGHT_LIMITED_DEG
      limited = at_max or capped
    self.frames = self.frames + 1 if limited else 0
    return self.frames >= self.on_frames
