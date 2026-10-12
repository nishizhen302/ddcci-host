# -*- coding: utf-8 -*-
"""无边框窗口 chrome —— WS_THICKFRAME + NCCALCSIZE 铺满 + NCHITTEST 缩放 + DWM 圆角。

pywebview 各入口 (app.py = pinmux/phytune, app_nanwei.py = DDCCI 控制台) 共用这套
窗口装饰逻辑。抽成独立模块的目的: 让 app_nanwei 不必 `import app` —— 后者会连带
把 phytune 整包拉进依赖树, 使南微控制台的打包混入无关界面。这里只依赖 sys + ctypes。

用法: webview.start(func=winchrome.style_native_window); 前端边缘缩放经 Api 调
winchrome._HWND / WM_APP_RESIZE。_HWND 是可变全局, 跨模块引用务必用属性访问
(winchrome._HWND), 不要 from-import 取快照 (会拿到建窗前的 0)。
"""
import os
import sys

_HWND = 0  # 主窗口句柄
_OLD_WNDPROC = None     # 子类化前的原窗口过程 (CallWindowProc 回退用)
_NEW_WNDPROC_REF = None  # 新窗口过程的 ctypes 回调, 必须全局保活否则崩溃
_RESIZE_BORDER = 8       # 边缘缩放命中区厚度 (逻辑像素, 按 DPI 缩放)
WM_APP_RESIZE = 0x8001   # 自定义消息: 前端请求边缘缩放 (wParam=HT 码), 在 GUI 线程处理
# Qt 后端 (Win7 版, DDCCI_GUI=qt) 走轻量路径: 不改边框, 只保留缩放/移动和圆角 (见 style_native_window)
_QT_LIGHT = os.environ.get("DDCCI_GUI") == "qt"


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


_RZ = None   # Qt 轻量路径的手动缩放状态: (ht, 起点光标x, y, 起始 left, top, right, bottom, 最小宽, 最小高)


def _min_size_px(hwnd):
    """窗口最小尺寸 (物理像素) = pywebview 的 min_size (逻辑像素) × DPI 缩放。"""
    import ctypes
    lw, lh = 640, 400
    try:
        import webview
        lw, lh = webview.windows[0].min_size
    except Exception:
        pass
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd) or 96
    except Exception:                       # Win7 没有 GetDpiForWindow
        dc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88) or 96
        ctypes.windll.user32.ReleaseDC(0, dc)
    return int(lw * dpi / 96), int(lh * dpi / 96)


def _manual_resize(hwnd, msg):
    """Qt 轻量路径没有 WS_THICKFRAME, 系统原生缩放 (SC_SIZE) 不响应, 这里自己跟着鼠标改窗口。
    返回 True 表示消息已处理。"""
    global _RZ
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    WM_MOUSEMOVE, WM_LBUTTONUP, WM_CAPTURECHANGED = 0x0200, 0x0202, 0x0215
    if _RZ is None:
        return False
    if msg == WM_MOUSEMOVE:
        ht, cx0, cy0, l, t, r, b, mw, mh = _RZ
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        dx, dy = pt.x - cx0, pt.y - cy0
        if ht in (10, 13, 16):              # 左边
            l = min(l + dx, r - mw)
        if ht in (11, 14, 17):              # 右边
            r = max(r + dx, l + mw)
        if ht in (12, 13, 14):              # 上边
            t = min(t + dy, b - mh)
        if ht in (15, 16, 17):              # 下边
            b = max(b + dy, t + mh)
        SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
        user32.SetWindowPos(hwnd, 0, l, t, r - l, b - t, SWP_NOZORDER | SWP_NOACTIVATE)
        return True
    if msg in (WM_LBUTTONUP, WM_CAPTURECHANGED):
        _RZ = None
        if msg == WM_LBUTTONUP:
            user32.ReleaseCapture()
        return True
    return False


def _wndproc(hwnd, msg, wparam, lparam):
    """子类化后的窗口过程: 接管 WM_NCCALCSIZE(去非客户区) 与 WM_NCHITTEST(边缘缩放),
    以及自定义 WM_APP_RESIZE(在 GUI 线程上发起原生缩放循环)。
    其余消息回退给原过程。任何异常都回退, 绝不让 GUI 崩。"""
    import ctypes
    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    WM_NCLBUTTONDOWN = 0x00A1
    try:
        if msg == WM_NCCALCSIZE and wparam and not _QT_LIGHT:
            return 0  # 客户区 = 整个窗口, 无非客户边框 (去掉那圈白框)
        if msg == WM_NCHITTEST:
            ht = _hittest(hwnd, lparam)
            if ht is not None:
                return ht
            # 不在边缘 → 落到原过程返回 HTCLIENT, 拖拽交给 pywebview-drag-region
        if _QT_LIGHT:
            if _manual_resize(hwnd, msg):
                return 0
            if msg == WM_NCLBUTTONDOWN and 10 <= int(wparam) <= 17:
                # 按在边缘 (原生命中或前端 .resz 发来的): 开始手动缩放
                global _RZ
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                pt, rc = wintypes.POINT(), wintypes.RECT()
                user32.GetCursorPos(ctypes.byref(pt))
                user32.GetWindowRect(hwnd, ctypes.byref(rc))
                mw, mh = _min_size_px(hwnd)
                _RZ = (int(wparam), pt.x, pt.y, rc.left, rc.top, rc.right, rc.bottom, mw, mh)
                user32.SetCapture(hwnd)
                return 0
        if msg == WM_APP_RESIZE:
            # 已在 GUI 线程: 先松开 WebView2 的鼠标捕获, 再进系统原生缩放循环
            user32 = ctypes.windll.user32
            user32.ReleaseCapture()
            user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, int(wparam), 0)
            return 0
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


def _set_dwm_corners(hwnd, dwm):
    """Win11: 去掉顶部边框线 + DWM 原生圆角。Win7/10 上这些属性不存在, 调用失败无害。"""
    import ctypes
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


def style_native_window():
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

        if _QT_LIGHT:
            # Qt 后端 (Win7 版): 不加 WS_THICKFRAME、不接管 NCCALCSIZE —— 这两步会让 QtWebEngine
            # 的画面停在加边框时缩小的尺寸, 贴着左下角画, 顶部和右侧各留一条黑边 (200% 屏实测
            # 24px, 抖动尺寸/改 Qt 尺寸都去不掉)。Qt 的无边框窗口客户区本来就是整窗, 只需
            # 子类化保留边缘缩放命中和 WM_APP_RESIZE (系统原生缩放/移动循环), 再加圆角即可。
            _install_subclass(hwnd)
            _set_dwm_corners(hwnd, dwm)
            return

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

        # 强制 Qt 按"客户区已铺满整窗"重新布局 webview: 加 WS_THICKFRAME 时 Windows 先把
        # 客户区缩小, Qt 据此缩了 webview; NCCALCSIZE=0 把客户区撑满后 Qt 收不到尺寸变化,
        # 顶/右会残留窗口深色底(白皮肤下=黑条)。这里抖动 1px 尺寸逼 Qt 重新 relayout 铺满。
        from ctypes import wintypes as _wt
        _r = _wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(_r))
        _w, _h = _r.right - _r.left, _r.bottom - _r.top
        SWP_SIZE = 0x0002 | 0x0004  # NOMOVE|NOZORDER (允许改 size)
        # 宽高都抖动且幅度要够: 高 DPI 下 1 物理像素 < 1 逻辑像素, 会被取整成"没变"
        # 而不触发 relayout; 缩 20px 再还原, 确保跨过 1 逻辑像素、Qt 真重排铺满。
        user32.SetWindowPos(hwnd, 0, 0, 0, _w - 20, _h - 20, SWP_SIZE)
        user32.SetWindowPos(hwnd, 0, 0, 0, _w, _h, SWP_SIZE)

        _set_dwm_corners(hwnd, dwm)
    except Exception:
        pass  # 样式优化失败不影响主功能
