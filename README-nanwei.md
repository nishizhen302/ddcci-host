# 南微协议控制台

按《IIC协议(南微)》PDF 实现的显示器上位机：亮度 / 对比度 / 色温 / Gamma / 模拟按键 / 版本读取。

## 协议要点

标准 DDC/CI (MCCS) 帧格式，但从机地址 **0x5E**（读回 0x5F），非标准 0x6E：

| 功能 | 操作码 | 值 |
|---|---|---|
| 亮度 / 对比度 | 0x10 / 0x12 | 0x00~0x64 |
| 色温 | 0x14 | User=0x05, 9300K=0x06, 6500K=0x08 |
| Gamma | 0x72 | gamma1~7 = 0x06~0x0C |
| 模拟按键 | 0x96 (命令字 **0xC0**，非 SET VCP) | Menu=0, Right=1, Left=2, Exit=3，键值在高字节 |
| 硬件 / 软件版本 | 0xE0 / 0xC9 | 只读 |

- 写：`5E 51 84 03 op hi lo chk`，chk = 前 7 字节异或
- 读：`5E 51 82 01 op chk` → 等 >40ms → 从 0x5F 读 11 字节，chk2 = 前 10 字节异或 ^ 0x50
- 按键：`5E 51 84 C0 96 key 00 chk`（无回读）

## 用法

```
nanwei-console.bat              # GUI 控制台 (默认 USB 小板后端)
py -3 nanwei_cli.py check       # 链路自检: 版本 + 四参数各读一次
py -3 nanwei_cli.py set brightness 50
py -3 nanwei_cli.py key menu

rem 台式机上切显卡通道:
set DDCCI_BACKEND=gpu
py -3 nanwei_cli.py check       # 通了再开 nanwei-console.bat (同样先 set)
```

## 分层

- `nanwei_core.py` — 协议语义（操作码 / 值表 / 按键帧 / 设备封装），纯逻辑可单测
- `backends/` — 传输通道，可插拔，`set DDCCI_BACKEND=<名字>` 切换：
  - `rawusb`（笔记本开发期用）：Realtek USB ISP 小板旁路 I²C，接显示器任一 DDC 口
  - `gpu`（最终形态，**待台式机实测**）：显卡 HDMI/DP 原始 I²C，NVIDIA(nvapi64)
    与 AMD(atiadlxx) 双通道自动探测——每条候选通道发一帧"读亮度"，有应答才算数。
    照抄同事旧工具（Nicomsoft WinI2C-DDC）在 64 位系统上的实际路径：其 ddcdrv.sys
    是 x86 驱动 64 位加载不了，真正干活的就是 NVIDIASDK/ATISDK 用户态通道。
    排障开 `set DDCCI_GPU_DEBUG=1`
- `app_nanwei.py` + `ui/nanwei/` — pywebview 控制台
- `tests/test_nanwei_core.py` — 金标准 = PDF 的校验和示例

## 注意

- 0x5E 是南微显示器**出厂固件的原生从机地址**（同事的旧显卡工具即对 0x5E 收发），
  非标准 0x6E —— 所以 Windows dxva2 那套标准 API 打不到它，必须走原始 I²C 通道。
- `backends/raw_usb_backend.py` 的模块默认 `_SLAVE = 0x5E`。给**标准固件**(0x6E)
  用 pinmux/phytune 时组帧函数显式传 `slave=0x6E`（纯函数已带参数）。
