#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pywebview 外壳 + JS 桥。

把 ddcci_core 的语义方法暴露成 window.pywebview.api.*；
捕获后端异常, 翻译成前端可显示的状态对象 {ok, error?, hint?, ...}，绝不抛进 JS。

运行: py -3 app.py   (Win11 自带 Edge WebView2)
"""
import os
import sys

import webview

from ddcci_core import select_backend, pick_default_monitor, parse_caps

HERE = os.path.dirname(os.path.abspath(__file__))
WIN_TITLE = "DDC/CI 控制台"

_HWND = 0  # 主窗口句柄
_OLD_WNDPROC = None     # 子类化前的原窗口过程 (CallWindowProc 回退用)
_NEW_WNDPROC_REF = None  # 新窗口过程的 ctypes 回调, 必须全局保活否则崩溃
_RESIZE_BORDER = 8       # 边缘缩放命中区厚度 (逻辑像素, 按 DPI 缩放)


def _find_own_window():
    """枚举本进程的顶层窗口, 返回可见、面积最大的那个的 hwnd (即主窗口)。
    比 FindWindow 按标题匹配可靠 (CJK/斜杠标题匹配不到)。"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    best = [0, 0]  # [hwnd, area]

    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            area = (r.right - r.left) * (r.bottom - r.top)
            if area > best[1]:
                best[0], best[1] = hwnd, area
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return best[0]


def _hittest(hwnd, lparam):
    """WM_NCHITTEST: 判断鼠标在不在四边/四角的缩放命中区, 返回对应 HT* 码。
    返回 None 表示不在边缘 (交给原过程, 通常是客户区/拖拽区)。"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    # lparam 低16位=屏幕x, 高16位=屏幕y (有符号)
    x = ctypes.c_short(lparam & 0xFFFF).value
    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    try:
        dpi = user32.GetDpiForWindow(hwnd) or 96
    except Exception:
        dpi = 96
    m = max(4, int(_RESIZE_BORDER * dpi / 96))
    left = x < r.left + m
    right = x >= r.right - m
    top = y < r.top + m
    bottom = y >= r.bottom - m
    HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
    HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
    if top and left:
        return HTTOPLEFT
    if top and right:
        return HTTOPRIGHT
    if bottom and left:
        return HTBOTTOMLEFT
    if bottom and right:
        return HTBOTTOMRIGHT
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    return None


def _wndproc(hwnd, msg, wparam, lparam):
    """子类化后的窗口过程: 接管 WM_NCCALCSIZE(去非客户区) 与 WM_NCHITTEST(边缘缩放)。
    其余消息回退给原过程。任何异常都回退, 绝不让 GUI 崩。"""
    import ctypes
    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    try:
        if msg == WM_NCCALCSIZE and wparam:
            return 0  # 客户区 = 整个窗口, 无非客户边框 (去掉那圈白框)
        if msg == WM_NCHITTEST:
            ht = _hittest(hwnd, lparam)
            if ht is not None:
                return ht
            # 不在边缘 → 落到原过程返回 HTCLIENT, 拖拽交给 pywebview-drag-region
    except Exception:
        pass
    return ctypes.windll.user32.CallWindowProcW(_OLD_WNDPROC, hwnd, msg, wparam, lparam)


def _install_subclass(hwnd):
    """把 _wndproc 装到窗口上 (替换 GWLP_WNDPROC), 保存原过程。
    去掉 WS_THICKFRAME 后, 靠 NCHITTEST 实现无边框拖拽缩放。"""
    global _OLD_WNDPROC, _NEW_WNDPROC_REF
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    LRESULT = ctypes.c_ssize_t
    WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)
    _NEW_WNDPROC_REF = WNDPROCTYPE(_wndproc)  # 全局保活

    is64 = ctypes.sizeof(ctypes.c_void_p) == 8
    SetWLP = user32.SetWindowLongPtrW if is64 else user32.SetWindowLongW
    SetWLP.restype = ctypes.c_void_p
    SetWLP.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]

    GWLP_WNDPROC = -4
    newproc = ctypes.cast(_NEW_WNDPROC_REF, ctypes.c_void_p)
    _OLD_WNDPROC = SetWLP(hwnd, GWLP_WNDPROC, newproc)


def _style_native_window():
    """无边框窗口收尾: 去掉 WS_THICKFRAME (消除白框+方阴影), 改用 NCHITTEST 子类化做边缘缩放,
    再叠大圆角区域。在 GUI 起来后由 webview.start(func=...) 回调里跑; 仅 Windows 生效, 失败静默。"""
    global _HWND
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        import time

        user32 = ctypes.windll.user32
        dwm = ctypes.windll.dwmapi
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.restype = ctypes.c_long

        hwnd = 0
        for _ in range(60):  # 窗口可能还没建好, 轮询拿句柄
            hwnd = _find_own_window()
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            return
        _HWND = hwnd

        # WS_THICKFRAME: 让窗口可缩放 + Aero Snap (无标题栏)
        GWL_STYLE = -16
        WS_THICKFRAME = 0x00040000
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_THICKFRAME)

        # 子类化: WM_NCCALCSIZE 返回 0 → 客户区铺满整窗, 消掉 THICKFRAME 那 12px 白边框
        # (WebView2 内缩露白的根因); WM_NCHITTEST 补回边缘缩放命中 (因为客户区吃掉了边框)。
        _install_subclass(hwnd)

        SWP = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)

        # 去掉 Win11 顶部那条边框线 (DWMWA_BORDER_COLOR = COLOR_NONE)
        DWMWA_BORDER_COLOR = 34
        DWMWA_COLOR_NONE = 0xFFFFFFFE
        col = ctypes.c_uint(DWMWA_COLOR_NONE)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR,
                                  ctypes.byref(col), ctypes.sizeof(col))

        # DWM 原生圆角 (DWMWCP_ROUND): 干净、抗锯齿、带正常阴影, 无白边/无脚。
        # 半径由系统定 (中等, 用户认可的大小); 配合 NCCALCSIZE 铺满后, 圆角内直接是深色画布。
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        pref = ctypes.c_int(DWMWCP_ROUND)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                  ctypes.byref(pref), ctypes.sizeof(pref))
    except Exception:
        pass  # 样式优化失败不影响主功能


def _err(e):
    """把异常翻译成前端状态对象, 带下一步提示。"""
    hint = None
    if isinstance(e, IndexError):
        hint = "显示器序号超范围, 刷新列表后重试。"
    elif isinstance(e, ValueError):
        hint = "参数或后端名不对。"
    return {"ok": False, "error": str(e) or e.__class__.__name__, "hint": hint}


class Api:
    """JS 桥。所有方法返回 JSON-able 的状态对象, 不抛异常给前端。"""

    def __init__(self, backend_name="dxva2"):
        self._backend_name = backend_name
        self._be = None

    def _ensure(self):
        if self._be is None:
            self._be = select_backend(self._backend_name)
        return self._be

    # ---- 暴露给前端的 API ----

    def list_monitors(self):
        """枚举显示器 + 读各自 caps + 选默认 (认 model(RTK) 板)。"""
        try:
            be = self._ensure()
            mons = be.enum_monitors()
            out = []
            default_id = None
            for m in mons:
                caps = be.read_caps(m.id)
                info = parse_caps(caps)
                if default_id is None and info["model"] and "RTK" in info["model"].upper():
                    default_id = m.id
                out.append({
                    "id": m.id,
                    "description": m.description,
                    "model": info["model"],
                    "type": info["type"],
                    "vcp_codes": sorted(info["vcp_codes"]),
                    "vcp_values": {str(k): v for k, v in info["vcp_values"].items()},
                    "caps": caps,
                })
            if default_id is None and mons:
                default_id = mons[0].id
            return {"ok": True, "monitors": out, "default": default_id,
                    "backend": self._backend_name, "address": be.address}
        except Exception as e:  # 桥接层兜底, 任何后端异常都翻译
            return _err(e)

    def get_caps(self, mon_id):
        try:
            be = self._ensure()
            caps = be.read_caps(int(mon_id))
            if caps is None:
                return {"ok": False, "error": "读不到 capabilities",
                        "hint": "该显示器可能不支持或 DDC/CI 未开。"}
            info = parse_caps(caps)
            return {"ok": True, "caps": caps,
                    "model": info["model"], "type": info["type"],
                    "vcp_codes": sorted(info["vcp_codes"]),
                    "vcp_values": {str(k): v for k, v in info["vcp_values"].items()}}
        except Exception as e:
            return _err(e)

    def get_vcp(self, code, mon_id):
        try:
            be = self._ensure()
            r = be.get_vcp(int(mon_id), int(code))
            if r is None:
                return {"ok": False, "error": "VCP 0x%02X 读不回" % int(code),
                        "hint": "该 VCP 可能不被支持, 或待固件验证。"}
            return {"ok": True, "current": r[0], "maximum": r[1]}
        except Exception as e:
            return _err(e)

    def set_vcp(self, code, value, mon_id):
        try:
            be = self._ensure()
            ok = be.set_vcp(int(mon_id), int(code), int(value))
            if not ok:
                return {"ok": False, "error": "写 VCP 0x%02X 失败" % int(code)}
            return {"ok": True}
        except Exception as e:
            return _err(e)

    def set_backend(self, name):
        try:
            if self._be is not None:
                self._be.close()
            self._be = None
            self._backend_name = name
            self._ensure()
            return {"ok": True, "backend": name}
        except Exception as e:
            return _err(e)

    # ---- 无边框窗口控制 (自绘标题栏调用) ----
    def minimize_window(self):
        try:
            webview.windows[0].minimize()
            return {"ok": True}
        except Exception as e:
            return _err(e)

    def close_window(self):
        try:
            webview.windows[0].destroy()
            return {"ok": True}
        except Exception as e:
            return _err(e)


def main():
    api = Api()
    window = webview.create_window(
        WIN_TITLE,
        os.path.join(HERE, "ui", "index.html"),
        js_api=api,
        width=500, height=840, min_size=(460, 640),
        background_color="#0a0a0b",  # 默认白, 改深色避免顶部露白缝
        frameless=True, easy_drag=False,  # 去原生标题栏; 拖动由 pbar 的 drag-region 负责
    )
    # func 在 GUI 线程起来后执行: WS_THICKFRAME + NCCALCSIZE 铺满 + NCHITTEST 缩放 + DWM 圆角
    func = None if os.environ.get("DDCCI_NOSTYLE") else _style_native_window
    webview.start(func, debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
