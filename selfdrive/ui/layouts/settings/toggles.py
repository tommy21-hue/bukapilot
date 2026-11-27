from cereal import log
from openpilot.common.params import Params, UnknownKeyName
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import multiple_button_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.common.mod_params import param_known, get_int_safe
from openpilot.selfdrive.controls.lib.turn_desire import TURN_DESIRE_SPEED_OPTIONS, TURN_DESIRE_SPEED_DEFAULT, clamp_turn_speed

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants

# Description constants
DESCRIPTIONS = {
  "OpenpilotEnabledToggle": tr_noop(
    "Use the openpilot system for adaptive cruise control and lane keep driver assistance. " +
    "Your attention is required at all times to use this feature."
  ),
  "DisengageOnAccelerator": tr_noop("When enabled, pressing the accelerator pedal will disengage openpilot."),
  "LongitudinalPersonality": tr_noop(
    "Standard is recommended. In aggressive mode, openpilot will follow lead cars closer and be more aggressive with the gas and brake. " +
    "In relaxed mode openpilot will stay further away from lead cars. On supported cars, you can cycle through these personalities with " +
    "your steering wheel distance button."
  ),
  "IsLdwEnabled": tr_noop(
    "Receive alerts to steer back into the lane when your vehicle drifts over a detected lane line " +
    "without a turn signal activated while driving over 31 mph (50 km/h)."
  ),
  "AlwaysOnDM": tr_noop("Enable driver monitoring even when openpilot is not engaged."),
  'RecordFront': tr_noop("Upload data from the driver facing camera and help improve the driver monitoring algorithm."),
  "IsMetric": tr_noop("Display speed in km/h instead of mph."),
  "RecordAudio": tr_noop("Record and store microphone audio while driving. The audio will be included in the dashcam video in comma connect."),
  "StopAlert": tr_noop(
    "Chime and show \"Stop Ahead – Brake\" when the driving model predicts a stop ahead (red light or stop sign) " +
    "while openpilot is engaged and the car is not slowing. Alert only: it never brakes for you. " +
    "Quiet when a car ahead is detected."
  ),
  "StopAlertSound": tr_noop("Also chime for the Stop Ahead alert. Off: the alert is visual only."),
  "NudgelessLaneChange": tr_noop(
    "Needs Auto Lane Change on. At 60 km/h or more, the lane change starts by itself 1 second after you " +
    "signal, if the car's blind spot monitor is clear on that side for that whole second. Cancels and asks you " +
    "to take over if the blind spot monitor sees a car while changing. One lane change per signal. " +
    "Below 60 km/h you still nudge the wheel."
  ),
  "DMWiderGaze": tr_noop(
    "Count side-to-side looks up to 35° (stock 23°) as paying attention, so mirror checks don't trigger " +
    "driver monitoring warnings. Looking down is unchanged. Applies from the next drive."
  ),
  "DMExtraTime": tr_noop(
    "Add up to 3 seconds before the first driver monitoring warning. Every later warning keeps its stock timing " +
    "after that. Applies from the next drive."
  ),
  "TurnDesires": tr_noop(
    "Below the speed set below, the turn signal makes openpilot take the turn instead of changing lanes, " +
    "and steering stays on while signalling. Steering limits are unchanged: the car can only steer gentle " +
    "turns (about 22 m radius or wider), so most intersection corners will ask you to take control."
  ),
  "TurnDesireSpeed": tr_noop("Turn desires work below this speed."),
  "ShowBlindspot": tr_noop(
    "KA2 light bars: while the car's blind spot monitor sees a vehicle, the bar on that side turns amber and " +
    "the other bar keeps its normal colour. Kommu warnings, take-over alerts and faults always take priority."
  ),
}


class TogglesLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._is_release = self._params.get_bool("IsReleaseBranch")

    # param, title, desc, icon, needs_restart
    self._toggle_defs = {
      "OpenpilotEnabledToggle": (
        lambda: tr("Enable openpilot"),
        DESCRIPTIONS["OpenpilotEnabledToggle"],
        "chffr_wheel.png",
        True,
      ),
      "ExperimentalMode": (
        lambda: tr("Experimental Mode"),
        "",
        "experimental_white.png",
        False,
      ),
      "DisengageOnAccelerator": (
        lambda: tr("Disengage on Accelerator Pedal"),
        DESCRIPTIONS["DisengageOnAccelerator"],
        "disengage_on_accelerator.png",
        False,
      ),
      "IsLdwEnabled": (
        lambda: tr("Enable Lane Departure Warnings"),
        DESCRIPTIONS["IsLdwEnabled"],
        "warning.png",
        False,
      ),
      "AlwaysOnDM": (
        lambda: tr("Always-On Driver Monitoring"),
        DESCRIPTIONS["AlwaysOnDM"],
        "monitoring.png",
        False,
      ),
      "RecordFront": (
        lambda: tr("Record and Upload Driver Camera"),
        DESCRIPTIONS["RecordFront"],
        "monitoring.png",
        True,
      ),
      "RecordAudio": (
        lambda: tr("Record and Upload Microphone Audio"),
        DESCRIPTIONS["RecordAudio"],
        "microphone.png",
        True,
      ),
      "IsMetric": (
        lambda: tr("Use Metric System"),
        DESCRIPTIONS["IsMetric"],
        "metric.png",
        False,
      ),
      "StopAlert": (
        lambda: tr("Stop Ahead Alert"),
        DESCRIPTIONS["StopAlert"],
        "warning.png",
        False,
      ),
      "StopAlertSound": (
        lambda: tr("Stop Ahead Alert Sound"),
        DESCRIPTIONS["StopAlertSound"],
        "warning.png",
        False,
      ),
      "NudgelessLaneChange": (
        lambda: tr("Nudgeless Lane Change"),
        DESCRIPTIONS["NudgelessLaneChange"],
        "chffr_wheel.png",
        False,
      ),
      "DMWiderGaze": (
        lambda: tr("Wider Driver Monitoring Gaze Zone"),
        DESCRIPTIONS["DMWiderGaze"],
        "monitoring.png",
        False,
      ),
      "TurnDesires": (
        lambda: tr("Turn Desires"),
        DESCRIPTIONS["TurnDesires"],
        "chffr_wheel.png",
        False,
      ),
      "ShowBlindspot": (
        lambda: tr("Blind Spot on Light Bars"),
        DESCRIPTIONS["ShowBlindspot"],
        "warning.png",
        False,
      ),
    }

    # my-mods toggles: hide any whose Param isn't compiled into params_pyx.so yet (prebuilt branch)
    for mod_param in ("StopAlert", "StopAlertSound", "NudgelessLaneChange", "DMWiderGaze", "TurnDesires", "ShowBlindspot"):
      if not param_known(mod_param, self._params):
        self._toggle_defs.pop(mod_param, None)

    self._long_personality_setting = multiple_button_item(
      lambda: tr("Driving Personality"),
      lambda: tr(DESCRIPTIONS["LongitudinalPersonality"]),
      buttons=[lambda: tr("Aggressive"), lambda: tr("Standard"), lambda: tr("Relaxed")],
      button_width=255,
      callback=self._set_longitudinal_personality,
      selected_index=self._params.get("LongitudinalPersonality", return_default=True),
      icon="speed_limit.png"
    )

    # my-mods: DMExtraTime selector (index == extra seconds), only if the Param is compiled in
    self._dm_extra_time_setting = None
    if param_known("DMExtraTime", self._params):
      self._dm_extra_time_setting = multiple_button_item(
        lambda: tr("Extra Time Before DM Warning"),
        lambda: tr(DESCRIPTIONS["DMExtraTime"]),
        buttons=[lambda: tr("Off"), lambda: "+1 s", lambda: "+2 s", lambda: "+3 s"],
        button_width=255,
        callback=lambda idx: self._params.put("DMExtraTime", idx),
        selected_index=self._params.get("DMExtraTime", return_default=True) or 0,
        icon="monitoring.png"
      )

    # my-mods: TurnDesireSpeed selector (stores km/h)
    self._turn_speed_setting = None
    if param_known("TurnDesireSpeed", self._params):
      cur = clamp_turn_speed(get_int_safe("TurnDesireSpeed", TURN_DESIRE_SPEED_DEFAULT, self._params))
      self._turn_speed_setting = multiple_button_item(
        lambda: tr("Turn Desire Speed"),
        lambda: tr(DESCRIPTIONS["TurnDesireSpeed"]),
        buttons=[lambda v=v: f"{v} km/h" for v in TURN_DESIRE_SPEED_OPTIONS],
        button_width=200,
        callback=lambda idx: self._params.put("TurnDesireSpeed", TURN_DESIRE_SPEED_OPTIONS[idx]),
        selected_index=min(range(len(TURN_DESIRE_SPEED_OPTIONS)), key=lambda i: abs(TURN_DESIRE_SPEED_OPTIONS[i] - cur)),
        icon="speed_limit.png"
      )

    self._toggles = {}
    self._locked_toggles = set()
    for param, (title, desc, icon, needs_restart) in self._toggle_defs.items():
      toggle = toggle_item(
        title,
        desc,
        self._params.get_bool(param),
        callback=lambda state, p=param: self._toggle_callback(state, p),
        icon=icon,
      )

      try:
        locked = self._params.get_bool(param + "Lock")
      except UnknownKeyName:
        locked = False
      toggle.action_item.set_enabled(not locked)

      # Make description callable for live translation
      additional_desc = ""
      if needs_restart and not locked:
        additional_desc = tr("Changing this setting will restart openpilot if the car is powered on.")
      toggle.set_description(lambda og_desc=toggle.description, add_desc=additional_desc: tr(og_desc) + (" " + tr(add_desc) if add_desc else ""))

      # track for engaged state updates
      if locked:
        self._locked_toggles.add(param)

      self._toggles[param] = toggle

      # insert longitudinal personality after NDOG toggle
      if param == "DisengageOnAccelerator":
        self._toggles["LongitudinalPersonality"] = self._long_personality_setting
      if param == "DMWiderGaze" and self._dm_extra_time_setting is not None:
        self._toggles["DMExtraTime"] = self._dm_extra_time_setting
      if param == "TurnDesires" and self._turn_speed_setting is not None:
        self._toggles["TurnDesireSpeed"] = self._turn_speed_setting

    self._update_experimental_mode_icon()
    self._scroller = Scroller(list(self._toggles.values()), line_separator=True, spacing=0)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._long_personality_setting.action_item.set_selected_button(personality)
      ui_state.personality = personality

  def show_event(self):
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    e2e_description = tr(
      "openpilot defaults to driving in chill mode. Experimental mode enables alpha-level features that aren't ready for chill mode. " +
      "Experimental features are listed below:<br>" +
      "<h4>End-to-End Longitudinal Control</h4><br>" +
      "Let the driving model control the gas and brakes. openpilot will drive as it thinks a human would, including stopping for red lights and stop signs. " +
      "Since the driving model decides the speed to drive, the set speed will only act as an upper bound. This is an alpha quality feature; " +
      "mistakes should be expected.<br>" +
      "<h4>New Driving Visualization</h4><br>" +
      "The driving visualization will transition to the road-facing wide-angle camera at low speeds to better show some turns. " +
      "The Experimental mode logo will also be shown in the top right corner."
    )

    if ui_state.CP is not None:
      if ui_state.has_longitudinal_control:
        self._toggles["ExperimentalMode"].action_item.set_enabled(True)
        self._toggles["ExperimentalMode"].set_description(e2e_description)
        self._long_personality_setting.action_item.set_enabled(True)
      else:
        # no long for now
        self._toggles["ExperimentalMode"].action_item.set_enabled(False)
        self._toggles["ExperimentalMode"].action_item.set_state(False)
        self._long_personality_setting.action_item.set_enabled(False)
        self._params.remove("ExperimentalMode")

        unavailable = tr("Experimental mode is currently unavailable on this car since the car's stock ACC is used for longitudinal control.")

        long_desc = unavailable + " " + tr("openpilot longitudinal control may come in a future update.")
        if ui_state.CP.alphaLongitudinalAvailable:
          if self._is_release:
            long_desc = unavailable + " " + tr("An alpha version of openpilot longitudinal control can be tested, along with " +
                                               "Experimental mode, on non-release branches.")
          else:
            long_desc = tr("Enable the openpilot longitudinal control (alpha) toggle to allow Experimental mode.")

        self._toggles["ExperimentalMode"].set_description("<b>" + long_desc + "</b><br><br>" + e2e_description)
    else:
      self._toggles["ExperimentalMode"].set_description(e2e_description)

    self._update_experimental_mode_icon()

    # TODO: make a param control list item so we don't need to manage internal state as much here
    # refresh toggles from params to mirror external changes
    for param in self._toggle_defs:
      self._toggles[param].action_item.set_state(self._params.get_bool(param))

    # these toggles need restart, block while engaged
    for toggle_def in self._toggle_defs:
      if self._toggle_defs[toggle_def][3] and toggle_def not in self._locked_toggles:
        self._toggles[toggle_def].action_item.set_enabled(not ui_state.engaged)

  def _render(self, rect):
    self._scroller.render(rect)

  def _update_experimental_mode_icon(self):
    icon = "experimental.png" if self._toggles["ExperimentalMode"].action_item.get_state() else "experimental_white.png"
    self._toggles["ExperimentalMode"].set_icon(icon)

  def _handle_experimental_mode_toggle(self, state: bool):
    confirmed = self._params.get_bool("ExperimentalModeConfirmed")
    if state and not confirmed:
      def confirm_callback(result: int):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("ExperimentalMode", True)
          self._params.put_bool("ExperimentalModeConfirmed", True)
        else:
          self._toggles["ExperimentalMode"].action_item.set_state(False)
        self._update_experimental_mode_icon()

      # show confirmation dialog
      content = (f"<h1>{self._toggles['ExperimentalMode'].title}</h1><br>" +
                 f"<p>{self._toggles['ExperimentalMode'].description}</p>")
      dlg = ConfirmDialog(content, tr("Enable"), rich=True)
      gui_app.set_modal_overlay(dlg, callback=confirm_callback)
    else:
      self._update_experimental_mode_icon()
      self._params.put_bool("ExperimentalMode", state)

  def _toggle_callback(self, state: bool, param: str):
    if param == "ExperimentalMode":
      self._handle_experimental_mode_toggle(state)
      return

    self._params.put_bool(param, state)
    if self._toggle_defs[param][3]:
      self._params.put_bool("OnroadCycleRequested", True)

  def _set_longitudinal_personality(self, button_index: int):
    self._params.put("LongitudinalPersonality", button_index)
