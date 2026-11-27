"""StopAlert: warn the driver when the driving model plans a stop ahead but the car isn't slowing.

Alert only. This never sends any speed, brake or steering command; it just tells selfdrived
whether to show the "Stop ahead - brake" alert.

Why not modelV2.action.shouldStop? That flag only turns on when the model expects the car to be
stopped within about one second, which is too late to be a useful warning. Instead we look at the
model's planned speed over the next few seconds (modelV2.velocity), the same signal that
conditional_experimental_mode.py uses.
"""
import numpy as np

from cereal import log
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_CTRL

STOP_ALERT_HORIZON_S = 6.0           # look this far ahead in the model's plan
STOP_ALERT_PLAN_STOP_SPEED = 1.0     # m/s; planned speed below this counts as "stopped"
STOP_ALERT_MIN_SPEED = 15 * CV.KPH_TO_MS   # don't alert when already crawling
STOP_ALERT_NOT_SLOWING_ACCEL = -0.5  # m/s^2; car decelerating harder than this counts as slowing
STOP_ALERT_ON_TIME = 0.3             # s the condition must hold before alerting (filters model flicker)
STOP_ALERT_OFF_TIME = 0.5            # s the condition must be gone before the alert clears (no repeat chimes)
MODEL_PLAN_LEN = 33                  # ModelConstants.IDX_N


def stop_alert_event(sound_on: bool):
  """Silent unless the StopAlertSound setting is on."""
  return log.OnroadEvent.EventName.stopAheadBrakeSound if sound_on else log.OnroadEvent.EventName.stopAheadBrake


def model_plans_stop(velocity_x, t, horizon_s=STOP_ALERT_HORIZON_S, stop_speed=STOP_ALERT_PLAN_STOP_SPEED) -> bool:
  """True if the model's planned speed drops below stop_speed within horizon_s seconds."""
  if len(velocity_x) != MODEL_PLAN_LEN or len(t) != MODEL_PLAN_LEN:
    return False  # model output missing or not ready yet
  v = np.asarray(velocity_x)
  ts = np.asarray(t)
  return bool(np.any(v[ts <= horizon_s] < stop_speed))


class StopAlert:
  def __init__(self):
    self.active = False
    self._on_frames = 0
    self._off_frames = 0

  def reset(self):
    self.active = False
    self._on_frames = 0
    self._off_frames = 0

  def update(self, toggle_on: bool, engaged: bool, v_ego: float, a_ego: float, brake_pressed: bool,
             lead_status: bool, model_valid: bool, velocity_x, t) -> bool:
    """Call once per selfdrived frame (100 Hz). Returns True while the alert should show."""
    if not toggle_on or not engaged:
      self.reset()
      return False

    raw = (model_valid and
           v_ego > STOP_ALERT_MIN_SPEED and
           not brake_pressed and
           a_ego > STOP_ALERT_NOT_SLOWING_ACCEL and
           # The model also plans to stop behind a stopped car. Stock ACC already handles that,
           # so stay quiet whenever a car ahead is detected.
           not lead_status and
           model_plans_stop(velocity_x, t))

    if raw:
      self._on_frames += 1
      self._off_frames = 0
      if self._on_frames * DT_CTRL >= STOP_ALERT_ON_TIME:
        self.active = True
    else:
      self._on_frames = 0
      self._off_frames += 1
      # Driver braking or slowing clears the alert straight away; otherwise wait a moment
      if brake_pressed or a_ego <= STOP_ALERT_NOT_SLOWING_ACCEL or self._off_frames * DT_CTRL >= STOP_ALERT_OFF_TIME:
        self.active = False

    return self.active
