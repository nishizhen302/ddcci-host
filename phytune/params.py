# -*- coding: utf-8 -*-
"""PHY 调试参数模型: 从 rl6410_params.json 载入命名参数, 经位域读改写驱动 RegAccess。

每个 Param 把一个具名参数映射到 寄存器(page/offset) 的一段位域(mask/shift),
read = peek 整字节后取位域; write = 范围校验 + 读改写(只动 mask 内的位)。
"""
import json
import os

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rl6410_params.json")


class Param(object):
    """一个具名可调参数。"""

    __slots__ = ("name", "group", "label", "page", "offset", "mask", "shift",
                 "min", "max", "default", "live", "note", "slot")

    def __init__(self, d):
        self.name = d["name"]
        self.group = d["group"]
        self.label = d.get("label", d["name"])
        self.page = int(d["page"])
        self.offset = int(d["offset"])
        self.mask = int(d["mask"])
        self.shift = int(d.get("shift", 0))
        self.min = int(d["min"])
        self.max = int(d["max"])
        self.default = int(d.get("default", d["min"]))
        self.live = bool(d.get("live", True))
        self.note = d.get("note", "")
        # P1: 非在线参数固定 override 槽位 (重锁后固化); 在线参数无需固化, slot=None
        self.slot = d.get("slot", None)
        if self.slot is not None:
            self.slot = int(self.slot)

    def read(self, ra):
        """读回当前位域值; peek 失败返回 None。"""
        cur = ra.peek(self.page, self.offset)
        if cur is None:
            return None
        return (cur & self.mask) >> self.shift

    def write(self, ra, value):
        """范围校验 + 读改写。越界抛 ValueError; peek 失败返回 False; 否则返回 poke 结果。"""
        value = int(value)
        if not (self.min <= value <= self.max):
            raise ValueError("%s=%d 越界 [%d, %d]" % (self.name, value, self.min, self.max))
        cur = ra.peek(self.page, self.offset)
        if cur is None:
            return False
        newbyte = (cur & ~self.mask) | ((value << self.shift) & self.mask)
        return ra.poke(self.page, self.offset, newbyte)

    def to_dict(self):
        """给前端用的可序列化描述。"""
        return {"name": self.name, "group": self.group, "label": self.label,
                "page": self.page, "offset": self.offset,
                "min": self.min, "max": self.max, "default": self.default,
                "live": self.live, "note": self.note, "slot": self.slot}


class ParamModel(object):
    """参数集 + 分组。"""

    def __init__(self, groups, params):
        self.groups = groups
        self.params = params
        self._by_name = {p.name: p for p in params}

    def by_name(self, name):
        return self._by_name[name]


def load_params(path=None):
    """从 JSON 载入参数模型。"""
    with open(path or _DEFAULT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    groups = data.get("groups", [])
    params = [Param(d) for d in data.get("params", [])]
    return ParamModel(groups, params)
