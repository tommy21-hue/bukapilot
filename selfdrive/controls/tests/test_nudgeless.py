from types import SimpleNamespace

import pytest
from cereal import log
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
import openpilot.selfdrive.controls.lib.desire_helper as dh_module
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper
from openpilot.selfdrive.controls.lib.nudgeless import NudgelessTimer, NudgelessMonitor, NUDGELESS_DELAY

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection
DELAY_FRAMES = round(NUDGELESS_DELAY / DT_MDL)
FAST = 70 * CV.KPH_TO_MS
MEDIUM = 50 * CV.KPH_TO_MS  # above stock ALC minimum (32 km/h), below nudgeless minimum (60 km/h)


class FakeParams:
  values: dict = {}

  def get_bool(self, key):
    return self.values.get(key, False)


@pytest.fixture
def make_dh(monkeypatch):
  def _make(nudgeless=True):
    FakeParams.values = {"IsAlcEnabled": True, "NavDesiresAllowed": False, "NudgelessLaneChange": nudgeless}
    monkeypatch.setattr(dh_module, "Params", FakeParams)
    monkeypatch.setattr(dh_module, "get_bool_safe", lambda key, params=None: FakeParams.values.get(key, False))
    return DesireHelper()
  return _make


def cs(v=FAST, left=False, right=False, left_bs=False, right_bs=False, torque=0.0):
  return SimpleNamespace(vEgo=v, leftBlinker=left, rightBlinker=right, leftBlindspot=left_bs, rightBlindspot=right_bs,
                         lkaDisabled=False, steeringPressed=abs(torque) > 0, steeringTorque=torque)


def step(dh, carstate, frames=1, lane_change_prob=1.0):
  for _ in range(frames):
    dh.update(carstate, True, lane_change_prob)
  return dh.lane_change_state


class TestNudgelessTimer:
  def test_ready_after_delay(self):
    t = NudgelessTimer()
    assert not any(t.update(True, FAST, False) for _ in range(DELAY_FRAMES - 1))
    assert t.update(True, FAST, False)

  def test_bsm_restarts_delay(self):
    t = NudgelessTimer()
    for _ in range(DELAY_FRAMES - 1):
      t.update(True, FAST, False)
    t.update(True, FAST, True)
    assert not t.update(True, FAST, False)

  def test_too_slow_or_disabled(self):
    t = NudgelessTimer()
    assert not any(t.update(True, MEDIUM, False) for _ in range(DELAY_FRAMES * 3))
    assert not any(t.update(False, FAST, False) for _ in range(DELAY_FRAMES * 3))


class TestDesireHelperNudgeless:
  def test_starts_after_one_second(self, make_dh):
    dh = make_dh()
    step(dh, cs(left=True))  # off -> preLaneChange
    assert dh.lane_change_state == LaneChangeState.preLaneChange
    assert step(dh, cs(left=True), DELAY_FRAMES - 1) == LaneChangeState.preLaneChange
    assert step(dh, cs(left=True)) == LaneChangeState.laneChangeStarting
    assert dh.desire == log.Desire.laneChangeLeft

  def test_toggle_off_needs_nudge(self, make_dh):
    dh = make_dh(nudgeless=False)
    assert step(dh, cs(right=True), DELAY_FRAMES * 4) == LaneChangeState.preLaneChange
    assert step(dh, cs(right=True, torque=-2.0)) == LaneChangeState.laneChangeStarting

  def test_below_60_needs_nudge(self, make_dh):
    dh = make_dh()
    assert step(dh, cs(v=MEDIUM, left=True), DELAY_FRAMES * 4) == LaneChangeState.preLaneChange
    assert step(dh, cs(v=MEDIUM, left=True, torque=2.0)) == LaneChangeState.laneChangeStarting

  def test_waits_for_blind_spot_to_clear(self, make_dh):
    dh = make_dh()
    assert step(dh, cs(left=True, left_bs=True), DELAY_FRAMES * 4) == LaneChangeState.preLaneChange
    # BSM clears: still needs a full second of clear before starting
    step(dh, cs(left=True))
    assert step(dh, cs(left=True), DELAY_FRAMES - 2) == LaneChangeState.preLaneChange
    assert step(dh, cs(left=True)) == LaneChangeState.laneChangeStarting

  def test_other_side_bsm_does_not_block(self, make_dh):
    dh = make_dh()
    assert step(dh, cs(left=True, right_bs=True), DELAY_FRAMES + 1) == LaneChangeState.laneChangeStarting

  def test_bsm_mid_change_aborts(self, make_dh):
    dh = make_dh()
    assert step(dh, cs(left=True), DELAY_FRAMES + 1) == LaneChangeState.laneChangeStarting
    assert step(dh, cs(left=True, left_bs=True)) == LaneChangeState.off
    assert dh.desire == log.Desire.none
    # stays cancelled while the blinker stays on, even after BSM clears
    assert step(dh, cs(left=True), DELAY_FRAMES * 4) == LaneChangeState.off
    # blinker off then on again: allowed to try again
    step(dh, cs())
    step(dh, cs(left=True))
    assert dh.lane_change_state == LaneChangeState.preLaneChange

  def test_bsm_mid_change_aborts_nudged_change_too(self, make_dh):
    dh = make_dh()
    step(dh, cs(v=MEDIUM, right=True))
    assert step(dh, cs(v=MEDIUM, right=True, torque=-2.0)) == LaneChangeState.laneChangeStarting
    assert step(dh, cs(v=MEDIUM, right=True, right_bs=True)) == LaneChangeState.off

  def test_toggle_off_keeps_stock_mid_change_behaviour(self, make_dh):
    dh = make_dh(nudgeless=False)
    step(dh, cs(left=True))
    assert step(dh, cs(left=True, torque=2.0)) == LaneChangeState.laneChangeStarting
    assert step(dh, cs(left=True, left_bs=True)) == LaneChangeState.laneChangeStarting

  def test_one_automatic_change_per_blinker(self, make_dh):
    dh = make_dh()
    assert step(dh, cs(left=True), DELAY_FRAMES + 1) == LaneChangeState.laneChangeStarting
    # finish the lane change with the blinker still held
    step(dh, cs(left=True), int(2.0 / DT_MDL), lane_change_prob=0.0)
    assert dh.lane_change_state == LaneChangeState.preLaneChange
    # no second automatic change...
    assert step(dh, cs(left=True), DELAY_FRAMES * 4) == LaneChangeState.preLaneChange
    # ...but a nudge still works
    assert step(dh, cs(left=True, torque=2.0)) == LaneChangeState.laneChangeStarting


class TestNudgelessMonitor:
  def test_detects_bsm_abort(self):
    m = NudgelessMonitor()
    assert not m.update(True, True, LaneChangeState.laneChangeStarting, LaneChangeDirection.left, False, False)
    assert m.update(True, True, LaneChangeState.off, LaneChangeDirection.none, True, False)

  def test_normal_finish_is_not_abort(self):
    m = NudgelessMonitor()
    m.update(True, True, LaneChangeState.laneChangeStarting, LaneChangeDirection.left, False, False)
    assert not m.update(True, True, LaneChangeState.laneChangeFinishing, LaneChangeDirection.left, True, False)

  def test_disabled_never_aborts(self):
    m = NudgelessMonitor()
    m.update(False, True, LaneChangeState.laneChangeStarting, LaneChangeDirection.left, False, False)
    assert not m.update(False, True, LaneChangeState.off, LaneChangeDirection.none, True, False)

  def test_used_until_blinker_off(self):
    m = NudgelessMonitor()
    assert m.show_nudgeless_alert(True, FAST)
    m.update(True, True, LaneChangeState.laneChangeStarting, LaneChangeDirection.left, False, False)
    assert not m.show_nudgeless_alert(True, FAST)
    m.update(True, False, LaneChangeState.off, LaneChangeDirection.none, False, False)
    assert m.show_nudgeless_alert(True, FAST)
    assert not m.show_nudgeless_alert(True, MEDIUM)
