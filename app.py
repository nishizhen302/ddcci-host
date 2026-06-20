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
from phytune.regaccess import RegAccess
from phytune.params import load_params
from phytune import ced as ced_mod
from phytune.pins import load_pins, GPIO_OUT_KINDS as P_GPIO_OUT_KINDS

# 源码运行时 = 脚本目录; PyInstaller 打包后 = 解压临时目录(_MEIPASS), ui 资源在其下
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
WIN_TITLE = "DDC/CI 控制台"

_HWND = 0  # 主窗口句柄
_OLD_WNDPROC = None     # 子类化前的原窗口过程 (CallWindowProc 回退用)
_NEW_WNDPROC_REF = None  # 新窗口过程的 ctypes 回调, 必须全局保活否则崩溃
_RESIZE_BORDER = 8       # 边缘缩放命中区厚度 (逻辑像素, 按 DPI 缩放)
WM_APP_RESIZE = 0x8001   # 自定义消息: 前端请求边缘缩放 (wParam=HT 码), 在 GUI 线程处理


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
    """子类化后的窗口过程: 接管 WM_NCCALCSIZE(去非客户区) 与 WM_NCHITTEST(边缘缩放),
    以及自定义 WM_APP_RESIZE(在 GUI 线程上发起原生缩放循环)。
    其余消息回退给原过程。任何异常都回退, 绝不让 GUI 崩。"""
    import ctypes
    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    WM_NCLBUTTONDOWN = 0x00A1
    try:
        if msg == WM_NCCALCSIZE and wparam:
            return 0  # 客户区 = 整个窗口, 无非客户边框 (去掉那圈白框)
        if msg == WM_NCHITTEST:
            ht = _hittest(hwnd, lparam)
            if ht is not None:
                return ht
            # 不在边缘 → 落到原过程返回 HTCLIENT, 拖拽交给 pywebview-drag-region
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

    # ---- PHY 调试: 具名寄存器 peek/poke ----
    def phytune_peek(self, page, offset, mon_id):
        try:
            be = self._ensure()
            v = RegAccess(be, int(mon_id)).peek(int(page), int(offset))
            if v is None:
                return {"ok": False, "error": "peek 0x%02X:0x%02X 失败" % (int(page), int(offset)),
                        "hint": "确认已烧带 _DEBUG_PHY_TUNE_SUPPORT 的调试固件。"}
            return {"ok": True, "value": v}
        except Exception as e:
            return _err(e)

    def phytune_poke(self, page, offset, data, type_, mon_id):
        try:
            be = self._ensure()
            ok = RegAccess(be, int(mon_id)).poke(int(page), int(offset), int(data), int(type_))
            return {"ok": True} if ok else {"ok": False,
                    "error": "poke 0x%02X:0x%02X<-0x%02X 失败" % (int(page), int(offset), int(data))}
        except Exception as e:
            return _err(e)

    # ---- PHY 调试: 命名参数模型(分组滑杆用) ----
    def _model(self):
        if getattr(self, "_param_model", None) is None:
            self._param_model = load_params()
        return self._param_model

    def phytune_params(self):
        """返回参数表(分组 + 参数描述)给前端建控件。"""
        try:
            m = self._model()
            return {"ok": True, "groups": m.groups,
                    "params": [p.to_dict() for p in m.params]}
        except Exception as e:
            return _err(e)

    def phytune_param_read(self, name, mon_id, port=2):
        try:
            ra = RegAccess(self._ensure(), int(mon_id))
            v = self._model().by_name(name).read(ra, int(port))
            if v is None:
                return {"ok": False, "error": "读 %s 失败" % name,
                        "hint": "确认已烧调试固件且 DDC/CI 为标准 0x6E 模式。"}
            return {"ok": True, "value": v}
        except Exception as e:
            return _err(e)

    def phytune_param_write(self, name, value, mon_id, port=2):
        try:
            ra = RegAccess(self._ensure(), int(mon_id))
            ok = self._model().by_name(name).write(ra, int(value), int(port))
            return {"ok": True} if ok else {"ok": False, "error": "写 %s 失败" % name}
        except Exception as e:
            return _err(e)

    # ---- PHY 调试 P1: override 表(让重锁后被覆盖的 DFE 值固化)----
    def phytune_override_pin(self, name, mon_id, port=2):
        """把参数当前值钉进它的固定 override 槽(按端口选页); 固件重锁后自动盖回。"""
        try:
            p = self._model().by_name(name)
            if p.slot is None:
                return {"ok": False, "error": "%s 是在线参数, 无需固化" % name}
            ra = RegAccess(self._ensure(), int(mon_id))
            ok = ra.override_pin(p.eff_page(int(port)), p.offset, p.slot)
            return {"ok": True, "slot": p.slot} if ok else {"ok": False, "error": "钉住 %s 失败" % name}
        except Exception as e:
            return _err(e)

    def phytune_override_clear(self, name, mon_id):
        """取消固化某参数(清它的 override 槽)。"""
        try:
            p = self._model().by_name(name)
            if p.slot is None:
                return {"ok": False, "error": "%s 无 override 槽" % name}
            ra = RegAccess(self._ensure(), int(mon_id))
            ok = ra.override_clear(p.slot)
            return {"ok": True} if ok else {"ok": False, "error": "清除 %s 失败" % name}
        except Exception as e:
            return _err(e)

    def phytune_override_clearall(self, mon_id):
        """清空整张 override 表。"""
        try:
            ra = RegAccess(self._ensure(), int(mon_id))
            ok = ra.override_clearall()
            return {"ok": True} if ok else {"ok": False, "error": "清空 override 表失败"}
        except Exception as e:
            return _err(e)

    def phytune_dfe_freeze(self, mon_id, on, port=2):
        """[一键开眼] 冻结/解冻 DFE 自适应环 (P7B_A1/B1/C1 = DFE_EN_2, 三 lane)。
        on=True 写 0x00 = 关全部自适应环 → 均衡器定在当前系数, 手动设的 LE/Tap1 才不被冲掉;
        on=False 写 0xC3 = 恢复 LE+Vth+Tap0~1 自适应(>1000M 档默认, 近似值, 真值随像素钟,
        彻底恢复靠重锁/拔插)。按端口偏移 D3=P7C。"""
        try:
            port = int(port)
            if not (2 <= port <= 5):
                return {"ok": False, "error": "port 只能 2~5"}
            page = 0x7B + (port - 2)
            val = 0x00 if on else 0xC3
            ra = RegAccess(self._ensure(), int(mon_id))
            for off in (0xA1, 0xB1, 0xC1):       # L0/L1/L2 DFE_EN_2
                if not ra.poke(page, off, val):
                    return {"ok": False, "error": "写 P%02X_%02X 失败" % (page, off)}
            return {"ok": True}
        except Exception as e:
            return _err(e)

    def phytune_dfe_reload(self, mon_id, port=2, lane=None):
        """[一键开眼] 把 A5/B5/C5(LE+Tap1 初值)推进活均衡器: 翻转 P7B_AA/BA/CA[2:1]
        (置 0x06 再清), 即固件自己用的 "Reload LE/Tap1" 动作(TMDSRx2.c:1538)。
        lane=None 三 lane 全 reload; 0/1/2 只 reload 该 lane。按端口偏移。"""
        try:
            port = int(port)
            if not (2 <= port <= 5):
                return {"ok": False, "error": "port 只能 2~5"}
            page = 0x7B + (port - 2)
            regs = {0: 0xAA, 1: 0xBA, 2: 0xCA}
            offs = list(regs.values()) if lane is None else [regs[int(lane)]]
            ra = RegAccess(self._ensure(), int(mon_id))
            for off in offs:
                cur = ra.peek(page, off)
                if cur is None:
                    return {"ok": False, "error": "读 P%02X_%02X 失败" % (page, off)}
                if not ra.poke(page, off, cur | 0x06):     # 置 reload 位
                    return {"ok": False, "error": "置 reload 失败"}
                if not ra.poke(page, off, cur & ~0x06):    # 清回 (脉冲)
                    return {"ok": False, "error": "清 reload 失败"}
            return {"ok": True}
        except Exception as e:
            return _err(e)

    def phytune_ced_read(self, mon_id, port=2):
        """[误码监视] 读当前端口三通道 (R/G/B) SCDC 字符误码计数 (CED)。
        sink 硬件实时统计, 读后清零 → 定时轮询得到的是该间隔内的误码率, 作为
        调 LE/Tap1/CDR 的客观方向判据。纯上位机读, 不需改固件。
        返回 {ok, channels:[{name,label,count,valid}], valid}; valid=任一通道有效
        (= 链路处在 HDMI2.0 加扰高速模式, 才有误码统计)。"""
        try:
            ra = RegAccess(self._ensure(), int(mon_id))
            r = ced_mod.read_ced(ra, int(port))
            if r is None:
                return {"ok": False, "error": "读 CED 失败",
                        "hint": "确认已烧调试固件且 DDC/CI 为标准 0x6E 模式。"}
            return {"ok": True, "channels": r["channels"], "valid": r["valid"]}
        except Exception as e:
            return _err(e)

    def phytune_output_enable(self, mon_id, on, port=2):
        """[自检 B] 开/关当前端口 TMDS RGB 输出 (P71_A6[6:4], 按端口偏移)。
        关=画面立刻黑, 开=恢复。这是固件 AVMute 用的同一个使能, 安全可逆。
        用来肉眼证明"写实时到了硅片/画面"。"""
        try:
            port = int(port)
            if not (2 <= port <= 5):
                return {"ok": False, "error": "port 只能 2~5"}
            page = 0x71 + (port - 2)          # 频检/控制页随端口偏移: D2=0x71 D3=0x72...
            ra = RegAccess(self._ensure(), int(mon_id))
            cur = ra.peek(page, 0xA6)
            if cur is None:
                return {"ok": False, "error": "读 P%02X_A6 失败" % page}
            newb = (cur | 0x70) if on else (cur & ~0x70)   # bit[6:5:4] = RGB 输出使能
            ok = ra.poke(page, 0xA6, newb)
            return {"ok": True} if ok else {"ok": False, "error": "写输出使能失败"}
        except Exception as e:
            return _err(e)

    # ---- 管脚配置器 ----
    def _pindb(self):
        if getattr(self, "_pin_db", None) is None:
            self._pin_db = load_pins()
        return self._pin_db

    def pin_db(self):
        """返回按域分组的全脚静态表(给前端建列表)。"""
        try:
            db = self._pindb()
            domains = [{"domain": d, "pins": [p.to_dict() for p in ps]}
                       for d, ps in db.by_domain()]
            return {"ok": True, "domains": domains}
        except Exception as e:
            return _err(e)

    def pin_read(self, ball, mon_id):
        """读单脚当前复用值/功能名(+GPIO 电平, 若当前是 GPIO 输出)。"""
        try:
            ra = RegAccess(self._ensure(), int(mon_id))
            pin = self._pindb().by_ball(ball)
            mux = pin.read_mux(ra)
            if mux is None:
                return {"ok": False, "error": "读 %s 失败" % ball,
                        "hint": "板不在线或 DDC/CI 未开; 拔插后点 ↻ 重新枚举。"}
            level = None
            if mux["kind"] in P_GPIO_OUT_KINDS and pin.gpio:
                level = pin.gpio_read(ra)
            return {"ok": True, "mux": mux, "level": level}
        except Exception as e:
            return _err(e)

    def pin_set_mux(self, ball, val, mon_id):
        try:
            ra = RegAccess(self._ensure(), int(mon_id))
            ok = self._pindb().by_ball(ball).set_mux(ra, int(val))
            return {"ok": True} if ok else {"ok": False, "error": "切 %s 复用失败" % ball}
        except Exception as e:
            return _err(e)

    def gpio_read(self, ball, mon_id):
        try:
            ra = RegAccess(self._ensure(), int(mon_id))
            v = self._pindb().by_ball(ball).gpio_read(ra)
            if v is None:
                return {"ok": False, "error": "%s 无 GPIO 映射或读失败" % ball}
            return {"ok": True, "level": v}
        except Exception as e:
            return _err(e)

    def gpio_set(self, ball, level, mon_id):
        try:
            ra = RegAccess(self._ensure(), int(mon_id))
            ok = self._pindb().by_ball(ball).gpio_set(ra, int(level))
            return {"ok": True} if ok else {"ok": False, "error": "置 %s 电平失败" % ball}
        except Exception as e:
            return _err(e)

    def pin_reset_default(self, ball, mon_id):
        try:
            ra = RegAccess(self._ensure(), int(mon_id))
            ok = self._pindb().by_ball(ball).reset_default(ra)
            return {"ok": True} if ok else {"ok": False, "error": "还原 %s 默认失败" % ball}
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

    def start_resize(self, ht):
        """前端在窗口边/角 pointerdown 时调用: 发 WM_NCLBUTTONDOWN 进系统原生缩放循环。
        因 WebView2 子窗铺满整窗、父窗 NCHITTEST 摸不到边缘, 改由 JS 触发 (同拖动机制)。
        ht = HT 命中码 (10..17: 左/右/上/左上/右上/下/左下/右下)。"""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            if _HWND:
                # 投到 GUI 线程处理 (ReleaseCapture 必须在拥有捕获的线程上才生效)
                user32.PostMessageW(_HWND, WM_APP_RESIZE, int(ht), 0)
            return {"ok": True}
        except Exception as e:
            return _err(e)


def main():
    api = Api()
    if os.environ.get("DDCCI_PINMUX"):
        page = "pinmux/index.html"
    elif os.environ.get("DDCCI_PHYTUNE"):
        page = "phytune/index.html"
    else:
        page = "index.html"
    window = webview.create_window(
        WIN_TITLE,
        os.path.join(HERE, "ui", page),
        js_api=api,
        width=500, height=840, min_size=(460, 640),
        background_color="#0a0a0b",  # 默认白, 改深色避免顶部露白缝
        frameless=True, easy_drag=False,  # 去原生标题栏; 拖动由 pbar 的 drag-region 负责
    )
    # func 在 GUI 线程起来后执行: WS_THICKFRAME + NCCALCSIZE 铺满 + NCHITTEST 缩放 + DWM 圆角
    func = None if os.environ.get("DDCCI_NOSTYLE") else _style_native_window
    # 渲染后端: Win11 默认 edgechromium(WebView2); Win7 走 'qt'(PyQt5 + QtWebEngine 自带 Chromium)。
    # 由 DDCCI_GUI 环境变量选择, 不设则交给 pywebview 自动探测 (保持原 Win11 行为)。
    gui = os.environ.get("DDCCI_GUI") or None
    if gui == "qt":
        # 高 DPI 缩放: 必须在 QApplication(webview.start 内部创建)之前开启高 DPI 缩放属性,
        # 否则 ①QT_SCALE_FACTOR(冻结时由 app_win7 注入)不生效 ②非感知时被系统位图拉伸=点击偏移。
        # 说明: 非冻结时 AA 自动检测系数正常工作; 冻结时自动检测失灵恒为 1x, 由 app_win7 注入的
        # QT_SCALE_FACTOR 在此 AA 之上补足正确系数(1×系数), 故两种情形都得到正确缩放。
        try:
            from qtpy.QtCore import Qt, QCoreApplication
            QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
            QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        except Exception:
            pass
    webview.start(func, gui=gui, debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
