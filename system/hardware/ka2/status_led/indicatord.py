#!/usr/bin/env python3
"""
Indicator LED Service (indicatord) — state-change only, uses process preemption for blink

- Subscribes to selfdriveState (active, alertType) and driverCameraState (integLines for brightness).
- Only updates LEDs when (color, mode, rate) changes.
- Blink runs "indefinitely" (duration=600s) but is preempted instantly when the state changes.
- Not-running fallback to solid YELLOW if selfdriveState stalls or is unavailable.
"""

import time
import threading
from typing import Optional
from collections.abc import Callable

from openpilot.common.params import Params
from openpilot.common.mod_params import get_bool_safe
from openpilot.system.hardware.ka2.status_led.status_led import set_led, set_rainbow, WS2812_SCRIPT_DEFAULT
from cereal import messaging

StateTuple = tuple[str, str, Optional[str], str]  # (color, mode, rate, brightness)
AGNOS_UPDATE_STATE_PREFIX = "download and install OS "

# my-mods StopAlert: both bars blink red (slow, so it differs from Kommu's fast red = critical take-over)
# while the "Stop Ahead - Brake" alert shows. Uses Kommu's overrides hook, so the normal LED state
# comes back the moment the alert clears. Only fires when the StopAlert toggle is on (no alert otherwise).
MOD_LED_OVERRIDES = {
  "stopAheadBrake/warning": ("RED", "blink", "slow"),
  "stopAheadBrakeSound/warning": ("RED", "blink", "slow"),
}

# my-mods ShowBlindspot: while the car's BSM sees a vehicle, the bar on that side turns amber and the
# other bar keeps Kommu's colour. Only over a SOLID Kommu state that isn't red or yellow: any blinking
# (warning / take-over), red (fault) or yellow (openpilot not running) state wins and both bars show it.
# The strip takes colours as B-R-G hex, like COLORS in status_led.py: amber R255 G170 B0 -> "00FFAA".
BSM_AMBER_HEX = "00FFAA"
BSM_BLOCKING_COLORS = ("RED", "YELLOW")
BSM_HOLD_S = 0.5           # keep amber this long after BSM clears: no flicker, fewer LED process restarts
BSM_STALE_S = 0.5          # no carState for this long -> treat as no blind spot
PARAM_REFRESH_S = 1.0


def bsm_bar_colors(color: str, mode: str, left: bool, right: bool, swap_sides: bool) -> tuple[str, str]:
    """(bar A colour, bar B colour). Bar A is the left bar unless swap_sides (Param LedBarSwapSides)."""
    if mode != "solid" or color in BSM_BLOCKING_COLORS or not (left or right):
        return color, color
    a_bsm, b_bsm = (right, left) if swap_sides else (left, right)
    return (BSM_AMBER_HEX if a_bsm else color, BSM_AMBER_HEX if b_bsm else color)


class BlindspotHold:
    """On straight away, off only after BSM_HOLD_S without a detection."""
    def __init__(self):
        self.last_seen: Optional[float] = None

    def update(self, detected: bool, now: float) -> bool:
        if detected:
            self.last_seen = now
        return self.last_seen is not None and now - self.last_seen < BSM_HOLD_S

class AlertLEDService:
    def __init__(
        self,
        *,
        ws_script: str = WS2812_SCRIPT_DEFAULT,
        brightness_min: int = 50,
        brightness_max: int = 200,
        integ_min: int = 100,
        integ_max: int = 892,
        not_running_brightness: str = "200",
        topic_cs: str = "selfdriveState",
        topic_dc: str = "driverCameraState",
        base_poll_ms: int = 500,
        overrides: Optional[dict[str, tuple[str, str, Optional[str]]]] = None,
        on_change: Optional[Callable[[bool, str, StateTuple], None]] = None,
        not_running_timeout_s: float = 1.0,
        debug: bool = False,
    ):
        self.ws_script = ws_script
        self.brightness_min = int(brightness_min)
        self.brightness_max = int(brightness_max)
        self.integ_min = int(integ_min)
        self.integ_max = int(integ_max)
        self.not_running_brightness = str(not_running_brightness)
        self.topic_cs = topic_cs
        self.topic_dc = topic_dc
        self.base_poll_ms = max(1, int(base_poll_ms))
        self.overrides = {k.lower(): v for k, v in (overrides or {}).items()}
        self.on_change = on_change
        self.not_running_timeout_s = float(not_running_timeout_s)
        self.debug = debug

        self._stop = threading.Event()
        self._sm = messaging.SubMaster([self.topic_cs, self.topic_dc, "carState"])
        self._params = Params()

        # my-mods ShowBlindspot state
        self._show_bsm = False
        self._swap_sides = False
        self._last_param_t = -PARAM_REFRESH_S
        self._bsm_raw = (False, False)
        self._bsm_time: Optional[float] = None
        self._bsm_hold = (BlindspotHold(), BlindspotHold())
        self._last_b: str = "YELLOW"

        self._last_key: Optional[tuple[str, str, str, Optional[str]]] = None
        self._last_state: Optional[StateTuple] = None
        self._last_msg_time_cs: Optional[float] = None
        self._last_integ: int = (self.integ_min + self.integ_max) // 2
        self._last_active = False
        self._last_alert_type = "not_running"
        self._agnos_update_led_active = False

        # boot → not-running yellow (counts as a state)
        state = ("YELLOW", "solid", None, self.not_running_brightness)
        self._apply(state, active=False, alert_type="not_running", force=True)
        self._last_state = state
        self._last_key = (state[0], state[0], state[1], state[2])

    def stop(self):
        self._stop.set()

    def run_forever(self):
        while not self._stop.is_set():
            now = time.monotonic()
            self._sm.update(self.base_poll_ms)
            now = time.monotonic()

            agnos_update_active = self._agnos_update_in_progress()
            update_just_finished = self._agnos_update_led_active and not agnos_update_active
            if agnos_update_active:
                if not self._agnos_update_led_active:
                    self._apply_rainbow()
                    self._agnos_update_led_active = True
            elif update_just_finished:
                # Let the normal state machine restore the previous LED state.
                self._agnos_update_led_active = False
                self._last_key = None

            if now - self._last_param_t >= PARAM_REFRESH_S:
                self._show_bsm = get_bool_safe("ShowBlindspot", self._params)
                self._swap_sides = get_bool_safe("LedBarSwapSides", self._params)
                self._last_param_t = now
            if self._sm.updated["carState"]:
                car_state = self._sm["carState"]
                self._bsm_raw = (bool(car_state.leftBlindspot), bool(car_state.rightBlindspot))
                self._bsm_time = now

            if self._sm.updated[self.topic_dc]:
                dc = self._sm[self.topic_dc]
                v = getattr(dc, "integLines", None)
                if isinstance(v, (int, float)):
                    self._last_integ = int(v)

            if self._sm.updated[self.topic_cs]:
                cs = self._sm[self.topic_cs]
                self._last_msg_time_cs = now
                active = bool(getattr(cs, "active", False))
                alert_type = (getattr(cs, "alertType", "") or "")

                # Personality toggle is informational; keep current LED state unchanged.
                if alert_type.strip().lower() == "personalitychanged/warning":
                    if self.debug:
                        print("[indicatord] personalityChanged/warning -> keep previous LED state", flush=False)
                    continue

                color, mode, rate = self._classify_key(alert_type, active)
                a_color, b_color = self._bar_colors(color, mode, now)
                key = (a_color, b_color, mode, rate)
                brightness = str(self._map_integ_to_brightness_inverse(self._last_integ))
                desired: StateTuple = (a_color, mode, rate, brightness)
                self._last_state = desired
                self._last_b = b_color
                self._last_active = active
                self._last_alert_type = alert_type

                if agnos_update_active:
                    # Keep recording the latest normal state, but let the rainbow
                    # own the LEDs until the AGNOS update state leaves progress.
                    self._last_key = key
                    continue

                if key != self._last_key:
                    self._apply(desired, active=active, alert_type=alert_type, force=True, b_color=b_color)
                    self._last_key = key
                    if self.on_change:
                        self._safe_on_change(active, alert_type, desired)
                else:
                    if self.debug:
                        print("[indicatord] CS updated but state unchanged", flush=False)

            # not-running fallback
            no_heartbeat = (self._last_msg_time_cs is None) or ((now - self._last_msg_time_cs) > self.not_running_timeout_s)
            if not agnos_update_active and ((not self._sm.alive[self.topic_cs]) or no_heartbeat):
                key = ("YELLOW", "YELLOW", "solid", None)
                if self._last_key != key:
                    state = ("YELLOW", "solid", None, self.not_running_brightness)
                    self._apply(state, active=False, alert_type="not_running", force=True)
                    self._last_state = state
                    self._last_b = "YELLOW"
                    self._last_key = key
                    if self.on_change:
                        self._safe_on_change(False, "not_running", state)

            if update_just_finished and self._last_key is None and self._last_state is not None:
                self._apply(self._last_state, active=self._last_active, alert_type=self._last_alert_type, force=True,
                            b_color=self._last_b)
                self._last_key = (self._last_state[0], self._last_b, self._last_state[1], self._last_state[2])

    def _bar_colors(self, color: str, mode: str, now: float) -> tuple[str, str]:
        """my-mods ShowBlindspot on top of Kommu's colour. Off: both bars Kommu's colour, as stock."""
        fresh = self._bsm_time is not None and now - self._bsm_time < BSM_STALE_S
        left = self._bsm_hold[0].update(self._show_bsm and fresh and self._bsm_raw[0], now)
        right = self._bsm_hold[1].update(self._show_bsm and fresh and self._bsm_raw[1], now)
        return bsm_bar_colors(color, mode, left, right, self._swap_sides)

    def _agnos_update_in_progress(self) -> bool:
        try:
            state = self._params.get("UpdaterState") or ""
            if isinstance(state, bytes):
                state = state.decode("utf-8", "replace")
            return str(state).startswith(AGNOS_UPDATE_STATE_PREFIX)
        except Exception:
            return False

    def _apply_rainbow(self) -> None:
        try:
            set_rainbow(ws_script=self.ws_script, fire_and_forget=True)
            if self.debug:
                print("[indicatord] AGNOS update -> rainbow", flush=False)
        except Exception as e:
            if self.debug:
                print(f"[indicatord] failed to show AGNOS rainbow: {e!r}", flush=False)

    # mapping: alert_type format is "eventName/eventType" (e.g. cameraMalfunction/permanent, wrongGear/noEntry)
    # Event types (ET): enable, noEntry, warning, userDisable, softDisable, immediateDisable, permanent
    #
    # LED behavior summary:
    #   GREEN solid:  enable (engage), active with no alert
    #   RED blink:    immediateDisable when active (critical take-over)
    #   RED solid:    immediateDisable when not active, critical permanent (malfunction, faulted, etc.)
    #   ORANGE blink: softDisable, userDisable, warning (active or not)
    #   ORANGE solid: noEntry, softDisable when not active, warning permanent (dashcam, etc.)
    #   BLUE solid:   startup events, userDisable when not active, low-priority permanent, preEnable, overrides
    #   YELLOW solid: not_running fallback (selfdriveState unavailable)
    def _classify_key(self, alert_type: str, active: bool) -> tuple[str, str, Optional[str]]:
        raw = (alert_type or "").strip()
        tl = raw.lower()
        parts = tl.split("/", 1)
        event_name = parts[0] if parts else ""
        event_type = parts[1] if len(parts) > 1 else ""

        if tl in self.overrides:
            color, mode, rate = self.overrides[tl]
            return (color, mode, rate)

        # Keep all startup alerts consistently blue (e.g. startup/noEntry, startup/permanent).
        if "startup" in event_name:
            return ("BLUE", "solid", None)

        # engage (buttonEnable/enable, pcmEnable/enable) — always green, matches soundd engage.wav
        if event_type == "enable":
            return ("GREEN", "solid", None)

        # --- Active (openpilot engaged) ---
        if active:
            if event_type == "immediatedisable":
                return ("RED", "blink", "fast")
            if event_type in ("softdisable", "userdisable"):
                return ("ORANGE", "blink", "fast")
            if event_type == "warning":
                return ("ORANGE", "blink", "fast")
            return ("GREEN", "solid", None)

        # --- Not active ---
        if event_type == "immediatedisable":
            return ("RED", "solid", None)
        if event_type in ("noentry", "softdisable"):
            return ("ORANGE", "solid", None)
        if event_type == "warning":
            return ("ORANGE", "blink", "fast")
        if event_type == "userdisable":
            return ("BLUE", "solid", None)

        # permanent: classify by event name (matches events.py EVENTS)
        if event_type == "permanent":
            if any(x in event_name for x in ("malfunction", "faulted", "error", "overheat", "outofspace",
                                             "relay", "accfaulted", "steerunavailable", "canerror", "canbus",
                                             "vehiclesensors", "sensorinvalid", "calibrationinvalid")):
                return ("RED", "solid", None)
            if any(x in event_name for x in ("dashcam", "calibration", "locationd", "paramsd",
                                             "unrecognized", "cameraframerate", "fan")):
                return ("ORANGE", "solid", None)
            return ("BLUE", "solid", None)

        # enable, preEnable, overrideLateral, overrideLongitudinal, or unknown
        return ("BLUE", "solid", None)

    def _map_integ_to_brightness_inverse(self, integ: int) -> int:
        if integ <= self.integ_min:
            return self.brightness_max
        if integ >= self.integ_max:
            return self.brightness_min
        t = (integ - self.integ_min) / (self.integ_max - self.integ_min)
        return int(round(self.brightness_max - t * (self.brightness_max - self.brightness_min)))

    def _apply(self, state: StateTuple, active: bool, alert_type: str, *, force: bool = False,
               b_color: Optional[str] = None):
        color, mode, rate, brightness = state
        # For blink: set a long duration; preemption stops it on next state change
        kwargs = {"duration": "600"} if mode in ("blink", "run") else {}
        # my-mods: bar B gets its own colour only when it differs (blind spot); otherwise exactly as stock
        set_led(color, b_color if b_color not in (None, color) else None, mode=mode, rate=rate, brightness=brightness,
                ws_script=self.ws_script, fire_and_forget=True, **kwargs)
        if self.debug:
            print(f"[indicatord]{' [FORCE]' if force else ''} -> {mode} {color} " +
                  f"{('rate='+rate) if rate else ''} b={brightness}", flush=False)

    def _safe_on_change(self, active: bool, alert_type: str, state: StateTuple):
        try:
            self.on_change and self.on_change(active, alert_type, state)
        except Exception:
            pass

def main(*, debug: bool = False):
    svc = AlertLEDService(debug=debug, overrides=MOD_LED_OVERRIDES)
    try:
        svc.run_forever()
    except KeyboardInterrupt:
        svc.stop()

if __name__ == "__main__":
    main(debug=False)
