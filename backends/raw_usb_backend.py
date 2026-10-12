# -*- coding: utf-8 -*-
r"""Backend B —— Realtek USB ISP 小板 (RTUsb 裸 USB 管道) 上的 DDC/CI。

为什么要它: Backend A (dxva2) 借显示器的视频通道走 DDC/CI, 依赖 scaler+面板处于
正常显示状态才应答。一旦把面板关掉 (如 poke Panel_ON=0), 这条通道跟着失效 ——
"坐在树枝上锯树枝"。本后端走旁路 I²C (USB 小板直连显示器 DDC 脚), 不依赖面板开着,
关了屏也能继续 poke 把它救回来。

传输已在 PanelCalib 项目真机调通并验证 (2026-06-18): Comm.dll 在 RUN 态对 0x6E 发
DDC 写恒 NAK, 是死路; 正解是复刻 Beacon/USBLibrary 的裸 USB 管道 —— 按 RTUsb 私有
设备接口 GUID 用 CreateFile + WriteFile/ReadFile 直收发, 无 DeviceIoControl。

== 链路 (cap_beacon 抓包解出) ==
- 设备: VID_2007/PID_0808 "Realtek LCD USB ISP Tool"; 接口 GUID {d3a14581-...}。
- 板包: 写 `12 slave sub lenHi lenLo data... sum8` (写后 ReadFile(2)=00 00 状态);
        读 `11 slave sub lenHi lenLo sum8` 再 ReadFile(n+2) (尾 2 字节=板 status+sum8)。
        sum8 = 前字节和 & 0xFF (板包外层校验, 与 DDC 帧内 XOR 校验是两层, 别混)。
- DDC/CI: slave=0x6E, sub=0x51, data=[0x80|len, *payload, xorchk] (xor 含 0x6E^0x51)。

本后端实现 base.Backend 的 VCP 级接口 (get_vcp/set_vcp), 故上层 RegAccess(peek/poke)
与整个 pinmux/phytune UI 零改动即可切到 USB 通道。peek/poke 用厂商 VCP 0xE5/0xE6,
本质就是标准 SET/GET VCP, 在此层封 DDC/CI 标准帧即可。

== 坑 (PanelCalib 实测) ==
- 0x6E 回包有延迟+可能带前导 0, 读前需 settle (>=120ms) 并在缓冲里扫 `6E 8x` 模式。
- 写命令的板写状态 (ReadFile(2)) 不总可靠, 以"读得回 GET 回包"为送达判据 (round-trip)。
"""
import ctypes
import os
import time
from ctypes import wintypes

from backends.base import Backend, Monitor
from backends.edid import edid_name

# RTUsb 私有设备接口 GUID (非通用 USB GUID); SetupAPI 按此枚举得设备路径。
_RTUSB_GUID = (0xd3a14581, 0xfdda, 0x4402, (0xb5, 0xf9, 0x83, 0x73, 0xeb, 0xc5, 0x4d, 0xdb))
_SLAVE = 0x5E          # 显示器 DDC/CI 8bit 从地址 (南微协议显示器原生 0x5E, 非标准 0x6E)
_SUB = 0x51            # DDC/CI 源地址 (virtual host)
_CMD_SET_VCP = 0x03    # DDC/CI SET VCP Feature 命令字
_CMD_GET_VCP = 0x01    # DDC/CI GET VCP Feature 命令字
_OP_GET_REPLY = 0x02   # GET VCP Feature Reply 操作码


# ============ 纯函数: 组帧/解析 (不碰硬件, 可离线单测) ============

def sum8(b):
    """板包外层校验 = 前字节之和 & 0xFF。"""
    return sum(b) & 0xFF


def board_write_packet(data, slave=_SLAVE, sub=_SUB):
    """组板包 I²C 写: 12 slave sub lenHi lenLo data... sum8。"""
    pk = [0x12, slave, sub, (len(data) >> 8) & 0xFF, len(data) & 0xFF] + list(data)
    pk.append(sum8(pk))
    return pk


def board_read_packet(n, slave=_SLAVE, sub=_SUB):
    """组板包 I²C 读请求: 11 slave sub lenHi lenLo sum8。"""
    pk = [0x11, slave, sub, (n >> 8) & 0xFF, n & 0xFF]
    pk.append(sum8(pk))
    return pk


def ddc_frame(payload, slave=_SLAVE, sub=_SUB):
    """DDC/CI data 段 = [0x80|len, *payload, xorchk]; xor 种子含 slave 与 sub。"""
    body = [0x80 | (len(payload) & 0x7F)] + list(payload)
    chk = slave ^ sub
    for x in body:
        chk ^= x
    return body + [chk & 0xFF]


def set_vcp_payload(code, value):
    """SET VCP: [0x03, code, valueHi, valueLo]。"""
    return [_CMD_SET_VCP, code & 0xFF, (value >> 8) & 0xFF, value & 0xFF]


def get_vcp_payload(code):
    """GET VCP 请求: [0x01, code]。"""
    return [_CMD_GET_VCP, code & 0xFF]


def parse_vcp_reply(buf, code=None, slave=_SLAVE):
    """从读回缓冲扫 GET VCP Feature Reply, 返回 (current, maximum); 解析不出返回 None。

    标准回包 (去掉外层): 6E 88 02 result vcp typ maxHi maxLo curHi curLo chk。
    扫 `slave` 后跟 `0x8x` (含长度位) 且其后操作码=0x02 的位置起解。
    """
    n = len(buf)
    for i in range(n - 1):
        if buf[i] == slave and (buf[i + 1] & 0x80):
            body = buf[i + 2:]
            if len(body) < 8 or body[0] != _OP_GET_REPLY:
                continue
            # body: [0x02, result, vcp, typ, maxHi, maxLo, curHi, curLo]
            vcp = body[2]
            if code is not None and vcp != (code & 0xFF):
                continue
            maximum = (body[4] << 8) | body[5]
            current = (body[6] << 8) | body[7]
            return current, maximum
    return None


# ============ 硬件: 裸 USB 管道 ============

class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD),
                ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]


class _SP_DID(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("g", _GUID),
                ("f", wintypes.DWORD), ("r", ctypes.POINTER(ctypes.c_ulong))]


def _find_device_path():
    """按 RTUsb GUID 用 SetupAPI 实时枚举设备路径 (免硬编码)。找不到返回 None。"""
    setupapi = ctypes.WinDLL("setupapi")
    # ★必须声明 restype/argtypes: 64 位下 HDEVINFO 句柄是 8 字节指针, 不声明会被 ctypes
    # 当 32 位 int 截断 → 后续枚举全失败 → 误报"设备未找到"(32 位 Python 侥幸不暴露)。
    setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                              wintypes.HWND, wintypes.DWORD]
    setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                                     ctypes.c_void_p, wintypes.DWORD,
                                                     ctypes.c_void_p]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                                          ctypes.c_void_p, wintypes.DWORD,
                                                          ctypes.c_void_p, ctypes.c_void_p]
    g = _GUID(_RTUSB_GUID[0], _RTUSB_GUID[1], _RTUSB_GUID[2],
              (ctypes.c_ubyte * 8)(*_RTUSB_GUID[3]))
    h = setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 0x12)  # PRESENT|DEVICEINTERFACE
    did = _SP_DID()
    did.cb = ctypes.sizeof(did)
    path = None
    i = 0
    while setupapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(g), i, ctypes.byref(did)):
        req = wintypes.DWORD(0)
        setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(did), None, 0, ctypes.byref(req), None)
        buf = ctypes.create_string_buffer(req.value)
        # SP_DEVICE_INTERFACE_DETAIL_DATA.cbSize: 64位=8, 32位=6
        ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
        if setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(did), buf, req.value, None, None):
            path = ctypes.wstring_at(ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD))
        i += 1
    return path


class RawUsbBackend(Backend):
    """RTUsb 裸 USB 管道上的 DDC/CI 后端。单板对单 scaler, 枚举返回一个虚拟显示器。"""

    name = "rawusb"
    address = _SLAVE

    def __init__(self, read_settle=0.15, set_settle=0.12, slave=None):
        # 从机地址: 显式参数 > 环境变量 DDCCI_SLAVE (如 0x6E, 标准机型陪练用) > 模块默认 0x5E
        if slave is None:
            slave = int(os.environ.get("DDCCI_SLAVE", "0"), 0) or _SLAVE
        self._slave = slave & 0xFF
        self.address = self._slave
        self._read_settle = read_settle
        # SET VCP 写完到下一条命令(尤其 GET 锁存地址后读回)之间必须留时间给固件单线程
        # 处理完, 否则地址没锁好就 GET -> 读空。非活动口走 0x6E 时固件处理更慢, 这步必须。
        self._set_settle = set_settle
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        path = _find_device_path()
        if not path:
            raise RuntimeError(
                "USB 小板未找到 (VID_2007/PID_0808 'Realtek LCD USB ISP Tool', "
                "GUID d3a14581)。确认小板已插、未被烧录工具独占。")
        self._k32.CreateFileW.restype = wintypes.HANDLE
        self._k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.HANDLE]
        # 同理声明读写/关闭, 64 位下句柄按指针传, 别被截断。
        _pdw = ctypes.POINTER(wintypes.DWORD)
        self._k32.WriteFile.restype = wintypes.BOOL
        self._k32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, _pdw, ctypes.c_void_p]
        self._k32.ReadFile.restype = wintypes.BOOL
        self._k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, _pdw, ctypes.c_void_p]
        self._k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._h = self._k32.CreateFileW(path, 0x80000000 | 0x40000000, 3, None, 3, 0, None)
        if self._h in (None, 0, wintypes.HANDLE(-1).value):
            raise RuntimeError("打开 USB 小板失败 err=%d" % ctypes.get_last_error())
        # 板初始化 (cap_beacon 首包)
        self._write_bytes([0x17, 0, 0, 0, 0, 0, 0x17])
        self._read_bytes(2)

    # ---- 低层 USB 管道 ----
    def _write_bytes(self, byts):
        a = (ctypes.c_ubyte * len(byts))(*byts)
        wr = wintypes.DWORD(0)
        self._k32.WriteFile(self._h, a, len(byts), ctypes.byref(wr), None)
        return wr.value

    def _read_bytes(self, n):
        a = (ctypes.c_ubyte * n)()
        rd = wintypes.DWORD(0)
        self._k32.ReadFile(self._h, a, n, ctypes.byref(rd), None)
        return [a[j] for j in range(rd.value)]

    # ---- 板包 I²C ----
    def _i2c_write(self, data):
        self._write_bytes(board_write_packet(data, slave=self._slave))
        return self._read_bytes(2)   # 板写状态 (00 00 = OK)

    def _i2c_read(self, n):
        self._write_bytes(board_read_packet(n, slave=self._slave))
        return self._read_bytes(n + 2)   # 尾 2 字节 = 板 status + sum8

    def read_edid_name(self):
        """经小板读屏 EDID 取"厂商 型号"; 读不到返回 None。

        板包的 sub 字段就是寄存器/偏移, 所以 EDID 读 = 从 0xA1 偏移 0 读 128 字节。
        小板固件对 0xA0/0xA1 认不认没在真机验过, 所以整段包在 try 里, 拿不到就退回
        默认名 —— 绝不能因为取个显示名把主力通道搞挂。
        """
        try:
            self._write_bytes(board_read_packet(128, slave=0xA1, sub=0x00))
            raw = self._read_bytes(130)
            edid = list(raw[:128])
            if len(edid) < 128 or edid[0] != 0x00 or edid[1] != 0xFF:
                return None
            return edid_name(edid)
        except Exception:
            return None

    # ---- Backend 接口 ----
    def enum_monitors(self):
        name = self.read_edid_name() or "USB 小板"
        return [Monitor(0, "%s (USB 0x%02X)" % (name, self._slave))]

    def set_vcp(self, mon_id, code, value):
        self._i2c_write(ddc_frame(set_vcp_payload(code, value), slave=self._slave))
        # 留时间给固件处理这条 SET(如锁存 peek 地址), 再让上层发下一条 GET/SET。
        time.sleep(self._set_settle)
        return True

    def get_vcp(self, mon_id, code, retries=4):
        # 坑(PanelCalib 实测): 回包有延迟、可能带前导 0, 需 settle 后多读几次扫 `slave 8x`。
        self._i2c_write(ddc_frame(get_vcp_payload(code), slave=self._slave))
        for _ in range(max(1, retries)):
            time.sleep(self._read_settle)
            raw = self._i2c_read(16)   # 多读几字节容前导 0 + 完整 11 字节回包
            r = parse_vcp_reply(raw, code, slave=self._slave)
            if r is not None:
                return r
        return None

    def send_raw(self, mon_id, payload):
        """发任意 payload 的 DDC/CI 帧 (南微模拟按键 0xC0 等非标命令)。组帧/校验同标准帧。"""
        self._i2c_write(ddc_frame(payload, slave=self._slave))
        time.sleep(self._set_settle)
        return True

    def read_caps(self, mon_id):
        # capabilities 长帧分片读暂未实现; pinmux/phytune 不依赖 caps, 返回 None。
        return None

    def close(self):
        h = getattr(self, "_h", None)
        if h:
            try:
                self._k32.CloseHandle(h)
            except Exception:
                pass
            self._h = None
