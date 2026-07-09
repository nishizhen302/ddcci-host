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
    assert nw.KEYS == {"menu": 0x00, "right": 0x01, "left": 0x02, "exit": 0x03}


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


def test_versions_none_when_silent():
    be = FakeBackend()
    dev = nw.NanweiMonitor(be, 0)
    v = dev.versions()
    assert v == {"hw": None, "sw": None}
