# -*- coding: utf-8 -*-
"""RL6410 调试 VCP 操作码 + 载荷打包/解包(纯函数)。

与固件 UserCommonDdcciDefine.h 的 _DDCCI_OPCODE_DBG_* 一一对应。
DDC/CI 一次 SET VCP 只能带 16bit value, 故地址/数据分别编码。
"""

VCP_ADDR_LATCH = 0xE0   # SET: page<<8|offset 锁存地址; GET: peek 返回当前值
VCP_POKE = 0xE1         # SET: type<<8|data 写入锁存地址
VCP_OVERRIDE = 0xE2     # SET: op<<8|slot 操作 override 表


def pack_addr(page, offset):
    """page+offset -> 16bit 载荷。越界抛 ValueError。"""
    if not (0 <= page <= 0xFF):
        raise ValueError("page 越界: %r" % (page,))
    if not (0 <= offset <= 0xFF):
        raise ValueError("offset 越界: %r" % (offset,))
    return (page << 8) | offset


def unpack_addr(value):
    """16bit 载荷 -> (page, offset)。"""
    return ((value >> 8) & 0xFF, value & 0xFF)


def pack_poke(data, type_=0):
    """data(8bit) + type(0=直接页, 1=data-port) -> 16bit 载荷。"""
    if not (0 <= data <= 0xFF):
        raise ValueError("data 越界: %r" % (data,))
    if type_ not in (0, 1):
        raise ValueError("type 只能 0/1: %r" % (type_,))
    return (type_ << 8) | data
