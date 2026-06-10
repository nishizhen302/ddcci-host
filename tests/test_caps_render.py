# -*- coding: utf-8 -*-
"""阶段 3 单测: caps -> 控件集。

控件由 caps 驱动: parse_caps 给出"支持哪些 VCP + 各自允许值",前端据此生成控件集。
这里在数据层断言: 允许值提取正确, 且按 前端同样的划分规则 (主控件 / 信号源 / raw 兜底)
得到的控件集符合预期 —— 不同 caps -> 不同控件集。
"""
import ddcci_core

# 与 ui/app.js 一致的划分常量
MAIN_ORDER = [0x72, 0x10, 0x12, 0x14]
SIGNAL_VCP = 0x60

# RTK = 真板 caps; DELL = 构造串(含裸 72 以覆盖"无允许值括号"用例, 不等同真机 U2724D)
RTK_CAPS = (
    "(prot(monitor)type(LCD)model(RTK)cmds(01 02 03 07 0C E3 F3)"
    "vcp(02 04 05 06 08 0B 0C 10 12 14(01 02 04 05 06 08 0B) 16 18 1A 52 "
    "60(01 03 04 0F 10 11 12) 72(00 01 02 03 04) 87 AC AE B2 B6 C6 C8 "
    "CA CC(01 02 03 04 06 0A 0D) D6(01 04 05) DF FD FF)mswhql(1)asset_eep(40)mccs_ver(2.2))"
)
DELL_CAPS = (
    "(prot(monitor)type(LCD)model(U2724D)cmds(01 02 03 07 0C E3 F3)"
    "vcp(02 04 05 08 10 12 14(01 04 05 06 08 09 0B 0C) 16 18 1A 52 60(0F 11 ) "
    "72 87 AC AE B2 B6 C6 C8 C9 CA D6(01 04 05) DF E0(03) F0(09 0A A1 ) FD)"
    "mccs_ver(2.1))"
)


def classify(caps):
    """复刻前端控件集划分, 返回 (主控件codes, 有信号源?, raw兜底codes)。"""
    info = ddcci_core.parse_caps(caps)
    codes = info["vcp_codes"]
    main = [c for c in MAIN_ORDER if c in codes]
    has_signal = SIGNAL_VCP in codes
    known = set(MAIN_ORDER) | {SIGNAL_VCP}
    raw = sorted(c for c in codes if c not in known)
    return main, has_signal, raw, info


def test_rtk_allowed_values():
    info = ddcci_core.parse_caps(RTK_CAPS)
    assert info["vcp_values"][0x14] == [1, 2, 4, 5, 6, 8, 11]   # 色温预设
    assert info["vcp_values"][0x72] == [0, 1, 2, 3, 4]          # gamma 档
    assert info["vcp_values"][0x60] == [1, 3, 4, 15, 16, 17, 18]  # 信号源
    # 连续值 VCP 无嵌套允许值 -> 空列表
    assert info["vcp_values"][0x10] == []
    assert info["vcp_values"][0x12] == []


def test_rtk_control_set():
    main, has_signal, raw, _ = classify(RTK_CAPS)
    assert main == [0x72, 0x10, 0x12, 0x14]   # 四个主控件都在
    assert has_signal is True
    # raw 兜底里不含主控件 / 信号源, 但含确实存在的其他 VCP
    for c in (0x72, 0x10, 0x12, 0x14, 0x60):
        assert c not in raw
    assert 0xCC in raw and 0x52 in raw and 0xFF in raw


def test_dell_differs_from_rtk():
    rtk_main, _, _, _ = classify(RTK_CAPS)
    dell_main, dell_sig, dell_raw, dell_info = classify(DELL_CAPS)
    # Dell 也有这几个主控件, 但允许值集不同 (caps 驱动 -> 控件内容不同)
    assert dell_info["vcp_values"][0x14] == [1, 4, 5, 6, 8, 9, 11, 12]
    assert dell_info["vcp_values"][0x14] != ddcci_core.parse_caps(RTK_CAPS)["vcp_values"][0x14]
    # Dell 的 0x72 无允许值括号(连续/无枚举), RTK 的有 -> 不同显示器控件来源不同
    assert dell_info["vcp_values"][0x72] == []
    # Dell 有 E0 这种 RTK 没有的 raw VCP
    assert 0xE0 in dell_raw and 0xE0 not in classify(RTK_CAPS)[2]


def test_unknown_only_falls_to_raw():
    # 只有一个未知 VCP 的显示器 -> 无主控件, 该 VCP 落 raw 兜底
    caps = "(prot(monitor)type(LCD)model(X)vcp(AB)mccs_ver(2.2))"
    main, has_signal, raw, _ = classify(caps)
    assert main == [] and has_signal is False
    assert raw == [0xAB]


def test_segment_options_from_caps():
    # 色温 segment 选项 = caps 允许值 (而非写死)
    info = ddcci_core.parse_caps("(vcp(14(04 05 08)))")
    assert info["vcp_values"][0x14] == [4, 5, 8]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print("PASS", fn.__name__)
        except Exception as e:
            failed += 1; print("FAIL", fn.__name__, "->", repr(e))
    print("\n%d passed, %d failed" % (len(fns) - failed, failed))
    raise SystemExit(1 if failed else 0)
