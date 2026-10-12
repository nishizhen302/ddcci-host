# -*- coding: utf-8 -*-
"""南微协议层单测 —— 金标准帧全部来自《IIC协议(南微)》PDF 的示例与命令表。"""
import pytest

import nanwei_core as nw
from backends.raw_usb_backend import (ddc_frame, get_vcp_payload,
                                      set_vcp_payload, parse_vcp_reply)


def full_frame(payload):
    """线上完整帧 = 从机地址 5E + 源地址 51 + ddc_frame (板包外层不算)。"""
    return [0x5E, 0x51] + ddc_frame(payload)


# ---- 写命令 (PDF 第 1 页) ----

def test_set_brightness_frame():
    # S 5E 51 84 03 10 00 Value chk, chk=5E^51^84^03^10^00^value (PDF 注 5)
    f = full_frame(set_vcp_payload(nw.OP_BRIGHTNESS, 0x32))
    chk = 0x5E ^ 0x51 ^ 0x84 ^ 0x03 ^ 0x10 ^ 0x00 ^ 0x32
    assert f == [0x5E, 0x51, 0x84, 0x03, 0x10, 0x00, 0x32, chk]


@pytest.mark.parametrize("op", [nw.OP_CONTRAST, nw.OP_COLORTEMP, nw.OP_GAMMA])
def test_set_frames_shape(op):
    f = full_frame(set_vcp_payload(op, 0x08))
    assert f[:4] == [0x5E, 0x51, 0x84, 0x03]
    assert f[4] == op and f[5] == 0x00 and f[6] == 0x08
    x = 0
    for b in f[:-1]:
        x ^= b
    assert f[-1] == x  # 校验位 = 前 7 字节异或


def test_sim_key_frame():
    # 模拟按键: S 5E 51 84 C0 96 Value 00 chk —— 键值在高字节位 (与 SET VCP 相反)
    f = full_frame(nw.key_payload(nw.KEYS["right"]))
    assert f[:5] == [0x5E, 0x51, 0x84, 0xC0, 0x96]
    assert f[5] == 0x01 and f[6] == 0x00
    x = 0
    for b in f[:-1]:
        x ^= b
    assert f[-1] == x


def test_key_values():
    # ok=0x04 不在 PDF 里, 2026-07-10 真机逐值试出来的 (进工厂菜单要用)
    assert nw.KEYS == {"menu": 0x00, "right": 0x01, "left": 0x02, "exit": 0x03, "ok": 0x04}


def test_macro_sequences():
    assert nw.FACTORY_KEYS == ("menu", "ok")
    assert nw.AGING_KEYS == ("menu", "ok", "menu", "menu", "right", "menu", "exit", "exit")
    assert set(nw.AGING_KEYS) <= set(nw.KEYS)


# ---- 读命令 (PDF 第 2-4 页) ----

def test_get_colortemp_frame():
    # PDF 注 1 给的例子: checksum1 = 5E^51^82^01^14 = 0x98
    f = full_frame(get_vcp_payload(nw.OP_COLORTEMP))
    assert f == [0x5E, 0x51, 0x82, 0x01, 0x14, 0x98]


def test_parse_reply_colortemp():
    # 回包例 (读色温, 当前 User=0x05, 最大 0x0D): 5E 88 02 00 14 00 00 0D 00 05 chk2
    frame = [0x5E, 0x88, 0x02, 0x00, 0x14, 0x00, 0x00, 0x0D, 0x00, 0x05]
    chk2 = 0x50
    for b in frame:
        chk2 ^= b
    frame.append(chk2)
    assert nw.reply_checksum_ok(frame)
    # 板子读回可能带前导 0 与尾部状态字节, 解析要能扫出来
    assert parse_vcp_reply([0x00, 0x00] + frame + [0x00, 0x63], code=0x14) == (0x05, 0x0D)


def test_parse_reply_wrong_code_rejected():
    frame = [0x5E, 0x88, 0x02, 0x00, 0x10, 0x00, 0x00, 0x64, 0x00, 0x32, 0x00]
    assert parse_vcp_reply(frame, code=0x14) is None


def test_reply_checksum_bad():
    frame = [0x5E, 0x88, 0x02, 0x00, 0x14, 0x00, 0x00, 0x0D, 0x00, 0x05, 0xFF]
    assert not nw.reply_checksum_ok(frame)


# ---- 值表 ----

def test_colortemp_table():
    assert {o["label"]: o["value"] for o in nw.COLORTEMP_VALUES} == \
        {"6500K": 0x08, "9300K": 0x06, "User": 0x05}


def test_gamma_table():
    vals = [o["value"] for o in nw.GAMMA_VALUES]
    assert vals == list(range(0x06, 0x0D))  # gamma1..7


# ---- 设备封装 (假后端) ----

class FakeBackend:
    address = 0x5E
    name = "fake"

    def __init__(self):
        self.raw = []
        self.vcp = {nw.OP_BRIGHTNESS: [0x32, 0x64]}

    def get_vcp(self, mon_id, code):
        v = self.vcp.get(code)
        return tuple(v) if v else None

    def set_vcp(self, mon_id, code, value):
        self.vcp.setdefault(code, [0, 0x64])[0] = value
        return True

    def send_raw(self, mon_id, payload):
        self.raw.append(list(payload))
        return True


def test_monitor_roundtrip():
    be = FakeBackend()
    dev = nw.NanweiMonitor(be, 0)
    assert dev.get(nw.OP_BRIGHTNESS) == (0x32, 0x64)
    dev.set(nw.OP_BRIGHTNESS, 0x40)
    assert dev.get(nw.OP_BRIGHTNESS) == (0x40, 0x64)
    dev.press_key("exit")
    assert be.raw == [[0xC0, 0x96, 0x03, 0x00]]


def test_press_key_value_accepts_unknown_code():
    be = FakeBackend()
    dev = nw.NanweiMonitor(be, 0)
    dev.press_key_value(0x04)
    assert be.raw == [[0xC0, 0x96, 0x04, 0x00]]


def test_macro_sends_full_sequence_in_order():
    be = FakeBackend()
    dev = nw.NanweiMonitor(be, 0)
    sent = dev.start_aging(key_gap=0)   # key_gap=0: 单测不等那 0.35s×8
    assert sent == list(nw.AGING_KEYS)
    assert be.raw == [[0xC0, 0x96, nw.KEYS[k], 0x00] for k in nw.AGING_KEYS]


def test_enter_factory_sends_menu_then_ok():
    be = FakeBackend()
    dev = nw.NanweiMonitor(be, 0)
    assert dev.enter_factory(key_gap=0) == ["menu", "ok"]
    assert be.raw == [[0xC0, 0x96, 0x00, 0x00], [0xC0, 0x96, 0x04, 0x00]]


def test_versions_none_when_silent():
    be = FakeBackend()
    dev = nw.NanweiMonitor(be, 0)
    v = dev.versions()
    assert v == {"hw": None, "sw": None}


# ---- 216pin 机型 (协议从固件逆向, 见 docs/protocol-216pin.md) ----

def test_make_monitor_picks_class_by_model():
    be = FakeBackend()
    assert type(nw.make_monitor("156", be)) is nw.NanweiMonitor
    assert isinstance(nw.make_monitor("216", be), nw.Monitor216)
    with pytest.raises(ValueError):
        nw.make_monitor("999", be)


def test_model_table_addresses():
    assert nw.model_info("156")["slaves"] == [0x5E, 0x6E]
    assert nw.model_info("216")["slaves"] == [0x6E]      # 固件 FF23 只写 0x6E (0x6A 是调试模式)


def test_216_colortemp_uses_mccs_values():
    assert {o["label"]: o["value"] for o in nw.COLORTEMP_VALUES_216} == {
        "6500K": 0x05, "9300K": 0x08, "7500K": 0x06, "5000K": 0x04, "sRGB": 0x01, "User": 0x0B}


def test_216_gamma_written_by_c0_91_and_read_back_minus_one():
    be = FakeBackend()
    dev = nw.Monitor216(be, 0)
    dev.set_choice("gamma", 3)
    assert be.raw == [[0xC0, 0x91, 0x02, 0x00]]          # gamma3 = 子命令参数 2
    assert dev.choice_payload("gamma", 1) == [0xC0, 0x91, 0x00, 0x00]
    be.vcp[nw.OP_GAMMA] = [0x04, 0x08]                    # GET 0x72 读回 = 档位+1
    assert dev.get_choice("gamma") == (3, 7)


def test_216_colortemp_goes_through_standard_vcp():
    be = FakeBackend()
    dev = nw.Monitor216(be, 0)
    dev.set_choice("colortemp", 0x08)
    assert be.vcp[nw.OP_COLORTEMP][0] == 0x08 and be.raw == []
    assert dev.get_choice("colortemp")[0] == 0x08


def test_216_tap_key_same_frame_as_156():
    be = FakeBackend()
    nw.Monitor216(be, 0).press_key("right")
    assert be.raw == [[0xC0, 0x96, 0x01, 0x00]]


def test_216_hold_key_then_release():
    be = FakeBackend()
    waited = []
    dev = nw.Monitor216(be, 0)
    assert dev.hold_key("right", 3, sleep=waited.append) == 3
    # 按住用 mode 01; RIGHT 在 mode 00 下发 1 会被固件换成消息 2, 所以按住发 2 保持同一个键
    assert be.raw == [[0xC0, 0x96, 0x02, 0x01], [0xC0, 0x96, 0xFF, 0x00]]
    assert waited == [3]


def test_216_hold_releases_even_if_wait_fails():
    be = FakeBackend()
    dev = nw.Monitor216(be, 0)

    def boom(_):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        dev.hold_key("menu", 1, sleep=boom)
    assert be.raw[-1] == [0xC0, 0x96, 0xFF, 0x00]         # 松开帧一定补发, 不留卡住的键


def test_216_hold_seconds_clamped():
    be = FakeBackend()
    assert nw.Monitor216(be, 0).hold_key("ok", 999, sleep=lambda s: None) == nw.HOLD_MAX_SEC


def test_216_versions_skip_unsupported_hw_opcode():
    be = FakeBackend()
    be.vcp[nw.OP_SW_VERSION] = [0x01, 0xFF]
    asked = []
    orig = be.get_vcp
    be.get_vcp = lambda mon, code: (asked.append(code), orig(mon, code))[1]
    assert nw.Monitor216(be, 0).versions() == {"hw": None, "sw": 1}
    assert nw.OP_HW_VERSION not in asked


def test_216_has_no_156_macros():
    dev = nw.Monitor216(FakeBackend(), 0)
    with pytest.raises(NotImplementedError):
        dev.start_aging(key_gap=0)


# ---- 机型自动识别 ----

class _AddrBe(FakeBackend):
    def __init__(self, address, vcp):
        super().__init__()
        self.address = address
        self.vcp.update(vcp)


def test_detect_0x5e_is_156_without_asking():
    be = _AddrBe(0x5E, {})
    be.get_vcp = lambda *a: pytest.fail("0x5E 不用读就知道是 156")
    assert nw.detect_model(be, 0) == "156"


def test_detect_216_by_gamma_max():
    assert nw.detect_model(_AddrBe(0x6E, {nw.OP_GAMMA: [0x04, 0x08]}), 0) == "216"


def test_detect_156_sample_on_0x6e():
    # 156pin 样机在 0x6E 应答南微命令集: 色温/gamma max 都是 0x0D
    be = _AddrBe(0x6E, {nw.OP_GAMMA: [0x08, 0x0D], nw.OP_COLORTEMP: [0x05, 0x0D]})
    assert nw.detect_model(be, 0) == "156"


def test_detect_falls_back_to_colortemp_then_216():
    assert nw.detect_model(_AddrBe(0x6E, {nw.OP_COLORTEMP: [0x05, 0x0B]}), 0) == "216"
    assert nw.detect_model(_AddrBe(0x6E, {}), 0) == "216"
