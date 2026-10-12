# -*- coding: utf-8 -*-
"""南微控制台 UI 结构契约 (2026-10-12 v4 界面)。

这些测试不跑浏览器, 只保护正式 HTML 的关键信息架构 (布局由用户逐项定过):
- 左栏 = 显示器 + 型号/连接方式; 右栏自上而下 = OSD 按键 → 宏/长按 → 色温/Gamma → 亮度/对比度
- 发送键值 / 通信记录 / 版本号是左下角不显眼的小字
- 目标选择是控制路径选择, 地址和机型只作为探测结果展示
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _html():
    return (ROOT / "ui" / "nanwei" / "index.html").read_text(encoding="utf-8")


def _js():
    return (ROOT / "ui" / "nanwei" / "app.js").read_text(encoding="utf-8")


def _css():
    return (ROOT / "ui" / "nanwei" / "style.css").read_text(encoding="utf-8")


def _right(html):
    return html[html.index('class="col right"'):]


def test_target_picker_shows_path_and_detected_address():
    html = _html()
    assert 'id="dev-name"' in html and 'id="dev-sub"' in html and 'id="dev-menu"' in html
    # 选显示器点名称本身; 名称下面那行只是状态 (2026-10-12 用户要求)
    pick = html[html.index('id="dev-pick"'):]
    assert pick.index('id="dev-name"') < pick.index('</button>')
    sub = html[html.index('id="dev-sub"') - 40:html.index('id="dev-sub"')]
    assert "<p" in sub
    assert 'id="addr-seg"' not in html          # 地址自动探测, 不给手选
    js = _js()
    assert "t.address" in js                    # 探测到的地址显示在连接方式里


def test_right_column_order_matches_user_layout():
    """用户 2026-10-12 截图定的顺序: OSD 键 → 工厂/老化 (或长按) → 色温/Gamma → 亮度/对比度。"""
    r = _right(_html())
    order = ['class="module remote"', 'id="act-factory"', 'id="hold-tile"',
             'id="t-colortemp"', 'id="t-gamma"', 'id="s-brightness"', 'id="s-contrast"']
    pos = [r.index(x) for x in order]
    assert pos == sorted(pos), "右栏顺序被改乱了: %r" % order


def test_osd_keys_are_the_four_panel_keys_in_panel_order():
    r = _right(_html())
    keys = re.findall(r'class="key" data-key="(\w+)"', r)
    assert keys == ["menu", "left", "right", "exit"]


def test_macro_buttons_and_raw_key_kept():
    """工厂菜单/老化两个宏 + 发送键值入口必须在 (曾整批丢失过)。"""
    html = _html()
    assert 'id="act-factory"' in html and 'id="act-aging"' in html
    assert 'id="act-raw"' in html
    js = _js()
    assert "enter_factory" in js and "start_aging" in js and "press_key_raw" in js


def test_raw_key_log_and_version_are_low_key_in_left_column():
    """发送键值 / 通信记录 / 版本号放左下角小字, 不占右栏。"""
    html = _html()
    left = html[html.index('class="col left"'):html.index('class="col right"')]
    util = left[left.index('class="util"'):]
    for el in ('id="act-raw"', 'id="act-log"', 'id="ver-label"'):
        assert el in util, el + " 不在左下角"


def test_version_label_is_visible_and_clickable():
    """版本号是判断"现场那台机器跑的是哪一版"的唯一手段, 别被布局重构顺手删掉。"""
    html = _html()
    tag = html[html.index('id="ver-label"') - 80:]
    tag = tag[tag.index("<button"):]
    tag = tag[:tag.index(">")]
    assert "pywebview-no-drag" in tag
    js = _js()
    assert "app_version" in js and "check_update" in js and "open_repo" in js


def test_no_manual_model_selector():
    """机型按应答自动识别, 选目标即切界面; 不要启动选择页, 也不要单独的机型下拉框 (2026-10-12 用户要求)。"""
    html = _html()
    assert 'model-screen' not in html and 'id="model-select"' not in html
    assert 'id="model-chip"' not in html        # 识别结果也不单独显示 (用户嫌小标签丑, 2026-10-12)
    assert "r.meta" in _js()                    # 连上目标后按它的机型切界面


def test_model_specific_rows_are_tagged():
    """156pin 才有工厂/老化宏, 216pin 才有长按; 前端按 data-model 显隐。"""
    html = _html()
    macro = html[html.index('macro-row'):]
    assert 'data-model="156"' in macro[:60]
    assert macro.index('id="act-factory"') < macro.index('</div>')
    hold = html[html.index('hold-row'):]
    assert 'data-model="216"' in hold[:60]
    for el in ('id="hold-send"', 'id="hold-key"', 'id="hold-sec"'):
        assert el in hold
    assert "hold_key" in _js()


def test_choices_go_through_get_set_choice():
    """色温/Gamma 两种机型读回规则不同, 必须走后端换算过的 get_choice / set_choice。"""
    js = _js()
    assert "get_choice(" in js and "set_choice(" in js
    assert "set_param(META.ops.colortemp" not in js and "set_param(META.ops.gamma" not in js


def test_css_is_chromium83_safe():
    """Win7 版走 QtWebEngine (Chromium 83): 不认 color-mix()、flex 容器的 gap、inset 简写、aspect-ratio。

    grid 的 gap 不受影响, 用 grid-gap 写。新写样式时用了这些 = Win7 上那处直接失效, 这里拦住。
    """
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    assert "color-mix" not in css
    assert "aspect-ratio" not in css
    assert not re.search(r"(^|[;{\s])gap\s*:", css), "用了 gap:, 改成 grid-gap 或 margin"
    assert not re.search(r"(^|[;{\s])inset\s*:", css), "用了 inset 简写, 改成 left/top/right/bottom"


def test_standard_monitor_hides_keys_and_choices():
    """标准显示器 (系统 DDC/CI) 只有亮度/对比度: OSD 按键与色温/Gamma 方块按 features 显隐。"""
    html = _html()
    remote = html[html.index('class="module remote"') - 30:html.index('class="module remote"') + 60]
    assert 'data-feature="keys"' in remote
    tiles = html[:html.index('id="t-colortemp"')]
    assert tiles.rstrip().rsplit("<div", 1)[1].count('data-feature="choices"') == 1
    js = _js()
    assert '[data-feature]' in js
    assert 'hasFeature("choices")' in js and 'hasFeature("keys")' in js
    assert 'dxva2: "系统 DDC/CI"' in js


def test_qt_waits_for_webchannel_before_first_call():
    """Win7 (Qt) 版: 通道没建好就调接口会永远挂起 -> 就绪判断必须看 _QWebChannel。"""
    js = _js()
    ready = js[js.index("const bridgeReady"):js.index("const bridge =")]
    assert "qtwebengine" in ready and "_QWebChannel" in ready
    boot = js[js.index("requestAnimationFrame(() => setTimeout"):]
    assert "!window.pywebview" in boot        # 演示数据只给浏览器直接打开用
