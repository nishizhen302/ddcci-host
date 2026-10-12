# -*- coding: utf-8 -*-
"""窗口圆角: Win11 走 DWM 原生圆角, Win7/10 没有这个属性 -> 自己用 SetWindowRgn 裁 (2026-10-12 用户:
别人电脑上四边直角)。"""
import sys
from types import SimpleNamespace

import winchrome


def _build(monkeypatch, build):
    monkeypatch.delenv("DDCCI_ROUND_RGN", raising=False)
    monkeypatch.setattr(sys, "getwindowsversion", lambda: SimpleNamespace(build=build), raising=False)
    return winchrome._use_region_corners()


def test_win7_and_win10_clip_region_win11_uses_dwm(monkeypatch):
    assert _build(monkeypatch, 7601) is True        # Win7 SP1
    assert _build(monkeypatch, 19045) is True       # Win10 22H2
    assert _build(monkeypatch, 22000) is False      # Win11 首版起有 DWM 圆角
    assert _build(monkeypatch, 26200) is False


def test_env_override_for_local_verification(monkeypatch):
    monkeypatch.setattr(sys, "getwindowsversion", lambda: SimpleNamespace(build=26200), raising=False)
    monkeypatch.setenv("DDCCI_ROUND_RGN", "1")
    assert winchrome._use_region_corners() is True
    monkeypatch.setenv("DDCCI_ROUND_RGN", "0")
    assert winchrome._use_region_corners() is False
