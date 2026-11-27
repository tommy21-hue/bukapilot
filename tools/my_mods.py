#!/usr/bin/env python3
"""Turn my-mods features on and off over SSH (the KA2 has no screen and the KommuAI app only shows
Kommu's own settings).

  cd /data/openpilot
  python3 tools/my_mods.py                      # list every mod setting and its value
  python3 tools/my_mods.py on StopAlert         # turn a feature on
  python3 tools/my_mods.py off StopAlert        # turn it off
  python3 tools/my_mods.py set TurnDesireSpeed 22

All settings are Params, off by default. Unless noted, a change applies within about a second;
driver monitoring settings apply from the next drive.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root, for "openpilot"

from openpilot.common.params import Params
from openpilot.common.mod_params import param_known

# name: (kind, allowed values for int settings, default, description)
MODS = {
  "StopAlert": ("bool", None, False, "Stop Ahead alert when the model plans a stop and the car isn't slowing; red light bars"),
  "StopAlertSound": ("bool", None, False, "Also chime for the Stop Ahead alert (off = visual only)"),
  "NudgelessLaneChange": ("bool", None, False, "Lane change without a nudge at 60+ km/h (needs Auto Lane Change on)"),
  "DMWiderGaze": ("bool", None, False, "Driver monitoring: side looks up to 35 deg count as attentive (next drive)"),
  "DMExtraTime": ("int", (0, 1, 2, 3), 0, "Driver monitoring: seconds added before the first warning (next drive)"),
  "TurnDesires": ("bool", None, False, "Below the turn speed, the blinker means take the turn"),
  "TurnDesireSpeed": ("int", (20, 22, 25, 28, 30), 25, "Turn desires work below this speed, km/h"),
  "ShowBlindspot": ("bool", None, False, "Blind spot: amber light bar on that side"),
  "LedBarSwapSides": ("bool", None, False, "Swap which light bar is left/right for the blind spot"),
}


def show(params: Params) -> None:
  width = max(len(n) for n in MODS)
  for name, (kind, _, default, desc) in MODS.items():
    if not param_known(name, params):
      value = "NOT COMPILED (rebuild params_pyx.so)"
    elif kind == "bool":
      value = "on" if params.get_bool(name) else "off"
    else:
      raw = params.get(name, return_default=True)
      value = str(raw if raw is not None else default)
    print(f"{name:<{width}}  {value:<8}  {desc}")


def fail(msg: str) -> int:
  print(msg, file=sys.stderr)
  return 1


def main(argv: list[str], params: Params | None = None) -> int:
  params = params or Params()
  if not argv:
    show(params)
    return 0

  cmd, args = argv[0], argv[1:]
  if cmd not in ("on", "off", "set") or not args or args[0] not in MODS:
    return fail(__doc__)
  name = args[0]
  kind, allowed, _, _ = MODS[name]
  if not param_known(name, params):
    return fail(f"{name} isn't compiled into params_pyx.so yet: run the rebuild step first.")

  if cmd in ("on", "off"):
    if kind != "bool":
      return fail(f"{name} takes a value: python3 tools/my_mods.py set {name} {'|'.join(map(str, allowed))}")
    params.put_bool(name, cmd == "on")
  else:
    if kind != "int" or len(args) != 2:
      return fail(f"use: python3 tools/my_mods.py on|off {name}" if kind == "bool" else f"use: set {name} VALUE")
    try:
      value = int(args[1])
    except ValueError:
      return fail(f"{args[1]!r} is not a number")
    if value not in allowed:
      return fail(f"{name} must be one of {', '.join(map(str, allowed))}")
    params.put(name, value)

  show(params)
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
