from openpilot.common.params import UnknownKeyName
from openpilot.tools import my_mods


class FakeParams:
  def __init__(self, known):
    self.known, self.values = set(known), {}

  def check_key(self, key):
    if key not in self.known:
      raise UnknownKeyName(key)
    return key

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def get(self, key, return_default=False):
    return self.values.get(key)

  def put_bool(self, key, val):
    self.values[key] = val

  def put(self, key, val):
    self.values[key] = val


def test_list_shows_everything_off_by_default(capsys):
  assert my_mods.main([], FakeParams(my_mods.MODS)) == 0
  lines = capsys.readouterr().out.splitlines()
  values = {line.split()[0]: line.split()[1] for line in lines}
  assert set(values) == set(my_mods.MODS)
  assert values["StopAlert"] == "off" and values["TurnDesireSpeed"] == "25" and values["DMExtraTime"] == "0"


def test_on_off():
  p = FakeParams(my_mods.MODS)
  assert my_mods.main(["on", "StopAlert"], p) == 0 and p.values["StopAlert"] is True
  assert my_mods.main(["off", "StopAlert"], p) == 0 and p.values["StopAlert"] is False


def test_set_int_validated():
  p = FakeParams(my_mods.MODS)
  assert my_mods.main(["set", "TurnDesireSpeed", "22"], p) == 0 and p.values["TurnDesireSpeed"] == 22
  assert my_mods.main(["set", "TurnDesireSpeed", "40"], p) == 1 and p.values["TurnDesireSpeed"] == 22
  assert my_mods.main(["set", "DMExtraTime", "4"], p) == 1
  assert my_mods.main(["on", "DMExtraTime"], p) == 1  # int setting needs "set"


def test_rejects_unknown_and_uncompiled():
  p = FakeParams([])
  assert my_mods.main(["on", "NotAMod"], p) == 1
  assert my_mods.main(["on", "StopAlert"], p) == 1  # not compiled yet: refuse, don't crash
  assert p.values == {}


def test_every_mod_is_registered_off_by_default():
  from openpilot.common.basedir import BASEDIR
  with open(f"{BASEDIR}/common/params_keys.h") as f:
    keys = f.read()
  for name, (kind, _, default, _) in my_mods.MODS.items():
    expected = f'"{default}"' if kind == "int" else '"0"'
    assert f'{{"{name}", {{PERSISTENT, {kind.upper()}, {expected}}}}}' in keys, name
