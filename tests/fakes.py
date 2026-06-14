# -*- coding: utf-8 -*-
"""测试替身: 不接硬件, 记录 VCP 往来, 供 RegAccess 单测。"""
from backends.base import Backend, Monitor


class FakeBackend(Backend):
    name = "fake"
    address = 0x6E

    def __init__(self, get_returns=None):
        # get_returns: {(mon_id, code): (current, maximum)} 预置 get_vcp 应答
        self._get_returns = dict(get_returns or {})
        self.sets = []          # [(mon_id, code, value), ...] 按序记录所有 set_vcp
        self.set_result = True  # set_vcp 返回值(可改成 False 测失败路径)

    def enum_monitors(self):
        return [Monitor(0, "FakeMon")]

    def get_vcp(self, mon_id, code):
        return self._get_returns.get((mon_id, code))

    def set_vcp(self, mon_id, code, value):
        self.sets.append((mon_id, code, value))
        return self.set_result

    def read_caps(self, mon_id):
        return "(prot(monitor)type(lcd)model(RTK))"
