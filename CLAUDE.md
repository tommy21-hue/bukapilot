# Rules for Claude Code: bukapilot on a 2024 BYD Seal Premium (KommuAssist 2)

## Never change
- Panda safety code (anything under panda/board/safety) or its torque, steering-rate, acceleration or braking limits.
- The BYD car port's control limits (max steering torque, rate limits, accel/brake limits).
- Disengaging on brake pedal, accelerator override or steering override.
- Driver monitoring, EXCEPT: widening the face/gaze angle accepted as attentive so mirror and side-window checks don't alert, and adding up to 3 seconds ON TOP of the stock time before the first warning. Never make any driver monitoring time shorter than stock. Never silence or remove driver monitoring alerts.
- The car must never pull away from a stop without the driver pressing the accelerator.
If a feature would need any of the above, STOP and tell me instead of doing it.

## How to work
- Before editing, list the files you plan to change and why, then wait for my OK.
- Every new feature gets its own toggle in Settings, OFF by default, stored as a Param.
- All work happens on the my-mods branch, one commit per feature with a clear message.
- Reference forks are in ../ref-sunnypilot and ../ref-frogpilot (MIT licensed). Port ideas from there and keep their licence notices.
- Run existing tests and linting for anything you touch; add tests where the repo has a pattern for them.
- Explain things simply. I'm learning.

## Feature requirements
- Nudgeless lane change: blinker on, speed at least 60 km/h, blind spot clear on that side from the car's own BSM signal, abort if BSM triggers mid-change.
- Turn desires: only below a set low speed (default 25 km/h, adjustable 20-30 km/h in Settings), blinker-triggered, within stock steering limits.