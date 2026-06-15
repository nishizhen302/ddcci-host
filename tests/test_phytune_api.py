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
    assert {g["id"] for g in r["groups"]} == {"freq", "cdr", "dfe", "ssc"}
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


def test_api_param_write_targets_selected_port():
    # D3: dfe_le_l0 写应打到 P7C(0x7C) 而非默认 D2 的 0x7B
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x8C, 0xFF)})
    api = _api_with_fake(be)
    r = api.phytune_param_write("dfe_le_l0", 20, 0, 3)
    assert r["ok"] is True
    assert be.sets[0] == (0, vc.VCP_ADDR_LATCH, 0x7CA2)


def test_api_override_pin_targets_selected_port():
    be = FakeBackend()
    api = _api_with_fake(be)
    r = api.phytune_override_pin("dfe_le_l0", 0, 3)   # D3 → P7C_A2 = 0x7CA2
    assert r == {"ok": True, "slot": 0}
    assert be.sets == [
        (0, vc.VCP_ADDR_LATCH, 0x7CA2),
        (0, vc.VCP_OVERRIDE, (vc.OVERRIDE_OP_PIN << 8) | 0),
    ]


def test_api_dfe_freeze_writes_en2_zero_on_three_lanes():
    be = FakeBackend()
    api = _api_with_fake(be)
    r = api.phytune_dfe_freeze(0, True, 2)   # D2 → 页 0x7B, A1/B1/C1 <- 0x00
    assert r["ok"] is True
    assert be.sets == [
        (0, vc.VCP_ADDR_LATCH, 0x7BA1), (0, vc.VCP_POKE, 0x0000),
        (0, vc.VCP_ADDR_LATCH, 0x7BB1), (0, vc.VCP_POKE, 0x0000),
        (0, vc.VCP_ADDR_LATCH, 0x7BC1), (0, vc.VCP_POKE, 0x0000),
    ]


def test_api_dfe_freeze_off_restores_and_uses_port_page():
    be = FakeBackend()
    api = _api_with_fake(be)
    r = api.phytune_dfe_freeze(0, False, 3)   # D3 → 页 0x7C, 恢复 0xC3
    assert r["ok"] is True
    assert be.sets[0] == (0, vc.VCP_ADDR_LATCH, 0x7CA1)
    assert be.sets[1] == (0, vc.VCP_POKE, 0x00C3)


def test_api_dfe_reload_single_lane_toggles_init8():
    # lane0 → P7B_AA, 当前 0x00 → 置 0x06 再清 0x00
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x00, 0xFF)})
    api = _api_with_fake(be)
    r = api.phytune_dfe_reload(0, 2, 0)
    assert r["ok"] is True
    # 末两笔 poke = 置 0x06 / 清 0x00
    pokes = [s for s in be.sets if s[1] == vc.VCP_POKE]
    assert pokes == [(0, vc.VCP_POKE, 0x0006), (0, vc.VCP_POKE, 0x0000)]


def test_api_dfe_reload_all_lanes_targets_three_regs():
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x00, 0xFF)})
    api = _api_with_fake(be)
    r = api.phytune_dfe_reload(0, 2)   # lane=None → AA/BA/CA 全部
    assert r["ok"] is True
    latched = [s[2] for s in be.sets if s[1] == vc.VCP_ADDR_LATCH]
    # 每个 reg: 1 次 peek 锁存 + 2 次 poke 前的锁存 = 3 次, 三个 reg 应含 7BAA/7BBA/7BCA
    assert 0x7BAA in latched and 0x7BBA in latched and 0x7BCA in latched


def test_api_ced_read_returns_three_channels():
    be = FakeBackend(scdc_returns={
        0x50: 0x0A, 0x51: 0x80,   # Ch0(R): 10 valid
        0x52: 0x00, 0x53: 0x80,   # Ch1(G): 0
        0x54: 0x00, 0x55: 0x80,   # Ch2(B): 0
    })
    api = _api_with_fake(be)
    r = api.phytune_ced_read(0, 2)
    assert r["ok"] is True and r["valid"] is True
    assert [c["count"] for c in r["channels"]] == [10, 0, 0]
    assert [c["label"] for c in r["channels"]] == ["R", "G", "B"]


def test_api_ced_read_targets_port_page():
    be = FakeBackend(scdc_returns={o: (0x80 if o & 1 else 0) for o in range(0x50, 0x56)})
    api = _api_with_fake(be)
    r = api.phytune_ced_read(0, 3)
    assert r["ok"] is True
    assert be.sets[0] == (0, vc.VCP_ADDR_LATCH, 0x7239)   # D3 → SCDC 选择落页 0x72


def test_api_output_enable_off_clears_rgb_bits_on_port():
    # D3: P72_A6, 当前 0xF5 → 关输出 = 清 bit[6:5:4](0x70) → 0x85
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0xF5, 0xFF)})
    api = _api_with_fake(be)
    r = api.phytune_output_enable(0, False, 3)
    assert r["ok"] is True
    assert be.sets[0] == (0, vc.VCP_ADDR_LATCH, 0x72A6)
    assert be.sets[-1] == (0, vc.VCP_POKE, 0x0085)


def test_api_output_enable_on_sets_rgb_bits():
    # D2: P71_A6, 当前 0x85 → 开输出 = 置 0x70 → 0xF5
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x85, 0xFF)})
    api = _api_with_fake(be)
    r = api.phytune_output_enable(0, True, 2)
    assert r["ok"] is True
    assert be.sets[0] == (0, vc.VCP_ADDR_LATCH, 0x71A6)
    assert be.sets[-1] == (0, vc.VCP_POKE, 0x00F5)
