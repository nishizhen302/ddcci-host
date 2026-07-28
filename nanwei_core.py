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
