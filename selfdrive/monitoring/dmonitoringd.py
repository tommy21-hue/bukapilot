#!/usr/bin/env python3
import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process
from openpilot.selfdrive.monitoring.helpers import DriverMonitoring, DRIVER_MONITOR_SETTINGS
from openpilot.common.mod_params import get_bool_safe, get_int_safe
from openpilot.system.hardware import HARDWARE

KA2_DM_MIN_HZ = 5.0
KA2_DM_MAX_DT_S = 1.0 / KA2_DM_MIN_HZ


def dmonitoringd_thread():
  config_realtime_process([0, 1, 2, 3], 5)

  params = Params()
  pm = messaging.PubMaster(['driverMonitoringState'])
  sm = messaging.SubMaster(['driverStateV2', 'liveCalibration', 'carState', 'selfdriveState', 'modelV2'], poll='driverStateV2')

  # my-mods: DMWiderGaze / DMExtraTime are read once per drive (dmonitoringd restarts each drive)
  dm_settings = DRIVER_MONITOR_SETTINGS(device_type=HARDWARE.get_device_type(),
                                        wider_gaze=get_bool_safe("DMWiderGaze", params),
                                        extra_time=get_int_safe("DMExtraTime", 0, params))
  DM = DriverMonitoring(rhd_saved=params.get_bool("IsRhdDetected"), settings=dm_settings, always_on=params.get_bool("AlwaysOnDM"))
  demo_mode = False
  is_ka2 = HARDWARE.get_device_type() == "ka2"
  last_driverstate_t = None

  # 20Hz <- dmonitoringmodeld
  while True:
    sm.update()
    if not sm.updated['driverStateV2']:
      # iterate when model has new output
      continue

    if is_ka2:
      # On KA2, keep strict alive/valid checks, but accept dmonitoring model down to ~5Hz.
      # Poll-based SubMaster frequency checks are too strict for mixed-rate dependencies here.
      valid = sm.all_alive() and sm.all_valid()
      cur_driverstate_t = sm.logMonoTime['driverStateV2'] * 1e-9
      if last_driverstate_t is not None:
        valid = valid and ((cur_driverstate_t - last_driverstate_t) <= KA2_DM_MAX_DT_S)
      last_driverstate_t = cur_driverstate_t
    else:
      valid = sm.all_checks()
    if demo_mode and sm.valid['driverStateV2']:
      DM.run_step(sm, demo=demo_mode)
    elif valid:
      DM.run_step(sm, demo=demo_mode)

    # publish
    dat = DM.get_state_packet(valid=valid)
    pm.send('driverMonitoringState', dat)

    # load live always-on toggle
    if sm['driverStateV2'].frameId % 40 == 1:
      DM.always_on = params.get_bool("AlwaysOnDM")
      demo_mode = params.get_bool("IsDriverViewEnabled")

    # save rhd virtual toggle every 5 mins
    if (sm['driverStateV2'].frameId % 6000 == 0 and not demo_mode and
     DM.wheelpos.prob_offseter.filtered_stat.n > DM.settings._WHEELPOS_FILTER_MIN_COUNT and
     DM.wheel_on_right == (DM.wheelpos.prob_offseter.filtered_stat.M > DM.settings._WHEELPOS_THRESHOLD)):
      params.put_bool_nonblocking("IsRhdDetected", DM.wheel_on_right)

def main():
  dmonitoringd_thread()


if __name__ == '__main__':
  main()
