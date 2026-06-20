# 管脚配置器（Pinmux Configurator）

面向硬件工程师的在线管脚配置工具：软件工程师不在场时，自己就能改管脚试探，而不必等改固件重烧。

- 选脚 → 切复用功能（GPIO / I²C / 其他外设）
- GPIO 模式下：设输入/输出、置 1 / 置 0、读回电平
- 一键还原本板默认值
- 按"所属域"固定分组 + 按球名/功能搜索
- 危险脚标红，改动时弹二次确认

底层走现有 DDC/CI peek/poke（VCP `0xE5`/`0xE6`）+ `RegAccess`，**固件无需为本功能改动**（但板上需已烧带 `_DEBUG_PHY_TUNE_SUPPORT`、即支持 0xE5/0xE6 的调试固件，且 DDC/CI 为标准 0x6E 模式——与 phytune 同一前提）。

## 启动

双击 **`管脚配置.bat`**（无控制台窗口）。若不弹窗，跑 `pinmux-console.bat` 看报错。
等价命令：`set DDCCI_PINMUX=1 && py -3 app.py`。

仅支持 Win10/Win11（WebView2）。

## 换板 / 换 PCB

管脚表 `phytune/rl6410_pins.json` 由 generator 从固件头生成。换板后重跑一次：

```
py -3 -m tools.gen_pins
```

默认读 codex 现役 RL6410 树（`tools/gen_pins.py` 顶部 `_FW` 路径）；本机路径不同时显式传：
`py -3 -m tools.gen_pins --example <PINSHARE> --demod <DEMO_x PINSHARE> --mcu <McuCommonInclude.h>`

数据来源：
- `*_PCB_EXAMPLE_PINSHARE.h` —— 每个复用值的完整功能名
- 本板 `*_DEMO_x_..._PINSHARE.h` —— 本板默认值
- `*_McuCommonInclude.h` —— GPIO 名 `P<n>D<b>` → 数据寄存器 0xFExx 映射

## 注意事项

- **危险脚**：默认功能为 LVDS/PANEL/TCON/Flash 或 DDC 控制口的脚标红；改它们可能黑屏，或断开本控制链路（需重新上电）。改动弹二次确认。危险口径=按**本板默认功能**判（不是只要带危险备选就标）。手动追加危险脚：编辑 `tools/gen_pins.py` 的 `DANGER_OVERRIDE` 后重跑 generator。
- **GPIO 电平的字节内 bit**：当前按 RTD 惯例取 bit 0（`tools/gen_pins.py` 的 `GPIO_LEVEL_BIT`）。如实机发现某 GPIO 输出脚拨电平无效，核对后改该常量重跑 generator。
- **端口 1/3**（数据/AUX 口）无 MCU GPIO 数据寄存器，其 `gpio` 为空，电平控件置灰；复用切换不受影响。
- 列表行显示的是该脚**默认功能**摘要（不为每个脚开屏狂读 DDC）；右侧详情显示的才是实时读回的当前值。
- 板掉线/拔插后读失败：点顶栏 ↻ 重新枚举显示器句柄再读。
