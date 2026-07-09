# -*- coding: utf-8 -*-
r"""Backend C —— 显卡 (HDMI/DP) 原始 I²C 上的 DDC/CI, 支持非标从机地址 (南微 0x5E)。

为什么要它: Windows 标准 DDC/CI API (dxva2) 只认 0x37(0x6E), 打不到 0x5E。
同事的旧工具 (Nicomsoft WinI2C-DDC / DDCHelper.dll) 证实了显卡厂商 SDK 的
用户态 I²C 通道对 0x5E 可行 —— 它在 64 位系统上走的就是 NVIDIASDK/ATISDK 模式
(其 ddcdrv.sys 是 x86 驱动, 64 位系统根本加载不了)。本后端用 ctypes 直接复刻
这两条路, 不需要内核驱动、不需要 32 位桥接:

- NVIDIA: nvapi64.dll  NvAPI_I2CWrite / NvAPI_I2CRead (接口 ID 来自公开 nvapi.h)
- AMD:    atiadlxx.dll ADL_Display_WriteAndReadI2C   (旧工具字符串里就有这条)

通道定位不靠猜: 枚举出的每个候选通道 (NVIDIA 每个 display handle / AMD 每个
adapter × I²C line) 各发一条"读亮度"探测帧, 能解析出回包的才算一台显示器。

⚠️ 状态: 结构体/接口 ID 按公开头文件编写, 尚未在真显卡上实测 (笔记本只有核显)。
到台式机上跑 `set DDCCI_BACKEND=gpu && py -3 nanwei_cli.py check` 验证;
排障开 `set DDCCI_GPU_DEBUG=1` 看每步返回码。
"""
import ctypes
import os
import sys
import time

from backends.base import Backend, Monitor
from backends.raw_usb_backend import (_SLAVE, _SUB, ddc_frame, get_vcp_payload,
                                      set_vcp_payload, parse_vcp_reply)

_DEBUG = bool(os.environ.get("DDCCI_GPU_DEBUG"))


def _dbg(fmt, *a):
    if _DEBUG:
        sys.stderr.write("[gpu] " + (fmt % a) + "\n")


# ============ NVIDIA: nvapi64.dll ============
# 接口 ID 与结构体按 NVIDIA 公开发布的 nvapi.h; QueryInterface 是唯一命名导出。
_NV_ID = {
    "Initialize": 0x0150E828,
    "EnumNvidiaDisplayHandle": 0x9ABDD40D,
    "GetAssociatedDisplayOutputId": 0xD995937E,
    "I2CRead": 0x2FDE12C5,
    "I2CWrite": 0xE812EB07,
}
_NVAPI_END_ENUMERATION = -7
_NVAPI_I2C_SPEED_DEPRECATED = 0xFFFF


class _NvI2cInfoV3(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("displayMask", ctypes.c_uint32),
        ("bIsDDCPort", ctypes.c_uint8),
        ("i2cDevAddress", ctypes.c_uint8),
        ("pbI2cRegAddress", ctypes.POINTER(ctypes.c_uint8)),
        ("regAddrSize", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_uint8)),
        ("cbSize", ctypes.c_uint32),
        ("i2cSpeed", ctypes.c_uint32),        # 必须 = DEPRECATED, 实际速度看 i2cSpeedKhz
        ("i2cSpeedKhz", ctypes.c_uint32),     # 0xFFFF = 默认
        ("portId", ctypes.c_uint8),
        ("bIsPortIdSet", ctypes.c_uint32),    # 0 = 用 displayMask 自动选口
    ]


_NV_I2C_INFO_VER3 = ctypes.sizeof(_NvI2cInfoV3) | (3 << 16)


class _NvChannel:
    """一个 NVIDIA display handle = 一条候选 DDC 通道。"""

    def __init__(self, funcs, handle, output_id, idx, slave=_SLAVE):
        self._f = funcs
        self._h = handle
        self._mask = output_id
        self.slave = slave
        self.desc = "NVIDIA display #%d (outputId 0x%X)" % (idx, output_id)

    def _info(self, dev_addr, reg, data_buf, nbytes):
        info = _NvI2cInfoV3()
        info.version = _NV_I2C_INFO_VER3
        info.displayMask = self._mask
        info.bIsDDCPort = 1
        info.i2cDevAddress = dev_addr
        if reg is not None:
            info.pbI2cRegAddress = ctypes.cast(reg, ctypes.POINTER(ctypes.c_uint8))
            info.regAddrSize = 1
        else:
            info.pbI2cRegAddress = None
            info.regAddrSize = 0
        info.pbData = ctypes.cast(data_buf, ctypes.POINTER(ctypes.c_uint8))
        info.cbSize = nbytes
        info.i2cSpeed = _NVAPI_I2C_SPEED_DEPRECATED
        info.i2cSpeedKhz = 0xFFFF
        info.portId = 0
        info.bIsPortIdSet = 0
        return info

    def i2c_write(self, data):
        """写: 从机地址 + 寄存器(源地址) 0x51 + ddc 帧。"""
        reg = (ctypes.c_uint8 * 1)(_SUB)
        buf = (ctypes.c_uint8 * len(data))(*data)
        info = self._info(self.slave, reg, buf, len(data))
        st = self._f["I2CWrite"](self._h, ctypes.byref(info))
        _dbg("nv write st=%d", st)
        return st == 0

    def i2c_read(self, n):
        """读回包: 直接从从机读 n 字节 (DDC 回读无寄存器阶段)。"""
        buf = (ctypes.c_uint8 * n)()
        info = self._info(self.slave, None, buf, n)
        st = self._f["I2CRead"](self._h, ctypes.byref(info))
        _dbg("nv read st=%d", st)
        if st != 0:
            return []
        return list(buf)


def _enum_nv_channels(slave=_SLAVE):
    try:
        nvapi = ctypes.WinDLL("nvapi64.dll")
    except OSError:
        _dbg("nvapi64.dll 不存在 (无 NVIDIA 驱动)")
        return []
    qi = nvapi.nvapi_QueryInterface
    qi.restype = ctypes.c_void_p
    qi.argtypes = [ctypes.c_uint32]
    funcs = {}
    for name, iid in _NV_ID.items():
        p = qi(iid)
        if not p:
            _dbg("nvapi 接口 %s(0x%08X) 拿不到", name, iid)
            return []
        proto = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p) \
            if name != "Initialize" else ctypes.CFUNCTYPE(ctypes.c_int)
        if name == "EnumNvidiaDisplayHandle":
            proto = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p))
        funcs[name] = proto(p)
    st = funcs["Initialize"]()
    _dbg("nvapi Initialize st=%d", st)
    if st != 0:
        return []
    chans = []
    i = 0
    while True:
        h = ctypes.c_void_p()
        st = funcs["EnumNvidiaDisplayHandle"](i, ctypes.byref(h))
        if st == _NVAPI_END_ENUMERATION:
            break
        if st != 0:
            _dbg("nvapi enum #%d st=%d", i, st)
            break
        out_id = ctypes.c_uint32(0)
        funcs["GetAssociatedDisplayOutputId"](h, ctypes.byref(out_id))
        chans.append(_NvChannel(funcs, h, out_id.value or 1, i, slave=slave))
        i += 1
    _dbg("nvapi 枚举到 %d 个 display", len(chans))
    return chans


# ============ AMD: atiadlxx.dll ============
_ADL_I2C_ACTION_READ = 1
_ADL_I2C_ACTION_WRITE = 2
_ADL_MAX_I2C_LINES = 8   # 每个 adapter 探测的 I²C line 范围


class _AdlI2c(ctypes.Structure):
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iLine", ctypes.c_int),
        ("iAddress", ctypes.c_int),   # 8bit 从机地址
        ("iOffset", ctypes.c_int),
        ("iAction", ctypes.c_int),
        ("iSpeed", ctypes.c_int),     # kHz
        ("iDataSize", ctypes.c_int),
        ("pcData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _AdlChannel:
    """AMD 一个 adapter × 一条 I²C line = 一条候选通道。"""

    def __init__(self, adl, adapter, line, slave=_SLAVE):
        self._adl = adl
        self._adapter = adapter
        self._line = line
        self.slave = slave
        self.read_addr = slave   # 有的驱动读要传 slave|1, 探测时两种都试
        self.desc = "AMD adapter %d line %d" % (adapter, line)

    def _xfer(self, action, addr, offset, offset_size, data):
        buf = (ctypes.c_ubyte * max(1, len(data)))(*data)
        pk = _AdlI2c()
        pk.iSize = ctypes.sizeof(pk)
        pk.iLine = self._line
        pk.iAddress = addr
        pk.iOffset = offset if offset_size else 0
        pk.iAction = action
        pk.iSpeed = 100
        pk.iDataSize = len(data)
        pk.pcData = buf
        st = self._adl.ADL_Display_WriteAndReadI2C(self._adapter, ctypes.byref(pk))
        _dbg("adl %s st=%d", "wr" if action == _ADL_I2C_ACTION_WRITE else "rd", st)
        return st, list(buf)

    def i2c_write(self, data):
        # 从机地址, 偏移(源地址) 0x51, 数据 = ddc 帧
        st, _ = self._xfer(_ADL_I2C_ACTION_WRITE, self.slave, _SUB, 1, data)
        return st == 0

    def i2c_read(self, n):
        st, buf = self._xfer(_ADL_I2C_ACTION_READ, self.read_addr, 0, 0, [0] * n)
        return buf if st == 0 else []


def _enum_adl_channels(slave=_SLAVE):
    try:
        adl = ctypes.WinDLL("atiadlxx.dll")
    except OSError:
        _dbg("atiadlxx.dll 不存在 (无 AMD 驱动)")
        return []
    ALLOC = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int)
    _bufs = []   # 防 GC

    def _malloc(sz):
        b = ctypes.create_string_buffer(sz)
        _bufs.append(b)
        return ctypes.cast(b, ctypes.c_void_p).value

    cb = ALLOC(_malloc)
    if adl.ADL_Main_Control_Create(cb, 1) != 0:   # 1 = 只枚举已接显示器的 adapter
        _dbg("ADL_Main_Control_Create 失败")
        return []
    n = ctypes.c_int(0)
    adl.ADL_Adapter_NumberOfAdapters_Get(ctypes.byref(n))
    _dbg("adl adapters = %d", n.value)
    chans = []
    for a in range(n.value):
        for line in range(_ADL_MAX_I2C_LINES):
            chans.append(_AdlChannel(adl, a, line, slave=slave))
    # 保活: callback 与缓冲挂到通道上, 防止 ADL 用到已回收内存
    for c in chans:
        c._keepalive = (cb, _bufs)
    return chans


# ============ 探测 + Backend ============

def _probe(channel, settle=0.06, retries=2):
    """向通道发"读亮度", 能解析出回包 = 真显示器。AMD 读地址 slave/slave|1 都试。"""
    slave = channel.slave
    frame = ddc_frame(get_vcp_payload(0x10), slave=slave)
    for read_addr in (None, slave | 1):
        if read_addr is not None:
            if not hasattr(channel, "read_addr"):
                break
            channel.read_addr = read_addr
        try:
            if not channel.i2c_write(frame):
                continue
            for _ in range(retries):
                time.sleep(settle)
                raw = channel.i2c_read(16)
                if parse_vcp_reply(raw, 0x10, slave=slave) is not None:
                    _dbg("probe OK: %s", channel.desc)
                    return True
        except Exception as e:
            _dbg("probe %s 异常: %s", channel.desc, e)
    return False


class GpuI2CBackend(Backend):
    """显卡原始 I²C 后端 (NVIDIA NVAPI / AMD ADL 自动探测)。"""

    name = "gpu"
    address = _SLAVE

    def __init__(self, read_settle=0.06, set_settle=0.06, slave=None):
        # 从机地址: 显式参数 > 环境变量 DDCCI_SLAVE > 模块默认 0x5E (同 rawusb 规则)
        if slave is None:
            slave = int(os.environ.get("DDCCI_SLAVE", "0"), 0) or _SLAVE
        self._slave = slave & 0xFF
        self.address = self._slave
        # PDF 要求读回等 >40ms; 显卡通道无 USB 板中转, 60ms 足够
        self._read_settle = read_settle
        self._set_settle = set_settle
        candidates = _enum_nv_channels(self._slave) + _enum_adl_channels(self._slave)
        if not candidates:
            raise RuntimeError(
                "没找到显卡 I²C 通道 (nvapi64.dll / atiadlxx.dll 都加载不了)。"
                "确认这台机器有 NVIDIA/AMD 显卡且装了官方驱动; "
                "笔记本核显请改用 USB 小板 (DDCCI_BACKEND=rawusb)。")
        self._chans = [c for c in candidates if _probe(c, self._read_settle)]
        if not self._chans:
            raise RuntimeError(
                "显卡通道枚举到 %d 条, 但 0x%02X 都无应答。确认显示器接在这块显卡上、"
                "从机地址选对 (0x5E/0x6E); 开 DDCCI_GPU_DEBUG=1 看逐通道返回码。"
                % (len(candidates), self._slave))

    def enum_monitors(self):
        return [Monitor(i, c.desc + " (DDC/CI 0x%02X)" % self._slave)
                for i, c in enumerate(self._chans)]

    def set_vcp(self, mon_id, code, value):
        ch = self._chans[mon_id]
        ok = ch.i2c_write(ddc_frame(set_vcp_payload(code, value), slave=self._slave))
        time.sleep(self._set_settle)
        return ok

    def get_vcp(self, mon_id, code, retries=3):
        ch = self._chans[mon_id]
        if not ch.i2c_write(ddc_frame(get_vcp_payload(code), slave=self._slave)):
            return None
        for _ in range(max(1, retries)):
            time.sleep(self._read_settle)
            r = parse_vcp_reply(ch.i2c_read(16), code, slave=self._slave)
            if r is not None:
                return r
        return None

    def send_raw(self, mon_id, payload):
        ch = self._chans[mon_id]
        ok = ch.i2c_write(ddc_frame(payload, slave=self._slave))
        time.sleep(self._set_settle)
        return ok

    def read_caps(self, mon_id):
        return None
