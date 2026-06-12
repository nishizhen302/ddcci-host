# -*- coding: utf-8 -*-
"""Backend A —— Windows 标准 DDC/CI (dxva2)。

从原 ddcci.py 平移而来。关键坑 (原样保留, 别动):
  1) 64 位下句柄是 8 字节, 不声明 argtypes 会被 ctypes 当 32 位截断。
  2) VCP code 用 c_ubyte (wintypes.BYTE 是有符号的, 会出错)。

地址固定 0x6E —— dxva2 (SetVCPFeature 等) 写死打到 0x6E, 不给改地址的口子。
板子若配在 0x5E 应答, dxva2 物理上够不着 → 走 Backend B (未来)。
"""
import ctypes
from ctypes import wintypes

from .base import Backend, Monitor

user32 = ctypes.WinDLL("user32", use_last_error=True)
dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)


class PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [("hPhysicalMonitor", wintypes.HANDLE),
                ("szPhysicalMonitorDescription", wintypes.WCHAR * 128)]


# 声明 argtypes/restype —— 64 位下句柄是 8 字节, 不声明会被 ctypes 当 32 位截断。
LPDWORD = ctypes.POINTER(wintypes.DWORD)
dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [wintypes.HMONITOR, LPDWORD]
dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [wintypes.HMONITOR, wintypes.DWORD, ctypes.POINTER(PHYSICAL_MONITOR)]
dxva2.GetPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
dxva2.DestroyPhysicalMonitor.argtypes = [wintypes.HANDLE]
dxva2.DestroyPhysicalMonitor.restype = wintypes.BOOL
dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes = [wintypes.HANDLE, ctypes.c_ubyte, LPDWORD, LPDWORD, LPDWORD]
dxva2.GetVCPFeatureAndVCPFeatureReply.restype = wintypes.BOOL
dxva2.SetVCPFeature.argtypes = [wintypes.HANDLE, ctypes.c_ubyte, wintypes.DWORD]
dxva2.SetVCPFeature.restype = wintypes.BOOL
dxva2.GetCapabilitiesStringLength.argtypes = [wintypes.HANDLE, LPDWORD]
dxva2.GetCapabilitiesStringLength.restype = wintypes.BOOL
dxva2.CapabilitiesRequestAndCapabilitiesReply.argtypes = [wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD]
dxva2.CapabilitiesRequestAndCapabilitiesReply.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL


def _enum_hmonitors():
    """枚举所有 HMONITOR。"""
    hmons = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def _cb(hmon, hdc, lprc, lparam):
        hmons.append(hmon)
        return True

    if not user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return hmons


# ---------------------------------------------------------------------------
# EDID 机型名 (QueryDisplayConfig, user32, Win7+)
#
# GetPhysicalMonitorsFromHMONITOR 给的描述 = 显示器驱动 INF 的设备描述,
# 没装厂商 INF 的显示器一律是 "Generic PnP Monitor"。
# DISPLAYCONFIG_TARGET_DEVICE_NAME.monitorFriendlyDeviceName 直接取自
# EDID 0xFC 机型名描述符, 不依赖驱动。按 GDI 设备名 (\\.\DISPLAY1) 和
# HMONITOR 对账。
# ---------------------------------------------------------------------------

class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _DC_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", _LUID), ("id", wintypes.DWORD),
                ("modeInfoIdx", wintypes.DWORD), ("statusFlags", wintypes.DWORD)]


class _DC_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.DWORD), ("Denominator", wintypes.DWORD)]


class _DC_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [("adapterId", _LUID), ("id", wintypes.DWORD),
                ("modeInfoIdx", wintypes.DWORD),
                ("outputTechnology", wintypes.DWORD), ("rotation", wintypes.DWORD),
                ("scaling", wintypes.DWORD), ("refreshRate", _DC_RATIONAL),
                ("scanLineOrdering", wintypes.DWORD), ("targetAvailable", wintypes.BOOL),
                ("statusFlags", wintypes.DWORD)]


class _DC_PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", _DC_PATH_SOURCE_INFO),
                ("targetInfo", _DC_PATH_TARGET_INFO),
                ("flags", wintypes.DWORD)]


class _DC_MODE_INFO(ctypes.Structure):
    # 真身是 header + union, 这里只占位凑 sizeof, 内容不用
    _fields_ = [("infoType", wintypes.DWORD), ("id", wintypes.DWORD),
                ("adapterId", _LUID), ("_union", ctypes.c_byte * 48)]


class _DC_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("size", wintypes.DWORD),
                ("adapterId", _LUID), ("id", wintypes.DWORD)]


class _DC_SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", _DC_DEVICE_INFO_HEADER),
                ("viewGdiDeviceName", wintypes.WCHAR * 32)]


class _DC_TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", _DC_DEVICE_INFO_HEADER),
                ("flags", wintypes.DWORD),
                ("outputTechnology", wintypes.DWORD),
                ("edidManufactureId", wintypes.USHORT),
                ("edidProductCodeId", wintypes.USHORT),
                ("connectorInstance", wintypes.DWORD),
                ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
                ("monitorDevicePath", wintypes.WCHAR * 128)]


_QDC_ONLY_ACTIVE_PATHS = 2
_GET_SOURCE_NAME = 1   # DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
_GET_TARGET_NAME = 2   # DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME


def _edid_names_by_gdi_device():
    """{GDI 设备名 -> [EDID 机型名, ...]}。任何一步失败都安静返回 {} (名字回退驱动描述)。"""
    names = {}
    try:
        npath = wintypes.UINT()
        nmode = wintypes.UINT()
        if user32.GetDisplayConfigBufferSizes(
                _QDC_ONLY_ACTIVE_PATHS, ctypes.byref(npath), ctypes.byref(nmode)):
            return {}
        paths = (_DC_PATH_INFO * npath.value)()
        modes = (_DC_MODE_INFO * nmode.value)()
        if user32.QueryDisplayConfig(
                _QDC_ONLY_ACTIVE_PATHS, ctypes.byref(npath), paths,
                ctypes.byref(nmode), modes, None):
            return {}
        for p in paths[:npath.value]:
            src = _DC_SOURCE_DEVICE_NAME()
            src.header.type = _GET_SOURCE_NAME
            src.header.size = ctypes.sizeof(src)
            src.header.adapterId = p.sourceInfo.adapterId
            src.header.id = p.sourceInfo.id
            if user32.DisplayConfigGetDeviceInfo(ctypes.byref(src)):
                continue
            tgt = _DC_TARGET_DEVICE_NAME()
            tgt.header.type = _GET_TARGET_NAME
            tgt.header.size = ctypes.sizeof(tgt)
            tgt.header.adapterId = p.targetInfo.adapterId
            tgt.header.id = p.targetInfo.id
            if user32.DisplayConfigGetDeviceInfo(ctypes.byref(tgt)):
                continue
            name = tgt.monitorFriendlyDeviceName.strip()
            if name:
                names.setdefault(src.viewGdiDeviceName, []).append(name)
    except Exception:
        return {}
    return names


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


def _gdi_device_of(hmon):
    """HMONITOR -> GDI 设备名 (\\\\.\\DISPLAY1); 失败返回 None。"""
    mi = _MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(mi)
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    return mi.szDevice


class Dxva2Backend(Backend):
    """Windows 标准 DDC/CI 后端。内部持有 physical monitor 句柄表, close 时统一 destroy。"""

    name = "dxva2"
    address = 0x6E  # dxva2 写死, 不可改

    def __init__(self):
        self._handles = []   # mon_id -> hPhysicalMonitor
        self._descs = []     # mon_id -> 描述

    def enum_monitors(self):
        self.close()  # 释放上一轮句柄, 避免泄漏
        self._handles = []
        self._descs = []
        edid_names = _edid_names_by_gdi_device()
        for hmon in _enum_hmonitors():
            count = wintypes.DWORD()
            if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count)):
                continue
            if count.value == 0:
                continue
            arr = (PHYSICAL_MONITOR * count.value)()
            if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, count.value, arr):
                continue
            # 优先用 EDID 0xFC 机型名 (驱动描述对没装厂商 INF 的屏只会是
            # "Generic PnP Monitor"); 克隆模式一个 hmon 带多台, 按序对应
            names = edid_names.get(_gdi_device_of(hmon), [])
            for i, pm in enumerate(arr):
                name = names[i] if i < len(names) else None
                self._descs.append(name or pm.szPhysicalMonitorDescription)
                self._handles.append(pm.hPhysicalMonitor)
        return [Monitor(i, d) for i, d in enumerate(self._descs)]

    def _handle(self, mon_id):
        """按 mon_id 取句柄。未枚举过则先枚举。越界抛 IndexError。"""
        if not self._handles:
            self.enum_monitors()
        if mon_id < 0 or mon_id >= len(self._handles):
            raise IndexError("显示器序号 %d 超范围 (共 %d 个)" % (mon_id, len(self._handles)))
        return self._handles[mon_id]

    def get_vcp(self, mon_id, code):
        h = self._handle(mon_id)
        cur = wintypes.DWORD()
        mx = wintypes.DWORD()
        vct = wintypes.DWORD()  # MC_VCP_CODE_TYPE, 忽略
        ok = dxva2.GetVCPFeatureAndVCPFeatureReply(
            h, code, ctypes.byref(vct),
            ctypes.byref(cur), ctypes.byref(mx))
        if not ok:
            return None
        return cur.value, mx.value

    def set_vcp(self, mon_id, code, value):
        h = self._handle(mon_id)
        return bool(dxva2.SetVCPFeature(h, code, value))

    def read_caps(self, mon_id):
        h = self._handle(mon_id)
        length = wintypes.DWORD()
        if not dxva2.GetCapabilitiesStringLength(h, ctypes.byref(length)) or length.value == 0:
            return None
        buf = ctypes.create_string_buffer(length.value)
        if not dxva2.CapabilitiesRequestAndCapabilitiesReply(h, buf, length.value):
            return None
        return buf.value.decode("ascii", "replace")

    def close(self):
        for h in self._handles:
            try:
                dxva2.DestroyPhysicalMonitor(h)
            except Exception:
                pass
        self._handles = []
        self._descs = []
