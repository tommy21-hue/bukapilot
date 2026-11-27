import numpy as np

from openpilot.common.realtime import DT_CTRL
from cereal import log
from openpilot.selfdrive.controls.lib.stop_alert import (
  StopAlert, model_plans_stop, stop_alert_event, MODEL_PLAN_LEN, STOP_ALERT_ON_TIME, STOP_ALERT_OFF_TIME,
)
from openpilot.selfdrive.modeld.constants import ModelConstants

T = list(ModelConstants.T_IDXS)
assert len(T) == MODEL_PLAN_LEN


def plan_stopping_at(t_stop, v0=15.0):
  """Planned speed that falls linearly from v0 to 0 at t_stop, then stays stopped."""
  return [max(v0 * (1 - t / t_stop), 0.0) for t in T]


CRUISE_PLAN = [15.0] * MODEL_PLAN_LEN
STOP_PLAN = plan_stopping_at(4.0)
ON_FRAMES = int(np.ceil(STOP_ALERT_ON_TIME / DT_CTRL)) + 1
OFF_FRAMES = int(np.ceil(STOP_ALERT_OFF_TIME / DT_CTRL)) + 1


def run(sa, frames, **kw):
  args = dict(toggle_on=True, engaged=True, v_ego=15.0, a_ego=0.0, brake_pressed=False,
              lead_status=False, model_valid=True, velocity_x=STOP_PLAN, t=T)
  args.update(kw)
  out = False
  for _ in range(frames):
    out = sa.update(**args)
  return out


class TestModelPlansStop:
  def test_stop_within_horizon(self):
    assert model_plans_stop(plan_stopping_at(4.0), T)

  def test_stop_beyond_horizon(self):
    assert not model_plans_stop(plan_stopping_at(9.0), T)

  def test_cruising(self):
    assert not model_plans_stop(CRUISE_PLAN, T)

  def test_missing_model_output(self):
    assert not model_plans_stop([], [])


class TestStopAlert:
  def test_alerts_when_stop_planned_and_not_slowing(self):
    assert run(StopAlert(), ON_FRAMES)

  def test_needs_condition_to_hold(self):
    # a single-frame model blip should not chime
    assert not run(StopAlert(), 1)

  def test_toggle_off_never_alerts(self):
    assert not run(StopAlert(), ON_FRAMES * 3, toggle_on=False)

  def test_not_engaged_never_alerts(self):
    assert not run(StopAlert(), ON_FRAMES * 3, engaged=False)

  def test_quiet_with_lead_car(self):
    assert not run(StopAlert(), ON_FRAMES * 3, lead_status=True)

  def test_quiet_when_already_slowing(self):
    assert not run(StopAlert(), ON_FRAMES * 3, a_ego=-1.0)

  def test_quiet_when_braking(self):
    assert not run(StopAlert(), ON_FRAMES * 3, brake_pressed=True)

  def test_quiet_at_low_speed(self):
    assert not run(StopAlert(), ON_FRAMES * 3, v_ego=3.0)

  def test_quiet_when_model_invalid(self):
    assert not run(StopAlert(), ON_FRAMES * 3, model_valid=False)

  def test_quiet_when_cruising(self):
    assert not run(StopAlert(), ON_FRAMES * 3, velocity_x=CRUISE_PLAN)

  def test_brake_clears_alert_immediately(self):
    sa = StopAlert()
    assert run(sa, ON_FRAMES)
    assert not run(sa, 1, brake_pressed=True)

  def test_holds_briefly_through_model_flicker(self):
    sa = StopAlert()
    assert run(sa, ON_FRAMES)
    # model drops the stop for a moment: alert stays (no repeat chime) ...
    assert run(sa, 5, velocity_x=CRUISE_PLAN)
    # ... and clears once the stop has been gone long enough
    assert not run(sa, OFF_FRAMES, velocity_x=CRUISE_PLAN)

  def test_disengage_clears_alert(self):
    sa = StopAlert()
    assert run(sa, ON_FRAMES)
    assert not run(sa, 1, engaged=False)


def test_silent_unless_sound_setting_on():
  assert stop_alert_event(False) == log.OnroadEvent.EventName.stopAheadBrake
  assert stop_alert_event(True) == log.OnroadEvent.EventName.stopAheadBrakeSound
