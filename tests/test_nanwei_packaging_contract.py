# -*- coding: utf-8 -*-
"""Packaging contract for the Nanwei Win11 build."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_nanwei_console_spec_uses_webview2_without_qt_runtime():
    spec = _read("Nanwei-Console.spec")
    assert "webview.platforms.edgechromium" in spec
    assert "collect_all" not in spec
    assert "webview.platforms.qt" not in spec
    assert "PyQtWebEngine" not in spec


def test_nanwei_specs_ship_the_32bit_nvapi_helper():
    """英伟达通道全靠 tools/nvddc32.exe; 打包漏了它 = 到真机上只剩 USB 小板一条路。"""
    for spec in ("DDCCI-Nanwei.spec", "Nanwei-Console.spec", "Nanwei-Win7.spec"):
        assert "tools/nvddc32.exe" in _read(spec), spec


def test_nanwei_app_releases_backend_and_hard_exits_on_close():
    """关窗必须关后端 + 硬退进程。

    2026-07-30 回归: 原来 webview.start() 返回后什么都不做 —— 常驻的 nvddc32.exe
    留着, QtWebEngine 的渲染器进程和 Qt 清理线程又把主进程吊住, 用户任务管理器里
    攒下一堆 DDCCI-Nanwei-Win7.exe。
    """
    app = _read("app_nanwei.py")
    assert "def shutdown(self)" in app
    assert "api.shutdown()" in app
    assert "os._exit(0)" in app
    # shutdown 必须在 finally 里, 不能只在正常返回路径上
    tail = app[app.index("webview.start("):]
    assert "finally:" in tail[:tail.index("api.shutdown()")]


def test_nanwei_app_does_not_default_to_qt_backend():
    app = _read("app_nanwei.py")
    assert 'os.environ.get("DDCCI_GUI") or None' in app
    assert 'os.environ.get("DDCCI_WEBVIEW_GUI", "qt")' not in app
