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


def _css():
    return (ROOT / "ui" / "nanwei" / "style.css").read_text(encoding="utf-8")


def test_every_color_mix_has_a_win7_fallback_in_front():
    """Win7 版走 QtWebEngine(Chromium 83), 不认 color-mix(), 整条声明会被丢弃。

    约定: 每条含 color-mix 的声明前面必须紧挨一条同属性的 fallback 声明 (用 :root 里
    预计算好的变量)。新写样式时忘了垫 fallback = Win7 上那处颜色直接没有, 这里拦住。
    """
    import re
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)          # 注释里提到 color-mix 不算
    # 按 ; 切成声明 (多行简写也能整条拿到), 每条取属性名
    decls = [d.strip() for d in css.replace("{", ";").replace("}", ";").split(";")]
    decls = [" ".join(d.split()) for d in decls if ":" in d]
    missing = []
    for i, decl in enumerate(decls):
        if "color-mix" not in decl or decl.startswith("--"):
            continue
        prop = decl.split(":", 1)[0].strip()
        prev = decls[i - 1] if i else ""
        if not prev.startswith(prop + ":") or "color-mix" in prev:
            missing.append(decl)
    assert not missing, "这些 color-mix 声明缺 Win7 fallback: %r" % missing


def test_flex_gap_containers_are_patched_for_win7():
    """Chromium 83 不支持 flex 容器的 gap (grid 的不受影响)。

    样式表末尾的补丁把这些容器 gap 归 0 + 改 margin 复刻; 少一个 = Win7 上那处挤成一团。
    """
    css = _css()
    flex_gap_containers = [".brand", ".title-actions", ".target-option",
                           ".chip-row", ".seg", ".macro-btn", ".raw-key-row"]
    patch = css[css.index("flex-gap 兼容补丁"):]
    for sel in flex_gap_containers:
        assert sel in patch, "%s 没进 Win7 flex-gap 补丁" % sel


def test_nanwei_ui_hides_image_color_and_log_under_more_settings():
    html = _html()
    assert 'class="more-drawer"' in html
    assert 'class="panel accordion primary"' in html
    assert 'class="panel accordion settings"' in html
    assert 'class="log-drawer"' in html
