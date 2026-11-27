import numpy as np

from cereal import log
from openpilot.common.params import Params
from openpilot.common.realtime import DT_DMON
from openpilot.selfdrive.monitoring.helpers import DriverMonitoring, DRIVER_MONITOR_SETTINGS, DM_WIDER_YAW_THRESHOLD, \
  DM_WIDER_YAW_THRESHOLD_SLACK, DM_EXTRA_TIME_MAX
from openpilot.system.hardware import HARDWARE

EventName = log.OnroadEvent.EventName
dm_settings = DRIVER_MONITOR_SETTINGS(device_type=HARDWARE.get_device_type())

TEST_TIMESPAN = 120  # seconds
DISTRACTED_SECONDS_TO_ORANGE = dm_settings._DISTRACTED_TIME - dm_settings._DISTRACTED_PROMPT_TIME_TILL_TERMINAL + 1
DISTRACTED_SECONDS_TO_RED = dm_settings._DISTRACTED_TIME + 1
INVISIBLE_SECONDS_TO_ORANGE = dm_settings._AWARENESS_TIME - dm_settings._AWARENESS_PROMPT_TIME_TILL_TERMINAL + 1
INVISIBLE_SECONDS_TO_RED = dm_settings._AWARENESS_TIME + 1

def make_msg(face_detected, distracted=False, model_uncertain=False, yaw=0.):
  ds = log.DriverStateV2.new_message()
  ds.leftDriverData.faceOrientation = [0., yaw, 0.]
  ds.leftDriverData.facePosition = [0., 0.]
  ds.leftDriverData.faceProb = 1. * face_detected
  ds.leftDriverData.leftEyeProb = 1.
  ds.leftDriverData.rightEyeProb = 1.
  ds.leftDriverData.leftBlinkProb = 1. * distracted
  ds.leftDriverData.rightBlinkProb = 1. * distracted
  ds.leftDriverData.faceOrientationStd = [1.*model_uncertain, 1.*model_uncertain, 1.*model_uncertain]
  ds.leftDriverData.facePositionStd = [1.*model_uncertain, 1.*model_uncertain]
  # TODO: test both separately when e2e is used
  ds.leftDriverData.phoneProb = 0.
  return ds


# driver state from neural net, 10Hz
msg_NO_FACE_DETECTED = make_msg(False)
msg_ATTENTIVE = make_msg(True)
msg_DISTRACTED = make_msg(True, distracted=True)
msg_ATTENTIVE_UNCERTAIN = make_msg(True, model_uncertain=True)
msg_DISTRACTED_UNCERTAIN = make_msg(True, distracted=True, model_uncertain=True)
msg_DISTRACTED_BUT_SOMEHOW_UNCERTAIN = make_msg(True, distracted=True, model_uncertain=dm_settings._POSESTD_THRESHOLD*1.5)

# driver interaction with car
car_interaction_DETECTED = True
car_interaction_NOT_DETECTED = False

# some common state vectors
always_no_face = [msg_NO_FACE_DETECTED] * int(TEST_TIMESPAN / DT_DMON)
always_attentive = [msg_ATTENTIVE] * int(TEST_TIMESPAN / DT_DMON)
always_distracted = [msg_DISTRACTED] * int(TEST_TIMESPAN / DT_DMON)
always_true = [True] * int(TEST_TIMESPAN / DT_DMON)
always_false = [False] * int(TEST_TIMESPAN / DT_DMON)

class TestMonitoring:
  def _run_seq(self, msgs, interaction, engaged, standstill, settings=None):
    DM = DriverMonitoring(settings=settings)
    events = []
    for idx in range(len(msgs)):
      DM._update_states(msgs[idx], [0, 0, 0], 0, engaged[idx], standstill[idx])
      # cal_rpy and car_speed don't matter here

      # evaluate events at 10Hz for tests
      DM._update_events(interaction[idx], engaged[idx], standstill[idx], 0, 0)
      events.append(DM.current_events)
    assert len(events) == len(msgs), f"got {len(events)} for {len(msgs)} driverState input msgs"
    return events, DM

  def _assert_no_events(self, events):
    assert all(not len(e) for e in events)

  # engaged, driver is attentive all the time
  def test_fully_aware_driver(self):
    events, _ = self._run_seq(always_attentive, always_false, always_true, always_false)
    self._assert_no_events(events)

  # engaged, driver is distracted and does nothing
  def test_fully_distracted_driver(self):
    events, d_status = self._run_seq(always_distracted, always_false, always_true, always_false)
    assert len(events[int((d_status.settings._DISTRACTED_TIME-d_status.settings._DISTRACTED_PRE_TIME_TILL_TERMINAL)/2/DT_DMON)]) == 0
    assert events[int((d_status.settings._DISTRACTED_TIME-d_status.settings._DISTRACTED_PRE_TIME_TILL_TERMINAL + \
                    ((d_status.settings._DISTRACTED_PRE_TIME_TILL_TERMINAL-d_status.settings._DISTRACTED_PROMPT_TIME_TILL_TERMINAL)/2))/DT_DMON)].names[0] == \
                    EventName.preDriverDistracted
    assert events[int((d_status.settings._DISTRACTED_TIME-d_status.settings._DISTRACTED_PROMPT_TIME_TILL_TERMINAL + \
                    ((d_status.settings._DISTRACTED_PROMPT_TIME_TILL_TERMINAL)/2))/DT_DMON)].names[0] == EventName.promptDriverDistracted
    assert events[int((d_status.settings._DISTRACTED_TIME + \
                    ((TEST_TIMESPAN-10-d_status.settings._DISTRACTED_TIME)/2))/DT_DMON)].names[0] == EventName.driverDistracted
    assert isinstance(d_status.awareness, float)

  # engaged, no face detected the whole time, no action
  def test_fully_invisible_driver(self):
    events, d_status = self._run_seq(always_no_face, always_false, always_true, always_false)
    assert len(events[int((d_status.settings._AWARENESS_TIME-d_status.settings._AWARENESS_PRE_TIME_TILL_TERMINAL)/2/DT_DMON)]) == 0
    assert events[int((d_status.settings._AWARENESS_TIME-d_status.settings._AWARENESS_PRE_TIME_TILL_TERMINAL + \
                      ((d_status.settings._AWARENESS_PRE_TIME_TILL_TERMINAL-d_status.settings._AWARENESS_PROMPT_TIME_TILL_TERMINAL)/2))/DT_DMON)].names[0] == \
                      EventName.preDriverUnresponsive
    assert events[int((d_status.settings._AWARENESS_TIME-d_status.settings._AWARENESS_PROMPT_TIME_TILL_TERMINAL + \
                      ((d_status.settings._AWARENESS_PROMPT_TIME_TILL_TERMINAL)/2))/DT_DMON)].names[0] == EventName.promptDriverUnresponsive
    assert events[int((d_status.settings._AWARENESS_TIME + \
                      ((TEST_TIMESPAN-10-d_status.settings._AWARENESS_TIME)/2))/DT_DMON)].names[0] == EventName.driverUnresponsive

  # engaged, down to orange, driver pays attention, back to normal; then down to orange, driver touches wheel
  #  - should have short orange recovery time and no green afterwards; wheel touch only recovers when paying attention
  def test_normal_driver(self):
    ds_vector = [msg_DISTRACTED] * int(DISTRACTED_SECONDS_TO_ORANGE/DT_DMON) + \
                [msg_ATTENTIVE] * int(DISTRACTED_SECONDS_TO_ORANGE/DT_DMON) + \
                [msg_DISTRACTED] * int((DISTRACTED_SECONDS_TO_ORANGE+2)/DT_DMON) + \
                [msg_ATTENTIVE] * (int(TEST_TIMESPAN/DT_DMON)-int((DISTRACTED_SECONDS_TO_ORANGE*3+2)/DT_DMON))
    interaction_vector = [car_interaction_NOT_DETECTED] * int(DISTRACTED_SECONDS_TO_ORANGE*3/DT_DMON) + \
                         [car_interaction_DETECTED] * (int(TEST_TIMESPAN/DT_DMON)-int(DISTRACTED_SECONDS_TO_ORANGE*3/DT_DMON))
    events, _ = self._run_seq(ds_vector, interaction_vector, always_true, always_false)
    assert len(events[int(DISTRACTED_SECONDS_TO_ORANGE*0.5/DT_DMON)]) == 0
    assert events[int((DISTRACTED_SECONDS_TO_ORANGE-0.1)/DT_DMON)].names[0] == EventName.promptDriverDistracted
    assert len(events[int(DISTRACTED_SECONDS_TO_ORANGE*1.5/DT_DMON)]) == 0
    assert events[int((DISTRACTED_SECONDS_TO_ORANGE*3-0.1)/DT_DMON)].names[0] == EventName.promptDriverDistracted
    assert events[int((DISTRACTED_SECONDS_TO_ORANGE*3+0.1)/DT_DMON)].names[0] == EventName.promptDriverDistracted
    assert len(events[int((DISTRACTED_SECONDS_TO_ORANGE*3+2.5)/DT_DMON)]) == 0

  # engaged, down to orange, driver dodges camera, then comes back still distracted, down to red, \
  #                          driver dodges, and then touches wheel to no avail, disengages and reengages
  #  - orange/red alert should remain after disappearance, and only disengaging clears red
  def test_biggest_comma_fan(self):
    _invisible_time = 2  # seconds
    ds_vector = always_distracted[:]
    interaction_vector = always_false[:]
    op_vector = always_true[:]
    ds_vector[int(DISTRACTED_SECONDS_TO_ORANGE/DT_DMON):int((DISTRACTED_SECONDS_TO_ORANGE+_invisible_time)/DT_DMON)] \
                                                        = [msg_NO_FACE_DETECTED] * int(_invisible_time/DT_DMON)
    ds_vector[int((DISTRACTED_SECONDS_TO_RED+_invisible_time)/DT_DMON):int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time)/DT_DMON)] \
                                                        = [msg_NO_FACE_DETECTED] * int(_invisible_time/DT_DMON)
    interaction_vector[int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+0.5)/DT_DMON):int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+1.5)/DT_DMON)] \
                                                        = [True] * int(1/DT_DMON)
    op_vector[int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+2.5)/DT_DMON):int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+3)/DT_DMON)] \
                                                        = [False] * int(0.5/DT_DMON)
    events, _ = self._run_seq(ds_vector, interaction_vector, op_vector, always_false)
    assert events[int((DISTRACTED_SECONDS_TO_ORANGE+0.5*_invisible_time)/DT_DMON)].names[0] == EventName.promptDriverDistracted
    assert events[int((DISTRACTED_SECONDS_TO_RED+1.5*_invisible_time)/DT_DMON)].names[0] == EventName.driverDistracted
    assert events[int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+1.5)/DT_DMON)].names[0] == EventName.driverDistracted
    assert len(events[int((DISTRACTED_SECONDS_TO_RED+2*_invisible_time+3.5)/DT_DMON)]) == 0

  # engaged, invisible driver, down to orange, driver touches wheel; then down to orange again, driver appears
  #  - both actions should clear the alert, but momentary appearance should not
  def test_sometimes_transparent_commuter(self):
    _visible_time = np.random.choice([0.5, 10])
    ds_vector = always_no_face[:]*2
    interaction_vector = always_false[:]*2
    ds_vector[int((2*INVISIBLE_SECONDS_TO_ORANGE+1)/DT_DMON):int((2*INVISIBLE_SECONDS_TO_ORANGE+1+_visible_time)/DT_DMON)] = \
                                                                                             [msg_ATTENTIVE] * int(_visible_time/DT_DMON)
    interaction_vector[int((INVISIBLE_SECONDS_TO_ORANGE)/DT_DMON):int((INVISIBLE_SECONDS_TO_ORANGE+1)/DT_DMON)] = [True] * int(1/DT_DMON)
    events, _ = self._run_seq(ds_vector, interaction_vector, 2*always_true, 2*always_false)
    assert len(events[int(INVISIBLE_SECONDS_TO_ORANGE*0.5/DT_DMON)]) == 0
    assert events[int((INVISIBLE_SECONDS_TO_ORANGE-0.1)/DT_DMON)].names[0] == EventName.promptDriverUnresponsive
    assert len(events[int((INVISIBLE_SECONDS_TO_ORANGE+0.1)/DT_DMON)]) == 0
    if _visible_time == 0.5:
      assert events[int((INVISIBLE_SECONDS_TO_ORANGE*2+1-0.1)/DT_DMON)].names[0] == EventName.promptDriverUnresponsive
      assert events[int((INVISIBLE_SECONDS_TO_ORANGE*2+1+0.1+_visible_time)/DT_DMON)].names[0] == EventName.preDriverUnresponsive
    elif _visible_time == 10:
      assert events[int((INVISIBLE_SECONDS_TO_ORANGE*2+1-0.1)/DT_DMON)].names[0] == EventName.promptDriverUnresponsive
      assert len(events[int((INVISIBLE_SECONDS_TO_ORANGE*2+1+0.1+_visible_time)/DT_DMON)]) == 0

  # engaged, invisible driver, down to red, driver appears and then touches wheel, then disengages/reengages
  #  - only disengage will clear the alert
  def test_last_second_responder(self):
    _visible_time = 2  # seconds
    ds_vector = always_no_face[:]
    interaction_vector = always_false[:]
    op_vector = always_true[:]
    ds_vector[int(INVISIBLE_SECONDS_TO_RED/DT_DMON):int((INVISIBLE_SECONDS_TO_RED+_visible_time)/DT_DMON)] = [msg_ATTENTIVE] * int(_visible_time/DT_DMON)
    interaction_vector[int((INVISIBLE_SECONDS_TO_RED+_visible_time)/DT_DMON):int((INVISIBLE_SECONDS_TO_RED+_visible_time+1)/DT_DMON)] = [True] * int(1/DT_DMON)
    op_vector[int((INVISIBLE_SECONDS_TO_RED+_visible_time+1)/DT_DMON):int((INVISIBLE_SECONDS_TO_RED+_visible_time+0.5)/DT_DMON)] = [False] * int(0.5/DT_DMON)
    events, _ = self._run_seq(ds_vector, interaction_vector, op_vector, always_false)
    assert len(events[int(INVISIBLE_SECONDS_TO_ORANGE*0.5/DT_DMON)]) == 0
    assert events[int((INVISIBLE_SECONDS_TO_ORANGE-0.1)/DT_DMON)].names[0] == EventName.promptDriverUnresponsive
    assert events[int((INVISIBLE_SECONDS_TO_RED-0.1)/DT_DMON)].names[0] == EventName.driverUnresponsive
    assert events[int((INVISIBLE_SECONDS_TO_RED+0.5*_visible_time)/DT_DMON)].names[0] == EventName.driverUnresponsive
    assert events[int((INVISIBLE_SECONDS_TO_RED+_visible_time+0.5)/DT_DMON)].names[0] == EventName.driverUnresponsive
    assert len(events[int((INVISIBLE_SECONDS_TO_RED+_visible_time+1+0.1)/DT_DMON)]) == 0

  # disengaged, always distracted driver
  #  - dm should stay quiet when not engaged
  def test_pure_dashcam_user(self):
    events, _ = self._run_seq(always_distracted, always_false, always_false, always_false)
    assert sum(len(event) for event in events) == 0

  # engaged, car stops at traffic light, down to orange, no action, then car starts moving
  #  - should only reach green when stopped, but continues counting down on launch
  def test_long_traffic_light_victim(self):
    _redlight_time = 60  # seconds
    standstill_vector = always_true[:]
    standstill_vector[int(_redlight_time/DT_DMON):] = [False] * int((TEST_TIMESPAN-_redlight_time)/DT_DMON)
    events, d_status = self._run_seq(always_distracted, always_false, always_true, standstill_vector)
    assert events[int((d_status.settings._DISTRACTED_TIME-d_status.settings._DISTRACTED_PRE_TIME_TILL_TERMINAL+1)/DT_DMON)].names[0] == \
                                                                                                                    EventName.preDriverDistracted
    assert events[int((_redlight_time-0.1)/DT_DMON)].names[0] == EventName.preDriverDistracted
    assert events[int((_redlight_time+0.5)/DT_DMON)].names[0] == EventName.promptDriverDistracted

  # engaged, model is somehow uncertain and driver is distracted
  #  - should fall back to wheel touch after uncertain alert
  def test_somehow_indecisive_model(self):
    ds_vector = [msg_DISTRACTED_BUT_SOMEHOW_UNCERTAIN] * int(TEST_TIMESPAN/DT_DMON)
    interaction_vector = always_false[:]
    events, d_status = self._run_seq(ds_vector, interaction_vector, always_true, always_false)
    assert EventName.preDriverUnresponsive in \
                              events[int((INVISIBLE_SECONDS_TO_ORANGE-1+DT_DMON*d_status.settings._HI_STD_FALLBACK_TIME-0.1)/DT_DMON)].names
    assert EventName.promptDriverUnresponsive in \
                              events[int((INVISIBLE_SECONDS_TO_ORANGE-1+DT_DMON*d_status.settings._HI_STD_FALLBACK_TIME+0.1)/DT_DMON)].names
    assert EventName.driverUnresponsive in \
                              events[int((INVISIBLE_SECONDS_TO_RED-1+DT_DMON*d_status.settings._HI_STD_FALLBACK_TIME+0.1)/DT_DMON)].names



# ********** my-mods: DMWiderGaze / DMExtraTime **********
def first_event_time(events, name):
  return next(i * DT_DMON for i, e in enumerate(events) if name in e.names)


class TestMonitoringMods:
  def test_defaults_are_stock(self):
    stock = DRIVER_MONITOR_SETTINGS(device_type=HARDWARE.get_device_type())
    assert stock._POSE_YAW_THRESHOLD == 0.4020
    assert stock._POSE_YAW_THRESHOLD_SLACK == 0.5042
    assert stock._DISTRACTED_TIME == 11.
    assert stock._AWARENESS_TIME == 30.

  def test_wider_gaze_numbers(self):
    stock = DRIVER_MONITOR_SETTINGS(device_type=HARDWARE.get_device_type())
    wide = DRIVER_MONITOR_SETTINGS(device_type=HARDWARE.get_device_type(), wider_gaze=True)
    assert wide._POSE_YAW_THRESHOLD == DM_WIDER_YAW_THRESHOLD > stock._POSE_YAW_THRESHOLD
    assert wide._POSE_YAW_THRESHOLD_SLACK == DM_WIDER_YAW_THRESHOLD_SLACK > stock._POSE_YAW_THRESHOLD_SLACK
    assert wide._POSE_YAW_THRESHOLD_STRICT == wide._POSE_YAW_THRESHOLD
    # looking down (pitch) and every timer untouched
    for attr in ("_POSE_PITCH_THRESHOLD", "_POSE_PITCH_THRESHOLD_SLACK", "_PITCH_NATURAL_THRESHOLD", "_DISTRACTED_TIME",
                 "_AWARENESS_TIME", "_DISTRACTED_PRE_TIME_TILL_TERMINAL", "_DISTRACTED_PROMPT_TIME_TILL_TERMINAL"):
      assert getattr(wide, attr) == getattr(stock, attr), attr

  def test_extra_time_never_shortens_any_stage(self):
    stock = DRIVER_MONITOR_SETTINGS(device_type=HARDWARE.get_device_type())
    for extra in (-5, 0, 1, 2, 3, 10):
      mod = DRIVER_MONITOR_SETTINGS(device_type=HARDWARE.get_device_type(), extra_time=extra)
      added = mod._DISTRACTED_TIME - stock._DISTRACTED_TIME
      assert 0. <= added <= DM_EXTRA_TIME_MAX
      assert mod._AWARENESS_TIME - stock._AWARENESS_TIME == added
      # warning stages after the first warning keep exactly stock length
      for attr in ("_DISTRACTED_PRE_TIME_TILL_TERMINAL", "_DISTRACTED_PROMPT_TIME_TILL_TERMINAL",
                   "_AWARENESS_PRE_TIME_TILL_TERMINAL", "_AWARENESS_PROMPT_TIME_TILL_TERMINAL"):
        assert getattr(mod, attr) == getattr(stock, attr), attr
    assert DRIVER_MONITOR_SETTINGS(device_type=HARDWARE.get_device_type(), extra_time=10)._DISTRACTED_TIME == 14.

  def test_extra_time_shifts_warnings_by_exactly_extra(self):
    stock_events, _ = self._run(always_distracted)
    mod_events, _ = self._run(always_distracted, extra_time=3)
    for name in (EventName.preDriverDistracted, EventName.promptDriverDistracted, EventName.driverDistracted):
      shift = first_event_time(mod_events, name) - first_event_time(stock_events, name)
      assert abs(shift - 3.) <= 2 * DT_DMON, name
    # first warning: ~3 s stock -> ~6 s with +3 s (plus the 0.25 s distraction filter lag in both)
    assert abs(first_event_time(stock_events, EventName.preDriverDistracted) - 3.) <= 0.5
    assert abs(first_event_time(mod_events, EventName.preDriverDistracted) - 6.) <= 0.5

  def test_wider_gaze_allows_mirror_check_both_sides(self):
    for yaw in (-0.55, 0.45):  # ~27-30 deg off centre: beyond stock 23 deg, inside wider 35 deg
      looking_at_mirror = [make_msg(True, yaw=yaw)] * int(TEST_TIMESPAN / DT_DMON)
      stock_events, _ = self._run(looking_at_mirror)
      assert EventName.preDriverDistracted in [n for e in stock_events for n in e.names]
      wide_events, _ = self._run(looking_at_mirror, wider_gaze=True)
      names = [n for e in wide_events for n in e.names]
      assert len(names) == 0, names

  def test_wider_gaze_still_catches_looking_away(self):
    looking_away = [make_msg(True, yaw=-0.8)] * int(TEST_TIMESPAN / DT_DMON)  # ~50 deg
    events, _ = self._run(looking_away, wider_gaze=True, extra_time=3)
    names = [n for e in events for n in e.names]
    assert EventName.preDriverDistracted in names and EventName.driverDistracted in names

  def _run(self, msgs, wider_gaze=False, extra_time=0):
    Params().remove("DriverTooDistracted")  # a previous run in the same test may have hit the terminal alert
    settings = DRIVER_MONITOR_SETTINGS(device_type=HARDWARE.get_device_type(), wider_gaze=wider_gaze, extra_time=extra_time)
    return TestMonitoring._run_seq(None, msgs, always_false, always_true, always_false, settings=settings)
