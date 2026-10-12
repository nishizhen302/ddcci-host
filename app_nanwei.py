#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""南微协议控制台 —— pywebview 外壳 + JS 桥。

固定协议控件 (亮度/对比度/色温/Gamma/模拟按键/版本), 不依赖 caps;
后端默认 rawusb (USB 小板旁路 I²C, 从机 0x5E)。以后切显卡通道 =
加一个显卡 I²C Backend, 设 DDCCI_BACKEND 即可, 本文件与前端零改动。

运行: py -3 app_nanwei.py   (或 南微控制台.bat)
"""
import json
import os
import sys
import urllib.error
import urllib.request
import webbrowser

import webview

import version
import winchrome  # 共享无边框窗口样式/缩放机制, 避免拉入其它界面依赖
from ddcci_core import select_backend
import nanwei_core as nw
from backends.raw_usb_backend import get_vcp_payload, set_vcp_payload

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
WIN_TITLE = "DDCCI控制台"


def _default_settings_path():
    # 页面由 pywebview 的随机端口 http 服务提供, origin 每次启动都变 -> localStorage 记不住东西;
    # 需要跨启动保留的选择 (机型) 存这里。
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DDCCI-Nanwei", "settings.json")


def _err(e, backend=None):
    hint = None
    if isinstance(e, RuntimeError):
        if backend == "gpu":
            # 英伟达机走的是 32 位 helper 子进程 (64 位 nvapi 是死路), 分层排障靠 nvscan
            hint = "显卡通道不通: 跑 nanwei_cli.py nvscan 看 helper 起没起来、哪块屏应答。"
        else:
            hint = "确认 USB 小板已插好、未被烧录工具独占。"
    elif isinstance(e, NotImplementedError):
        hint = "当前后端不支持该操作, 切 rawusb 后端。"
    return {"ok": False, "error": str(e) or e.__class__.__name__, "hint": hint}


class Api:
    """JS 桥。所有方法返回 JSON-able 状态对象, 不抛异常给前端; 附 tx 帧十六进制供日志窗。"""

    def __init__(self, backend_name="rawusb", settings_path=None):
        self._backend_name = backend_name
        self._be = None
        self._dev = None
        self._settings_path = settings_path or _default_settings_path()
        self._model = self._load_settings().get("model", nw.DEFAULT_MODEL)
        if self._model not in nw.MODEL_IDS:
            self._model = nw.DEFAULT_MODEL

    def _load_settings(self):
        try:
            with open(self._settings_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_settings(self, **changes):
        """写失败 (只读目录等) 不影响使用, 只是下次启动不记得。"""
        try:
            data = self._load_settings()
            data.update(changes)
            os.makedirs(os.path.dirname(self._settings_path), exist_ok=True)
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _ensure(self):
        if self._dev is None:
            raise RuntimeError("尚未建链, 先 connect + select_monitor")
        return self._dev

    def shutdown(self):
        """放掉长期持有的后端 (gpu 后端会顺带关掉 32 位 helper 子进程)。

        关窗时必须调 —— 不调就留一个 nvddc32.exe 在任务管理器里 (2026-07-30 实遇)。
        """
        dev, be, self._be, self._dev = self._dev, self._be, None, None
        if dev is not None and hasattr(dev, "release_keys"):
            try:
                dev.release_keys()      # 216pin: 关窗时万一还按着键, 补发松开
            except Exception:
                pass
        if be is not None:
            try:
                be.close()
            except Exception:
                pass

    # ---- 机型 (启动选择页) ----
    def models(self):
        """可选机型。slaves 给前端显示用十六进制串。"""
        out = []
        for m in nw.MODELS:
            item = dict(m)
            item["slaves"] = ["0x%02X" % a for a in m["slaves"]]
            out.append(item)
        return {"ok": True, "models": out, "current": self._model}

    def select_model(self, model_id):
        """切机型: 断开当前连接, 之后的扫描/建链/控件都按新机型来。返回新机型的协议常量。"""
        try:
            nw.model_info(model_id)
            self.shutdown()
            self._model = str(model_id)
            self._save_settings(model=self._model)
            return self.protocol_meta()
        except Exception as e:
            return _err(e)

    def _model_cls(self):
        return nw.Monitor216 if self._model == "216" else nw.NanweiMonitor

    # ---- 连接 / 选显示器 ----
    def discover_targets(self):
        """扫描可用控制路径。地址 0x5E/0x6E 都探, 每台应答的显示器自动识别机型
        (nw.detect_model), 前端选中哪个目标就按它的机型切界面 —— 客户不用手选机型。

        快扫: gpu 只探显示器级通道 (fallback_scan=False), 启动明显更快;
        全部落空时才放开 line 盲扫重扫一次 gpu (保底不丢功能)。
        """
        targets = []
        errors = []

        def scan(name, slave, **kw):
            be = None
            try:
                be = select_backend(name, slave=slave, **kw)
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
                        "model": nw.detect_model(be, m.id),
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

        backends = [self._backend_name]
        for name in ("rawusb", "gpu"):
            if name not in backends:
                backends.append(name)
        slaves = nw.ALL_SLAVES
        for name in backends:
            for slave in slaves:
                if name == "gpu":
                    scan(name, slave, fallback_scan=False)
                else:
                    scan(name, slave)
        if not targets:
            errors.append("快扫无目标, 放开 line 盲扫重试 gpu")
            for slave in slaves:
                scan("gpu", slave, fallback_scan=True)
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
            model = str(target.get("model") or self._model)
            nw.model_info(model)
            if model != self._model:
                self._model = model
                self._save_settings(model=model)
            self._backend_name = backend_name
            self._be = select_backend(backend_name, slave=slave)
            mons = self._be.enum_monitors()
            if not mons:
                raise RuntimeError("后端 %s 没枚举到显示器" % backend_name)
            self._dev = nw.make_monitor(self._model, self._be, mon_id)
            versions = self._dev.versions()
            desc = next((m.description for m in mons if m.id == mon_id), mons[0].description)
            return {"ok": True, "backend": backend_name, "address": "0x%02X" % self._be.address,
                    "mon_id": mon_id, "description": desc, "versions": versions,
                    "model": self._model, "meta": self.protocol_meta()}
        except Exception as e:
            self._be = None
            self._dev = None
            err = _err(e, self._backend_name)
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
            err = _err(e, self._backend_name)
            err["backend"] = self._backend_name
            return err

    def select_monitor(self, mon_id):
        """选中一台显示器并读它的版本 (版本读不到不算失败, 前端显示 — 即可)。"""
        try:
            if self._be is None:
                raise RuntimeError("尚未建链")
            self._dev = nw.make_monitor(self._model, self._be, int(mon_id))
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

    def get_choice(self, kind):
        """读色温/gamma, 返回已换算成"选项值"的 current (各机型读回规则不同)。"""
        try:
            dev = self._ensure()
            r = dev.get_choice(str(kind))
            tx = nw.frame_hex(get_vcp_payload(nw.CHOICE_OPS[str(kind)]), dev.slave)
            if r is None:
                return {"ok": False, "error": "无应答", "tx": tx}
            return {"ok": True, "current": r[0], "maximum": r[1], "tx": tx}
        except Exception as e:
            return _err(e)

    def set_choice(self, kind, value):
        try:
            dev = self._ensure()
            dev.set_choice(str(kind), int(value))
            return {"ok": True, "tx": nw.frame_hex(dev.choice_payload(str(kind), int(value)), dev.slave)}
        except Exception as e:
            return _err(e)

    def hold_key(self, name, seconds):
        """216pin: 按住某键 seconds 秒再松开 (长按类 OSD 操作)。期间前端锁住按键区。"""
        try:
            if not nw.model_info(self._model)["hold"]:
                return {"ok": False, "error": "当前机型不支持长按"}
            dev = self._ensure()
            held = dev.hold_key(str(name), float(seconds))
            k = nw.HOLD_KEYS_216[str(name)]
            tx = "%s  … %.1fs …  %s" % (
                nw.frame_hex(nw.key_payload_216(k, nw.KEY_MODE_HOLD), dev.slave), held,
                nw.frame_hex(nw.key_payload_216(nw.KEY_RELEASE_216, nw.KEY_MODE_TAP), dev.slave))
            return {"ok": True, "seconds": held, "tx": tx}
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

    def enter_factory(self):
        """按键宏进工厂菜单: Menu→OK。前端按钮期间置灰。"""
        if not nw.model_info(self._model)["macros"]:
            return {"ok": False, "error": "当前机型没有这个按键宏"}
        try:
            dev = self._ensure()
            sent = dev.enter_factory()
            return {"ok": True, "keys": sent,
                    "tx": " → ".join(k.upper() for k in sent)}
        except Exception as e:
            return _err(e)

    def start_aging(self):
        """按键宏开启老化: Menu→OK 进工厂菜单, 再 Menu×2→Right→Menu→Exit×2。

        整个宏约 3 秒 (含按键间隔), 前端按钮期间置灰。
        """
        if not nw.model_info(self._model)["macros"]:
            return {"ok": False, "error": "当前机型没有这个按键宏"}
        try:
            dev = self._ensure()
            sent = dev.start_aging()
            return {"ok": True, "keys": sent,
                    "tx": " → ".join(k.upper() for k in sent)}
        except Exception as e:
            return _err(e)

    def press_key_raw(self, value):
        """按任意键值发一次模拟按键 (0~255, 十进制或 '0x04')。逆向 OK 等未知键用。"""
        try:
            val = int(str(value), 0) & 0xFF
            dev = self._ensure()
            dev.press_key_value(val)
            return {"ok": True, "tx": nw.frame_hex(nw.key_payload(val), dev.slave)}
        except Exception as e:
            return _err(e)

    def protocol_meta(self):
        """协议常量交给前端渲染 (单一数据源, 前端不重复写值表), 按当前机型给。"""
        cls = self._model_cls()
        info = nw.model_info(self._model)
        return {"ok": True,
                "model": self._model,
                "features": {"macros": info["macros"], "hold": info["hold"]},
                "colortemp": cls.COLORTEMP,
                "gamma": cls.GAMMA,
                "ops": {"brightness": nw.OP_BRIGHTNESS, "contrast": nw.OP_CONTRAST,
                        "colortemp": nw.OP_COLORTEMP, "gamma": nw.OP_GAMMA}}

    # ---- 版本 / 检查更新 (仓库公开, 匿名对比 GitHub) ----
    def app_version(self):
        """本机版本, 不联网 —— 标题栏先把版本号显示出来, 别干等联网那 6 秒超时。"""
        info = version.get_local()
        return {"ok": True, "version": info["version"], "sha": info["sha"],
                "date": info["date"], "source": info["source"]}

    def _gh_json(self, url):
        req = urllib.request.Request(url, headers={
            "User-Agent": "DDCCI-Nanwei-UpdateCheck",
            "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read().decode("utf-8"))

    def check_update(self):
        """对比本机打包时的提交与远端分支最新提交。

        产线机器多半没网, 所以任何失败都只填 error 让前端安静显示版本号, 不弹错。
        """
        info = version.get_local()
        result = {"ok": True, "current": info["version"], "sha": info["sha"],
                  "date": info["date"], "has_update": False, "behind_by": 0,
                  "latest_sha": "", "url": version.REPO_URL, "error": None}
        sha_full = info.get("sha_full")
        if not sha_full:
            result["error"] = "无法确定当前版本 (这份源码没有 git 记录)"
            return result
        try:
            latest = self._gh_json("https://api.github.com/repos/%s/commits/%s"
                                   % (version.REPO, version.BRANCH))
            latest_sha = latest.get("sha", "")
            result["latest_sha"] = latest_sha[:7]
            if latest_sha and latest_sha != sha_full:
                try:
                    cmp = self._gh_json(
                        "https://api.github.com/repos/%s/compare/%s...%s"
                        % (version.REPO, sha_full, latest_sha))
                    if cmp.get("status") in ("ahead", "diverged"):
                        result["has_update"] = True
                        result["behind_by"] = cmp.get("ahead_by", 0)
                except Exception:
                    # 比不了几乎都是"本机这个提交还没推上去"(远端根本没有这个 sha)。
                    # 那是开发版跑在前面, 不是落后 —— 别谎报有更新。
                    result["error"] = "本机版本未推送到远端, 无法比对"
        except urllib.error.URLError:
            result["error"] = "网络不可用, 暂时无法检查更新"
        except Exception as e:
            result["error"] = "检查失败: %s" % type(e).__name__
        return result

    def open_repo(self):
        try:
            webbrowser.open(version.REPO_URL)
            return {"ok": True}
        except Exception as e:
            return _err(e)

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
        width=690, height=420, min_size=(640, 400),
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
            # Win7 打包入口已按主屏 DPI 注入 QT_SCALE_FACTOR; 这时再开 Qt 自动缩放会叠成两倍
            # (200% 屏上窗口变 4 倍大, 2026-10-12 实测)。只在没注入时才让 Qt 自己检测。
            if not os.environ.get("QT_SCALE_FACTOR"):
                QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
            QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        except Exception:
            pass
    try:
        webview.start(func, gui=gui, debug="--debug" in sys.argv)
    finally:
        api.shutdown()
    # 关窗后硬退: QtWebEngine (Win7 版) 的渲染器进程和 Qt 自己的清理线程会让
    # 主进程赖着不走, 任务管理器里就攒下一堆。后端已在上面关干净, 这里直接退。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
