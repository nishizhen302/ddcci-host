# -*- coding: utf-8 -*-
"""gpu_i2c_backend 离线单测 —— 结构体布局 + 探测/收发逻辑 (假通道, 不碰显卡)。"""
import ctypes

from backends import gpu_i2c_backend as G
from backends.raw_usb_backend import ddc_frame, get_vcp_payload


def test_nv_i2c_info_layout():
    # 2026-07-24 真机抓包确认要用 V1(不是 V3)。x64 上 NV_I2C_INFO_V1 = 48 字节
    # (对齐后)，version 高 16 位 = 1，低 16 位 = sizeof。
    assert ctypes.sizeof(G._NvI2cInfoV1) == 48
    assert G._NV_I2C_INFO_VER1 >> 16 == 1
    assert G._NV_I2C_INFO_VER1 & 0xFFFF == 48


def test_adl_i2c_layout():
    # 7 个 int + 对齐 + 指针 = 40 字节 (x64)
    assert ctypes.sizeof(G._AdlI2c) == 40


def _fake_funcs(accepted_handle):
    """假 nvapi: 只有 handle == accepted_handle 的 I2CWrite 不回 -8。"""
    calls = []

    def write(handle, _info):
        h = handle.value or 0
        calls.append(h)
        return 0 if h == accepted_handle else G._NVAPI_INVALID_HANDLE

    return {"I2CWrite": write}, calls


def test_nv_handle_probed_when_only_one_display_enumerated(monkeypatch):
    """回归 2026-07-30: 只接一块屏时不能拿 masks[0] 当 handle。

    抓包那台机 handle=0x100 / 目标屏 mask=0x400。屏数一变, masks[0] 就是 0x400,
    而 0x400 当 handle 恒 -8 —— 整条通道看着像死了 (GUI 报 0x5E 无应答)。
    """
    monkeypatch.delenv("DDCCI_NV_HANDLE", raising=False)
    funcs, calls = _fake_funcs(0x100)
    h = G._pick_nv_handle(funcs, [0x400], [], 0x5E)
    assert h.value == 0x100
    assert calls[0] == 0x400          # 先试枚举到的 mask (老规则), 被 -8 挡掉
    assert 0x100 in calls             # 再扫单 bit 候选, 探到能用的


def test_nv_handle_prefers_enumerated_mask_when_it_works(monkeypatch):
    """两块屏都在时行为不变: masks[0] 就是对的, 一次命中不乱扫。"""
    monkeypatch.delenv("DDCCI_NV_HANDLE", raising=False)
    funcs, calls = _fake_funcs(0x100)
    h = G._pick_nv_handle(funcs, [0x100, 0x400], [], 0x5E)
    assert h.value == 0x100
    assert calls == [0x100]


def test_nv_handle_env_override(monkeypatch):
    monkeypatch.setenv("DDCCI_NV_HANDLE", "0x800")
    funcs, calls = _fake_funcs(0x100)
    assert G._pick_nv_handle(funcs, [0x400], [], 0x5E).value == 0x800
    assert calls == []                # 人工指定就不探了


def test_nv_handle_falls_back_when_all_rejected(monkeypatch):
    """全候选都 -8 (驱动层真的没了): 退回老行为, 让上层报"无应答"而不是崩。"""
    monkeypatch.delenv("DDCCI_NV_HANDLE", raising=False)
    funcs, _ = _fake_funcs(None)
    assert G._pick_nv_handle(funcs, [0x400], [], 0x5E).value == 0x400


def test_nv_handle_candidates_cover_recipe_values():
    cands = [c.value or 0 for c in G._nv_handle_candidates([0x400], [])]
    assert cands[0] == 0x400          # 枚举到的优先
    assert 0x100 in cands             # 抓包实证过的那个值一定在表里
    assert len(cands) == len(set(cands))


def test_dedup_keeps_first_channel_per_screen():
    """同一台屏在 nv64 直连和 nv32 桥上各出现一次时, UI 只该看到一条。

    2026-07-30: handle 修好后两条通道同时通了, 简化文案后两行字一模一样。
    """
    class C:
        def __init__(self, label, desc):
            self.label, self.desc = label, desc

    a = C("JRD UC1190_DVI", "JRD UC1190_DVI (mask 0x100)")
    b = C("JRD UC1190_DVI", "NVIDIA(32桥) JRD UC1190_DVI (mask 0x100)")
    c = C("DEL U2412", "DEL U2412 (mask 0x400)")
    assert G._dedup_by_label([a, b, c]) == [a, c]


def test_enum_monitors_shows_only_screen_name_and_address():
    class C:
        label = "JRD UC1190_DVI"
        desc = "JRD UC1190_DVI (mask 0x100)"

    be = GpuBackendForTest([C()], slave=0x5E)
    assert be.enum_monitors()[0].description == "JRD UC1190_DVI (DDC/CI 0x5E)"


class FakeChannel:
    """记录写入、按脚本回读的假通道。"""

    def __init__(self, reply=None, fail_write=False, slave=0x5E):
        self.desc = "fake"
        self.slave = slave
        self.writes = []
        self._reply = reply or []
        self._fail_write = fail_write

    def i2c_write(self, data):
        if self._fail_write:
            return False
        self.writes.append(list(data))
        return True

    def i2c_read(self, n):
        return list(self._reply[:n])


def _brightness_reply(cur=0x32, mx=0x64):
    frame = [0x5E, 0x88, 0x02, 0x00, 0x10, 0x00, 0x00, mx, 0x00, cur]
    chk = 0x50
    for b in frame:
        chk ^= b
    return frame + [chk]


def test_probe_ok_on_reply():
    ch = FakeChannel(reply=_brightness_reply())
    assert G._probe(ch, settle=0)
    # 探测发的就是"读亮度"帧
    assert ch.writes[0] == ddc_frame(get_vcp_payload(0x10))


def test_probe_fail_no_reply():
    assert not G._probe(FakeChannel(reply=[0] * 16), settle=0)
    assert not G._probe(FakeChannel(fail_write=True), settle=0)


def test_backend_vcp_roundtrip_with_fake():
    be = GpuBackendForTest([FakeChannel(reply=_brightness_reply(0x28))])
    assert be.get_vcp(0, 0x10) == (0x28, 0x64)
    be.set_vcp(0, 0x10, 0x30)
    # SET 帧: 84 03 10 00 30 chk
    assert be._chans[0].writes[-1][:5] == [0x84, 0x03, 0x10, 0x00, 0x30]
    be.send_raw(0, [0xC0, 0x96, 0x01, 0x00])
    assert be._chans[0].writes[-1][:5] == [0x84, 0xC0, 0x96, 0x01, 0x00]


class GpuBackendForTest(G.GpuI2CBackend):
    """跳过硬件枚举, 注入假通道。"""

    def __init__(self, chans, slave=0x5E):
        self._read_settle = 0
        self._set_settle = 0
        self._slave = slave
        self.address = slave
        self._chans = chans


def test_adl_ddc_channel_is_primary_line_scan_is_fallback():
    # 2026-07-10 真机通过的是显示器级 DDC block 通道; line 盲扫只当兜底
    assert getattr(G._AdlDdcChannel, "is_fallback", False) is False
    assert G._AdlChannel.is_fallback is True


def test_pick_channels_skips_blind_scan_when_display_channel_answers():
    good = FakeChannel(reply=_brightness_reply())
    blind = FakeChannel(reply=_brightness_reply())
    blind.is_fallback = True
    assert G._pick_channels([good, blind], settle=0) == [good]
    assert blind.writes == []          # 盲扫通道一帧都没发


def test_pick_channels_falls_back_when_no_display_channel_answers():
    dead = FakeChannel(reply=[0] * 16)
    blind = FakeChannel(reply=_brightness_reply())
    blind.is_fallback = True
    assert G._pick_channels([dead, blind], settle=0) == [blind]
    # 快扫模式下不碰盲扫通道, 宁可返回空让上层重扫
    assert G._pick_channels([dead, blind], settle=0, fallback_scan=False) == []


def test_backend_registered():
    import ddcci_core
    assert "gpu" in ddcci_core.available_backends()
