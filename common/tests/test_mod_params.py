from openpilot.common.params import UnknownKeyName
from openpilot.common.mod_params import param_known, get_bool_safe, get_int_safe


class FakeParams:
  """Stands in for a params_pyx.so that only knows some keys."""
  def __init__(self, values):
    self.values = values

  def check_key(self, key):
    if key not in self.values:
      raise UnknownKeyName(key)
    return key

  def get_bool(self, key):
    self.check_key(key)
    return bool(self.values[key])

  def get(self, key, return_default=False):
    self.check_key(key)
    return self.values[key]


P = FakeParams({"KnownOn": True, "KnownOff": False, "Speed": 27, "Unset": None})


def test_param_known():
  assert param_known("KnownOn", P)
  assert not param_known("NotCompiledYet", P)


def test_get_bool_safe():
  assert get_bool_safe("KnownOn", P)
  assert not get_bool_safe("KnownOff", P)
  # unknown key (params_pyx.so not rebuilt yet) means feature off, not a crash
  assert not get_bool_safe("NotCompiledYet", P)


def test_get_int_safe():
  assert get_int_safe("Speed", 25, P) == 27
  assert get_int_safe("Unset", 25, P) == 25
  assert get_int_safe("NotCompiledYet", 25, P) == 25
