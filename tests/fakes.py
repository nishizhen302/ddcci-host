# -*- coding: utf-8 -*-
"""测试替身: 不接硬件, 记录 VCP 往来, 供 RegAccess 单测。"""
from backends.base import Backend, Monitor
from phytune import vcp_codes as vc


class FakeBackend(Backend):
    name = "fake"
    address = 0x6E

    def __init__(self, get_returns=None, scdc_returns=None, peek_returns=None):
        # get_returns: {(mon_id, code): (current, maximum)} 预置 get_vcp 应答
        self._get_returns = dict(get_returns or {})
        # scdc_returns: {scdc_offset: byte} 模拟 SCDC 间接寄存器内容
        # (先 poke 0x39=偏移 选定, 再 peek 0x3A 读出对应字节)
        self._scdc_returns = dict(scdc_returns or {})
        # peek_returns: {(page, offset): byte} 按锁存地址区分 peek 应答
        # (RegAccess.peek 先锁存地址再读 0xE5; 多个不同寄存器的读靠这个区分)
        self._peek_returns = dict(peek_returns or {})
        self.sets = []          # [(mon_id, code, value), ...] 按序记录所有 set_vcp
        self.set_result = True  # set_vcp 返回值(可改成 False 测失败路径)
        self._last_latch = None  # 最近一次锁存的 16bit 地址
        self._scdc_sel = None    # 最近经 0x39 选定的 SCDC 偏移

    def enum_monitors(self):
        return [Monitor(0, "FakeMon")]

    def get_vcp(self, mon_id, code):
        # SCDC 间接读: 若刚锁存的是数据窗 0x3A 且已选定偏移, 返回该 SCDC 字节
        if (code == vc.VCP_ADDR_LATCH and self._last_latch is not None
                and (self._last_latch & 0xFF) == 0x3A
                and self._scdc_sel in self._scdc_returns):
            return (self._scdc_returns[self._scdc_sel], 0xFF)
        # 按锁存地址区分的 peek 应答 (page, offset)
        if code == vc.VCP_ADDR_LATCH and self._last_latch is not None:
            key = ((self._last_latch >> 8) & 0xFF, self._last_latch & 0xFF)
            if key in self._peek_returns:
                return (self._peek_returns[key], 0xFF)
        return self._get_returns.get((mon_id, code))

    def set_vcp(self, mon_id, code, value):
        self.sets.append((mon_id, code, value))
        if code == vc.VCP_ADDR_LATCH:
            self._last_latch = value
        elif code == vc.VCP_POKE:
            # 若刚锁存的是 SCDC 选择寄存器 0x39, 这笔 poke 的数据 = 选定的 SCDC 偏移
            if self._last_latch is not None and (self._last_latch & 0xFF) == 0x39:
                self._scdc_sel = value & 0xFF
        return self.set_result

    def read_caps(self, mon_id):
        return "(prot(monitor)type(lcd)model(RTK))"
