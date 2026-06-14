# -*- coding: utf-8 -*-
import pytest
from tests.fakes import FakeBackend
from phytune.regaccess import RegAccess
from phytune import vcp_codes as vc
from phytune import params as P


def test_load_params_has_groups_and_params():
    model = P.load_params()
    assert {g["id"] for g in model.groups} == {"freq", "cdr", "dfe"}
    names = {p.name for p in model.params}
    assert {"freq_offset", "freq_stable", "cdr_icp", "dfe_le_l0", "dfe_le_l1", "dfe_le_l2"} <= names


def test_param_lookup_and_fields():
    model = P.load_params()
    p = model.by_name("freq_offset")
    assert (p.page, p.offset, p.mask, p.shift) == (0x71, 0xE7, 0x07, 0)
    assert p.min == 0 and p.max == 7 and p.live is True


def test_read_extracts_bitfield():
    # 寄存器当前值 0x8C; dfe_le mask 0x3F → 0x0C = 12
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x8C, 0xFF)})
    ra = RegAccess(be, 0)
    p = P.load_params().by_name("dfe_le_l0")
    assert p.read(ra) == 12


def test_write_is_read_modify_write_preserving_other_bits():
    # 当前 0x8C(bit7=1); 写 dfe_le=20(0x14) → (0x8C & ~0x3F)|0x14 = 0x94
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x8C, 0xFF)})
    ra = RegAccess(be, 0)
    p = P.load_params().by_name("dfe_le_l0")
    assert p.write(ra, 20) is True
    # 最后一笔 set 应是 poke 写入 0x94
    assert be.sets[-1] == (0, vc.VCP_POKE, 0x0094)


def test_write_rejects_out_of_range():
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x8C, 0xFF)})
    ra = RegAccess(be, 0)
    p = P.load_params().by_name("dfe_le_l0")
    with pytest.raises(ValueError):
        p.write(ra, 25)   # > max 24


def test_write_returns_false_when_peek_fails():
    be = FakeBackend()           # get 返回 None → peek 失败
    ra = RegAccess(be, 0)
    p = P.load_params().by_name("freq_offset")
    assert p.write(ra, 3) is False


def test_write_with_shift_and_mask():
    # 构造一个 shift 测试: freq_offset mask 0x07 shift 0, 当前 0xF5 → 写 2 → (0xF5&~7)|2 = 0xF2
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0xF5, 0xFF)})
    ra = RegAccess(be, 0)
    p = P.load_params().by_name("freq_offset")
    p.write(ra, 2)
    assert be.sets[-1] == (0, vc.VCP_POKE, 0x00F2)


def test_eff_page_offsets_by_port():
    # freq base 0x71(D2); D3=0x72 D4=0x73 D5=0x74。DFE base 0x7B; D3=0x7C。
    m = P.load_params()
    f = m.by_name("freq_offset")
    assert [f.eff_page(p) for p in (2, 3, 4, 5)] == [0x71, 0x72, 0x73, 0x74]
    assert m.by_name("dfe_le_l0").eff_page(3) == 0x7C


def test_eff_page_rejects_bad_port():
    p = P.load_params().by_name("freq_offset")
    with pytest.raises(ValueError):
        p.eff_page(6)
    with pytest.raises(ValueError):
        p.eff_page(1)


def test_read_uses_port_page_for_latch():
    # D3 读 dfe_le_l0 → 应锁存 P7C_A2 = 0x7CA2(不是 D2 的 0x7BA2)
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x8C, 0xFF)})
    ra = RegAccess(be, 0)
    p = P.load_params().by_name("dfe_le_l0")
    p.read(ra, port=3)
    assert be.sets[-1] == (0, vc.VCP_ADDR_LATCH, 0x7CA2)


def test_write_uses_port_page():
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x8C, 0xFF)})
    ra = RegAccess(be, 0)
    p = P.load_params().by_name("dfe_le_l0")
    p.write(ra, 20, port=3)
    # 首笔=按 D3 页锁存 0x7CA2; 末笔=poke 0x94 (poke 内部会再锁存一次, 故中间还有一笔 latch)
    assert be.sets[0] == (0, vc.VCP_ADDR_LATCH, 0x7CA2)
    assert be.sets[-1] == (0, vc.VCP_POKE, 0x0094)
