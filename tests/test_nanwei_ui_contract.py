# -*- coding: utf-8 -*-
"""南微控制台 UI 结构契约。

这些测试不跑浏览器, 只保护正式 HTML 的关键信息架构:
- OSD 常驻在主界面
- 图像 / 色彩 / 日志藏进更多设置
- 目标选择是控制路径选择, 地址只作为探测结果展示
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _html():
    return (ROOT / "ui" / "nanwei" / "index.html").read_text(encoding="utf-8")


def test_nanwei_ui_has_target_picker_and_auto_address_result():
    html = _html()
    assert 'class="target-picker"' in html
    assert 'id="target-name"' in html
    assert 'id="addr-chip"' in html
    assert 'id="addr-seg"' not in html


def test_nanwei_ui_keeps_osd_before_secondary_drawer():
    html = _html()
    assert html.index('class="panel remote"') < html.index('class="more-drawer"')


def test_nanwei_ui_keeps_macro_buttons_next_to_osd_keys():
    """工厂菜单/老化两个宏按钮 + 自定义键值行必须留在 OSD 面板里 (曾整批丢失过)。"""
    html = _html()
    assert 'id="factory-btn"' in html and 'id="aging-btn"' in html
    assert 'id="raw-key-send"' in html
    assert html.index('class="key-grid"') < html.index('class="macro-row"')
    assert html.index('class="macro-row"') < html.index('class="more-drawer"')


def test_nanwei_ui_hides_image_color_and_log_under_more_settings():
    html = _html()
    assert 'class="more-drawer"' in html
    assert 'class="panel accordion primary"' in html
    assert 'class="panel accordion settings"' in html
    assert 'class="log-drawer"' in html
