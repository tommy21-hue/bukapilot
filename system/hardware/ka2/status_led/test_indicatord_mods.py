"""my-mods light bar behaviour in indicatord (KA2). The LED hardware and messaging are faked."""
from types import SimpleNamespace

import pytest

import openpilot.system.hardware.ka2.status_led.indicatord as ind


class FakeSubMaster:
  def __init__(self, services, **kwargs):
    self.data = {}
    self.updated = dict.fromkeys(services, False)
    self.alive = dict.fromkeys(services, True)

  def __getitem__(self, key):
    return self.data[key]

  def update(self, timeout=0):
    pass


@pytest.fixture
def svc(monkeypatch):
  calls = []
  monkeypatch.setattr(ind, "set_led", lambda *a, **k: calls.append((a, k)))
  monkeypatch.setattr(ind, "messaging", SimpleNamespace(SubMaster=FakeSubMaster))
  s = ind.AlertLEDService(overrides=ind.MOD_LED_OVERRIDES)
  s.led_calls = calls
  return s


class TestStopAlertBars:
  @pytest.mark.parametrize("name", ["stopAheadBrake/warning", "stopAheadBrakeSound/warning"])
  def test_stop_alert_red_slow_blink(self, svc, name):
    assert svc._classify_key(name, True) == ("RED", "blink", "slow")

  def test_kommu_mapping_unchanged_otherwise(self, svc):
    assert svc._classify_key("", True) == ("GREEN", "solid", None)
    assert svc._classify_key("laneChange/warning", True) == ("ORANGE", "blink", "fast")
    assert svc._classify_key("steerTempUnavailable/immediateDisable", True) == ("RED", "blink", "fast")
    assert svc._classify_key("startup/permanent", False) == ("BLUE", "solid", None)


# ---------- ShowBlindspot ----------
AMBER = ind.BSM_AMBER_HEX


class TestBarColors:
  def test_left_bsm_over_green(self):
    assert ind.bsm_bar_colors("GREEN", "solid", True, False, False) == (AMBER, "GREEN")

  def test_right_bsm_over_green(self):
    assert ind.bsm_bar_colors("GREEN", "solid", False, True, False) == ("GREEN", AMBER)

  def test_swap_sides(self):
    assert ind.bsm_bar_colors("GREEN", "solid", True, False, True) == ("GREEN", AMBER)

  def test_both_sides(self):
    assert ind.bsm_bar_colors("BLUE", "solid", True, True, False) == (AMBER, AMBER)

  @pytest.mark.parametrize("color,mode", [("ORANGE", "blink"), ("RED", "blink"), ("RED", "solid"), ("YELLOW", "solid")])
  def test_kommu_warnings_and_faults_win(self, color, mode):
    assert ind.bsm_bar_colors(color, mode, True, True, False) == (color, color)

  def test_no_bsm_is_stock(self):
    assert ind.bsm_bar_colors("GREEN", "solid", False, False, False) == ("GREEN", "GREEN")


def test_hold():
  h = ind.BlindspotHold()
  assert h.update(True, 10.0)
  assert h.update(False, 10.0 + ind.BSM_HOLD_S / 2)
  assert not h.update(False, 10.0 + ind.BSM_HOLD_S + 0.01)


def step(svc, monkeypatch, now, alert="", active=True, left=False, right=False, show=True):
  """Run exactly one iteration of the real run_forever loop."""
  monkeypatch.setattr(ind, "get_bool_safe", lambda key, params=None: show if key == "ShowBlindspot" else False)
  monkeypatch.setattr(ind.time, "monotonic", lambda: now)
  monkeypatch.setattr(svc, "_agnos_update_in_progress", lambda: False)
  svc._last_param_t = -10.  # re-read params this step
  sm = svc._sm
  sm.data = {"selfdriveState": SimpleNamespace(active=active, alertType=alert),
             "carState": SimpleNamespace(leftBlindspot=left, rightBlindspot=right)}
  sm.updated = {"selfdriveState": True, "carState": True, "driverCameraState": False}
  sm.update = lambda timeout=0: svc._stop.set()
  svc._stop.clear()
  svc.led_calls.clear()
  svc.run_forever()
  return svc.led_calls[-1][0][:2] if svc.led_calls else None  # (a colour, b colour) passed to set_led


class TestLoop:
  def test_engaged_left_bsm_then_clear(self, svc, monkeypatch):
    assert step(svc, monkeypatch, 100.) == ("GREEN", None)               # stock: both bars green
    assert step(svc, monkeypatch, 100.1, left=True) == (AMBER, "GREEN")  # left bar amber
    assert step(svc, monkeypatch, 100.2) is None                         # held (no flicker, no LED restart)
    assert step(svc, monkeypatch, 100.2 + ind.BSM_HOLD_S) == ("GREEN", None)  # back to Kommu's normal

  def test_toggle_off_is_stock(self, svc, monkeypatch):
    step(svc, monkeypatch, 100., show=False)
    assert step(svc, monkeypatch, 100.1, left=True, right=True, show=False) is None  # unchanged

  def test_stop_alert_beats_bsm(self, svc, monkeypatch):
    step(svc, monkeypatch, 100.)
    assert step(svc, monkeypatch, 100.1, alert="stopAheadBrake/warning", left=True) == ("RED", None)

  def test_kommu_take_over_beats_bsm(self, svc, monkeypatch):
    step(svc, monkeypatch, 100.)
    assert step(svc, monkeypatch, 100.1, alert="steerTempUnavailable/immediateDisable", right=True) == ("RED", None)
