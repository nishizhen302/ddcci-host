# -*- coding: utf-8 -*-
"""app.Api 的 pin_* 桥接方法单测(注入 FakeBackend + 内联 PinDB)。"""
import app as appmod
from phytune import pins as P
from phytune import vcp_codes as vc
from tests.fakes import FakeBackend


def _api_with(get_returns=None, peek_returns=None):
    api = appmod.Api()
    api._be = FakeBackend(get_returns=get_returns or {}, peek_returns=peek_returns or {})
    pin = P.Pin({
        "ball": "TESTA",
        "share": {"page": 0x10, "offset": 0x20, "mask": 0x07, "shift": 0},
        "default": 0, "domain": "GPIO",
        "funcs": [{"val": 0, "name": "P4D0i", "kind": "gpio_in"},
                  {"val": 1, "name": "P4D0o", "kind": "gpio_out_pp"}],
        "gpio": {"name": "P4D0", "data_page": 0xFE, "data_offset": 0x00, "bit": 0},
        "danger": False, "danger_reason": "",
    })
    api._pin_db = P.PinDB([pin], domain_order=["GPIO"])
    return api


def test_pin_db_returns_grouped():
    r = _api_with().pin_db()
    assert r["ok"] is True
    assert r["domains"][0]["domain"] == "GPIO"
    assert r["domains"][0]["pins"][0]["ball"] == "TESTA"


def test_pin_set_mux_writes():
    api = _api_with(peek_returns={(0x10, 0x20): 0x00})
    r = api.pin_set_mux("TESTA", 1, 0)
    assert r["ok"] is True
    pokes = [s for s in api._be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0x01, 0))


def test_pin_set_mux_rejects_bad_value():
    api = _api_with(peek_returns={(0x10, 0x20): 0x00})
    r = api.pin_set_mux("TESTA", 7, 0)
    assert r["ok"] is False


def test_gpio_set_when_output():
    # 复用 0x10:20 = 0x01(输出PP); 数据 0xFE:00 = 0x00 → 置1
    api = _api_with(peek_returns={(0x10, 0x20): 0x01, (0xFE, 0x00): 0x00})
    r = api.gpio_set("TESTA", 1, 0)
    assert r["ok"] is True
    pokes = [s for s in api._be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0x01, 0))


def test_pin_read_reports_mux_and_level():
    # 复用=1(输出); 电平 0xFE:00 = 0x01
    api = _api_with(peek_returns={(0x10, 0x20): 0x01, (0xFE, 0x00): 0x01})
    r = api.pin_read("TESTA", 0)
    assert r["ok"] is True
    assert r["mux"]["val"] == 1
    assert r["level"] == 1


def test_gpio_read_ok_and_fail():
    # 电平 0xFE:00 = 0x01 → ok level 1
    api = _api_with(peek_returns={(0xFE, 0x00): 0x01})
    r = api.gpio_read("TESTA", 0)
    assert r["ok"] is True and r["level"] == 1
    # 无 peek 应答 → gpio_read 返回 None → {ok:False}
    api2 = _api_with()
    assert api2.gpio_read("TESTA", 0)["ok"] is False


def test_pin_read_offline_returns_hint():
    # 复用读不回(无 peek 应答) → {ok:False, hint}
    api = _api_with()
    r = api.pin_read("TESTA", 0)
    assert r["ok"] is False and r["hint"]


def test_pin_reset_default():
    api = _api_with(peek_returns={(0x10, 0x20): 0x05})
    r = api.pin_reset_default("TESTA", 0)
    assert r["ok"] is True
    pokes = [s for s in api._be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0x00, 0))  # 默认0 -> 0x05&~7=0
