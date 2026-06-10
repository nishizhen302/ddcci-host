# -*- coding: utf-8 -*-
"""阶段 1 单测: 后端抽取 + caps 解析。

可用 pytest 跑 (py -3 -m pytest tests/), 也可直接 py -3 tests/test_core.py。
"""
import ctypes
from ctypes import wintypes

import ddcci_core
from backends.base import Backend, Monitor
from backends.dxva2_backend import Dxva2Backend, dxva2


# 真板 caps 串样例 (RL6432, model(RTK), 顶层 vcp 列表 + 72 带允许值)。
SAMPLE_CAPS = (
    "(prot(monitor)type(LCD)model(RTK)cmds(01 02 03 07 0C E3 F3)"
    "vcp(10 12 14(05 08 0B) 16 18 1A 60(01 03 11) 72(00 01 02 03 04) AC AE)"
    "mccs_ver(2.2))"
)


def test_backend_is_subclass():
    assert issubclass(Dxva2Backend, Backend)


def test_select_backend_returns_instance():
    be = ddcci_core.select_backend("dxva2")
    try:
        assert isinstance(be, Dxva2Backend)
        assert be.name == "dxva2"
        assert be.address == 0x6E
    finally:
        be.close()


def test_select_backend_unknown_raises():
    try:
        ddcci_core.select_backend("nope")
    except ValueError:
        return
    raise AssertionError("未知后端应抛 ValueError")


def test_argtypes_guard():
    # 防 64 位句柄截断 + VCP code 必须 c_ubyte (有符号 BYTE 会出错) —— 声明须在位。
    assert dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes[0] is wintypes.HANDLE
    assert dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes[1] is ctypes.c_ubyte
    assert dxva2.SetVCPFeature.argtypes[0] is wintypes.HANDLE
    assert dxva2.SetVCPFeature.argtypes[1] is ctypes.c_ubyte


def test_parse_caps_vcp_codes():
    r = ddcci_core.parse_caps(SAMPLE_CAPS)
    # 顶层 VCP code 都在
    for code in (0x10, 0x12, 0x14, 0x16, 0x18, 0x1A, 0x60, 0x72, 0xAC, 0xAE):
        assert code in r["vcp_codes"], "缺 0x%02X" % code
    # 嵌套允许值不算 VCP code
    assert 0x11 not in r["vcp_codes"]   # 60 的允许值
    assert 0x05 not in r["vcp_codes"]   # 14 的允许值
    assert 0x04 not in r["vcp_codes"]   # 72 的允许值


def test_parse_caps_model_type():
    r = ddcci_core.parse_caps(SAMPLE_CAPS)
    assert r["model"] == "RTK"
    assert r["type"] == "LCD"


def test_parse_caps_empty():
    r = ddcci_core.parse_caps("")
    assert r["vcp_codes"] == set()
    assert r["model"] is None
    r2 = ddcci_core.parse_caps(None)
    assert r2["vcp_codes"] == set()


def test_monitor_dataclass():
    m = Monitor(3, "Generic PnP Monitor")
    assert m.id == 3 and m.description == "Generic PnP Monitor"


if __name__ == "__main__":
    # 无 pytest 也能跑: 逐个调用 test_*。
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception as e:
            failed += 1
            print("FAIL", fn.__name__, "->", repr(e))
    print("\n%d passed, %d failed" % (len(fns) - failed, failed))
    raise SystemExit(1 if failed else 0)
