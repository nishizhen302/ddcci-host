# 南微协议控制台

按《IIC协议(南微)》PDF 实现的显示器上位机：亮度 / 对比度 / 色温 / Gamma / 模拟按键 / 版本读取。

## 协议要点

标准 DDC/CI (MCCS) 帧格式，但从机地址 **0x5E**（读回 0x5F），非标准 0x6E：

| 功能 | 操作码 | 值 |
|---|---|---|
| 亮度 / 对比度 | 0x10 / 0x12 | 0x00~0x64 |
| 色温 | 0x14 | User=0x05, 9300K=0x06, 6500K=0x08 |
| Gamma | 0x72 | gamma1~7 = 0x06~0x0C |
| 模拟按键 | 0x96 (命令字 **0xC0**，非 SET VCP) | Menu=0, Right=1, Left=2, Exit=3, **OK=4**，键值在高字节 |
| 硬件 / 软件版本 | 0xE0 / 0xC9 | 只读 |

- 写：`5E 51 84 03 op hi lo chk`，chk = 前 7 字节异或
- 读：`5E 51 82 01 op chk` → 等 >40ms → 从 0x5F 读 11 字节，chk2 = 前 10 字节异或 ^ 0x50
- 按键：`5E 51 84 C0 96 key 00 chk`（无回读）
- **OK=0x04 是 2026-07-10 真机逐值试出来的，PDF 未收录**；GUI「自定义键值」行就是干这个用的
- 按键宏（PDF 没有对应命令，只能模拟 OSD 操作顺序走进去，键间隔 0.35s）：
  - 进工厂菜单 = `Menu → OK`
  - 开启老化 = 进工厂菜单后再 `Menu → Menu → Right → Menu → Exit → Exit`

## 用法

```
nanwei-console.bat              # GUI 控制台 (默认 USB 小板后端)
py -3 nanwei_cli.py check       # 链路自检: 版本 + 四参数各读一次
py -3 nanwei_cli.py set brightness 50
py -3 nanwei_cli.py key menu    # 也收键值: key 0x04 (逆向 PDF 没列的键)
py -3 nanwei_cli.py factory     # 按键宏: Menu→OK 进工厂菜单
py -3 nanwei_cli.py aging       # 按键宏: 进工厂菜单后一路进老化

rem 台式机上切显卡通道:
set DDCCI_BACKEND=gpu
py -3 nanwei_cli.py check       # 通了再开 nanwei-console.bat (同样先 set)

rem 英伟达机上连不上时的分层排障 (不建链, 直接问 32 位 helper):
py -3 nanwei_cli.py nvscan            # helper 起没起来 / 枚举到几块屏 / 哪块应答 0x5E
py -3 nanwei_cli.py nvshort 0x400 30  # 发短帧亮度 (90 val chk), 看屏亮度变不变
```

## 分层

- `nanwei_core.py` — 协议语义（操作码 / 值表 / 按键帧 / 设备封装），纯逻辑可单测
- `backends/` — 传输通道，可插拔，`set DDCCI_BACKEND=<名字>` 切换：
  - `rawusb`（笔记本开发期用）：Realtek USB ISP 小板旁路 I²C，接显示器任一 DDC 口
  - `gpu`（最终形态）：显卡 HDMI/DP 原始 I²C，三类候选通道自动探测——每条发一帧
    "读亮度"，有应答才算数。排障开 `set DDCCI_GPU_DEBUG=1`，只试某类通道用
    `set DDCCI_GPU_CHANNELS=nv32`（可选 `nv64,nv32,amd`）：
    - `nv64` 进程内直连 `nvapi64.dll`
    - `nv32` **32 位 helper 子进程 `tools/nvddc32.exe`**（见下）
    - `amd` 进程内直连 `atiadlxx.dll`（2026-07-10 真机验证通过）
- `tools/nvddc32.c` / `.exe` — 32 位 nvapi helper。**英伟达实机上 64 位 nvapi64 无论
  怎么调都回 -8 INVALID_HANDLE，只有 32 位 nvapi 通**；64 位进程加载不了 32 位 DLL，
  所以把 nvapi 调用隔离进这个 helper，`backends/nv32_helper.py` 按行驱动它。
  重新编译（本机无 MSVC，用 zig 交叉编）：
  `zig cc -target x86-windows-gnu -O2 -o tools/nvddc32.exe tools/nvddc32.c`
- `app_nanwei.py` + `ui/nanwei/` — pywebview 控制台
- `tests/test_nanwei_core.py` — 金标准 = PDF 的校验和示例

## 注意

- 0x5E 是南微显示器**出厂固件的原生从机地址**（同事的旧显卡工具即对 0x5E 收发），
  非标准 0x6E —— 所以 Windows dxva2 那套标准 API 打不到它，必须走原始 I²C 通道。
- `backends/raw_usb_backend.py` 的模块默认 `_SLAVE = 0x5E`。给**标准固件**(0x6E)
  用 pinmux/phytune 时组帧函数显式传 `slave=0x6E`（纯函数已带参数）。
- 英伟达那条通道的配方是 2026-07-24 抓别人能通 0x5E 的工具逆出来的，**每一项都是必需的**，
  改一处就不通：`NV_I2C_INFO_V1`（不是 V3）+ 非 Ex 的 `I2CWrite/I2CRead` + handle 传
  **第一块 display 的 displayMask 值**（传 `EnumNvidiaDisplayHandle` 的句柄恒 -8）+ 选屏
  靠结构体 `displayMask` 字段 + `regAddrSize=0`（源地址 0x51 并进 data，不作寄存器）+
  `i2cSpeed=0x0A` + 写 0x5E / 读 0x5F。
- 抓包里别人工具设亮度用的是**短帧** `5E 90 val chk`（chk = 0x5E^0x90^val），与 PDF 的
  长帧 `5E 51 84 03 10 hi lo chk` 是两套。控制台按 PDF 走长帧；真机上若长帧无应答，用
  `nanwei_cli.py nvshort` 发短帧对照，确认是帧格式问题还是通道问题。
