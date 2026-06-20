# -*- coding: utf-8 -*-
"""管脚模型: 把"管脚+功能"翻译成 pinshare/GPIO 寄存器的位域读改写, 跑在 RegAccess 上。

每个 Pin 把一个 BGA 球映射到:
  - pinshare 寄存器 (Page10 某 offset, 低若干 bit) = 复用功能选择
  - (可选) GPIO 数据寄存器 (0xFExx 某 bit) = 输出电平/读回
复用值语义: 0=输入<I> 1=推挽输出<PP> 2=开漏输出<OD>, 其余=外设。
"""
import json
import os

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rl6410_pins.json")

GPIO_IN = "gpio_in"
GPIO_OUT_PP = "gpio_out_pp"
GPIO_OUT_OD = "gpio_out_od"
GPIO_OUT_KINDS = (GPIO_OUT_PP, GPIO_OUT_OD)
RESERVED = "reserved"


class Pin(object):
    """一个 BGA 球的可配置项。"""

    __slots__ = ("ball", "share", "default", "domain", "funcs", "gpio",
                 "danger", "danger_reason", "_kind_by_val")

    def __init__(self, d):
        self.ball = d["ball"]
        self.share = d["share"]                 # {page, offset, mask, shift}
        self.default = int(d["default"])
        self.domain = d.get("domain", "OTHER")
        self.funcs = d.get("funcs", [])         # [{val, name, kind}]
        self.gpio = d.get("gpio")               # {name, data_page, data_offset, bit} | None
        self.danger = bool(d.get("danger", False))
        self.danger_reason = d.get("danger_reason", "")
        self._kind_by_val = {int(f["val"]): f.get("kind") for f in self.funcs}

    def _mask(self):
        return int(self.share["mask"])

    def _shift(self):
        return int(self.share["shift"])

    def _name_of(self, val):
        for f in self.funcs:
            if int(f["val"]) == val:
                return f["name"]
        return None

    def read_mux(self, ra):
        """读 pinshare 字节取位域 -> {val, name, kind}; peek 失败返回 None。"""
        cur = ra.peek(int(self.share["page"]), int(self.share["offset"]))
        if cur is None:
            return None
        val = (cur & self._mask()) >> self._shift()
        return {"val": val, "name": self._name_of(val), "kind": self._kind_by_val.get(val)}

    def set_mux(self, ra, val):
        """切复用: 校验 val 合法(在 funcs 且非 reserved) -> 读改写位域。
        非法值抛 ValueError; peek 失败返回 False; 否则返回 poke 结果。
        写后回读确认由调用方/UI 的 round-trip 承担(前端写完即重发 pin_read 刷新显示)。"""
        val = int(val)
        if val not in self._kind_by_val or self._kind_by_val[val] == RESERVED:
            raise ValueError("%s 不支持复用值 %d" % (self.ball, val))
        page, off = int(self.share["page"]), int(self.share["offset"])
        cur = ra.peek(page, off)
        if cur is None:
            return False
        newb = (cur & ~self._mask()) | ((val << self._shift()) & self._mask())
        return ra.poke(page, off, newb)

    def gpio_read(self, ra):
        """读 GPIO 电平(0/1); 无映射或 peek 失败返回 None。"""
        if not self.gpio:
            return None
        cur = ra.peek(int(self.gpio["data_page"]), int(self.gpio["data_offset"]))
        if cur is None:
            return None
        return (cur >> int(self.gpio["bit"])) & 1

    def gpio_set(self, ra, level):
        """置 GPIO 电平。无映射或当前非 GPIO 输出抛 ValueError;
        读现态失败返回 False; 否则返回 poke 结果。"""
        if not self.gpio:
            raise ValueError("%s 无 GPIO 数据寄存器映射" % self.ball)
        mux = self.read_mux(ra)
        if mux is None:
            return False
        if mux["kind"] not in GPIO_OUT_KINDS:
            raise ValueError("%s 当前非 GPIO 输出, 不能置电平" % self.ball)
        page = int(self.gpio["data_page"])
        off = int(self.gpio["data_offset"])
        bit = int(self.gpio["bit"])
        cur = ra.peek(page, off)
        if cur is None:
            return False
        newb = (cur | (1 << bit)) if int(level) else (cur & ~(1 << bit))
        return ra.poke(page, off, newb)

    def reset_default(self, ra):
        """还原本板默认复用值。"""
        return self.set_mux(ra, self.default)

    def to_dict(self):
        return {"ball": self.ball, "share": self.share, "default": self.default,
                "domain": self.domain, "funcs": self.funcs, "gpio": self.gpio,
                "danger": self.danger, "danger_reason": self.danger_reason}


class PinDB(object):
    """全脚集合 + 分组/搜索。"""

    def __init__(self, pins, domain_order=None):
        self.pins = pins
        self.domain_order = domain_order or []
        self._by_ball = {p.ball: p for p in pins}

    def by_ball(self, ball):
        return self._by_ball[ball]

    def by_domain(self):
        """返回 [(domain, [pin,...]), ...]; 按 domain_order, 其余域附后(字母序)。"""
        groups = {}
        for p in self.pins:
            groups.setdefault(p.domain, []).append(p)
        ordered = [d for d in self.domain_order if d in groups]
        ordered += [d for d in sorted(groups) if d not in self.domain_order]
        return [(d, groups[d]) for d in ordered]

    def search(self, text):
        """按球名或任一功能名子串匹配(大小写不敏感)。"""
        t = text.lower()
        out = []
        for p in self.pins:
            if t in p.ball.lower() or any(t in f.get("name", "").lower() for f in p.funcs):
                out.append(p)
        return out


def load_pins(path=None):
    """从 JSON 载入: {"domain_order": [...], "pins": [...]}。"""
    with open(path or _DEFAULT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    pins = [Pin(d) for d in data.get("pins", [])]
    return PinDB(pins, data.get("domain_order", []))
