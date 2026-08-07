# -*- coding: utf-8 -*-
import pytest
from tests.fakes import FakeBackend
from phytune.regaccess import RegAccess
from phytune import vcp_codes as vc
from phytune import ced


# ---- 纯解析 ----

def test_parse_ced_combines_lsb_msb_and_valid():
    # MSB bit7=1 有效, 低7位=0x01 → count = 0x34 | (0x01<<8) = 0x134
    assert ced.parse_ced(0x34, 0x81) == {"count": 0x134, "valid": True}


def test_parse_ced_invalid_when_msb_bit7_clear():
    assert ced.parse_ced(0x00, 0x00) == {"count": 0, "valid": False}


def test_parse_ced_max_15bit():
    assert ced.parse_ced(0xFF, 0xFF) == {"count": 0x7FFF, "valid": True}


def test_scdc_page_offsets_by_port():
    assert [ced.scdc_page(p) for p in (2, 3, 4, 5)] == [0x71, 0x72, 0x73, 0x74]


def test_scdc_page_rejects_bad_port():
    with pytest.raises(ValueError):
        ced.scdc_page(6)


# ---- SCDC 间接读序列 ----

def test_read_scdc_selects_offset_then_reads_data():
    # 读 SCDC 0x50: 先 poke 0x39<-0x50, 再 peek 0x3A
    be = FakeBackend(scdc_returns={0x50: 0x34})
    ra = RegAccess(be, 0)
    val = ra.read_scdc(0x71, 0x50)
    assert val == 0x34
    # 序列: 锁存 0x7139 → poke 0x50 → 锁存 0x713A → (get 读数据)
    assert be.sets == [
        (0, vc.VCP_ADDR_LATCH, 0x7139),
        (0, vc.VCP_POKE, 0x0050),
        (0, vc.VCP_ADDR_LATCH, 0x713A),
    ]


def test_read_scdc_none_when_select_fails():
    be = FakeBackend()
    be.set_result = False
    ra = RegAccess(be, 0)
    assert ra.read_scdc(0x71, 0x50) is None


# ---- 三通道 CED ----

def test_read_ced_three_channels_d2():
    # Ch0=R 有 0x012 个误码, Ch1=G 0, Ch2=B 0x105; 均有效
    be = FakeBackend(scdc_returns={
        0x50: 0x12, 0x51: 0x80,   # Ch0: 0x012 valid
        0x52: 0x00, 0x53: 0x80,   # Ch1: 0 valid
        0x54: 0x05, 0x55: 0x81,   # Ch2: 0x105 valid
    })
    ra = RegAccess(be, 0)
    r = ced.read_ced(ra, port=2)
    assert r["valid"] is True
    assert r["channels"] == [
        {"name": "ch0", "label": "R", "count": 0x012, "valid": True},
        {"name": "ch1", "label": "G", "count": 0x000, "valid": True},
        {"name": "ch2", "label": "B", "count": 0x105, "valid": True},
    ]


def test_read_ced_invalid_link_all_zero():
    # 非加扰/低速链路: 所有 MSB bit7=0 → valid=False(误码统计未运行)
    be = FakeBackend(scdc_returns={o: 0x00 for o in (0x50, 0x51, 0x52, 0x53, 0x54, 0x55)})
    ra = RegAccess(be, 0)
    r = ced.read_ced(ra, port=2)
    assert r["valid"] is False
    assert all(c["count"] == 0 and c["valid"] is False for c in r["channels"])


def test_read_ced_uses_port_page_d3():
    # D3: SCDC 选择/数据应落在页 0x72
    be = FakeBackend(scdc_returns={0x50: 0x01, 0x51: 0x80, 0x52: 0, 0x53: 0x80, 0x54: 0, 0x55: 0x80})
    ra = RegAccess(be, 0)
    ced.read_ced(ra, port=3)
    assert be.sets[0] == (0, vc.VCP_ADDR_LATCH, 0x7239)   # D3 → 页 0x72


def test_read_ced_none_when_read_fails():
    be = FakeBackend()   # 无 scdc_returns → read_scdc 的 peek 返回 None
    ra = RegAccess(be, 0)
    assert ced.read_ced(ra, port=2) is None
