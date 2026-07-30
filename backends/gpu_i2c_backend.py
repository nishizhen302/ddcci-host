# -*- coding: utf-8 -*-
r"""Backend C —— 显卡 (HDMI/DP) 原始 I²C 上的 DDC/CI, 支持非标从机地址 (南微 0x5E)。

为什么要它: Windows 标准 DDC/CI API (dxva2) 只认 0x37(0x6E), 打不到 0x5E。
同事的旧工具 (Nicomsoft WinI2C-DDC / DDCHelper.dll) 证实了显卡厂商 SDK 的
用户态 I²C 通道对 0x5E 可行 —— 它在 64 位系统上走的就是 NVIDIASDK/ATISDK 模式
(其 ddcdrv.sys 是 x86 驱动, 64 位系统根本加载不了)。本后端用 ctypes 直接复刻
这两条路, 不需要内核驱动、不需要 32 位桥接:

- NVIDIA: nvapi64.dll  NvAPI_I2CWrite / NvAPI_I2CRead (接口 ID 来自公开 nvapi.h)
- NVIDIA(32 位桥): tools/nvddc32.exe —— 见下, 实机唯一走得通的那条
- AMD:    atiadlxx.dll ADL_Display_WriteAndReadI2C   (旧工具字符串里就有这条)

通道定位不靠猜: 枚举出的每个候选通道 (NVIDIA 每个 display / AMD 每个 adapter ×
I²C line) 各发一条"读亮度"探测帧, 能解析出回包的才算一台显示器。

== 2026-07-24 实机结论 (英伟达 + Win7, 抓别人能通 0x5E 的工具得到) ==
1. 结构体要 NV_I2C_INFO_V1 (不是 V3), 非 Ex 的 I2CWrite/I2CRead, i2cSpeed=0x0A。
2. handle 参数要传"第一块 display 的 displayMask 值", 不是 EnumNvidiaDisplayHandle
   返回的 0xDE0000xx 句柄 (传句柄恒 -8 INVALID_HANDLE); 选哪块屏靠结构体 displayMask。
3. DDC 源地址 0x51 并进 data, regAddrSize=0 (当寄存器发不通); 读地址 = 写地址|1 (0x5F)。
4. **那台机的 64 位 nvapi64 无论怎么调都回 -8, 只有 32 位 nvapi 能通** —— 所以本模块
   除了进程内直连 (nvapi64/atiadlxx), 还有一条 `nv32` 通道: 走 32 位 helper 子进程
   `tools/nvddc32.exe` (backends/nv32_helper.py)。两条都当候选丢进探测, 谁应答用谁。
AMD 侧 (2026-07-10 真机) 走 atiadlxx 直连即可, 无 32 位问题; 首选按显示器定位的
ADL_Display_DDCBlockAccess_Get (旧工具同款), adapter × line 盲扫只当兜底。

排障: `set DDCCI_BACKEND=gpu && py -3 nanwei_cli.py check`, 开 `set DDCCI_GPU_DEBUG=1`
看每条通道返回码; 只想试 32 位桥: `set DDCCI_GPU_CHANNELS=nv32`。
"""
import ctypes
import os
import sys
import time

from backends import nv32_helper
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
_NVAPI_INVALID_HANDLE = -8   # handle 没过驱动校验层, 帧根本没发出去
# 2026-07-24 真机抓包(别人能通 0x5E 的 Beacon_Qa_TestGamma, nvapi shim 拦截)结论：
# 之前 NV 恒 -5 的真凶是用了 V3 结构体。能通的工具用 NV_I2C_INFO_V1(version 低16位=
# sizeof)，非 Ex I2CWrite/Read，i2cSpeed 用固定值 0x0A(V1 没有 i2cSpeedKhz/portId)。
_NVAPI_I2C_SPEED = 0x0A


class _NvI2cInfoV1(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("displayMask", ctypes.c_uint32),
        ("bIsDDCPort", ctypes.c_uint8),
        ("i2cDevAddress", ctypes.c_uint8),
        ("pbI2cRegAddress", ctypes.POINTER(ctypes.c_uint8)),
        ("regAddrSize", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_uint8)),
        ("cbSize", ctypes.c_uint32),
        ("i2cSpeed", ctypes.c_uint32),        # V1 尾字段；抓包实测填 0x0A
    ]


# version 低 16 位是结构体字节数(64 位下 = 48 → 0x00010030；32 位工具是 0x00010020)，
# 由 ctypes.sizeof 自动算，跟着调用方位数走，别硬编码。
_NV_I2C_INFO_VER1 = ctypes.sizeof(_NvI2cInfoV1) | (1 << 16)


class _NvChannel:
    """一块 NVIDIA display (由 displayMask 标识) = 一条候选 DDC 通道。

    handle 由 `_pick_nv_handle` 探出来 (不能按屏数猜, 见那里的注释), 全通道共用
    同一个; 区分目标屏只靠结构体里的 displayMask。
    """

    def __init__(self, funcs, handle, mask, idx, slave=_SLAVE):
        self._f = funcs
        self._h = handle
        self._mask = mask
        self.slave = slave
        # label = UI 里给人看的显示器身份 (EDID 名优先); desc = 日志/排障用的全量细节
        self.label = "NVIDIA display #%d" % idx
        self.desc = "NVIDIA display #%d (mask 0x%X)" % (idx, mask)

    def read_edid_name(self):
        """读 EDID 取"厂商 型号"; 读不到返回 None。只在枚举时调一次。"""
        try:
            off = (ctypes.c_uint8 * 1)(0x00)
            info = self._info(0xA0, off, 1)
            if self._f["I2CWrite"](self._h, ctypes.byref(info)) != 0:
                return None
            time.sleep(0.04)
            buf = (ctypes.c_uint8 * 128)()
            info = self._info(0xA1, buf, 128)
            if self._f["I2CRead"](self._h, ctypes.byref(info)) != 0:
                return None
            return nv32_helper.edid_name(list(buf))
        except Exception as e:
            _dbg("nv EDID 读失败: %s", e)
            return None

    def _info(self, dev_addr, data_buf, nbytes):
        info = _NvI2cInfoV1()
        info.version = _NV_I2C_INFO_VER1
        info.displayMask = self._mask
        info.bIsDDCPort = 1
        info.i2cDevAddress = dev_addr
        info.pbI2cRegAddress = None      # 源地址 0x51 并进 data, 不作寄存器
        info.regAddrSize = 0
        info.pbData = ctypes.cast(data_buf, ctypes.POINTER(ctypes.c_uint8))
        info.cbSize = nbytes
        info.i2cSpeed = _NVAPI_I2C_SPEED
        return info

    def i2c_write(self, data):
        """写: 数据 = 源地址 0x51 + ddc 帧 (从机地址由 i2cDevAddress 给)。"""
        payload = [_SUB] + list(data)
        buf = (ctypes.c_uint8 * len(payload))(*payload)
        info = self._info(self.slave, buf, len(payload))
        st = self._f["I2CWrite"](self._h, ctypes.byref(info))
        _dbg("nv write st=%d", st)
        return st == 0

    def i2c_read(self, n):
        """读回包: 从 从机读地址(=写地址|1, 即 0x5F) 读 n 字节 (DDC 回读无寄存器阶段)。
        抓包实测别人工具读用 0x5F，之前用 0x5E 读不到。"""
        buf = (ctypes.c_uint8 * n)()
        info = self._info(self.slave | 1, buf, n)
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
    masks = []
    raw_handles = []
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
        masks.append(out_id.value or 1)
        raw_handles.append(h)
        i += 1
    if not masks:
        _dbg("nvapi 一块 display 都没枚举到")
        return []
    handle = _pick_nv_handle(funcs, masks, raw_handles, slave)
    chans = [_NvChannel(funcs, handle, m, i, slave=slave) for i, m in enumerate(masks)]
    for c in chans:                       # 取显示器名, UI 列表要拿它当身份
        name = c.read_edid_name()
        if name:
            c.label = name
            c.desc = "%s (mask 0x%X)" % (name, c._mask)
    _dbg("nvapi 枚举到 %d 个 display, handle=0x%X", len(chans), handle.value or 0)
    return chans


def _nv_handle_candidates(masks, raw_handles):
    """handle 候选表, 优先级同 32 位 helper (tools/nvddc32.c 的 handle_candidates)。"""
    out = []
    for m in masks:
        if m not in out:
            out.append(m)
    for k in range(32):
        v = 1 << k
        if v not in out:
            out.append(v)
    return [ctypes.c_void_p(v) for v in out] + [h for h in raw_handles if h.value]


def _pick_nv_handle(funcs, masks, raw_handles, slave):
    """探出 I2CWrite/Read 该传的 handle。

    这个参数不是 Enum 出来的 0xDE0000xx 句柄 (那样恒 -8)。2026-07-24 抓包那台机上
    是 0x100, 当时枚举到两块屏 (0x100/0x400), 于是错记成"第一块 display 的 mask";
    2026-07-30 只接一块屏 (枚举只剩 0x400) 时 handle=0x400 恒 -8, 整条通道看着像
    死了。所以不猜: 逐个候选往 EDID 地址 0xA0 写一字节, 返回码不是 -8 就采纳
    (无副作用, 不读回, 全表扫完 <50ms)。全军覆没则退回老行为。
    """
    override = os.environ.get("DDCCI_NV_HANDLE")
    if override:
        try:
            return ctypes.c_void_p(int(override, 0))
        except ValueError:
            _dbg("DDCCI_NV_HANDLE=%r 不是数字, 忽略", override)
    probe = _NvChannel(funcs, None, masks[0], 0, slave=slave)
    buf = (ctypes.c_uint8 * 1)(0x00)
    for cand in _nv_handle_candidates(masks, raw_handles):
        info = probe._info(0xA0, buf, 1)
        st = funcs["I2CWrite"](cand, ctypes.byref(info))
        if st != _NVAPI_INVALID_HANDLE:
            _dbg("nv handle 探到 0x%X (A0 写 st=%d)", cand.value or 0, st)
            return cand
    _dbg("nv handle 全部候选都回 -8, 退回 masks[0]=0x%X", masks[0])
    return ctypes.c_void_p(masks[0])


# ============ NVIDIA (32 位桥): tools/nvddc32.exe ============
# 2026-07-24 当时结论是"64 位 nvapi64 全回 -8, 只有 32 位 nvapi 通", 于是有了这条桥。
# 2026-07-30 查明 -8 的真因是 handle 传错 (见 _pick_nv_handle), 与位数无关 —— 修完
# 64 位直连在同一台机上也通了。桥保留: 它已在真机长期验证, 且万一某驱动只认 32 位
# 仍是退路。协议/定位见 backends/nv32_helper.py。

class _Nv32Channel:
    """helper 里的一块 display = 一条候选 DDC 通道 (读写都经子进程一行命令)。"""

    def __init__(self, client, mask, name=None, slave=_SLAVE):
        self._c = client
        self._mask = mask
        self.slave = slave
        self.label = name or "NVIDIA display"
        self.desc = "NVIDIA(32桥) %s (mask 0x%X)" % (name or "display", mask)

    def i2c_write(self, data):
        try:
            self._c.write(self._mask, self.slave, [_SUB] + list(data))
            return True
        except nv32_helper.Nv32Error as e:
            _dbg("nv32 write 失败: %s", e)
            return False

    def i2c_read(self, n):
        try:
            return self._c.read(self._mask, self.slave | 1, n)
        except nv32_helper.Nv32Error as e:
            _dbg("nv32 read 失败: %s", e)
            return []

    def i2c_xfer(self, data, n, delay_ms):
        """写完等 delay_ms 再读 —— 一次子进程往返, GET VCP 用这条省一半 IPC。"""
        try:
            return self._c.xfer(self._mask, self.slave, self.slave | 1,
                                [_SUB] + list(data), n, delay_ms)
        except nv32_helper.Nv32Error as e:
            _dbg("nv32 xfer 失败: %s", e)
            return []


def _enum_nv32_channels(slave=_SLAVE):
    """拉起 helper 并列出它枚举到的 display。返回 (通道列表, client);
    helper 不可用时返回 ([], None) —— 非英伟达机走这条是正常的, 不报错。"""
    try:
        client = nv32_helper.Nv32Client().start()
    except nv32_helper.Nv32Error as e:
        _dbg("32 位 helper 不可用: %s", e)
        return [], None
    chans = []
    for m in client.masks:
        name = nv32_helper.edid_name(client.edid(m))
        chans.append(_Nv32Channel(client, m, name, slave=slave))
    _dbg("nv32 helper 枚举到 %d 个 display", len(chans))
    return chans, client


# ============ AMD: atiadlxx.dll ============
_ADL_I2C_ACTION_READ = 1
_ADL_I2C_ACTION_WRITE = 2
_ADL_MAX_I2C_LINES = 8   # 每个 adapter 探测的 I²C line 范围 (盲扫兜底用)
_ADL_DDC_OPTION_SWITCHDDC2 = 1
_ADL_DISPLAY_CONNECTED = 1


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


class _AdlDisplayID(ctypes.Structure):
    _fields_ = [
        ("iDisplayLogicalIndex", ctypes.c_int),
        ("iDisplayPhysicalIndex", ctypes.c_int),
        ("iDisplayLogicalAdapterIndex", ctypes.c_int),
        ("iDisplayPhysicalAdapterIndex", ctypes.c_int),
    ]


class _AdlDisplayInfo(ctypes.Structure):
    _fields_ = [
        ("displayID", _AdlDisplayID),
        ("iDisplayControllerIndex", ctypes.c_int),
        ("strDisplayName", ctypes.c_char * 256),
        ("strDisplayManufacturerName", ctypes.c_char * 256),
        ("iDisplayType", ctypes.c_int),
        ("iDisplayOutputType", ctypes.c_int),
        ("iDisplayConnector", ctypes.c_int),
        ("iDisplayInfoMask", ctypes.c_int),
        ("iDisplayInfoValue", ctypes.c_int),
    ]


class _AdlDdcChannel:
    """AMD 一台已接显示器 = 一条 DDC block 通道 (ADL_Display_DDCBlockAccess_Get)。

    旧工具 (WinI2C-DDC) 在 AMD 上走的就是这条, 2026-07-10 真机验证通过: 整帧含从机
    地址一起交给驱动, 按显示器定位, 不用猜 I²C line。写 = [slave 51 帧...];
    读 = 发 [slave|1] 收 n 字节。iOption 两种都试 (不同驱动对 DDC2 开关口味不一)。
    """

    def __init__(self, adl, adapter, display, name, slave=_SLAVE):
        self._adl = adl
        self._adapter = adapter
        self._display = display
        self.slave = slave
        self.read_addr = slave | 1
        self.framing = "opt0"
        self.label = name or "AMD display %d" % display
        self.desc = "AMD adapter %d display %d (%s)" % (adapter, display, name)

    def _option(self):
        return _ADL_DDC_OPTION_SWITCHDDC2 if self.framing == "opt1" else 0

    def i2c_write(self, data):
        block = [self.slave, _SUB] + list(data)
        buf = (ctypes.c_ubyte * len(block))(*block)
        rlen = ctypes.c_int(0)
        st = self._adl.ADL_Display_DDCBlockAccess_Get(
            self._adapter, self._display, self._option(), 0,
            len(block), buf, ctypes.byref(rlen), None)
        _dbg("adl-ddc write [%s] st=%d", self.framing, st)
        return st == 0

    def i2c_read(self, n):
        send = (ctypes.c_ubyte * 1)(self.read_addr)
        buf = (ctypes.c_ubyte * n)()
        rlen = ctypes.c_int(n)
        st = self._adl.ADL_Display_DDCBlockAccess_Get(
            self._adapter, self._display, self._option(), 0,
            1, send, ctypes.byref(rlen), buf)
        _dbg("adl-ddc read [0x%02X] st=%d rlen=%d", self.read_addr, st, rlen.value)
        if st != 0:
            return []
        return list(buf[:max(0, rlen.value)] or buf)


class _AdlChannel:
    """AMD 一个 adapter × 一条 I²C line = 一条候选通道 (原始 I²C, 盲扫兜底)。"""

    is_fallback = True   # 盲扫: 只有显示器级通道全落空时才试, 否则每次建链白等 8×N 条

    def __init__(self, adl, adapter, line, slave=_SLAVE):
        self._adl = adl
        self._adapter = adapter
        self._line = line
        self.slave = slave
        self.read_addr = slave   # 有的驱动读要传 slave|1, 探测时两种都试
        self.label = "AMD display (line %d)" % line   # 盲扫通道拿不到显示器名
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
    if n.value <= 0:
        _dbg("ADL 加载 OK 但枚举到 0 个 adapter")
        return []
    chans = []
    seen = set()
    # 首选: 每台已接显示器一条 DDC block 通道 (旧工具同款, 按显示器定位不用猜 line)
    try:
        adl.ADL_Display_DisplayInfo_Get.argtypes = [
            ctypes.c_int, ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.POINTER(_AdlDisplayInfo)), ctypes.c_int]
        for a in range(n.value):
            cnt = ctypes.c_int(0)
            infos = ctypes.POINTER(_AdlDisplayInfo)()
            st = adl.ADL_Display_DisplayInfo_Get(a, ctypes.byref(cnt), ctypes.byref(infos), 0)
            if st != 0 or not infos:
                _dbg("adl DisplayInfo_Get adapter %d st=%d", a, st)
                continue
            for j in range(cnt.value):
                di = infos[j]
                if not (di.iDisplayInfoValue & _ADL_DISPLAY_CONNECTED):
                    continue
                key = (di.displayID.iDisplayPhysicalAdapterIndex,
                       di.displayID.iDisplayPhysicalIndex)
                if key in seen:
                    continue
                seen.add(key)
                name = di.strDisplayName.decode("mbcs", "replace").strip("\x00 ")
                chans.append(_AdlDdcChannel(adl, a, di.displayID.iDisplayLogicalIndex,
                                            name, slave=slave))
        _dbg("adl DDC block 通道 = %d", len(chans))
    except Exception as e:
        _dbg("adl 显示器枚举异常: %s", e)
    # 兜底: adapter × line 盲扫 (标了 is_fallback, 首选通道全落空才探)
    for a in range(n.value):
        for line in range(_ADL_MAX_I2C_LINES):
            chans.append(_AdlChannel(adl, a, line, slave=slave))
    # 保活: callback 与缓冲挂到通道上, 防止 ADL 用到已回收内存
    for c in chans:
        c._keepalive = (cb, _bufs)
    return chans


# ============ 探测 + Backend ============

def _read_after_write(channel, frame, n, settle):
    """写一帧 + 等 settle + 读 n 字节。通道支持 i2c_xfer (32 位桥) 就一次往返干完。"""
    xfer = getattr(channel, "i2c_xfer", None)
    if xfer is not None:
        return xfer(frame, n, int(settle * 1000))
    if not channel.i2c_write(frame):
        return []
    time.sleep(settle)
    return channel.i2c_read(n)


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
            for _ in range(retries):
                raw = _read_after_write(channel, frame, 16, settle)
                if parse_vcp_reply(raw, 0x10, slave=slave) is not None:
                    _dbg("probe OK: %s", channel.desc)
                    return True
        except Exception as e:
            _dbg("probe %s 异常: %s", channel.desc, e)
    return False


def _pick_channels(candidates, settle, fallback_scan=True):
    """先探显示器级通道 (NV display / AMD DDC block), 全落空才放开盲扫通道。

    盲扫 = AMD adapter × line, 一台机能有几十条, 每条都要发帧等应答; 有显示器级
    通道时跳过它们, 建链快好几秒 (GUI 的快扫就是 fallback_scan=False)。
    """
    primary = [c for c in candidates if not getattr(c, "is_fallback", False)]
    live = [c for c in primary if _probe(c, settle)]
    if live or not fallback_scan:
        return _dedup_by_label(live)
    fallback = [c for c in candidates if getattr(c, "is_fallback", False)]
    return _dedup_by_label([c for c in fallback if _probe(c, settle)])


def _dedup_by_label(chans):
    """同一台屏只留一条通道。

    2026-07-30 起 64 位直连和 32 位桥在同一台机上都通了, 于是同一块屏出现两次、
    UI 上两行字一模一样。保留先探到的那条 (候选顺序 = nv64 直连优先, 少一个子进程)。
    """
    out, seen = [], set()
    for c in chans:
        key = getattr(c, "label", None) or c.desc
        if key in seen:
            _dbg("同屏重复通道, 跳过: %s", c.desc)
            continue
        seen.add(key)
        out.append(c)
    return out


class GpuI2CBackend(Backend):
    """显卡原始 I²C 后端 (NVIDIA NVAPI / AMD ADL 自动探测)。"""

    name = "gpu"
    address = _SLAVE

    def __init__(self, read_settle=0.06, set_settle=0.06, slave=None, fallback_scan=True):
        # 从机地址: 显式参数 > 环境变量 DDCCI_SLAVE > 模块默认 0x5E (同 rawusb 规则)
        if slave is None:
            slave = int(os.environ.get("DDCCI_SLAVE", "0"), 0) or _SLAVE
        self._slave = slave & 0xFF
        self.address = self._slave
        # PDF 要求读回等 >40ms; 显卡通道无 USB 板中转, 60ms 足够
        self._read_settle = read_settle
        self._set_settle = set_settle
        self._nv32 = None            # 32 位 helper 进程 (用到才有)
        # 想只试某类通道: DDCCI_GPU_CHANNELS=nv64,nv32,amd 里挑 (默认全试)
        want = [s.strip() for s in
                os.environ.get("DDCCI_GPU_CHANNELS", "nv64,nv32,amd").split(",") if s.strip()]
        candidates = []
        if "nv64" in want:
            candidates += _enum_nv_channels(self._slave)      # 进程内直连 (快)
        if "nv32" in want:
            chans, client = _enum_nv32_channels(self._slave)  # 32 位 helper (那台机唯一通的)
            candidates += chans
            self._nv32 = client
        if "amd" in want:
            candidates += _enum_adl_channels(self._slave)
        try:
            if not candidates:
                # 文案只用 ASCII 符号: 老机器 GBK 控制台 print 到 '²' 会抛
                # UnicodeEncodeError, 把真正的错误盖掉。
                raise RuntimeError(
                    "没找到显卡 I2C 通道 (nvapi64.dll / atiadlxx.dll 加载不了, "
                    "32 位 helper 也没枚举到 display)。确认这台机器有 NVIDIA/AMD 显卡"
                    "且装了官方驱动; 笔记本核显请改用 USB 小板 (DDCCI_BACKEND=rawusb)。")
            self._chans = _pick_channels(candidates, self._read_settle, fallback_scan)
            if not self._chans:
                raise RuntimeError(
                    "显卡通道枚举到 %d 条, 但 0x%02X 都无应答。确认显示器接在这块显卡上、"
                    "从机地址选对 (0x5E/0x6E); 开 DDCCI_GPU_DEBUG=1 看逐通道返回码。"
                    % (len(candidates), self._slave))
        except Exception:
            self.close()             # 建链失败别把 helper 进程留着
            raise

    def enum_monitors(self):
        # UI 里只要"屏名 (DDC/CI 0x5E)"; mask/桥/adapter 那些排障细节走 desc 进日志。
        return [Monitor(i, "%s (DDC/CI 0x%02X)" % (c.label, self._slave))
                for i, c in enumerate(self._chans)]

    def set_vcp(self, mon_id, code, value):
        ch = self._chans[mon_id]
        ok = ch.i2c_write(ddc_frame(set_vcp_payload(code, value), slave=self._slave))
        time.sleep(self._set_settle)
        return ok

    def get_vcp(self, mon_id, code, retries=3):
        ch = self._chans[mon_id]
        frame = ddc_frame(get_vcp_payload(code), slave=self._slave)
        for _ in range(max(1, retries)):
            r = parse_vcp_reply(_read_after_write(ch, frame, 16, self._read_settle),
                                code, slave=self._slave)
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

    def close(self):
        """关掉 32 位 helper 子进程 (直连通道无资源可放)。"""
        c, self._nv32 = getattr(self, "_nv32", None), None
        if c is not None:
            c.close()
