# 管脚配置器（Pinmux Configurator）设计文档

- 日期：2026-06-20
- 项目：`C:\code\ddcci-host`（DDC/CI 上位机），作为 phytune 之外的平级新功能
- 目标芯片/板：RL6410 系列，现役 PCB = `_RL6410_DEMO_D_1A4MHL1DP1mDP_DPTX_LVDS_VB1`（BGA-1024）
- 状态：设计已确认，待写实现计划

## 1. 背景与动机

使用者是硬件工程师。在现场调试硬件时，软件工程师不在场、或自己想快速验证某个想法时，希望能**自己改管脚试试**，而不必等软件工程师改固件重烧。

诉求**不到寄存器级别**，而是**面向"管脚"**：
- 把某个 GPIO 置 1 / 置 0、读回电平；
- 把一个复用管脚在 GPIO / I²C / 其他外设之间切换（"有时想让它当 IIC，有时当普通 IO"）。

因此本工具是一个**管脚配置器**，把"管脚 + 功能"翻译成底层寄存器读写，工具替使用者隐藏寄存器细节。

## 2. 范围

**做：**
- 选脚 → 切复用功能（GPIO 输入/推挽输出/开漏输出、I²C、其他外设）
- GPIO 模式下：设方向、置 1 / 置 0、读回电平
- 一键还原本板默认值（单脚 / 可选全部）
- 按"所属域/能力"固定分组 + 按球名/功能搜索
- 危险脚标记 + 二次确认

**不做（明确排除）：**
- 全部 ~11626 个寄存器的总表浏览（已否决，需求不在寄存器级）
- 原理图网络名（如 PANEL_ON/EDID_WP）检索——无 netlist 数据源，仅用 PINSHARE 的球名 + 功能名
- Win7 支持（本功能只走现有 Win11 WebView2 路径）
- 任意寄存器 peek/poke 逆田（已否决，纯管脚配置器）

## 3. 关键技术前提（已验证）

- **传输层已通**：dxva2 标准 DDC/CI（从机 0x6E）+ 固件私有 VCP `0xE5`（锁地址/peek）、`0xE6`（poke），可读写任意 XDATA 寄存器（地址 = `page<<8 | offset`）。RL6410 板已实机闭环验证（见 phytune 项目）。
- **pinshare 寄存器**在 Page10（0x10xx），**XDATA 可达**。复用值在低 3 位 `[2:0]`。
- **GPIO 数据寄存器**为 `volatile BYTE xdata MCU_FExx_PORTyz_PIN_REG`，地址 0xFExx，**同样在 peek/poke 的 16 位 XDATA 寻址范围内**。
- **结论：本功能固件零改动**，纯上位机工作，复用 phytune 的 `RegAccess` / 串行锁 / 窗口外壳 / app.py 桥接模式。
- **GPIO 方向**由 pinshare 值决定：`0=输入<I>`、`1=推挽输出<PP>`、`2=开漏输出<OD>`；其余值为外设功能（AUX/I²C/PWM/Test…）。

## 4. 架构（路线 1）

在 `ddcci-host` 内新增独立"管脚"页，与 phytune 平级、互不干扰。四层：

```
UI (ui/pinmux/)  ──JS桥──▶  app.py (Api 桥接方法)
                                  │
                              pins.py (Pin 模型, 位域读改写)
                                  │
                          phytune/regaccess.py (RegAccess: peek/poke + 串行锁)
                                  │
                          backends/ (dxva2 标准 DDC/CI, 0x6E)
                                  ▼
                          固件 0xE5/0xE6  ──▶  XDATA 寄存器
```

- 复用：`backends/`、`ddcci_core.py`、`phytune/regaccess.py`（peek/poke + DDC 串行锁）、`app.py` 窗口外壳与主题、显示器枚举/选择。
- 新增：`tools/gen_pins.py`、`phytune/rl6410_pins.json`、`phytune/pins.py`、`app.py` 新桥接方法、`ui/pinmux/`、`管脚配置.bat`。
- 入口：`app.py` main 增加模式分支，`DDCCI_PINMUX=1` 时加载 `ui/pinmux/`（与现有 `DDCCI_PHYTUNE` 同机制）。

## 5. 数据源与 generator

新脚本 `tools/gen_pins.py` 解析三处固件头文件，输出 `phytune/rl6410_pins.json`。换板/换 PCB 只需改输入路径重跑一次。

输入：
1. `Pcb/RL6410/BGA_1024/RL6410_DEMO_D_1A4MHL1DP1mDP_DPTX_LVDS_VB1_PINSHARE.h`
   —— 本板**默认值** + 寄存器位置注释 `// Page 10-0xXX[2:0]`。
2. `Pcb/RL6410/BGA_1024/RL6410_PCB_EXAMPLE_PINSHARE.h`
   —— 每个取值的**完整功能名**（如 `0: P1D0i<I>, 2: P1D0o<OD>, 3: AUX_P1`）。
3. `Kernel/Scaler/RL6410_Series_Scaler/Header/RL6410_Series_McuCommonInclude.h`
   —— `MCU_FExx_PORTyz_PIN_REG`，建 GPIO 名（`P{n}D{b}`）→ 数据寄存器地址 0xFExx + bit 的映射。

解析规则：
- 每个 `#define _PIN_<ball>  (N & 0x07)  // Page 10-0xXX[2:0]` 块：取 `ball`、默认值 `N`、寄存器 `page=0x10 offset=0xXX`、位域 `mask/shift`（由 `[2:0]` 解析）。
- 紧随其后的注释 `// 0 ~ M (0: name<I>, 1: ...)` 解析功能取值表：`val → {name, kind}`。
- 功能分类 `kind`：`<I>`=`gpio_in`、`<PP>`=`gpio_out_pp`、`<OD>`=`gpio_out_od`、`reserved`=`reserved`（禁选）、名字含 `IIC`/`DDC`=`i2c`、其余=`periph`。
- GPIO 映射：取功能名里的 `P{n}D{b}` → 经 McuCommonInclude 的端口表换算数据寄存器 + bit。**换算不出的脚 `gpio=null`**，UI 中其 GPIO 电平控件置灰，但复用切换照常可用。

### 5.1 pin JSON 结构

```json
{
  "ball": "Y6",
  "share": { "page": 16, "offset": 0, "mask": 7, "shift": 0 },
  "default": 0,
  "domain": "AUX_DP",
  "funcs": [
    { "val": 0, "name": "P1D0i", "kind": "gpio_in" },
    { "val": 2, "name": "P1D0o", "kind": "gpio_out_od" },
    { "val": 3, "name": "AUX_P1", "kind": "periph" }
  ],
  "gpio": { "name": "P1D0", "data_page": 254, "data_offset": 0, "bit": 0 },
  "danger": false,
  "danger_reason": ""
}
```

（`page:16` = 0x10；`data_page:254` = 0xFE。）

## 6. 所属域分组（方式 2 — 固定）

每个脚在 generator 阶段被固定归入一个 `domain`，位置不随当前复用变化。分类按脚的**完整功能名列表**关键词 + 显式覆盖表决定。域集合：

| domain | 标签 | 关键词/判据（示例） |
|---|---|---|
| `GPIO` | 数字 GPIO 端口 | 功能以 GPIO 输入/输出为主、无强外设归属 |
| `I2C_DDC` | I²C / DDC | 含 `IIC`/`DDC`/`SCL`/`SDA` |
| `AUX_DP` | AUX / DP | 含 `AUX`/`DP`/`HPD` |
| `LVDS_DISP` | 显示 / LVDS | 含 `LVDS`/`PANEL`/`TCON`/`VSYNC`/`HSYNC` |
| `PWM_BL` | PWM / 背光 | 含 `PWM`/`BL`/`DIMMING` |
| `FLASH_SPI` | Flash / SPI | 含 `FLASH`/`SPI`/`SF_` |
| `POWER_CTRL` | 电源 / 控制 | 含 `VCCK`/`POWER`/`_EN`/`RESET` |
| `TEST_DBG` | Test / 调试 | 含 `Test`/`UART`/`DEBUG` |
| `OTHER` | 其他 | 兜底 |

显式覆盖表 `DOMAIN_OVERRIDE = { "<ball>": "<domain>" }` 用于纠正个别误归类。UI 左侧按此分组、可折叠、显数量。

## 7. 模型层 `phytune/pins.py`

```python
class Pin:
    # 字段: ball, share{page,offset,mask,shift}, default, domain,
    #       funcs[{val,name,kind}], gpio{name,data_page,data_offset,bit}|None,
    #       danger, danger_reason

    def read_mux(self, ra) -> dict        # 读 pinshare 字节取位域 -> {val, name, kind}; 失败 None
    def set_mux(self, ra, val) -> bool    # 校验 val ∈ funcs 且非 reserved -> 读改写位域 -> 回读确认
    def gpio_read(self, ra) -> int|None   # 仅 gpio!=None: 读 0xFExx 对应 bit
    def gpio_set(self, ra, level) -> bool # 仅 gpio!=None 且当前为 GPIO 输出: 写 bit; 否则拒绝
    def reset_default(self, ra) -> bool   # 写回 default 到 pinshare 位域
```

- 所有写均为**读-改-写**，只动 `mask` 内的位，不破坏同寄存器其他位。
- `set_mux` 拒绝 `reserved` 和不在 `funcs` 内的值（抛 `ValueError`）。
- `gpio_set` 在 `gpio is None` 或当前复用非 GPIO 输出时拒绝（返回 False + 原因）。
- `PinDB`：从 `rl6410_pins.json` 载入，提供 `by_ball(ball)`、`by_domain()`（有序分组）、`search(text)`。

## 8. app.py 桥接 API

新增方法（异常统一翻译成 `{ok, error, hint}`，不抛进 JS；全部经 phytune 的 DDC 串行锁，避免读写竞态）：

| 方法 | 作用 |
|---|---|
| `pin_db()` | 返回分组后的全脚静态表（供 UI 渲染列表） |
| `pin_read(ball, mon)` | 读单脚当前复用值/功能名（+ GPIO 电平，若适用） |
| `pin_set_mux(ball, val, mon)` | 切复用，回读确认 |
| `gpio_read(ball, mon)` | 读 GPIO 电平 |
| `gpio_set(ball, level, mon)` | 置 GPIO 电平 |
| `pin_reset_default(ball, mon)` | 还原本脚默认值 |

`mon` 缺省时复用 `pick_default_monitor(be, "RTK")` 自动认板。

## 9. 界面（A 浅色现代）`ui/pinmux/`

复用现有窗口外壳/标题栏/主题/显示器选择/↻ 刷新。布局 = 顶栏 + 左列表 + 右详情：

- **顶栏**：标题（机型）+ 搜索框（按球名 / 功能关键词跨组过滤）+ 显示器下拉 + ↻。
- **左列表**：按 §6 的 `domain` **固定分组**，组可折叠、显数量；行显示 `球名 + 当前功能摘要`；危险脚 🔴 就近标红。
- **右详情**（选中脚）：
  - 标题：球名；副标题：复用寄存器 `P10_xx[2:0]`；当前功能 chip。
  - 复用功能下拉（来自 `funcs`，`reserved` 置灰）。
  - GPIO 电平：当前为 GPIO 输出 → 显示开关(0/1)；GPIO 输入 → 显示读回电平；`gpio=null` → 置灰。
  - 底部：还原默认 + 应用。
- **入口**：`app.py` main 加 `DDCCI_PINMUX=1` 分支加载 `ui/pinmux/`；`管脚配置.bat` 用 `pyw`（无黑窗）启动。

视觉基准：第一版样机 A（浅色现代）+ §6 分组样机 `layout-A-grouped.html`（存于 `.superpowers/brainstorm/`）。

## 10. 安全与错误处理

- **危险脚**：generator 按关键词（`LVDS`/`PANEL`/`VCCK`/`POWER`/`_EN`/承载 0x6E 的 DDC 控制脚 /`FLASH`/`RESET`）+ 显式 `DANGER_OVERRIDE` 清单打 `danger=true` 并写 `danger_reason`。
  - 承载本 DDC/CI 控制链路的脚为**最高危**（改了会当场失联）。
  - UI 红标；点"应用"时弹二次确认对话框，写明风险（"可能黑屏 / 断开本控制链路，需重新上电"）。
- 写后**必回读确认**；不一致标"未响应"，不阻塞 UI。
- peek/poke 失败 → `{ok:false}` + 提示"板不在线 / 拔插后点 ↻ 重新枚举"（↻ 先重新枚举显示器句柄再读，沿用 phytune 自愈逻辑）。
- 所有 DDC 操作经串行锁排队，避免多读写互抢锁。

## 11. 测试（pytest，复用 `tests/fakes.py` 的 FakeBackend）

- **generator 解析**：给一段 PINSHARE + McuCommon 片段 → 断言产出 JSON（位域 mask/shift、功能分类 kind、GPIO 映射、域归类、危险标记）。
- **pins.py 模型**：
  - 位域读-改-写正确性（不破坏同寄存器其他位）。
  - `set_mux` 拒绝 reserved / 越界值。
  - `gpio_read/gpio_set` bit 正确；`gpio=null` 或非 GPIO 输出时 `gpio_set` 被拒。
  - `reset_default` 写回默认值。
  - `PinDB` 分组/搜索。
- 沿用现有 ~56 测试风格，跑测：`./.venv38/Scripts/python.exe -m pytest`。

## 12. 交付物清单

- `tools/gen_pins.py`
- `phytune/rl6410_pins.json`
- `phytune/pins.py`
- `app.py`（新增 6 个桥接方法 + `DDCCI_PINMUX` 入口分支）
- `ui/pinmux/{index.html, app.js, style.css}`
- `管脚配置.bat`
- `tests/test_gen_pins.py`、`tests/test_pins.py`

## 13. 待实现期解决的开放点

- **GPIO 名 → 数据寄存器映射**：`P{n}D{b}` 编号与 `MCU_FExx_PORTyz` 的对应关系需在实现期核对（功能名端口号 vs SFR 端口号可能不同名）。映射不出的脚 `gpio=null`、电平控件置灰——不阻塞复用功能。
- **危险脚关键词清单**需结合本板实际功能名微调（首版从严，宁可多标）。
