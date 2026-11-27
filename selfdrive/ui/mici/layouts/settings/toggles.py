import pyray as rl
from collections.abc import Callable
from cereal import log

from openpilot.system.ui.widgets.scroller import Scroller
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigMultiParamToggle
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import NavWidget
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.common.mod_params import param_known, get_int_safe
from openpilot.selfdrive.ui.mici.widgets.button import BigMultiToggle
from openpilot.selfdrive.controls.lib.turn_desire import TURN_DESIRE_SPEED_OPTIONS, TURN_DESIRE_SPEED_DEFAULT, clamp_turn_speed

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants


class TurnSpeedParamToggle(BigMultiParamToggle):
  """my-mods: like BigMultiParamToggle but stores the km/h value, not the option index."""
  def __init__(self, text: str, param: str):
    super().__init__(text, param, [f"{v} km/h" for v in TURN_DESIRE_SPEED_OPTIONS])

  def _load_value(self):
    cur = clamp_turn_speed(get_int_safe(self._param, TURN_DESIRE_SPEED_DEFAULT, self._params))
    idx = min(range(len(TURN_DESIRE_SPEED_OPTIONS)), key=lambda i: abs(TURN_DESIRE_SPEED_OPTIONS[i] - cur))
    self.set_value(self._options[idx])

  def _handle_mouse_release(self, mouse_pos):
    BigMultiToggle._handle_mouse_release(self, mouse_pos)
    self._params.put_nonblocking(self._param, TURN_DESIRE_SPEED_OPTIONS[self._options.index(self.value)])


class TogglesLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable):
    super().__init__()
    self.set_back_callback(back_callback)

    self._personality_toggle = BigMultiParamToggle("driving personality", "LongitudinalPersonality", ["aggressive", "standard", "relaxed"])
    self._experimental_btn = BigParamControl("experimental mode", "ExperimentalMode")
    is_metric_toggle = BigParamControl("use metric units", "IsMetric")
    ldw_toggle = BigParamControl("lane departure warnings", "IsLdwEnabled")
    always_on_dm_toggle = BigParamControl("always-on driver monitor", "AlwaysOnDM")
    record_front = BigParamControl("record & upload driver camera", "RecordFront", toggle_callback=restart_needed_callback)
    record_mic = BigParamControl("record & upload mic audio", "RecordAudio", toggle_callback=restart_needed_callback)
    enable_openpilot = BigParamControl("enable openpilot", "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback)

    # my-mods toggles: (param, widget). Hidden if the Param isn't compiled into params_pyx.so yet (prebuilt branch).
    # Widgets are only created for known Params: BigParamControl reads its Param on creation.
    mod_toggles = [(p, BigParamControl(text, p)) for p, text in (
      ("StopAlert", "stop ahead alert"),
      ("NudgelessLaneChange", "nudgeless lane change"),
      ("DMWiderGaze", "wider dm gaze zone"),
      ("TurnDesires", "turn desires"),
      ("ShowBlindspot", "show blind spot indicators"),
    ) if param_known(p)]
    # index == extra seconds before the first driver monitoring warning
    mod_multi = [BigMultiParamToggle("extra dm warning time", "DMExtraTime", ["off", "+1 s", "+2 s", "+3 s"])] \
      if param_known("DMExtraTime") else []
    if param_known("TurnDesireSpeed"):
      mod_multi.append(TurnSpeedParamToggle("turn desire speed", "TurnDesireSpeed"))

    self._scroller = Scroller([
      self._personality_toggle,
      self._experimental_btn,
      is_metric_toggle,
      ldw_toggle,
      always_on_dm_toggle,
      *[w for _, w in mod_toggles],
      *mod_multi,
      record_front,
      record_mic,
      enable_openpilot,
    ], snap_items=False)

    # Toggle lists
    self._refresh_toggles = (
      ("ExperimentalMode", self._experimental_btn),
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("RecordFront", record_front),
      ("RecordAudio", record_mic),
      ("OpenpilotEnabledToggle", enable_openpilot),
      *mod_toggles,
    )

    enable_openpilot.set_enabled(lambda: not ui_state.engaged)
    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))
    record_mic.set_enabled(lambda: not ui_state.engaged)

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()

    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._personality_toggle.set_value(self._personality_toggle._options[personality])
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # CP gating for experimental mode
    if ui_state.CP is not None:
      if ui_state.has_longitudinal_control:
        self._experimental_btn.set_visible(True)
        self._personality_toggle.set_visible(True)
      else:
        # no long for now
        self._experimental_btn.set_visible(False)
        self._experimental_btn.set_checked(False)
        self._personality_toggle.set_visible(False)
        ui_state.params.remove("ExperimentalMode")

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))

  def _render(self, rect: rl.Rectangle):
    self._scroller.render(rect)
