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
        for hmon in _enum_hmonitors():
            count = wintypes.DWORD()
            if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count)):
                continue
            if count.value == 0:
                continue
            arr = (PHYSICAL_MONITOR * count.value)()
            if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, count.value, arr):
                continue
            for pm in arr:
                self._descs.append(pm.szPhysicalMonitorDescription)
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
