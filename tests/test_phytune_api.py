# -*- coding: utf-8 -*-
from tests.fakes import FakeBackend
from phytune import vcp_codes as vc
import app


def _api_with_fake(be):
    api = app.Api()
    api._be = be          # 直接注入替身, 跳过 _ensure 的真实后端
    return api


def test_api_phytune_poke_ok():
    be = FakeBackend()
    api = _api_with_fake(be)
    r = api.phytune_poke(0x7B, 0xA2, 0x8C, 0, 0)
    assert r["ok"] is True
    assert be.sets[-1] == (0, vc.VCP_POKE, 0x008C)


def test_api_phytune_peek_returns_value():
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x3F, 0xFF)})
    api = _api_with_fake(be)
    r = api.phytune_peek(0x71, 0xEC, 0)
    assert r == {"ok": True, "value": 0x3F}


def test_api_phytune_peek_fail():
    be = FakeBackend()
    be.set_result = False
    api = _api_with_fake(be)
    r = api.phytune_peek(0x71, 0xEC, 0)
    assert r["ok"] is False


def test_api_phytune_params_lists_groups_and_params():
    api = _api_with_fake(FakeBackend())
    r = api.phytune_params()
    assert r["ok"] is True
    assert {g["id"] for g in r["groups"]} == {"freq", "cdr", "dfe"}
    assert any(p["name"] == "freq_offset" for p in r["params"])


def test_api_param_read_extracts_field():
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x8C, 0xFF)})
    api = _api_with_fake(be)
    r = api.phytune_param_read("dfe_le_l0", 0)
    assert r == {"ok": True, "value": 12}


def test_api_param_write_read_modify_write():
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x8C, 0xFF)})
    api = _api_with_fake(be)
    r = api.phytune_param_write("dfe_le_l0", 20, 0)
    assert r["ok"] is True
    assert be.sets[-1] == (0, vc.VCP_POKE, 0x0094)


def test_api_override_pin_uses_param_slot():
    be = FakeBackend()
    api = _api_with_fake(be)
    r = api.phytune_override_pin("dfe_le_l0", 0)   # slot 0, P7B_A2 = 0x7BA2
    assert r == {"ok": True, "slot": 0}
    assert be.sets == [
        (0, vc.VCP_ADDR_LATCH, 0x7BA2),
        (0, vc.VCP_OVERRIDE, (vc.OVERRIDE_OP_PIN << 8) | 0),
    ]


def test_api_override_pin_rejects_live_param():
    be = FakeBackend()
    api = _api_with_fake(be)
    r = api.phytune_override_pin("freq_offset", 0)   # live, slot=None
    assert r["ok"] is False
    assert be.sets == []


def test_api_override_clear_sends_clear():
    be = FakeBackend()
    api = _api_with_fake(be)
    r = api.phytune_override_clear("dfe_le_l1", 0)    # slot 1
    assert r["ok"] is True
    assert be.sets == [(0, vc.VCP_OVERRIDE, (vc.OVERRIDE_OP_CLEAR << 8) | 1)]


def test_api_override_clearall():
    be = FakeBackend()
    api = _api_with_fake(be)
    r = api.phytune_override_clearall(0)
    assert r["ok"] is True
    assert be.sets == [(0, vc.VCP_OVERRIDE, (vc.OVERRIDE_OP_CLEARALL << 8) | 0)]
