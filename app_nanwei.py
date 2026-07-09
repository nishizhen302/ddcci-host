#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""南微协议控制台 —— pywebview 外壳 + JS 桥。

固定协议控件 (亮度/对比度/色温/Gamma/模拟按键/版本), 不依赖 caps;
后端默认 rawusb (USB 小板旁路 I²C, 从机 0x5E)。以后切显卡通道 =
加一个显卡 I²C Backend, 设 DDCCI_BACKEND 即可, 本文件与前端零改动。

运行: py -3 app_nanwei.py   (或 南微控制台.bat)
"""
import os
import sys

import webview

import winchrome  # 共享无边框窗口样式/缩放机制, 避免拉入其它界面依赖
from ddcci_core import select_backend
import nanwei_core as nw
from backends.raw_usb_backend import get_vcp_payload, set_vcp_payload

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
WIN_TITLE = "DDCCI控制台"


def _err(e):
    hint = None
    if isinstance(e, RuntimeError):
        hint = "确认 USB 小板已插好、未被烧录工具独占。"
    elif isinstance(e, NotImplementedError):
        hint = "当前后端不支持该操作, 切 rawusb 后端。"
    return {"ok": False, "error": str(e) or e.__class__.__name__, "hint": hint}


class Api:
    """JS 桥。所有方法返回 JSON-able 状态对象, 不抛异常给前端; 附 tx 帧十六进制供日志窗。"""

    def __init__(self, backend_name="rawusb"):
        self._backend_name = backend_name
        self._be = None
        self._dev = None

    def _ensure(self):
        if self._dev is None:
            raise RuntimeError("尚未建链, 先 connect + select_monitor")
        return self._dev

    # ---- 连接 / 选显示器 ----
    def discover_targets(self):
        """扫描可用控制路径。地址 0x5E/0x6E 自动探测, UI 只选择路径。"""
        targets = []
        errors = []
        backends = [self._backend_name]
        for name in ("rawusb", "gpu"):
            if name not in backends:
                backends.append(name)
        for name in backends:
            for slave in (0x5E, 0x6E):
                be = None
                try:
                    be = select_backend(name, slave=slave)
                    mons = be.enum_monitors()
                    live = []
                    for m in mons:
                        probe = be.get_vcp(m.id, nw.OP_BRIGHTNESS)
                        if probe is not None:
                            live.append(m)
                    for m in live:
                        tid = "%s:0x%02X:%s" % (name, slave, m.id)
                        targets.append({
                            "id": tid,
                            "backend": name,
                            "address": "0x%02X" % slave,
                            "mon_id": m.id,
                            "description": m.description,
                            "recommended": name == "rawusb",
                        })
                except Exception as e:
                    errors.append("%s 0x%02X: %s" % (name, slave, str(e) or e.__class__.__name__))
                finally:
                    if be is not None:
                        try:
                            be.close()
                        except Exception:
                            pass
        targets.sort(key=lambda t: (0 if t["recommended"] else 1, t["backend"], t["address"], t["mon_id"]))
        return {"ok": True, "targets": targets, "errors": errors}

    def connect_target(self, target):
        """按 discover_targets 返回的路径建链并选中显示器。"""
        try:
            if self._be is not None:
                self._be.close()
            self._be = None
            self._dev = None
            backend_name = str(target.get("backend") or self._backend_name)
            slave = int(str(target.get("address") or "0x5E"), 0)
            mon_id = int(target.get("mon_id", 0))
            self._backend_name = backend_name
            self._be = select_backend(backend_name, slave=slave)
            mons = self._be.enum_monitors()
            if not mons:
                raise RuntimeError("后端 %s 没枚举到显示器" % backend_name)
            self._dev = nw.NanweiMonitor(self._be, mon_id)
            versions = self._dev.versions()
            desc = next((m.description for m in mons if m.id == mon_id), mons[0].description)
            return {"ok": True, "backend": backend_name, "address": "0x%02X" % self._be.address,
                    "mon_id": mon_id, "description": desc, "versions": versions}
        except Exception as e:
            self._be = None
            self._dev = None
            err = _err(e)
            err["backend"] = self._backend_name
            return err

    def connect(self, slave=None):
        """(重新)建链并枚举显示器。slave = '0x5E'/'0x6E'/None(用环境变量或默认)。"""
        try:
            if self._be is not None:
                self._be.close()
            self._be = None
            self._dev = None
            kwargs = {}
            if slave:
                kwargs["slave"] = int(str(slave), 0)
            self._be = select_backend(self._backend_name, **kwargs)
            mons = self._be.enum_monitors()
            if not mons:
                raise RuntimeError("后端 %s 没枚举到显示器" % self._backend_name)
            return {"ok": True, "backend": self._backend_name,
                    "address": "0x%02X" % self._be.address,
                    "monitors": [{"id": m.id, "description": m.description} for m in mons]}
        except Exception as e:
            self._be = None
            self._dev = None
            err = _err(e)
            err["backend"] = self._backend_name
            return err

    def select_monitor(self, mon_id):
        """选中一台显示器并读它的版本 (版本读不到不算失败, 前端显示 — 即可)。"""
        try:
            if self._be is None:
                raise RuntimeError("尚未建链")
            self._dev = nw.NanweiMonitor(self._be, int(mon_id))
            return {"ok": True, "versions": self._dev.versions()}
        except Exception as e:
            self._dev = None
            return _err(e)

    # ---- 参数读写 ----
    def get_param(self, op):
        try:
            dev = self._ensure()
            r = dev.get(int(op))
            tx = nw.frame_hex(get_vcp_payload(int(op)), dev.slave)
            if r is None:
                return {"ok": False, "error": "无应答", "tx": tx}
            return {"ok": True, "current": r[0], "maximum": r[1], "tx": tx}
        except Exception as e:
            return _err(e)

    def set_param(self, op, value):
        try:
            dev = self._ensure()
            dev.set(int(op), int(value))
            return {"ok": True, "tx": nw.frame_hex(set_vcp_payload(int(op), int(value)), dev.slave)}
        except Exception as e:
            return _err(e)

    def press_key(self, name):
        try:
            if name not in nw.KEYS:
                raise ValueError("未知按键 %r" % name)
            dev = self._ensure()
            dev.press_key(name)
            return {"ok": True, "tx": nw.frame_hex(nw.key_payload(nw.KEYS[name]), dev.slave)}
        except Exception as e:
            return _err(e)

    def protocol_meta(self):
        """协议常量交给前端渲染 (单一数据源, 前端不重复写值表)。"""
        return {"ok": True,
                "colortemp": nw.COLORTEMP_VALUES,
                "gamma": nw.GAMMA_VALUES,
                "ops": {"brightness": nw.OP_BRIGHTNESS, "contrast": nw.OP_CONTRAST,
                        "colortemp": nw.OP_COLORTEMP, "gamma": nw.OP_GAMMA}}

    # ---- 无边框窗口控制 (同 app.py) ----
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
        try:
            import ctypes
            if winchrome._HWND:
                ctypes.windll.user32.PostMessageW(winchrome._HWND, winchrome.WM_APP_RESIZE, int(ht), 0)
            return {"ok": True}
        except Exception as e:
            return _err(e)

    def resize_to(self, width, height):
        """按前端测得的内容高度调整窗口 (逻辑像素), 实现窗口高度自适应内容。"""
        try:
            webview.windows[0].resize(int(width), int(height))
            return {"ok": True}
        except Exception as e:
            return _err(e)


def main():
    backend_name = os.environ.get("DDCCI_BACKEND", "rawusb")
    sys.stderr.write("[nanwei] backend = %s\n" % backend_name)
    api = Api(backend_name=backend_name)
    webview.create_window(
        WIN_TITLE,
        os.path.join(HERE, "ui", "nanwei", "index.html"),
        js_api=api,
        width=430, height=420, min_size=(390, 300),
        background_color="#0a0a0b",
        frameless=True, easy_drag=False,
    )
    func = None if os.environ.get("DDCCI_NOSTYLE") else winchrome.style_native_window
    # Win11 build: leave GUI auto-detection to pywebview so it uses Edge/WebView2.
    # Set DDCCI_GUI=qt only for a local compatibility experiment.
    gui = os.environ.get("DDCCI_GUI") or None
    if gui == "qt":
        try:
            from qtpy.QtCore import Qt, QCoreApplication
            QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
            QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        except Exception:
            pass
    webview.start(func, gui=gui, debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
