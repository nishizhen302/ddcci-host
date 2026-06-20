# -*- coding: utf-8 -*-
"""Pin / PinDB 单测: 位域读改写、复用校验、GPIO 电平、还原默认、分组搜索。"""
import pytest
from backends.base import Monitor
from tests.fakes import FakeBackend
from phytune.regaccess import RegAccess
from phytune import vcp_codes as vc
from phytune import pins as P


def _pin_y6():
    # Y6: pinshare P10_00[2:0]; 默认 0(输入); funcs 0=输入/2=开漏输出/3=AUX_P1;
    # GPIO 数据寄存器 0xFE00 bit0
    return P.Pin({
        "ball": "Y6",
        "share": {"page": 0x10, "offset": 0x00, "mask": 0x07, "shift": 0},
        "default": 0,
        "domain": "AUX_DP",
        "funcs": [
            {"val": 0, "name": "P1D0i", "kind": "gpio_in"},
            {"val": 1, "name": "reserved", "kind": "reserved"},
            {"val": 2, "name": "P1D0o", "kind": "gpio_out_od"},
            {"val": 3, "name": "AUX_P1", "kind": "periph"},
        ],
        "gpio": {"name": "P1D0", "data_page": 0xFE, "data_offset": 0x00, "bit": 0},
        "danger": False, "danger_reason": "",
    })


def _ra(get_returns=None):
    be = FakeBackend(get_returns=get_returns or {})
    return be, RegAccess(be, 0)


def test_read_mux_extracts_bitfield():
    # pinshare 当前 = 0xF3 → 低3位 = 3 = AUX_P1
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0xF3, 0xFF)})
    r = _pin_y6().read_mux(ra)
    assert r == {"val": 3, "name": "AUX_P1", "kind": "periph"}


def test_set_mux_read_modify_write_preserves_other_bits():
    # 当前 0xF3, 设复用=2 → 应写 0xF2 (高5位不动, 低3位=2)
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0xF3, 0xFF)})
    assert _pin_y6().set_mux(ra, 2) is True
    pokes = [s for s in be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0xF2, 0))


def test_set_mux_rejects_reserved_and_unknown():
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0x00, 0xFF)})
    pin = _pin_y6()
    with pytest.raises(ValueError):
        pin.set_mux(ra, 1)   # reserved
    with pytest.raises(ValueError):
        pin.set_mux(ra, 7)   # 不在 funcs


def test_gpio_set_requires_gpio_output_mode():
    # 复用当前=0(输入) → 置电平应被拒
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0x00, 0xFF)})
    with pytest.raises(ValueError):
        _pin_y6().gpio_set(ra, 1)


def test_gpio_set_writes_bit_when_output():
    # 复用=2(开漏输出), 数据寄存器当前 0x00 → 置1 应写 0x01 到 0xFE00
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x02, 0xFF)})
    ra = RegAccess(be, 0)
    assert _pin_y6().gpio_set(ra, 1) is True
    pokes = [s for s in be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0x01, 0))


def test_gpio_set_rejected_when_no_mapping():
    p = _pin_y6()
    p.gpio = None
    be, ra = _ra()
    with pytest.raises(ValueError):
        p.gpio_set(ra, 1)


def test_reset_default_writes_default_value():
    # 默认 0, 当前 0xF3 → 写回 0xF0
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0xF3, 0xFF)})
    assert _pin_y6().reset_default(ra) is True
    pokes = [s for s in be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0xF0, 0))


def test_pindb_group_and_search():
    db = P.PinDB([_pin_y6()], domain_order=["GPIO", "AUX_DP"])
    groups = db.by_domain()
    assert groups == [("AUX_DP", [db.by_ball("Y6")])]
    assert db.search("aux")[0].ball == "Y6"   # 按功能名命中
    assert db.search("y6")[0].ball == "Y6"     # 按球名命中
    assert db.search("zzz") == []
