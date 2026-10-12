# RL6410 PHY/CDR/DFE 现场调试上位机 —— 设计规格

> 日期：2026-06-14
> 目标芯片：Realtek RL6410 系列（HDMI 接收 TMDS PHY）
> 固件源码：`C:\Users\61093\Desktop\monitor firmware\New STD Code II 1P SVN2860`
> 上位机：`C:\code\ddcci-host`（Python + pywebview，复用现有 dxva2 传输层）

---

## 1. 背景与目标

现场调试 RL6410 显示器的 **PHY / CDR / DFE** 物理层寄存器（开机黑屏自恢复、主机开 SSC 点不亮等问题的调参），需要一个上位机：

1. **在线调**：上位机调某个命名参数 → 实时写入显示器寄存器，立即看效果。
2. **离线调**：对于无法在线生效或需固化的改动，调完 → 自动编译一版固件 bin → 用户烧录（可选一键调用烧录器命令行）。

复用已验证的 DDC/CI 传输层（`ddcci_core` + `backends/dxva2_backend`），亮度/对比度等消费级功能原样保留，本工具作为独立"PHY 调试"页面/入口存在于同一仓库。

### 核心现实约束（决定架构）

要调的 P7B（DFE/CDR）、P71（频检）寄存器，由 `SetPhy_EXINT0()` / `SetDFEInitial_EXINT0()` / `InterruptInitial()` 在**每次信号重锁时重新写入**。
→ 纯 poke 的在线值会在下一次信号扰动/重锁时被硬编码值覆盖。
→ 因此在线通道必须配 **override 表 + 重锁后 re-apply hook**，否则 DFE/CDR 调整不稳定。

---

## 2. 总体架构

```
┌─ UI 层 (新增 ui/phytune 页面) ──────────────────────┐
│  参数分组(DFE / CDR / 频检) · 命名滑杆/输入 · 实时读回   │
│  实时状态条(锁定态 + CED 错误计数 — 边调边看眼质量)      │
│  Profile 存取(JSON) · "烘焙并编译"按钮 + diff 预览 · 烧录 │
└──────────────────┬──────────────────────────────────┘
          ┌─────────┴─────────┐
      在线通道                离线通道
┌──────────────────┐   ┌──────────────────────────────┐
│ peek/poke VCP     │   │ 改 RL6410_DebugTune.h preset   │
│ + override 表登记  │   │ → UV4/-r 编译 → bin → (烧录)   │
└────────┬─────────┘   └──────────────────────────────┘
     传输层(复用 dxva2_backend: get_vcp / set_vcp 任意 VCP)
```

设计为可独立理解/测试的单元：
- **传输层**（已存在）：`backends/dxva2_backend.py` 提供 `get_vcp(idx,code)` / `set_vcp(idx,code,val)`。本工具不改它。
- **寄存器访问层**（新）：`phytune/regaccess.py`，把"读/写一个具名参数"翻译成 peek/poke/override VCP 序列。
- **参数模型层**（新）：`phytune/params.py` + `rl6410_params.yaml`，描述每个可调项。
- **编译/烧录层**（新）：`phytune/builder.py`，生成 `RL6410_DebugTune.h`、调编译、调烧录器。
- **UI 层**（新）：`ui/phytune/`（page + JS），通过 pywebview 暴露的 API 调用上述层。

---

## 3. 在线通道：调试 VCP 协议

新增厂商私有调试 VCP 操作码（取空闲区 `0xE5~0xE7`；`0xE0~E4` 已被固件 `_DDCCI_DISP_CALIB_*` 校准步骤值占用，`0xE3` 为 CONTROL_LOCK；同时避开 `0x72` gamma / `0xF0` 按键 / `0xF1` Dell DDM / `0xF3` cmds / `0xFD` MANUFACTURER）。固件侧在 `RTD2014Ddcci.c` 解析。

| VCP | 方向 | 载荷(16bit value) | 含义 |
|---|---|---|---|
| `0xE5` | SET | `page<<8 \| offset` | 锁存目标寄存器地址 |
| `0xE5` | GET | 返回 current=值 | **peek**：读锁存地址当前值 |
| `0xE6` | SET | `type<<8 \| data8` | **poke**：写 data 到锁存地址；type=0 直接页寄存器，type=1 data-port 间接 |
| `0xE7` | SET | `op<<8 \| slot` | **override 表**：op=1 登记(用上次 0xE5 地址+0xE6 值)，op=0 删除 slot，op=2 清空全部 |

> 地址编码：page 用 RL6410 的页号（如 0x71、0x7B），offset 为寄存器低 8 位。首批参数全部是**直接页寄存器**（`ScalerSetBit/ScalerSetByte` 访问），type=0 即可；type=1 预留给将来 data-port 间接寄存器（HDMI packet 类）。

### override 表（固件侧）

- XDATA 里一张定长表：`struct { BYTE port; WORD addr; BYTE value; BYTE type; bit active; } g_DebugOverride[24];`
- 在 `ScalerTMDSRx2SetDFEInitial_EXINT0()`、`ScalerTMDSRx2SetPhy_EXINT0()`、`ScalerTMDSRx2InterruptInitial()`（及 Rx3~5 对应函数）的**末尾**各加一行 `ScalerTMDSDebugApplyOverride(_Dx_INPUT_PORT);`，遍历表把 **port 匹配（或通配）且 active** 的项重新写回。
- Rx2~Rx5 四端口共用同一张表与同一个 apply 函数；每项带 `port` 字段，apply 时只应用与当前调用端口匹配的项（`port=0xFF` 视为通配，应用到所有端口）。上位机登记 override 时带上目标端口（默认取当前激活输入端口）。
- 编译开关 `_DEBUG_PHY_TUNE_SUPPORT`，量产固件关掉，零开销。

> **结论**：烧一版带 `_DEBUG_PHY_TUNE_SUPPORT` 的调试固件后，现场 PHY/DFE 调整全程在线实时，override 表保证调好的值扛过重锁；不必反复编译。

---

## 4. 离线通道：调完自动出 bin

### 4.1 一次性源码重构（参数化 preset）

把首批参数在四个端口文件里的写死数值，抽进一个**生成头** `Kernel/Scaler/RL6410_Series_Scaler/Header/RL6410_DebugTune.h`，用 `#define` 表达，`SetDFEInitial/SetPhy/InterruptInitial` 改为引用宏。

- 好处：上位机烘焙时**只改这一个头**，不 patch 四份克隆代码，安全可回退；在线 override 表与离线宏**共用同一套参数定义**（同一 `rl6410_params.yaml` 生成两边）。
- 该头带默认值（= 当前源码原值），不开调试时行为与现状完全一致。

### 4.2 烘焙 → 编译 → 烧录

1. 上位机把当前参数集 → 重新生成 `RL6410_DebugTune.h`。
2. 弹 **diff 预览**（旧值 vs 新值），用户确认。
3. 调编译：`build-rl6432-firmware` skill / UV4 `-r` 重编 + auto_link，产出 bin（路径与 MD5 回显）。
4. **烧录（可选一键）**：`phytune/flasher.py` 读 `flasher.json` 里的命令模板执行：
   ```json
   { "cmd": "C:\\path\\to\\isp_tool.exe", "args": ["-p", "{port}", "-f", "{bin}", "-erase", "-verify"], "port": "COM3" }
   ```
   `{bin}` / `{port}` 占位符运行时替换。用户首次填入自己的 ISP 工具命令；留空则只产 bin、手动烧。

---

## 5. 参数模型（首批：今天黑屏 + SSC 涉及的寄存器）

`rl6410_params.yaml` 每项字段：`name / group / page / offset / bitmask / shift / type(direct|dataport) / range / default / consumed_by / online_needs_override / src_macro`。

### 5.1 频检窗口（黑屏自恢复相关）—— `InterruptInitial`，page 0x71，direct

| 参数 | 寄存器 | 说明 |
|---|---|---|
| 频检 offset | `P71_E7_HDMI_FREQDET_OFFSET[2:0]` | 容差档(=1/32)，放宽抗 SSC/抗误判黑屏 |
| 稳定时间 | `P71_EC_HDMI_FREQDET_STABLE` | =0x3F(~5ms)，影响判稳/判丢速度 |
| 上界 M/L | `P71_E8 / P71_E9` | 频率上界 |
| 下界 M/L | `P71_EA / P71_EB` | 频率下界 |

### 5.2 CDR / 展频跟踪 —— `SetPhy_EXINT0`，page 0x7B，direct

| 参数 | 寄存器 | 说明 |
|---|---|---|
| KVCO | `P7B_2C_ANA_CDR_02[1:0]` | VCO 增益 |
| 电荷泵 Icp / Rs | `P7B_31_ANA_CDR_07` | 环路带宽核心，抬高带宽以跟住 SSC 扫频 |
| FLD 计数 H/L | `P7B_2E / P7B_2F_ANA_CDR_04/05` | FLD 参考计数 |
| VCO band L0~L2 | `P7B_32~P7B_37_ANA_CDR_08~13` | VCO band 选择，盖住 SSC 扫幅 |

### 5.3 DFE —— `SetDFEInitial_EXINT0`，page 0x7B，direct

| 参数 | 寄存器 | 说明 |
|---|---|---|
| LE 初值 L0~L2 | `P7B_A2 / B2 / C2_Lx_LIMIT_INIT` | 线性均衡高频提升，撑开垂直眼（SSC 点不亮主调项） |
| Tap1 初值 L0~L2 | `P7B_A5 / B5 / C5_Lx_INIT_3` | 第一抽头初值 |
| adapt_mode | `P7B_E0_MODE_TIMER[7:6]` | 自适应模式 / 开环 |
| Tap 增益组 | `P7B_E2~E5_GAIN_1~4` | 各抽头/LE 增益 |
| Tap 限幅组 | `P7B_E6~EB_LIMIT_1~6` | 各抽头限幅 |

> 注：黑屏自恢复的根因里，去抖逻辑（连续 N 次确认）与 MeasureClk 超时是**代码改动**，不是寄存器项，不进本参数表；但与之强相关的频检窗口（5.1）做成可调，便于现场缓解。代码层修复另走固件改动 + 离线编译。

---

## 6. UI 设计要点

- **连接区**：枚举显示器、自动认 RTK 板、链路状态；提示当前是否为带 `_DEBUG_PHY_TUNE_SUPPORT` 的调试固件（peek 一个特征寄存器判断）。
- **参数分组**：DFE / CDR / 频检 三组，每项命名滑杆 + 数值输入 + 范围；显示 peek 回来的当前值；标 `在线`/`仅编译` 徽章；标 `需override` 项。
- **应用方式**：单项 Apply（poke + 登记 override 表）；整组重置为默认。
- **实时眼质量状态条（杀手级）**：轮询 CED 错误计数 / 锁定态（`P71_0B~18` 那批），实时数字/曲线。拉 LE 滑杆时盯 CED 错误数下降即可判断眼图改善，无需示波器。
- **Profile**：当前参数集存/取 JSON（现场发现落盘，喂给编译）。
- **烘焙并编译**：diff 预览 → 编译 → bin 路径/MD5 → 可选一键烧录。

---

## 7. 模块边界与文件清单

新增（均在 `C:\code\ddcci-host`）：
```
phytune/
  __init__.py
  regaccess.py     # 具名参数 <-> peek/poke/override VCP 序列
  params.py        # 加载 rl6410_params.yaml，校验范围/编码位域
  builder.py       # 生成 RL6410_DebugTune.h、调编译
  flasher.py       # 读 flasher.json、执行烧录命令
  rl6410_params.yaml
  flasher.json     # 用户填自己的 ISP 命令(默认空 = 只产 bin)
ui/phytune/
  index.html  app.js  style.css
app.py             # 新增 phytune 页面入口 + 暴露 API(沿用现有 pywebview 模式)
tests/
  test_regaccess.py  # 位域编码/地址打包 round-trip
  test_params.py     # yaml 校验、范围越界拒绝
```

固件侧（`monitor firmware`，需烧调试固件）：
```
RTD2014Ddcci.c            # 加 0xE5~0xE7 调试 VCP 解析
RL6410_Series_TMDSRx2~5.c # SetDFEInitial/SetPhy/InterruptInitial 末尾加 apply hook
RL6410_DebugTune.h        # 新生成头(参数化 preset)
UserCommonDdcciDefine.h   # 加 _DDCCI_OPCODE 宏 + _DEBUG_PHY_TUNE_SUPPORT 开关
```

---

## 8. 错误处理与安全

- **越界保护**：上位机按 yaml range 夹值；固件 poke 不做范围判断（调试用），但 page 白名单（只允许 0x71/0x7B 等已知页）防误写关键寄存器。
- **链路失败**：peek/poke 走 set/get VCP，失败回显（沿用现有 backend 返回约定）。
- **重锁竞态**：override apply hook 在 init 函数末尾、临界区内执行，避免与中断争用。
- **量产隔离**：`_DEBUG_PHY_TUNE_SUPPORT` 关闭时，调试 VCP 与 override 表/hook 全部编译掉，量产 bin 零残留。
- **可回退**：`RL6410_DebugTune.h` 默认值 = 原源码值，烘焙前后可 diff/还原。

---

## 9. 测试策略

- **单元**：`regaccess` 地址打包/位域编码 round-trip；`params` yaml 加载与越界拒绝；`builder` 生成头与默认值幂等。
- **集成（需硬件）**：peek 已知寄存器值与固件 dump 比对；poke 一个无害寄存器读回一致；override 表登记后手动触发重锁、确认值保持。
- **离线链路**：烘焙一个改动 → 编译出 bin → MD5 稳定可复现。

---

## 10. 分期

- **P0 传输扩展**：固件加 0xE5~0xE7 + peek/poke（无 override）；上位机 `regaccess` + 最小 UI，能读写单个寄存器。烧一版调试固件验证链路。
- **P1 override 表**：固件加表 + apply hook；上位机登记/清除。验证调值扛过重锁。
- **P2 参数模型 + 分组 UI**：yaml + 命名滑杆 + 实时 CED 状态条。
- **P3 离线编译**：参数化头重构 + builder + diff + 编译产 bin。
- **P4 烧录集成**：flasher.json 命令模板 + 一键烧。

---

*本 spec 经用户确认整体方向（同仓扩展 + override 表 + 生成头 + 自动编译 + 可选命令行烧录；首批参数限定为黑屏+SSC 相关寄存器）后定稿。下一步进入 writing-plans 出实现计划。*
