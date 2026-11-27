"""Safe Param access for my-mods features.

This branch is "prebuilt": the list of allowed Param names is compiled into params_pyx.so, and the
device does not rebuild it. If a mod's Param name isn't in that compiled list yet, plain
Params().get_bool() raises UnknownKeyName and would crash the process (selfdrived, the UI...).
These helpers treat an unknown name as "feature off", so a missed rebuild can never break driving.
"""
from openpilot.common.params import Params, UnknownKeyName


def param_known(key: str, params: Params | None = None) -> bool:
  try:
    (params or Params()).check_key(key)
    return True
  except UnknownKeyName:
    return False


def get_bool_safe(key: str, params: Params | None = None) -> bool:
  """Params.get_bool, but False when the key isn't compiled into params_pyx.so yet."""
  try:
    return (params or Params()).get_bool(key)
  except UnknownKeyName:
    return False


def get_int_safe(key: str, default: int, params: Params | None = None) -> int:
  """Params.get for an INT param, falling back to default when unknown or unset."""
  try:
    val = (params or Params()).get(key, return_default=True)
  except UnknownKeyName:
    return default
  try:
    return int(val) if val is not None else default
  except (TypeError, ValueError):
    return default
