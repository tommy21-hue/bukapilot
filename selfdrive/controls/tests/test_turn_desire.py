from types import SimpleNamespace

import pytest
from cereal import log
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_CTRL
import openpilot.selfdrive.controls.lib.desire_helper as dh_module
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper
from openpilot.selfdrive.controls.lib.turn_desire import TurnDesire, TooTightDetector, clamp_turn_speed, TOO_TIGHT_TIME

LaneChangeState = log.LaneChangeState
KPH = CV.KPH_TO_MS


class TestTurnDesire:
  def test_below_set_speed_turns(self):
    td = TurnDesire()
    assert td.update(True, 25, True, False, 20 * KPH) == log.Desire.turnLeft
    assert td.update(True, 25, False, True, 20 * KPH) == log.Desire.turnRight

  def test_above_set_speed_no_turn(self):
    assert TurnDesire().update(True, 25, True, False, 27 * KPH) == log.Desire.none

  def test_off_without_blinker_or_toggle(self):
    assert TurnDesire().update(True, 25, False, False, 10 * KPH) == log.Desire.none
    assert TurnDesire().update(True, 25, True, True, 10 * KPH) == log.Desire.none  # hazards
    assert TurnDesire().update(False, 25, True, False, 10 * KPH) == log.Desire.none

  def test_hysteresis_when_accelerating_out(self):
    td = TurnDesire()
    td.update(True, 25, True, False, 20 * KPH)
    assert td.update(True, 25, True, False, 28 * KPH) == log.Desire.turnLeft   # within +5 km/h
    assert td.update(True, 25, True, False, 31 * KPH) == log.Desire.none       # beyond
    assert td.update(True, 25, True, False, 28 * KPH) == log.Desire.none       # doesn't re-latch above set speed

  def test_blinker_off_resets(self):
    td = TurnDesire()
    td.update(True, 25, True, False, 20 * KPH)
    td.update(True, 25, False, False, 20 * KPH)
    assert td.update(True, 25, True, False, 28 * KPH) == log.Desire.none

  def test_speed_setting_clamped(self):
    assert clamp_turn_speed(10) == 20
    assert clamp_turn_speed(45) == 30
    assert clamp_turn_speed(None) == 25
    assert clamp_turn_speed("27") == 27


class TestTooTight:
  ON = round(TOO_TIGHT_TIME / DT_CTRL)

  def run(self, det, frames, **kw):
    args = dict(turning=True, lat_active=True, v_ego=4.0, requested_deg=60., allowed_deg=60.)
    args.update(kw)
    return [det.update(**args) for _ in range(frames)][-1]

  def test_near_max_angle_alerts(self):
    assert self.run(TooTightDetector(120., DT_CTRL), self.ON, requested_deg=-118., allowed_deg=-118.)

  def test_car_capping_request_alerts(self):
    assert self.run(TooTightDetector(120., DT_CTRL), self.ON, requested_deg=100., allowed_deg=90.)

  def test_gentle_turn_quiet(self):
    assert not self.run(TooTightDetector(120., DT_CTRL), self.ON * 5, requested_deg=60., allowed_deg=58.)

  def test_needs_to_last(self):
    assert not self.run(TooTightDetector(120., DT_CTRL), self.ON - 1, requested_deg=119., allowed_deg=119.)

  def test_quiet_when_stopped_inactive_or_unknown_car(self):
    assert not self.run(TooTightDetector(120., DT_CTRL), self.ON * 2, requested_deg=119., v_ego=0.)
    assert not self.run(TooTightDetector(120., DT_CTRL), self.ON * 2, requested_deg=119., lat_active=False)
    assert not self.run(TooTightDetector(None, DT_CTRL), self.ON * 2, requested_deg=119., allowed_deg=50.)


class FakeParams:
  values: dict = {}

  def get_bool(self, key):
    return self.values.get(key, False)


@pytest.fixture
def make_dh(monkeypatch):
  def _make(turn_desires=True, speed=25):
    FakeParams.values = {"IsAlcEnabled": True, "NavDesiresAllowed": False, "TurnDesires": turn_desires}
    monkeypatch.setattr(dh_module, "Params", FakeParams)
    monkeypatch.setattr(dh_module, "get_bool_safe", lambda key, params=None: FakeParams.values.get(key, False))
    monkeypatch.setattr(dh_module, "get_int_safe", lambda key, default, params=None: speed)
    return DesireHelper()
  return _make


def cs(v, left=False, right=False, torque=0.0):
  return SimpleNamespace(vEgo=v, leftBlinker=left, rightBlinker=right, leftBlindspot=False, rightBlindspot=False,
                         lkaDisabled=False, steeringPressed=abs(torque) > 0, steeringTorque=torque)


class TestDesireHelperTurns:
  def test_turn_desire_sent_below_set_speed(self, make_dh):
    dh = make_dh()
    for _ in range(10):
      dh.update(cs(15 * KPH, left=True), True, 1.0)
    assert dh.desire == log.Desire.turnLeft
    assert dh.lane_change_state == LaneChangeState.off

  def test_needs_lateral_active(self, make_dh):
    dh = make_dh()
    dh.update(cs(15 * KPH, right=True), False, 1.0)
    assert dh.desire == log.Desire.none

  def test_toggle_off_is_stock(self, make_dh):
    dh = make_dh(turn_desires=False)
    for _ in range(10):
      dh.update(cs(15 * KPH, left=True), True, 1.0)
    assert dh.desire == log.Desire.none

  def test_lane_change_above_set_speed_unchanged(self, make_dh):
    dh = make_dh()
    dh.update(cs(50 * KPH, left=True), True, 1.0)
    dh.update(cs(50 * KPH, left=True, torque=2.0), True, 1.0)
    assert dh.lane_change_state == LaneChangeState.laneChangeStarting
    assert dh.desire == log.Desire.laneChangeLeft

  def test_adjustable_speed(self, make_dh):
    dh = make_dh(speed=20)
    dh.update(cs(22 * KPH, left=True), True, 1.0)
    assert dh.desire == log.Desire.none
    dh = make_dh(speed=30)
    dh.update(cs(28 * KPH, left=True), True, 1.0)
    assert dh.desire == log.Desire.turnLeft
