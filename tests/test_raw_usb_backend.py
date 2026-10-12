# -*- coding: utf-8 -*-
"""raw_usb_backend 纯组帧/解析单测 (不碰硬件)。

金标准帧是 Beacon/PanelCalib 在标准地址 0x6E 上实测的, 故显式传 slave=0x6E;
模块默认 _SLAVE 已改为 0x5E (南微/RK3576 固件), 不影响这些帧的正确性验证。
"""
from backends import raw_usb_backend as R


def test_default_slave_is_5e():
    # 南微协议 / RK3576 固件从机地址; 标准固件要 0x6E 时显式传参。
    assert R._SLAVE == 0x5E


def test_sum8_wraps():
    assert R.sum8([0x12, 0x6E, 0x51]) == (0x12 + 0x6E + 0x51) & 0xFF
    assert R.sum8([0xFF, 0xFF]) == 0xFE


def test_board_write_packet_shape():
    pk = R.board_write_packet([0xAA, 0xBB], slave=0x6E)
    # 12 slave sub lenHi lenLo data... sum8
    assert pk[:5] == [0x12, 0x6E, 0x51, 0x00, 0x02]
    assert pk[5:7] == [0xAA, 0xBB]
    assert pk[-1] == R.sum8(pk[:-1])


def test_board_read_packet_shape():
    pk = R.board_read_packet(11, slave=0x6E)
    assert pk[:5] == [0x11, 0x6E, 0x51, 0x00, 0x0B]
    assert pk[-1] == R.sum8(pk[:-1])


def test_ddc_frame_xor_includes_slave_and_sub():
    # 用 Beacon 实测过的 gamma 帧核对 xor: payload [0xC0,0x91,0x01]
    fr = R.ddc_frame([0xC0, 0x91, 0x01], slave=0x6E)
    assert fr[0] == (0x80 | 3)
    # 手算 chk = 6E^51^83^C0^91^01
    exp = 0x6E ^ 0x51 ^ 0x83 ^ 0xC0 ^ 0x91 ^ 0x01
    assert fr[-1] == exp


def test_set_vcp_payload():
    # SET 亮度(0x10)=100
    assert R.set_vcp_payload(0x10, 100) == [0x03, 0x10, 0x00, 0x64]
    # 16bit value 拆高低字节
    assert R.set_vcp_payload(0xE5, 0x1023) == [0x03, 0xE5, 0x10, 0x23]


def test_get_vcp_payload():
    assert R.get_vcp_payload(0x10) == [0x01, 0x10]


def test_parse_vcp_reply_brightness():
    # 实测亮度回包: cur=44(0x2C), max=100(0x64)
    buf = [0x6E, 0x88, 0x02, 0x00, 0x10, 0x00, 0x00, 0x64, 0x00, 0x2C, 0xEC]
    assert R.parse_vcp_reply(buf, 0x10, slave=0x6E) == (44, 100)


def test_parse_vcp_reply_skips_leading_zeros():
    # 回包前可能有前导 0, 需扫到 6E 8x 起
    buf = [0x00, 0x00, 0x6E, 0x88, 0x02, 0x00, 0xE5, 0x00, 0x00, 0xFF, 0x00, 0x07, 0x11]
    # peek 用 0xE5: cur 低字节=0x07
    cur, mx = R.parse_vcp_reply(buf, 0xE5, slave=0x6E)
    assert cur & 0xFF == 0x07
    assert mx == 0x00FF


def test_parse_vcp_reply_code_mismatch_returns_none():
    # 只有别的 code 的回包, 要的 code 没有 -> None
    buf = [0x6E, 0x88, 0x02, 0x00, 0x10, 0x00, 0x00, 0x64, 0x00, 0x2C, 0xEC]
    assert R.parse_vcp_reply(buf, 0xE5, slave=0x6E) is None


def test_parse_vcp_reply_no_reply_returns_none():
    assert R.parse_vcp_reply([0x00, 0x00, 0x00], 0x10) is None
    assert R.parse_vcp_reply([], 0x10) is None


def test_backend_registered():
    import ddcci_core
    assert "rawusb" in ddcci_core.available_backends()
