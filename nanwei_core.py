# -*- coding: utf-8 -*-
"""南微 (JUHOLD 巨融医疗) IIC 协议语义层 —— 按《IIC协议(南微)》PDF 实现。

该协议 = 标准 DDC/CI (MCCS) 帧格式, 但从机地址 0x5E (读回 0x5F), 非标准 0x6E:
- 写:  5E 51 84 03 op valHi valLo chk      (chk = 前 7 字节异或)
- 读:  5E 51 82 01 op chk  → 等 >40ms →  从 0x5F 读 11 字节:
       5E 88 02 00 op typ maxHi maxLo curHi curLo chk2   (chk2 = 前 10 字节异或 ^ 0x50)
- 模拟按键 (非标命令字 0xC0): 5E 51 84 C0 96 key 00 chk

本模块只懂协议语义, 不碰硬件; 组帧复用 backends.raw_usb_backend.ddc_frame
(其 slave/sub 默认已是 0x5E/0x51)。传输走 Backend 接口 (get_vcp/set_vcp/send_raw),
现在 = rawusb (USB 小板旁路 I²C), 以后加显卡 I²C 后端上层零改动。
"""
from backends.raw_usb_backend import ddc_frame, set_vcp_payload, get_vcp_payload

# ---- 操作码 (PDF 命令表) ----
OP_BRIGHTNESS = 0x10   # 亮度, 0x00~0x64
OP_CONTRAST   = 0x12   # 对比度, 0x00~0x64
OP_COLORTEMP  = 0x14   # 色温, 离散
OP_GAMMA      = 0x72   # Gamma, 离散
OP_HW_VERSION = 0xE0   # 硬件版本 (只读)
OP_SW_VERSION = 0xC9   # 软件版本 (只读)

# ---- 离散值表 ----
COLORTEMP_VALUES = [
    {"label": "6500K", "value": 0x08},
    {"label": "9300K", "value": 0x06},
    {"label": "User",  "value": 0x05},
]
GAMMA_VALUES = [{"label": "γ%d" % (i + 1), "value": 0x06 + i} for i in range(7)]  # gamma1..7 = 0x06..0x0C

# ---- 模拟按键 (命令字 0xC0, 键值在"设置值高字节") ----
CMD_SIM_KEY = 0xC0
KEY_OP = 0x96
KEYS = {"menu": 0x00, "right": 0x01, "left": 0x02, "exit": 0x03, "ok": 0x04}

# ---- 按键宏 (PDF 没有这两条命令, 只能按 OSD 操作顺序模拟按键走进去) ----
# ok=0x04 是 2026-07-10 真机逐值试出来的, PDF 未收录。
FACTORY_KEYS = ("menu", "ok")                                        # 进工厂菜单
AGING_KEYS = FACTORY_KEYS + ("menu", "menu", "right", "menu", "exit", "exit")  # 工厂菜单→老化
AGING_KEY_GAP = 0.35   # 按键间隔: OSD 要时间响应, 发太快固件会丢键


def key_payload(key_value):
    """模拟按键 payload: [0xC0, 0x96, key, 0x00]。注意键值在高字节位, 与 SET VCP 相反。"""
    return [CMD_SIM_KEY, KEY_OP, key_value & 0xFF, 0x00]


def frame_hex(payload, slave=0x5E):
    """完整线上帧的十六进制串, 给日志窗显示。

    线上顺序 = 从机地址 + 源地址 0x51 + ddc_frame(长度|0x80, payload, xor 校验);
    走 USB 小板时地址在板包头里, 这里补上还原成 PDF 命令表的完整帧。
    slave 默认南微 0x5E; 陪练标准机型 (DDCCI_SLAVE=0x6E) 时传实际地址。
    """
    return " ".join("%02X" % b for b in [slave, 0x51] + ddc_frame(payload, slave=slave))


def reply_checksum_ok(frame11):
    """校验 11 字节回包: chk2 = 前 10 字节异或 ^ 0x50 (PDF 注 2)。"""
    if len(frame11) != 11:
        return False
    chk = 0x50
    for b in frame11[:10]:
        chk ^= b
    return (chk & 0xFF) == frame11[10]


class NanweiMonitor:
    """一台南微协议显示器 = Backend + mon_id。方法返回语义值, 组帧细节不外漏。"""

    def __init__(self, backend, mon_id=0):
        self._be = backend
        self._mon = mon_id

    @property
    def slave(self):
        """实际从机地址 (南微 0x5E; 陪练标准机型时 DDCCI_SLAVE=0x6E)。"""
        return getattr(self._be, "address", 0x5E) or 0x5E

    def get(self, op):
        """读参数。返回 (current, maximum); 无应答返回 None。"""
        return self._be.get_vcp(self._mon, op)

    def set(self, op, value):
        """写参数。"""
        return self._be.set_vcp(self._mon, op, value & 0xFF)

    KEYPAD = None          # 156pin 是界面里固定的 4 键; 216pin 由 KEYPAD 表渲染

    def has_key(self, name):
        return name in KEYS

    def key_payload_for(self, name):
        return key_payload(KEYS[name])

    def press_key(self, name):
        """模拟按键 menu/right/left/exit/ok (非标 0xC0 帧, 无回读)。"""
        return self._be.send_raw(self._mon, key_payload(KEYS[name]))

    def press_key_value(self, value):
        """按任意键值发一次模拟按键 (逆向 OK 等 PDF 未列出的键时逐个试)。"""
        return self._be.send_raw(self._mon, key_payload(value & 0xFF))

    def press_keys(self, names, key_gap=AGING_KEY_GAP):
        """按序发一串模拟按键 (按键宏, 无回读)。返回已发按键名列表。"""
        import time
        sent = []
        for name in names:
            self.press_key(name)
            sent.append(name)
            time.sleep(key_gap)
        return sent

    def enter_factory(self, key_gap=AGING_KEY_GAP):
        """按 FACTORY_KEYS (Menu→OK) 进工厂菜单。"""
        return self.press_keys(FACTORY_KEYS, key_gap)

    def start_aging(self, key_gap=AGING_KEY_GAP):
        """按 AGING_KEYS 序列开启老化 (含进工厂菜单)。"""
        return self.press_keys(AGING_KEYS, key_gap)

    def versions(self):
        """读硬件/软件版本。读不到的项为 None。"""
        hw = self.get(OP_HW_VERSION)
        sw = self.get(OP_SW_VERSION)
        return {"hw": hw[0] if hw else None, "sw": sw[0] if sw else None}

    # ---- 离散项 (色温 / gamma): 机型差异收在这一层, 上层只认"选项值" ----
    model = "156"
    COLORTEMP = COLORTEMP_VALUES
    GAMMA = GAMMA_VALUES

    def choice_options(self, kind):
        return self.COLORTEMP if kind == "colortemp" else self.GAMMA

    def choice_payload(self, kind, value):
        """写该选项实际发出的 payload (给日志窗显示)。"""
        return set_vcp_payload(CHOICE_OPS[kind], value)

    def set_choice(self, kind, value):
        return self.set(CHOICE_OPS[kind], value)

    def get_choice(self, kind):
        """读回 (选项值, 最大值); 156pin 读回值就是选项值。"""
        return self.get(CHOICE_OPS[kind])


CHOICE_OPS = {"colortemp": OP_COLORTEMP, "gamma": OP_GAMMA}


# ======================================================================
# 216pin 机型 —— 协议从固件 C0105-00080(LG)_V110_0x11_260720.bin 逆向,
# 详见 docs/protocol-216pin.md。与 156pin 的差别:
# - 从机地址是标准 0x6E (不是 0x5E)
# - 色温 VCP 0x14 用 MCCS 标准值 (05=6500K 08=9300K 0B=User ...)
# - gamma: VCP 0x72 的写/读映射在固件里对不上 (写 02 读回 08), 所以写走自定义
#   C0 91 (v=0~6 → gamma1~7), 读走 GET 0x72 (读回 = 档位+1)
# - 不支持 0xE0 硬件版本, 软件版本 0xC9 固定回 1
# - 按键 C0 96 key mode: mode 00 = 发一次键 (同 156pin); mode 01 = 按住不放,
#   直到再收到一条 mode 00 帧; key>=0x10 + mode 00 = 只松开不发键
# ======================================================================
COLORTEMP_VALUES_216 = [
    {"label": "6500K", "value": 0x05},
    {"label": "9300K", "value": 0x08},
    {"label": "7500K", "value": 0x06},
    {"label": "5000K", "value": 0x04},
    {"label": "sRGB",  "value": 0x01},
    {"label": "User",  "value": 0x0B},
]
GAMMA_VALUES_216 = [{"label": "γ%d" % n, "value": n} for n in range(1, 8)]  # 选项值 = 固件档位 1~7

SUB_GAMMA_216 = 0x91
KEY_MODE_TAP = 0x00
KEY_MODE_HOLD = 0x01
KEY_RELEASE_216 = 0xFF
# 216pin 面板有 7 个物理键: ADC 按键扫描表 (两路电压各若干区间) -> 掩码 -> 按键消息号 0/1/2/3/6/8/9
# (docs/protocol-216pin.md 第 5 节)。只有 MENU/EXIT 能确定, 其余功能没在实机试过:
# 界面先按 1~7 编号、小字写推测, 用户实机试完再改 label/hint (2026-10-12)。
# alias = 键盘快捷键 / 156pin 叫法对应到哪个键 (必须和下面 HOLD_KEYS_216 的同名项是同一个消息号)。
KEYPAD_216 = [
    {"id": "k1", "msg": 0, "label": "1", "hint": "MENU", "alias": "menu"},
    {"id": "k2", "msg": 1, "label": "2", "hint": "左?", "alias": "left"},
    {"id": "k3", "msg": 2, "label": "3", "hint": "右?", "alias": "right"},
    {"id": "k4", "msg": 3, "label": "4", "hint": "EXIT", "alias": "exit"},
    {"id": "k5", "msg": 6, "label": "5", "hint": "?", "alias": None},
    {"id": "k6", "msg": 8, "label": "6", "hint": "?", "alias": None},
    {"id": "k7", "msg": 9, "label": "7", "hint": "?", "alias": None},
]
# 键名 -> 按键消息号。mode 01 (按住) 直接发消息号; mode 00 (点按) 固件会把 1/2 互换, 发之前先换回来,
# 保证"点一下"和"按住"是同一个键。menu/left/right/exit/ok 沿用 156pin 的叫法 (键盘快捷键/CLI):
# 156 点按 right 发 1 -> 216 固件得到消息 2, 所以 right = 消息 2。ok (消息 4) 不对应任何物理键。
HOLD_KEYS_216 = {"menu": 0x00, "left": 0x01, "right": 0x02, "exit": 0x03, "ok": 0x04}
HOLD_KEYS_216.update({k["id"]: k["msg"] for k in KEYPAD_216})


def tap_code_216(msg):
    """点按 (mode 00) 要发的键值: 消息 1/2 互换, 其余原样。"""
    return {1: 2, 2: 1}.get(msg, msg)
HOLD_MAX_SEC = 30.0


def gamma_payload_216(n):
    """216pin 写 gamma n (1~7): C0 91 (n-1) 00。"""
    return [CMD_SIM_KEY, SUB_GAMMA_216, (int(n) - 1) & 0xFF, 0x00]


def key_payload_216(key_value, mode=KEY_MODE_TAP):
    return [CMD_SIM_KEY, KEY_OP, key_value & 0xFF, mode & 0xFF]


class Monitor216(NanweiMonitor):
    """216pin 机型。帧格式同标准 DDC/CI, 差异见模块中段注释。"""

    model = "216"
    COLORTEMP = COLORTEMP_VALUES_216
    GAMMA = GAMMA_VALUES_216

    KEYPAD = KEYPAD_216

    def has_key(self, name):
        return name in HOLD_KEYS_216

    def key_payload_for(self, name):
        return key_payload_216(tap_code_216(HOLD_KEYS_216[name]), KEY_MODE_TAP)

    def press_key(self, name):
        """点一下 (mode 00)。name = k1~k7 或 menu/left/right/exit/ok。"""
        return self._be.send_raw(self._mon, self.key_payload_for(name))

    def choice_payload(self, kind, value):
        if kind == "gamma":
            return gamma_payload_216(value)
        return super().choice_payload(kind, value)

    def set_choice(self, kind, value):
        if kind == "gamma":
            return self._be.send_raw(self._mon, gamma_payload_216(value))
        return super().set_choice(kind, value)

    def get_choice(self, kind):
        r = super().get_choice(kind)
        if kind == "gamma" and r is not None:
            return (r[0] - 1, 7)       # 读回 = 档位+1; 档位 0 (gamma 关) 不在选项里, 显示为未选中
        return r

    def versions(self):
        sw = self.get(OP_SW_VERSION)   # 0xE0 不支持, 不去读 (rawusb 会重试 4 次白等)
        return {"hw": None, "sw": sw[0] if sw else None}

    def enter_factory(self, key_gap=AGING_KEY_GAP):
        raise NotImplementedError("216pin 的工厂菜单按键序列未知")

    def start_aging(self, key_gap=AGING_KEY_GAP):
        raise NotImplementedError("216pin 的老化按键序列未知")

    def release_keys(self):
        """松开所有按住的键, 不额外发键。"""
        return self._be.send_raw(self._mon, key_payload_216(KEY_RELEASE_216, KEY_MODE_TAP))

    def hold_key(self, name, seconds, sleep=None):
        """按住 name 键 seconds 秒再松开。无论中途出什么错, 都会补发松开帧。"""
        import time
        sleep = sleep or time.sleep
        if name not in HOLD_KEYS_216:
            raise ValueError("未知按键 %r" % name)
        seconds = max(0.2, min(HOLD_MAX_SEC, float(seconds)))
        try:
            self._be.send_raw(self._mon, key_payload_216(HOLD_KEYS_216[name], KEY_MODE_HOLD))
            sleep(seconds)
        finally:
            self.release_keys()
        return seconds


# ---- 机型自动识别 (扫描时按应答判, 客户不用手选) ----
# 0x5E 只有 156pin 南微用。0x6E 两种都可能 (156pin 样机也在 0x6E 应答过), 靠离散项的 max 区分:
# 216pin 固件 GET 0x72 回 max=0x08、GET 0x14 回 max=0x0B (逆向值, 待实机确认);
# 156pin 南微两项 max 都是 0x0D (2026-07-09 USB 小板实测)。
# 不能用"读不读得到 0xE0"判: 216 对不支持的码也回帧 (只是结果码=01), 解析器不看结果码。
MAX_216 = {OP_GAMMA: 0x08, OP_COLORTEMP: 0x0B}
MAX_156 = 0x0D


def detect_model(backend, mon_id):
    """返回 '156' / '216'。0x6E 上两项都对不上时按 216 处理 (0x6E 上正式出货的是 216)。"""
    if (getattr(backend, "address", 0x5E) or 0x5E) == 0x5E:
        return "156"
    for op in (OP_GAMMA, OP_COLORTEMP):
        r = backend.get_vcp(mon_id, op)
        if r is None:
            continue
        if r[1] == MAX_216[op]:
            return "216"
        if r[1] == MAX_156:
            return "156"
    return "216"


class MonitorStd(NanweiMonitor):
    """标准显示器 (戴尔等, 经 Windows 系统 DDC/CI 接口扫到): 只有亮度 / 对比度两个标准 VCP。

    不发 0xC0 自定义帧, 也不读南微的版本码 —— 别人家的显示器不认这些。
    """

    model = "std"
    COLORTEMP = []
    GAMMA = []

    def versions(self):
        return {"hw": None, "sw": None}

    def _unsupported(self, *a, **kw):
        raise NotImplementedError("标准显示器只支持亮度 / 对比度")

    press_key = press_key_value = press_keys = enter_factory = start_aging = _unsupported
    set_choice = get_choice = _unsupported


# ---- 机型表 ----
# keys = OSD 模拟按键, choices = 色温/Gamma 两块方块; 前端按这两个开关显隐。
MODELS = [
    {"id": "156", "label": "156pin", "title": "156pin 机型",
     "desc": "南微协议 · 地址 0x5E", "slaves": [0x5E, 0x6E], "macros": True, "hold": False,
     "keys": True, "choices": True},
    {"id": "216", "label": "216pin", "title": "216pin 机型",
     "desc": "标准 DDC/CI · 地址 0x6E", "slaves": [0x6E], "macros": False, "hold": True,
     "keys": True, "choices": True},
    {"id": "std", "label": "标准显示器", "title": "标准显示器",
     "desc": "系统 DDC/CI · 只控亮度/对比度", "slaves": [0x6E], "macros": False, "hold": False,
     "keys": False, "choices": False},
]
MODEL_IDS = [m["id"] for m in MODELS]
ALL_SLAVES = sorted({a for m in MODELS for a in m["slaves"]})     # 扫描时两种机型的地址都扫
DEFAULT_MODEL = "156"


def model_info(model_id):
    for m in MODELS:
        if m["id"] == str(model_id):
            return m
    raise ValueError("未知机型 %r, 可选: %s" % (model_id, ", ".join(MODEL_IDS)))


def make_monitor(model_id, backend, mon_id=0):
    model_info(model_id)               # 未知机型直接报错
    cls = {"216": Monitor216, "std": MonitorStd}.get(str(model_id), NanweiMonitor)
    return cls(backend, mon_id)
