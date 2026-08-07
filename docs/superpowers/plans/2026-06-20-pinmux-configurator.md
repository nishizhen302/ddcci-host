# 管脚配置器（Pinmux Configurator）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给硬件工程师一个在线管脚配置器——选脚→切复用(GPIO/I²C/外设)→GPIO 设方向/置1置0/读电平→还原本板默认，工具把"管脚+功能"翻译成底层寄存器读写。

**Architecture:** 在 `C:\code\ddcci-host` 内新增独立"管脚"页，与 phytune 平级。固件零改动，全部复用现有 DDC/CI peek/poke（VCP 0xE5/0xE6）+ `RegAccess` + JS 串行锁 + 窗口外壳。数据来自 generator 解析固件 PINSHARE/McuCommon 头 → `phytune/rl6410_pins.json`，模型层 `phytune/pins.py` 做位域读改写，`app.py` 暴露桥接方法，`ui/pinmux/` 渲染。

**Tech Stack:** Python 3.8（`.venv38`）、pytest、pywebview（WebView2，仅 Win11，不做 Win7）、纯 ctypes 后端、原生 JS/HTML/CSS（无框架）。

**参考：** spec = `docs/superpowers/specs/2026-06-20-pinmux-configurator-design.md`。现有同构实现可照搬：`phytune/params.py`（位域 Param 模型）、`phytune/regaccess.py`（peek/poke）、`app.py` 的 `phytune_*` 桥接方法与 `main()` 入口分支、`ui/phytune/app.js` 的 DDC 串行锁。

**测试运行约定：** 所有 pytest 用 venv38 解释器：
```
./.venv38/Scripts/python.exe -m pytest <路径> -v
```

**固件头文件路径（generator 输入，codex 现役 RL6410 树）：**
- 根：`C:\Users\61093\Desktop\monitor firmware - codex\New STD Code II 1P SVN2860`
- EXAMPLE（全功能选项）：`Pcb\RL6410\BGA_1024\RL6410_PCB_EXAMPLE_PINSHARE.h`
- DEMO_D（本板默认值）：`Pcb\RL6410\BGA_1024\RL6410_DEMO_D_1A4MHL1DP1mDP_DPTX_LVDS_VB1_PINSHARE.h`
- McuCommon（GPIO 数据寄存器）：`Kernel\Scaler\RL6410_Series_Scaler\Header\RL6410_Series_McuCommonInclude.h`

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `phytune/pins.py` | **创建**。`Pin`（位域读改写：复用/GPIO 电平/还原默认）+ `PinDB`（分组/搜索/按球名取）+ `load_pins()`。 |
| `tools/gen_pins.py` | **创建**。解析 PINSHARE×2 + McuCommon → 输出 `rl6410_pins.json`。纯文本解析 + 分类，可单测。 |
| `phytune/rl6410_pins.json` | **创建**（由 gen_pins.py 生成）。管脚静态表。 |
| `app.py` | **修改**。加 6 个 `pin_*` 桥接方法 + `main()` 加 `DDCCI_PINMUX` 入口分支。 |
| `ui/pinmux/index.html` | **创建**。A 浅色界面骨架（顶栏+左分组列表+右详情）。 |
| `ui/pinmux/style.css` | **创建**。A 浅色现代主题。 |
| `ui/pinmux/app.js` | **创建**。渲染分组列表/详情、切复用、GPIO 开关、危险二次确认，全走 DDC 串行锁。 |
| `管脚配置.bat` | **创建**。`pyw` 无黑窗启动（设 `DDCCI_PINMUX=1`）。 |
| `tests/test_pins.py` | **创建**。Pin/PinDB 单测（FakeBackend）。 |
| `tests/test_gen_pins.py` | **创建**。generator 解析单测（片段→断言）。 |

---

## Task 1: 管脚模型 `phytune/pins.py`

核心逻辑层，不接硬件，用 FakeBackend + RegAccess 测。先于 generator 实现（测试自带内联 pin dict，不依赖 JSON）。

**Files:**
- Create: `phytune/pins.py`
- Test: `tests/test_pins.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_pins.py`：

```python
# -*- coding: utf-8 -*-
"""Pin / PinDB 单测: 位域读改写、复用校验、GPIO 电平、还原默认、分组搜索。"""
import pytest
from backends.base import Monitor
from tests.fakes import FakeBackend
from phytune.regaccess import RegAccess
from phytune import vcp_codes as vc
from phytune import pins as P


def _pin_y6():
    # Y6: pinshare P10_00[2:0]; 默认 0(输入); funcs 0=输入/2=开漏输出/3=AUX_P1;
    # GPIO 数据寄存器 0xFE00 bit0
    return P.Pin({
        "ball": "Y6",
        "share": {"page": 0x10, "offset": 0x00, "mask": 0x07, "shift": 0},
        "default": 0,
        "domain": "AUX_DP",
        "funcs": [
            {"val": 0, "name": "P1D0i", "kind": "gpio_in"},
            {"val": 1, "name": "reserved", "kind": "reserved"},
            {"val": 2, "name": "P1D0o", "kind": "gpio_out_od"},
            {"val": 3, "name": "AUX_P1", "kind": "periph"},
        ],
        "gpio": {"name": "P1D0", "data_page": 0xFE, "data_offset": 0x00, "bit": 0},
        "danger": False, "danger_reason": "",
    })


def _ra(get_returns=None):
    be = FakeBackend(get_returns=get_returns or {})
    return be, RegAccess(be, 0)


def test_read_mux_extracts_bitfield():
    # pinshare 当前 = 0xF3 → 低3位 = 3 = AUX_P1
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0xF3, 0xFF)})
    r = _pin_y6().read_mux(ra)
    assert r == {"val": 3, "name": "AUX_P1", "kind": "periph"}


def test_set_mux_read_modify_write_preserves_other_bits():
    # 当前 0xF3, 设复用=2 → 应写 0xF2 (高5位不动, 低3位=2)
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0xF3, 0xFF)})
    assert _pin_y6().set_mux(ra, 2) is True
    pokes = [s for s in be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0xF2, 0))


def test_set_mux_rejects_reserved_and_unknown():
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0x00, 0xFF)})
    pin = _pin_y6()
    with pytest.raises(ValueError):
        pin.set_mux(ra, 1)   # reserved
    with pytest.raises(ValueError):
        pin.set_mux(ra, 7)   # 不在 funcs


def test_gpio_set_requires_gpio_output_mode():
    # 复用当前=0(输入) → 置电平应被拒
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0x00, 0xFF)})
    with pytest.raises(ValueError):
        _pin_y6().gpio_set(ra, 1)


def test_gpio_set_writes_bit_when_output():
    # 复用=2(开漏输出), 数据寄存器当前 0x00 → 置1 应写 0x01 到 0xFE00
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x02, 0xFF)})
    ra = RegAccess(be, 0)
    assert _pin_y6().gpio_set(ra, 1) is True
    pokes = [s for s in be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0x01, 0))


def test_gpio_set_rejected_when_no_mapping():
    p = _pin_y6()
    p.gpio = None
    be, ra = _ra()
    with pytest.raises(ValueError):
        p.gpio_set(ra, 1)


def test_reset_default_writes_default_value():
    # 默认 0, 当前 0xF3 → 写回 0xF0
    be, ra = _ra({(0, vc.VCP_ADDR_LATCH): (0xF3, 0xFF)})
    assert _pin_y6().reset_default(ra) is True
    pokes = [s for s in be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0xF0, 0))


def test_pindb_group_and_search():
    db = P.PinDB([_pin_y6()], domain_order=["GPIO", "AUX_DP"])
    groups = db.by_domain()
    assert groups == [("AUX_DP", [db.by_ball("Y6")])]
    assert db.search("aux")[0].ball == "Y6"   # 按功能名命中
    assert db.search("y6")[0].ball == "Y6"     # 按球名命中
    assert db.search("zzz") == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `./.venv38/Scripts/python.exe -m pytest tests/test_pins.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'phytune.pins'`）

- [ ] **Step 3: 实现 `phytune/pins.py`**

```python
# -*- coding: utf-8 -*-
"""管脚模型: 把"管脚+功能"翻译成 pinshare/GPIO 寄存器的位域读改写, 跑在 RegAccess 上。

每个 Pin 把一个 BGA 球映射到:
  - pinshare 寄存器 (Page10 某 offset, 低若干 bit) = 复用功能选择
  - (可选) GPIO 数据寄存器 (0xFExx 某 bit) = 输出电平/读回
复用值语义: 0=输入<I> 1=推挽输出<PP> 2=开漏输出<OD>, 其余=外设。
"""
import json
import os

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rl6410_pins.json")

GPIO_IN = "gpio_in"
GPIO_OUT_PP = "gpio_out_pp"
GPIO_OUT_OD = "gpio_out_od"
GPIO_OUT_KINDS = (GPIO_OUT_PP, GPIO_OUT_OD)
RESERVED = "reserved"


class Pin(object):
    """一个 BGA 球的可配置项。"""

    __slots__ = ("ball", "share", "default", "domain", "funcs", "gpio",
                 "danger", "danger_reason", "_kind_by_val")

    def __init__(self, d):
        self.ball = d["ball"]
        self.share = d["share"]                 # {page, offset, mask, shift}
        self.default = int(d["default"])
        self.domain = d.get("domain", "OTHER")
        self.funcs = d.get("funcs", [])         # [{val, name, kind}]
        self.gpio = d.get("gpio")               # {name, data_page, data_offset, bit} | None
        self.danger = bool(d.get("danger", False))
        self.danger_reason = d.get("danger_reason", "")
        self._kind_by_val = {int(f["val"]): f.get("kind") for f in self.funcs}

    def _mask(self):
        return int(self.share["mask"])

    def _shift(self):
        return int(self.share["shift"])

    def _name_of(self, val):
        for f in self.funcs:
            if int(f["val"]) == val:
                return f["name"]
        return None

    def read_mux(self, ra):
        """读 pinshare 字节取位域 -> {val, name, kind}; peek 失败返回 None。"""
        cur = ra.peek(int(self.share["page"]), int(self.share["offset"]))
        if cur is None:
            return None
        val = (cur & self._mask()) >> self._shift()
        return {"val": val, "name": self._name_of(val), "kind": self._kind_by_val.get(val)}

    def set_mux(self, ra, val):
        """切复用: 校验 val 合法(在 funcs 且非 reserved) -> 读改写位域。
        非法值抛 ValueError; peek 失败返回 False; 否则返回 poke 结果。"""
        val = int(val)
        if val not in self._kind_by_val or self._kind_by_val[val] == RESERVED:
            raise ValueError("%s 不支持复用值 %d" % (self.ball, val))
        page, off = int(self.share["page"]), int(self.share["offset"])
        cur = ra.peek(page, off)
        if cur is None:
            return False
        newb = (cur & ~self._mask()) | ((val << self._shift()) & self._mask())
        return ra.poke(page, off, newb)

    def gpio_read(self, ra):
        """读 GPIO 电平(0/1); 无映射或 peek 失败返回 None。"""
        if not self.gpio:
            return None
        cur = ra.peek(int(self.gpio["data_page"]), int(self.gpio["data_offset"]))
        if cur is None:
            return None
        return (cur >> int(self.gpio["bit"])) & 1

    def gpio_set(self, ra, level):
        """置 GPIO 电平。无映射或当前非 GPIO 输出抛 ValueError;
        读现态失败返回 False; 否则返回 poke 结果。"""
        if not self.gpio:
            raise ValueError("%s 无 GPIO 数据寄存器映射" % self.ball)
        mux = self.read_mux(ra)
        if mux is None:
            return False
        if mux["kind"] not in GPIO_OUT_KINDS:
            raise ValueError("%s 当前非 GPIO 输出, 不能置电平" % self.ball)
        page = int(self.gpio["data_page"])
        off = int(self.gpio["data_offset"])
        bit = int(self.gpio["bit"])
        cur = ra.peek(page, off)
        if cur is None:
            return False
        newb = (cur | (1 << bit)) if int(level) else (cur & ~(1 << bit))
        return ra.poke(page, off, newb)

    def reset_default(self, ra):
        """还原本板默认复用值。"""
        return self.set_mux(ra, self.default)

    def to_dict(self):
        return {"ball": self.ball, "share": self.share, "default": self.default,
                "domain": self.domain, "funcs": self.funcs, "gpio": self.gpio,
                "danger": self.danger, "danger_reason": self.danger_reason}


class PinDB(object):
    """全脚集合 + 分组/搜索。"""

    def __init__(self, pins, domain_order=None):
        self.pins = pins
        self.domain_order = domain_order or []
        self._by_ball = {p.ball: p for p in pins}

    def by_ball(self, ball):
        return self._by_ball[ball]

    def by_domain(self):
        """返回 [(domain, [pin,...]), ...]; 按 domain_order, 其余域附后(字母序)。"""
        groups = {}
        for p in self.pins:
            groups.setdefault(p.domain, []).append(p)
        ordered = [d for d in self.domain_order if d in groups]
        ordered += [d for d in sorted(groups) if d not in self.domain_order]
        return [(d, groups[d]) for d in ordered]

    def search(self, text):
        """按球名或任一功能名子串匹配(大小写不敏感)。"""
        t = text.lower()
        out = []
        for p in self.pins:
            if t in p.ball.lower() or any(t in f.get("name", "").lower() for f in p.funcs):
                out.append(p)
        return out


def load_pins(path=None):
    """从 JSON 载入: {"domain_order": [...], "pins": [...]}。"""
    with open(path or _DEFAULT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    pins = [Pin(d) for d in data.get("pins", [])]
    return PinDB(pins, data.get("domain_order", []))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `./.venv38/Scripts/python.exe -m pytest tests/test_pins.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add phytune/pins.py tests/test_pins.py
git commit -m "feat(pinmux): 管脚模型 Pin/PinDB(位域读改写+GPIO电平+分组搜索)"
```

---

## Task 2: 数据 generator `tools/gen_pins.py`

解析固件三份头文件 → 产出 `rl6410_pins.json`。纯文本解析 + 分类，全可单测。

**已核实的固件事实（写进解析逻辑）：**
- PINSHARE 每脚一块：`#define _PIN_<ball>  (<默认> & 0x<掩码>) // Page 10-0x<off>[hi:lo]`，紧随其后 `//` 注释行列出 `val: 功能名<类型>`（可跨行）。
- GPIO 数据寄存器：`McuCommonInclude.h` 的 `extern volatile BYTE xdata MCU_FExx_PORT<y><z>_PIN_REG;`，`PORT<y><z>` = MCU 端口 y、bit z，**每脚一个独立寄存器**（PORT40=0xFE00、PORT41=0xFE01…，端口 4~F）。
- 功能名里的 GPIO 名形如 `P<n>D<b>`（如 `P4D0i`/`P4D0o`）→ 对应 `PORT<n><b>` → 0xFExx。**端口 1/3 是数据/AUX 口，McuCommon 无对应寄存器 → `gpio=null`**（电平控件置灰，复用切换不受影响）。
- 电平在该独立寄存器内的 bit：先按 RTD 惯例假定 **bit 0**（常量 `GPIO_LEVEL_BIT`），Task 3 实机核实后定稿。

**Files:**
- Create: `tools/gen_pins.py`
- Test: `tests/test_gen_pins.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_gen_pins.py`：

```python
# -*- coding: utf-8 -*-
"""gen_pins 解析单测: 片段 -> 断言产出结构。"""
from tools import gen_pins as G

_EXAMPLE = """
#define _PIN_TESTA                 (1 & 0x07) // Page 10-0x20[2:0]
// 0 ~ 2 (0: P4D0i<I>, 1: P4D0o<PP>, 2: P4D0o<OD>)

#define _PIN_TESTB                 (0 & 0x07) // Page 10-0x21[2:0]
// 0 ~ 8 (0: P4D1i<I>, 2: P4D1o<OD>, 8: IICSCL2)

#define _PIN_TESTC                 (0 & 0x07) // Page 10-0x22[2:0]
// 0 ~ 1 (0: P5D0i<I>, 1: VCCK_OFF_EN)

#define _PIN_TESTD                 (0 & 0x07) // Page 10-0x23[2:0]
// 0 ~ 4 (0: P1D0i<I>, 1: reserved, 2: P1D0o<OD>, 3: AUX_P1,
//        4: AUX_N1)
"""

_DEMOD = """
#define _PIN_TESTA                 (2 & 0x07) // Page 10-0x20[2:0]
// 0 ~ 2 (0: P4D0i<I>, 1: P4D0o<PP>, 2: P4D0o<OD>)
"""

_MCU = """
extern volatile BYTE xdata MCU_FE00_PORT40_PIN_REG;
extern volatile BYTE xdata MCU_FE01_PORT41_PIN_REG;
"""


def test_parse_pinshare_fields():
    d = G.parse_pinshare(_EXAMPLE)
    a = d["TESTA"]
    assert a["default"] == 1
    assert a["share"] == {"page": 0x10, "offset": 0x20, "mask": 0x07, "shift": 0}
    assert a["funcs"][0] == {"val": 0, "name": "P4D0i", "kind": "gpio_in"}
    assert a["funcs"][1]["kind"] == "gpio_out_pp"
    assert a["funcs"][2]["kind"] == "gpio_out_od"


def test_parse_pinshare_multiline_comment():
    d = G.parse_pinshare(_EXAMPLE)
    names = [f["name"] for f in d["TESTD"]["funcs"]]
    assert "AUX_N1" in names          # 第二行注释也解析到
    kinds = {f["val"]: f["kind"] for f in d["TESTD"]["funcs"]}
    assert kinds[1] == "reserved"
    assert kinds[3] == "periph"


def test_parse_mcu_map():
    m = G.parse_mcu(_MCU)
    assert m == {"PORT40": 0xFE00, "PORT41": 0xFE01}


def test_gpio_for_maps_port_pin():
    funcs = G.parse_pinshare(_EXAMPLE)["TESTA"]["funcs"]
    g = G.gpio_for(funcs, {"PORT40": 0xFE00})
    assert g == {"name": "P4D0", "data_page": 0xFE, "data_offset": 0x00,
                 "bit": G.GPIO_LEVEL_BIT}


def test_gpio_for_returns_none_when_unmapped():
    funcs = G.parse_pinshare(_EXAMPLE)["TESTD"]["funcs"]   # P1Dx, McuCommon 无 PORT10
    assert G.gpio_for(funcs, {"PORT40": 0xFE00}) is None


def test_classify_domain():
    d = G.parse_pinshare(_EXAMPLE)
    assert G.classify_domain(d["TESTB"]["funcs"]) == "I2C_DDC"   # 含 IIC
    assert G.classify_domain(d["TESTC"]["funcs"]) == "POWER_CTRL"  # 含 VCCK
    assert G.classify_domain(d["TESTA"]["funcs"]) == "GPIO"       # 纯 GPIO


def test_classify_danger():
    d = G.parse_pinshare(_EXAMPLE)
    dng, reason = G.classify_danger("TESTC", d["TESTC"]["funcs"])  # VCCK
    assert dng is True and reason
    assert G.classify_danger("TESTA", d["TESTA"]["funcs"]) == (False, "")


def test_build_merges_default_from_demod():
    out = G.build(_EXAMPLE, _DEMOD, _MCU)
    assert out["domain_order"][0] == "GPIO"
    pins = {p["ball"]: p for p in out["pins"]}
    assert pins["TESTA"]["default"] == 2          # 取 DEMO_D 的默认值(2), 非 EXAMPLE(1)
    assert pins["TESTA"]["gpio"]["data_offset"] == 0x00
    assert pins["TESTC"]["danger"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `./.venv38/Scripts/python.exe -m pytest tests/test_gen_pins.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'tools.gen_pins'`）。先建空包：`tools/__init__.py`（空文件）。

- [ ] **Step 3: 实现 `tools/gen_pins.py`**

```python
# -*- coding: utf-8 -*-
"""管脚表 generator: 解析固件 PINSHARE×2 + McuCommon -> phytune/rl6410_pins.json。

换板/换 PCB 只需改输入路径重跑。纯文本解析, 不依赖固件能编译。
"""
import argparse
import json
import os
import re

# 电平在每脚独立 PIN_REG 内的 bit (RTD 惯例 bit0; Task 3 实机核实)
GPIO_LEVEL_BIT = 0

DOMAIN_ORDER = ["GPIO", "I2C_DDC", "AUX_DP", "LVDS_DISP", "PWM_BL",
                "FLASH_SPI", "POWER_CTRL", "TEST_DBG", "OTHER"]

# 域分类: 按序首个命中者胜 (names = 大写功能名串)
DOMAIN_RULES = [
    ("I2C_DDC", ("IIC", "DDC", "SCL", "SDA")),
    ("AUX_DP", ("AUX", "HPD", "HOTPLUG", "MHL")),
    ("PWM_BL", ("PWM", "BACKLIGHT", "DIMMING")),
    ("FLASH_SPI", ("FLASH", "SPI", "SF_")),
    ("POWER_CTRL", ("VCCK", "VCC", "POWER", "_EN", "RESET")),
    ("LVDS_DISP", ("LVDS", "PANEL", "TCON", "VSYNC", "HSYNC")),
    ("TEST_DBG", ("TEST", "UART", "DEBUG", "TDO", "TDI", "TCK")),
]

# 危险脚: 命中即标 danger (从严, 宁可多标); 可被 DANGER_OVERRIDE 强制
DANGER_RULES = [
    ("LVDS/显示", ("LVDS", "PANEL", "TCON")),
    ("电源/使能", ("VCCK", "VCC", "POWER", "_EN", "RESET")),
    ("Flash", ("FLASH", "SF_")),
    ("DDC 控制口", ("DDC",)),
]
DANGER_OVERRIDE = {}   # {ball: reason} 实机发现的额外危险脚手填

_PIN_RE = re.compile(
    r"#define\s+_PIN_(\w+)\s+\(\s*(\d+)\s*&\s*0x([0-9A-Fa-f]+)\s*\)"
    r"\s*//\s*Page\s*([0-9A-Fa-f]+)\s*-\s*0x([0-9A-Fa-f]+)\s*\[(\d+)(?::(\d+))?\]")
_FUNC_RE = re.compile(r"(\d+)\s*:\s*([^,()]+)")
_MCU_RE = re.compile(r"MCU_(FE[0-9A-Fa-f]{2})_PORT([0-9])([0-9])_PIN_REG")
_GPIO_NAME_RE = re.compile(r"^(P[0-9A-Fa-f]D[0-9])[io]?$", re.I)
_TAG_RE = re.compile(r"<([^>]+)>")


def _kind_and_name(raw):
    """功能名原文 -> (kind, 清理后的名)。"""
    raw = raw.strip()
    if raw.lower() == "reserved":
        return "reserved", "reserved"
    m = _TAG_RE.search(raw)
    tag = m.group(1).upper() if m else ""
    name = _TAG_RE.sub("", raw).strip()
    if tag == "I":
        return "gpio_in", name
    if tag == "PP":
        return "gpio_out_pp", name
    if tag == "OD":
        return "gpio_out_od", name
    up = name.upper()
    if any(k in up for k in ("IIC", "DDC", "SCL", "SDA")):
        return "i2c", name
    return "periph", name


def parse_pinshare(text):
    """-> {ball: {default, share{page,offset,mask,shift}, funcs[{val,name,kind}]}}。"""
    lines = text.splitlines()
    out = {}
    i = 0
    while i < len(lines):
        m = _PIN_RE.search(lines[i])
        if not m:
            i += 1
            continue
        ball, dflt, _maskhex, pg, off, hi, lo = m.groups()
        shift = int(lo) if lo is not None else int(hi)
        width = int(hi) - shift + 1
        mask = ((1 << width) - 1) << shift
        # 收集紧随的注释行 (可跨行)
        j = i + 1
        comment = []
        while j < len(lines) and lines[j].lstrip().startswith("//"):
            comment.append(lines[j].lstrip()[2:])
            j += 1
        funcs = []
        for fm in _FUNC_RE.finditer(" ".join(comment)):
            kind, name = _kind_and_name(fm.group(2))
            funcs.append({"val": int(fm.group(1)), "name": name, "kind": kind})
        out[ball] = {
            "default": int(dflt),
            "share": {"page": int(pg, 16), "offset": int(off, 16),
                      "mask": mask, "shift": shift},
            "funcs": funcs,
        }
        i = j
    return out


def parse_mcu(text):
    """-> {"PORT<y><z>": 0xFExx}。"""
    out = {}
    for m in _MCU_RE.finditer(text):
        out["PORT" + m.group(2) + m.group(3)] = int(m.group(1), 16)
    return out


def gpio_for(funcs, mcu_map):
    """从功能名里找 P<n>D<b> -> PORT<n><b> -> 数据寄存器映射; 找不到返回 None。"""
    for f in funcs:
        m = _GPIO_NAME_RE.match(f["name"])
        if not m:
            continue
        base = m.group(1).upper()              # 如 "P4D0"
        key = "PORT" + base[1] + base[3]       # "PORT40"
        if key in mcu_map:
            addr = mcu_map[key]
            return {"name": base, "data_page": (addr >> 8) & 0xFF,
                    "data_offset": addr & 0xFF, "bit": GPIO_LEVEL_BIT}
    return None


def classify_domain(funcs):
    names = " ".join(f["name"].upper() for f in funcs)
    for dom, kws in DOMAIN_RULES:
        if any(k in names for k in kws):
            return dom
    if any(f["kind"].startswith("gpio") for f in funcs):
        return "GPIO"
    return "OTHER"


def classify_danger(ball, funcs):
    if ball in DANGER_OVERRIDE:
        return True, DANGER_OVERRIDE[ball]
    names = " ".join(f["name"].upper() for f in funcs)
    for reason, kws in DANGER_RULES:
        if any(k in names for k in kws):
            return True, reason + " 相关, 改动可能黑屏/断链路"
    return False, ""


def build(example_text, demod_text, mcu_text):
    ex = parse_pinshare(example_text)
    dm = parse_pinshare(demod_text)
    mcu = parse_mcu(mcu_text)
    pins = []
    for ball in sorted(ex):
        e = ex[ball]
        funcs = e["funcs"]
        default = dm[ball]["default"] if ball in dm else e["default"]
        danger, reason = classify_danger(ball, funcs)
        pins.append({
            "ball": ball, "share": e["share"], "default": default,
            "domain": classify_domain(funcs), "funcs": funcs,
            "gpio": gpio_for(funcs, mcu),
            "danger": danger, "danger_reason": reason,
        })
    return {"domain_order": DOMAIN_ORDER, "pins": pins}


# 固件头默认路径 (codex 现役 RL6410 树)
_FW = r"C:\Users\61093\Desktop\monitor firmware - codex\New STD Code II 1P SVN2860"
_DEF_EXAMPLE = _FW + r"\Pcb\RL6410\BGA_1024\RL6410_PCB_EXAMPLE_PINSHARE.h"
_DEF_DEMOD = _FW + r"\Pcb\RL6410\BGA_1024\RL6410_DEMO_D_1A4MHL1DP1mDP_DPTX_LVDS_VB1_PINSHARE.h"
_DEF_MCU = _FW + r"\Kernel\Scaler\RL6410_Series_Scaler\Header\RL6410_Series_McuCommonInclude.h"
_DEF_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "phytune", "rl6410_pins.json")


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--example", default=_DEF_EXAMPLE)
    ap.add_argument("--demod", default=_DEF_DEMOD)
    ap.add_argument("--mcu", default=_DEF_MCU)
    ap.add_argument("--out", default=_DEF_OUT)
    a = ap.parse_args()
    data = build(_read(a.example), _read(a.demod), _read(a.mcu))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    n = len(data["pins"])
    ng = sum(1 for p in data["pins"] if p["gpio"])
    nd = sum(1 for p in data["pins"] if p["danger"])
    print("pins=%d  gpio_mapped=%d  danger=%d  -> %s" % (n, ng, nd, a.out))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `./.venv38/Scripts/python.exe -m pytest tests/test_gen_pins.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add tools/__init__.py tools/gen_pins.py tests/test_gen_pins.py
git commit -m "feat(pinmux): 管脚表 generator(解析 PINSHARE/McuCommon + 域/危险分类)"
```

---

## Task 3: 生成 `rl6410_pins.json` + 核对

- [ ] **Step 1: 跑 generator 生成真实表**

Run:
```
./.venv38/Scripts/python.exe -m tools.gen_pins
```
Expected: 打印 `pins=<数百>  gpio_mapped=<数十>  danger=<若干>  -> ...\phytune\rl6410_pins.json`，文件生成。

- [ ] **Step 2: 抽样核对**

用 Python 读出几个已知脚核对（在仓库根跑）：
```
./.venv38/Scripts/python.exe -c "from phytune.pins import load_pins; db=load_pins(); print(len(db.pins)); print([ (d,len(ps)) for d,ps in db.by_domain() ]); p=db.pins[0]; print(p.ball, p.share, p.domain, p.gpio)"
```
Expected: 总数为数百；分组非空且按 `domain_order`；首脚 `share.page==16`。
人工检查：① `gpio_mapped` 数量 > 0（端口 4~F 的 GPIO 脚应映射上）；② 危险脚里能看到 VCCK/PANEL/LVDS 类。

- [ ] **Step 3:（实机，有板时）核实 GPIO 电平 bit**

挑一个**安全的 GPIO 输出脚**（domain=GPIO、非 danger、gpio!=null，如某 PORT4x/5x 脚），用上位机：先 `pin_set_mux` 设成输出(PP)，再 `gpio_set` 置 1/0，量该脚电压或观察已知负载。
- 若电平随之变化 → `GPIO_LEVEL_BIT=0` 正确，无需改。
- 若不变 → 在 `tools/gen_pins.py` 调整 `GPIO_LEVEL_BIT` 后重跑 generator（此步是 spec §13 的开放点收口；无板可跳过，mux 切换功能不受影响）。

- [ ] **Step 4: 提交生成物**

```bash
git add phytune/rl6410_pins.json
git commit -m "feat(pinmux): 生成 RL6410 管脚表 rl6410_pins.json"
```

---

## Task 4: app.py 桥接方法 + 入口分支

照搬 `phytune_*` 方法的写法：构造 `RegAccess(self._ensure(), mon_id)`、异常走 `_err(e)`、返回 `{ok,...}`。

**Files:**
- Modify: `app.py`（加 `_pindb()` 惰性载入 + 6 个 `pin_*` 方法；`main()` 加 `DDCCI_PINMUX` 分支）
- Test: `tests/test_pin_api.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_pin_api.py`：

```python
# -*- coding: utf-8 -*-
"""app.Api 的 pin_* 桥接方法单测(注入 FakeBackend + 内联 PinDB)。"""
import app as appmod
from phytune import pins as P
from phytune import vcp_codes as vc
from tests.fakes import FakeBackend


def _api_with(get_returns=None):
    api = appmod.Api()
    api._be = FakeBackend(get_returns=get_returns or {})
    # 注入一个内联 PinDB, 不读真实 JSON
    pin = P.Pin({
        "ball": "TESTA",
        "share": {"page": 0x10, "offset": 0x20, "mask": 0x07, "shift": 0},
        "default": 0, "domain": "GPIO",
        "funcs": [{"val": 0, "name": "P4D0i", "kind": "gpio_in"},
                  {"val": 1, "name": "P4D0o", "kind": "gpio_out_pp"}],
        "gpio": {"name": "P4D0", "data_page": 0xFE, "data_offset": 0x00, "bit": 0},
        "danger": False, "danger_reason": "",
    })
    api._pin_db = P.PinDB([pin], domain_order=["GPIO"])
    return api


def test_pin_db_returns_grouped():
    r = _api_with().pin_db()
    assert r["ok"] is True
    assert r["domains"][0]["domain"] == "GPIO"
    assert r["domains"][0]["pins"][0]["ball"] == "TESTA"


def test_pin_set_mux_writes():
    api = _api_with({(0, vc.VCP_ADDR_LATCH): (0x00, 0xFF)})
    r = api.pin_set_mux("TESTA", 1, 0)
    assert r["ok"] is True
    pokes = [s for s in api._be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0x01, 0))


def test_pin_set_mux_rejects_bad_value():
    api = _api_with({(0, vc.VCP_ADDR_LATCH): (0x00, 0xFF)})
    r = api.pin_set_mux("TESTA", 7, 0)   # 不在 funcs
    assert r["ok"] is False


def test_gpio_set_and_read():
    # 复用=1(输出PP), 数据寄存器 0x00 -> 置1
    api = _api_with({(0, vc.VCP_ADDR_LATCH): (0x01, 0xFF)})
    r = api.gpio_set("TESTA", 1, 0)
    assert r["ok"] is True


def test_pin_reset_default():
    api = _api_with({(0, vc.VCP_ADDR_LATCH): (0x05, 0xFF)})
    r = api.pin_reset_default("TESTA", 0)
    assert r["ok"] is True
    pokes = [s for s in api._be.sets if s[1] == vc.VCP_POKE]
    assert pokes[-1] == (0, vc.VCP_POKE, vc.pack_poke(0x00, 0))  # 默认0 -> 0x05&~7=0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `./.venv38/Scripts/python.exe -m pytest tests/test_pin_api.py -v`
Expected: FAIL（`AttributeError: 'Api' object has no attribute 'pin_db'`）

- [ ] **Step 3: 实现 — `app.py` 顶部 import 加 pins**

在现有 `from phytune import ced as ced_mod`（约 18 行）后加一行：

```python
from phytune.pins import load_pins
```

- [ ] **Step 4: 实现 — Api 类加方法**

在 `app.py` 的 `phytune_output_enable` 方法之后、`set_backend` 之前，插入：

```python
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
        """读单脚当前复用值/功能名(+GPIO 电平, 若当前是 GPIO)。"""
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
```

- [ ] **Step 5: 实现 — 顶部加 GPIO 输出种类常量引用**

`pin_read` 用到 `P_GPIO_OUT_KINDS`。在 `app.py` 的 `from phytune.pins import load_pins` 行改为：

```python
from phytune.pins import load_pins, GPIO_OUT_KINDS as P_GPIO_OUT_KINDS
```

- [ ] **Step 6: 实现 — main() 入口分支**

把 `main()` 里这一行（约 518 行）：

```python
    page = "phytune/index.html" if os.environ.get("DDCCI_PHYTUNE") else "index.html"
```

改为：

```python
    if os.environ.get("DDCCI_PINMUX"):
        page = "pinmux/index.html"
    elif os.environ.get("DDCCI_PHYTUNE"):
        page = "phytune/index.html"
    else:
        page = "index.html"
```

- [ ] **Step 7: 运行测试确认通过**

Run: `./.venv38/Scripts/python.exe -m pytest tests/test_pin_api.py -v`
Expected: PASS（5 passed）

- [ ] **Step 8: 全量回归 + 提交**

Run: `./.venv38/Scripts/python.exe -m pytest -q`
Expected: 之前的 ~56 + 本次新增全部 PASS。

```bash
git add app.py tests/test_pin_api.py
git commit -m "feat(pinmux): app.py 加 pin_* 桥接方法 + DDCCI_PINMUX 入口"
```

---

## Task 5: 前端 `ui/pinmux/`（A 浅色现代）

复用现有窗口外壳（`app.py` 的无边框/拖动/缩放已通用）。视觉基准 = 第一版样机 A + 分组样机（`.superpowers/brainstorm/` 内）。DDC 操作全部走串行锁（照搬 `ui/phytune/app.js` 的 `lock/pump`）。

**Files:**
- Create: `ui/pinmux/index.html`、`ui/pinmux/style.css`、`ui/pinmux/app.js`

- [ ] **Step 1: 写 `ui/pinmux/index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>管脚配置</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="panel">
    <!-- 自绘标题栏(拖动区), 复用主 UI 的窗口控制 API -->
    <div class="pbar pywebview-drag-region">
      <span class="dot" id="conn-dot"></span>
      <span class="title">管脚配置</span>
      <select id="mon" class="sel pywebview-no-drag"></select>
      <button id="refresh" class="icon pywebview-no-drag" title="重新枚举">↻</button>
      <span class="grow"></span>
      <button id="win-min" class="icon pywebview-no-drag">—</button>
      <button id="win-close" class="icon pywebview-no-drag">×</button>
    </div>

    <div class="body">
      <div class="side">
        <input id="search" class="search" placeholder="搜索 球名 / 功能…">
        <div id="list"></div>
      </div>
      <div id="detail" class="detail"><p class="empty">选择左侧一个管脚</p></div>
    </div>
  </div>

  <!-- 8 个边角缩放手柄(无边框窗口) -->
  <div class="resz n"></div><div class="resz s"></div><div class="resz e"></div><div class="resz w"></div>
  <div class="resz ne"></div><div class="resz nw"></div><div class="resz se"></div><div class="resz sw"></div>

  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 写 `ui/pinmux/style.css`**

```css
:root{
  --bg:#f7f8fa; --surface:#ffffff; --border:#e3e6ea; --line:#eef1f4;
  --text:#1c2024; --muted:#8a93a0; --accent:#1f8fff; --accent-soft:#eef4ff;
  --ok:#1a9b58; --ok-soft:#e7f6ee; --danger:#c0392b;
}
*{ box-sizing:border-box; }
html,body{ margin:0; height:100vh; overflow:hidden; }
body{ font-family:-apple-system,"Segoe UI",Roboto,sans-serif; color:var(--text);
  background:var(--bg); font-size:13px; }
.panel{ height:100vh; display:flex; flex-direction:column; }

.pbar{ height:40px; flex:none; display:flex; align-items:center; gap:8px;
  padding:0 10px; background:var(--surface); border-bottom:1px solid var(--line); }
.pbar .title{ font-weight:600; color:#5b6470; }
.dot{ width:8px; height:8px; border-radius:50%; background:#cbd2da; }
.dot.on{ background:var(--ok); } .dot.err{ background:var(--danger); }
.grow{ flex:1; }
.sel{ background:#f1f3f6; border:1px solid var(--border); border-radius:7px;
  padding:3px 8px; font-size:12px; color:var(--text); max-width:150px; }
.icon{ background:none; border:none; font-size:15px; color:#5b6470; cursor:pointer;
  width:26px; height:26px; border-radius:6px; }
.icon:hover{ background:var(--line); }
#refresh.spin{ animation:spin .8s linear infinite; }
@keyframes spin{ to{ transform:rotate(360deg); } }

.body{ flex:1; display:flex; min-height:0; }
.side{ width:46%; background:var(--surface); border-right:1px solid var(--line);
  display:flex; flex-direction:column; min-height:0; }
.search{ margin:8px; padding:6px 10px; border:1px solid var(--border); border-radius:7px;
  font-size:12px; background:#f1f3f6; }
#list{ flex:1; overflow:auto; }
.grp{ padding:7px 12px; background:#f3f6fa; color:#5b6470; font-size:11px; font-weight:600;
  display:flex; justify-content:space-between; align-items:center; cursor:pointer;
  border-top:1px solid var(--line); position:sticky; top:0; }
.grp .ct{ background:#e3e8ef; border-radius:20px; padding:0 7px; font-size:10px; }
.grp.collapsed + .rows{ display:none; }
.row{ padding:6px 12px 6px 22px; display:flex; justify-content:space-between;
  align-items:center; border-bottom:1px solid var(--line); cursor:pointer; }
.row:hover{ background:#f7faff; }
.row.on{ background:var(--accent-soft); color:var(--accent); }
.row .fn{ color:var(--muted); font-size:11px; }
.row.on .fn{ color:#5b8de8; }
.row.danger .ball::before{ content:"🔴 "; }

.detail{ flex:1; padding:14px; overflow:auto; display:flex; flex-direction:column; gap:10px; }
.detail .empty{ color:var(--muted); }
.detail h4{ margin:0; font-size:15px; }
.sub{ color:var(--muted); font-size:11px; }
.chip{ align-self:flex-start; font-size:11px; background:var(--ok-soft); color:var(--ok);
  border-radius:20px; padding:3px 9px; }
.chip.danger{ background:#fdecea; color:var(--danger); }
.ctl{ background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:9px 11px; display:flex; justify-content:space-between; align-items:center; gap:10px; }
.ctl label{ color:#5b6470; }
.ctl select{ flex:1; max-width:60%; padding:4px 8px; border:1px solid var(--border);
  border-radius:6px; }
.sw{ width:40px; height:22px; border-radius:20px; background:#cbd2da; position:relative;
  cursor:pointer; transition:background .15s; }
.sw.on{ background:var(--accent); }
.sw::after{ content:""; position:absolute; width:18px; height:18px; border-radius:50%;
  background:#fff; top:2px; left:2px; transition:left .15s; }
.sw.on::after{ left:20px; }
.sw.disabled{ opacity:.4; pointer-events:none; }
.btns{ display:flex; gap:8px; margin-top:6px; }
.btn{ font-size:12px; border-radius:7px; padding:7px 14px; border:1px solid var(--border);
  background:var(--surface); color:#5b6470; cursor:pointer; }
.btn.p{ background:var(--accent); color:#fff; border-color:var(--accent); }
.btn:disabled{ opacity:.5; cursor:default; }
.note{ font-size:11px; color:var(--muted); }

.resz{ position:fixed; z-index:50; }
.resz.n{ top:0; left:8px; right:8px; height:6px; cursor:ns-resize; }
.resz.s{ bottom:0; left:8px; right:8px; height:6px; cursor:ns-resize; }
.resz.e{ right:0; top:8px; bottom:8px; width:6px; cursor:ew-resize; }
.resz.w{ left:0; top:8px; bottom:8px; width:6px; cursor:ew-resize; }
.resz.ne{ top:0; right:0; width:10px; height:10px; cursor:nesw-resize; }
.resz.nw{ top:0; left:0; width:10px; height:10px; cursor:nwse-resize; }
.resz.se{ bottom:0; right:0; width:10px; height:10px; cursor:nwse-resize; }
.resz.sw{ bottom:0; left:0; width:10px; height:10px; cursor:nesw-resize; }
```

- [ ] **Step 3: 写 `ui/pinmux/app.js`**

```javascript
// 管脚配置器前端: 分组列表 + 详情(切复用/GPIO电平/还原默认), DDC 操作走串行锁。
const el = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

let MON = null;            // 当前显示器号
let DOMAINS = [];          // [{domain, pins:[...]}]
let PIN_BY_BALL = {};      // ball -> pin
let SELECTED = null;       // 当前选中 ball

const DOMAIN_LABEL = {
  GPIO:"数字 GPIO", I2C_DDC:"I²C / DDC", AUX_DP:"AUX / DP",
  LVDS_DISP:"显示 / LVDS", PWM_BL:"PWM / 背光", FLASH_SPI:"Flash / SPI",
  POWER_CTRL:"电源 / 控制", TEST_DBG:"Test / 调试", OTHER:"其他",
};
const KIND_LABEL = {
  gpio_in:"输入", gpio_out_pp:"输出(推挽)", gpio_out_od:"输出(开漏)",
  i2c:"I²C", periph:"外设", reserved:"保留",
};
const GPIO_OUT_KINDS = ["gpio_out_pp","gpio_out_od"];

// ---- DDC 串行锁(照搬 phytune) ----
let _busy=false; const _q=[];
function lock(fn){ return new Promise((res,rej)=>{ _q.push({fn,res,rej}); pump(); }); }
async function pump(){
  if(_busy) return; const job=_q.shift(); if(!job) return;
  _busy=true;
  try{ job.res(await job.fn()); }catch(e){ job.rej(e); }
  finally{ _busy=false; pump(); }
}

function setConn(state){ // 'on' | 'err' | ''
  const d=el("conn-dot"); d.className="dot"+(state?(" "+state):"");
}

// ---- 显示器选择 ----
async function pickBoard(){
  const r=await api().list_monitors();
  const sel=el("mon"); sel.innerHTML="";
  if(!r.ok){ setConn("err"); return; }
  r.monitors.forEach(m=>{
    const o=document.createElement("option");
    o.value=m.id; o.textContent=`[${m.id}] ${m.model||m.description||""}`;
    sel.appendChild(o);
  });
  MON = (r.default!=null)? r.default : (r.monitors[0]&&r.monitors[0].id);
  sel.value=MON;
  setConn(MON!=null?"on":"err");
}

// ---- 列表渲染 ----
async function loadPins(){
  const r=await api().pin_db();
  if(!r.ok){ el("list").innerHTML="<p class='note' style='padding:12px'>读管脚表失败</p>"; return; }
  DOMAINS=r.domains; PIN_BY_BALL={};
  DOMAINS.forEach(g=>g.pins.forEach(p=>{ PIN_BY_BALL[p.ball]=p; }));
  renderList("");
}
function muxSummary(p){ // 列表行右侧: 显示默认功能名(静态, 不实时读, 避免开屏狂读)
  const f=p.funcs.find(x=>x.val===p.default);
  return f? (f.name+(f.kind&&KIND_LABEL[f.kind]?" · "+KIND_LABEL[f.kind]:"")) : "—";
}
function renderList(filter){
  const f=(filter||"").toLowerCase();
  const list=el("list"); list.innerHTML="";
  DOMAINS.forEach(g=>{
    const pins=g.pins.filter(p=> !f || p.ball.toLowerCase().includes(f)
      || p.funcs.some(x=>(x.name||"").toLowerCase().includes(f)));
    if(!pins.length) return;
    const grp=document.createElement("div");
    grp.className="grp";
    grp.innerHTML=`<span>${DOMAIN_LABEL[g.domain]||g.domain}</span><span class="ct">${pins.length}</span>`;
    const rows=document.createElement("div"); rows.className="rows";
    pins.forEach(p=>{
      const row=document.createElement("div");
      row.className="row"+(p.danger?" danger":"")+(p.ball===SELECTED?" on":"");
      row.innerHTML=`<span class="ball">${p.ball}</span><span class="fn">${muxSummary(p)}</span>`;
      row.onclick=()=>selectPin(p.ball);
      rows.appendChild(row);
    });
    grp.onclick=()=>grp.classList.toggle("collapsed");
    list.appendChild(grp); list.appendChild(rows);
  });
}

// ---- 详情 ----
async function selectPin(ball){
  SELECTED=ball; renderList(el("search").value);
  const p=PIN_BY_BALL[ball];
  const r=await lock(()=>api().pin_read(ball, MON));
  renderDetail(p, r&&r.ok? r : null);
}
function renderDetail(p, state){
  const d=el("detail");
  const curVal = state? state.mux.val : p.default;
  const curKind = state? state.mux.kind : (p.funcs.find(f=>f.val===p.default)||{}).kind;
  const opts=p.funcs.map(f=>{
    const dis=f.kind==="reserved"?" disabled":"";
    const sel=f.val===curVal?" selected":"";
    return `<option value="${f.val}"${sel}${dis}>${f.val}: ${f.name} (${KIND_LABEL[f.kind]||f.kind})</option>`;
  }).join("");
  const isOut = GPIO_OUT_KINDS.includes(curKind);
  const isIn = curKind==="gpio_in";
  const hasGpio = !!p.gpio;
  const level = state? state.level : null;
  const swCls = "sw"+(level?" on":"")+((!isOut||!hasGpio)?" disabled":"");
  let gpioRow="";
  if(hasGpio && (isOut||isIn)){
    gpioRow = isOut
      ? `<div class="ctl"><label>输出电平</label><div id="sw" class="${swCls}"></div></div>`
      : `<div class="ctl"><label>读回电平</label><span>${level==null?"—":level}</span></div>`;
  } else if(!hasGpio){
    gpioRow = `<div class="note">此脚无 GPIO 数据寄存器映射, 电平不可控。</div>`;
  }
  d.innerHTML = `
    <h4>${p.ball}</h4>
    <div class="sub">复用寄存器 P${p.share.page.toString(16).toUpperCase()}_${p.share.offset.toString(16).toUpperCase().padStart(2,"0")}[${maskBits(p.share)}]</div>
    <div class="chip${p.danger?" danger":""}">${p.danger?("🔴 "+(p.danger_reason||"危险脚")):("当前: "+(state?state.mux.name:"—")+(curKind?" ("+(KIND_LABEL[curKind]||curKind)+")":""))}</div>
    <div class="ctl"><label>复用功能</label><select id="mux">${opts}</select></div>
    ${gpioRow}
    <div class="btns">
      <button id="reset" class="btn">还原默认 (${p.default})</button>
      <button id="apply" class="btn p">应用</button>
    </div>
    ${state?"":"<div class='note'>未读到当前值(板可能不在线), 显示默认值。</div>"}`;
  el("apply").onclick=()=>applyMux(p);
  el("reset").onclick=()=>resetPin(p);
  if(el("sw") && isOut && hasGpio) el("sw").onclick=()=>toggleLevel(p);
}
function maskBits(s){ // mask/shift -> "hi:lo"
  let hi=s.shift, m=s.mask>>s.shift, w=0; while(m){m>>=1;w++;} hi=s.shift+w-1;
  return w<=1? String(s.shift) : `${hi}:${s.shift}`;
}

async function applyMux(p){
  const val=parseInt(el("mux").value,10);
  if(p.danger && !confirm(`${p.ball} 是危险脚\n${p.danger_reason}\n\n继续可能黑屏或断开本控制链路(需重新上电)。确定要改吗?`)) return;
  el("apply").disabled=true;
  const r=await lock(()=>api().pin_set_mux(p.ball, val, MON));
  el("apply").disabled=false;
  if(!r||!r.ok){ alert((r&&r.error)||"写失败"); return; }
  selectPin(p.ball);  // 回读刷新
}
async function resetPin(p){
  if(p.danger && !confirm(`${p.ball} 还原默认值 ${p.default}, 继续?`)) return;
  const r=await lock(()=>api().pin_reset_default(p.ball, MON));
  if(!r||!r.ok){ alert((r&&r.error)||"还原失败"); return; }
  selectPin(p.ball);
}
async function toggleLevel(p){
  const sw=el("sw"); const next=sw.classList.contains("on")?0:1;
  const r=await lock(()=>api().gpio_set(p.ball, next, MON));
  if(!r||!r.ok){ alert((r&&r.error)||"置电平失败"); return; }
  selectPin(p.ball);
}

// ---- 窗口控制 + 缩放(照搬 phytune wireWindowChrome 思路) ----
function wireWindowChrome(){
  el("win-min").onclick=()=>api().minimize_window();
  el("win-close").onclick=()=>api().close_window();
  const HT={n:12,s:15,e:11,w:10,ne:14,nw:13,se:17,sw:16};
  document.querySelectorAll(".resz").forEach(h=>{
    const k=[...h.classList].find(c=>c in HT);
    h.addEventListener("pointerdown",e=>{ e.preventDefault(); api().start_resize(HT[k]); });
  });
  // QtWebEngine 后端不认 drag-region(本项目已弃 Win7, 仅 WebView2; 保留无害)
}

// ---- 启动 ----
async function boot(){
  wireWindowChrome();
  el("search").addEventListener("input", e=>renderList(e.target.value));
  el("mon").addEventListener("change", e=>{ MON=parseInt(e.target.value,10);
    if(SELECTED) selectPin(SELECTED); });
  el("refresh").onclick=async()=>{
    const b=el("refresh"); b.classList.add("spin");
    try{ await pickBoard(); await loadPins(); if(SELECTED) await selectPin(SELECTED); }
    finally{ b.classList.remove("spin"); }
  };
  await pickBoard();
  await loadPins();
}
window.addEventListener("pywebviewready", boot);
```

- [ ] **Step 4: 语法自检**

Run: `node --check ui/pinmux/app.js`
Expected: 无输出（语法 OK）。

- [ ] **Step 5: 离线截图核对(深/浅一张即可)**

临时 `ui/pinmux/_preview.html`：内联 mock `window.pywebview.api`（`list_monitors` 返回 1 屏、`pin_db` 返回 2~3 个域的假数据、`pin_read` 返回固定 mux），引 `style.css`+`app.js`。用 msedge headless 截图：
```
msedge --headless=new --virtual-time-budget=2500 --screenshot=_pinmux.png --window-size=520,840 "file:///C:/code/ddcci-host/ui/pinmux/_preview.html"
```
自己 Read `_pinmux.png` 核对：左侧分组列表、右侧详情控件、危险脚红点是否符合 A 浅色样机。核对后删除 `_preview.html`/`_pinmux.png`。

- [ ] **Step 6: 提交**

```bash
git add ui/pinmux/index.html ui/pinmux/style.css ui/pinmux/app.js
git commit -m "feat(pinmux): A 浅色前端(分组列表+详情切复用/GPIO电平/还原默认)"
```

---

## Task 6: 启动脚本 + 实机冒烟 + 收尾

**Files:**
- Create: `管脚配置.bat`
- Modify: `README-Win7.md` 同级新增一节，或在 `README` 里加说明（若无 README 则建 `README-pinmux.md`）

- [ ] **Step 1: 写 `管脚配置.bat`**

照 `PHY调试.bat` 的写法（`pyw` 无黑窗 + 设环境变量）。**全英文 ASCII，避免 GBK 控制台乱码**（见 [[feedback_ps1_gbk_encoding]] 同理）：

```bat
@echo off
set DDCCI_PINMUX=1
start "" pyw -3 "%~dp0app.py"
exit
```

- [ ] **Step 2: 无窗冒烟(不接板也能跑)**

确认入口与桥接不抛异常（用默认后端但不真正操作硬件）：
```
./.venv38/Scripts/python.exe -c "import os; os.environ['DDCCI_PINMUX']='1'; from app import Api; a=Api(); r=a.pin_db(); print('pin_db ok=', r['ok'], 'domains=', len(r.get('domains',[])))"
```
Expected: `pin_db ok= True domains= <若干>`（pin_db 不碰硬件，只读 JSON）。

- [ ] **Step 3: 起窗冒烟**

Run: `set DDCCI_PINMUX=1 && ./.venv38/Scripts/python.exe app.py`
Expected: 弹出"管脚配置"窗口，左侧出现分组列表，无报错。（无板时右侧选脚显示默认值 + "未读到当前值"提示，属正常。）

- [ ] **Step 4:（实机，有 RTK 板时）端到端**

板在线（caps=model RTK、已烧带 0xE5/0xE6 调试固件）：
- 顶栏自动选中 RTK 板，连接点变绿。
- 选一个**安全 GPIO 输出脚**：切复用→输出(PP)→拨电平开关→量电压/看负载变化（同 Task 3 Step 3，互为验证）。
- 选一个 I²C 脚切到 GPIO 再切回，回读一致。
- 选一个**危险脚**点应用→确认弹二次确认框（可取消，不实际写）。

- [ ] **Step 5: 写说明 + 提交**

新建 `README-pinmux.md`（要点：用途、`管脚配置.bat` 启动、换板重跑 `python -m tools.gen_pins`、危险脚二次确认、GPIO 电平依赖 bit 已实机核实、固件需带 0xE5/0xE6）。

```bash
git add 管脚配置.bat README-pinmux.md
git commit -m "feat(pinmux): 启动脚本 + 说明文档"
```

- [ ] **Step 6: 最终全量回归**

Run: `./.venv38/Scripts/python.exe -m pytest -q`
Expected: 全绿（原有 + 本特性 test_pins / test_gen_pins / test_pin_api）。

---

## 自查（写完计划对照 spec）

**Spec 覆盖：**
- §2 范围（切复用/GPIO 置位读电平/还原默认/分组/搜索/危险标记）→ Task 1(模型)+Task 4(API)+Task 5(UI) 全覆盖。
- §5 数据源/解析规则 → Task 2。§5.1 JSON 结构 → Task 2 `build()` 输出 + Task 1 `Pin` 字段，**字段名一致**（ball/share{page,offset,mask,shift}/default/domain/funcs{val,name,kind}/gpio{name,data_page,data_offset,bit}/danger/danger_reason）。
- §6 所属域固定分组 → Task 2 `DOMAIN_ORDER`/`classify_domain` + Task 1 `PinDB.by_domain` + Task 5 `DOMAIN_LABEL`。
- §7 模型方法签名（read_mux/set_mux/gpio_read/gpio_set/reset_default）→ Task 1，与 §7 一致。
- §8 桥接 API（pin_db/pin_read/pin_set_mux/gpio_read/gpio_set/pin_reset_default）→ Task 4，方法名与 §8 表一致。
- §9 界面 A 浅色 + 入口 `DDCCI_PINMUX` + `管脚配置.bat` → Task 5 + Task 4 Step6 + Task 6。
- §10 危险脚标记 + 二次确认 + 回读 + 掉线提示 → Task 2(danger) + Task 5(confirm/回读) + Task 4(hint)。
- §11 测试 → Task 1/2/4 的 pytest。
- §13 GPIO 名→数据寄存器映射开放点 → 实现期已核实映射可行(端口4~F)，仅 bit 由 Task 3 Step3 实机收口。

**占位符扫描：** 无 TBD/TODO；每个代码步骤给了完整代码。

**类型/命名一致性：** `GPIO_OUT_KINDS`（pins.py 定义，app.py 以 `P_GPIO_OUT_KINDS` 导入别名，UI 内独立同名常量）；`set_mux/gpio_set/reset_default` 全程同名；JSON 顶层 `{domain_order, pins}` 与 `load_pins` 一致；`pin_db()` 返回 `{domains:[{domain,pins}]}` 与 UI `renderList` 消费一致。

**潜在风险点（执行者注意）：** GPIO 电平 bit（`GPIO_LEVEL_BIT`）是唯一未经实机确认的假设；无板时先交付 mux 切换（已确证），bit 待板到位用 Task 3 Step3 收口。

