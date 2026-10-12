# 固件交接：让 USB 小板在任意 DDC 口都能跑 DDC/CI 寄存器读写

**目标**：USB 转 I²C 小板（Realtek USB ISP Tool，VID_2007/PID_0808）接在**任意一个 DDC 口**
（例如 D1/HDMI），能对 scaler 做寄存器 peek/poke，**不依赖当前活动视频源**。
板=RL6432(RTD2785) 2785_A2 216PIN，屏=LG 27FHD。主机侧工具已就绪（见文末），只差固件配合。

---

## 1. 主机侧到底发什么（只有上位机这边清楚，供固件验证回包）

物理链路 = 裸 USB 管道复刻 Beacon/USBLibrary（**不是 Comm.dll，Comm.dll 在 RUN 态发 DDC 写恒 NAK**）：
- 按 RTUsb 私有接口 GUID `{d3a14581-fdda-4402-b5f9-8373ebc54ddb}` 枚举设备路径；
- `CreateFileW(GENERIC_RW, FILE_SHARE_RW, OPEN_EXISTING)` + `WriteFile`/`ReadFile` 收发。

**板包格式**（外层 sum8 = 前字节和&0xFF，由板处理，固件不用管）：
- 写：`12 <slave> <sub> <lenHi> <lenLo> <data...> <sum8>`
- 读：`11 <slave> <sub> <lenHi> <lenLo> <sum8>`，随后 `ReadFile(n+2)`，尾 2 字节=板status+sum8

**DDC/CI 帧**（封在板包 data 里）：slave=`0x6E`、sub=`0x51`、
`data = [0x80|len, <payload...>, xorchk]`，xorchk = 含 0x6E^0x51 的全字节 XOR。

**寄存器 peek/poke = 标准 SET/GET VCP，用厂商 VCP 0xE5/0xE6**（固件 `_DEBUG_PHY_TUNE_SUPPORT _ON` 已支持）：
- 锁地址：SET VCP `0xE5`，value = `(page<<8)|offset` → payload `[0x03,0xE5,page,offset]`
- 读回：GET VCP `0xE5` → payload `[0x01,0xE5]`，回包 `6E 88 02 result E5 typ maxH maxL curH curL chk`，
  peek 值 = curL
- 写：SET VCP `0xE6`，value = `(type<<8)|data` → payload `[0x03,0xE6,type,data]`

> 也就是说：固件只要在“小板所接的那条 DDC 通道”上以 0x6E 应答标准 DDC/CI，pinmux 即可工作。

---

## 2. 已查明的固件现状（RL6432 源码，供你确认/纠正）

- 全芯片**单个** DDC/CI 引擎：`MCU_FF23_IIC_SET_SLAVE`（0x6E=DDCCI / 0x6A=debug）+
  `MCU_FF22_IIC_CH_SEL`（选 DDC0~5/VGA 一条通道）。
- `ScalerMcuDdcRamEnable()` **无条件使能全部 DDC 通道**（含 DDC1）。
- 引擎**跟随活动视频源**：`ScalerMcuDdcciSwitchPort(_DDCCI_MODE, 活动源口)` 设 0x6E + 选该口通道。
- auto-switch：`_DDCCI_AUTO_SWITCH_SUPPORT` → `UserCommonDdcciHandler()` 空闲时
  `SET_DDCCI_AUTO_SWITCH()`=`MCU_FF2A_IIC_IRQ_CONTROL2 |= _BIT4`（硬件跨口自动切）。
  固件 `Pcb_Config_Check.h`/`Project_Config_Check.h` 两处 `#warning "should be _ON"`。

**实机实测（经 dxva2 在活动口 peek 运行态寄存器）**：FF23=0x6E、FF22=0x03(DDC2,活动源)、
**FF2A bit4=1（auto-switch 已使能）**。但 USB 小板接**非活动口 D1** 时 0x6E 始终 NAK；
把输入源切到 D1 后引擎才到 DDC1（但随即和小板抢总线/时钟拉伸把读撑住）。

**结论 / 卡点**：`_DDCCI_AUTO_SWITCH_SUPPORT _ON` 已生效（bit4=1），但**没有把 0x6E 桥到
非活动的 DDC1**。这一步需要懂 FF2A/FF22 硬件语义（datasheet）才能定——上位机侧推不出来。

---

## 3. 我试过的固件改动（可作起点，未解决）

1. `Project/Header/RL6432_Project.h`：加 `#define _DDCCI_AUTO_SWITCH_SUPPORT _ON`。
2. `Pcb/RL6432/LQFP_216/RL6432_2785_A2_216PIN_1A2H1DP1DVI_LVDS.h`：
   `_D1_INPUT_PORT_TYPE` 由 `_D1_DP_PORT` 改 `_D1_HDMI_PORT`（用户实物 D1=HDMI；
   **DP 走 AUX 无 I²C DDC，HDMI/DVI 才有 0x6E**）。
   > 还有一处未对齐：`_D1_EMBEDDED_DDCRAM_MAX_SIZE` D1=`_EDID_SIZE_256` 而 D2=`_EDID_SIZE_NONE`。
   > 用户板 D1/D2 电路完全相同，建议 D1 整体配成 D2 的镜像。
3. 现象“烧我的固件后 D1 要先点烧录再上电、D2 不用”——经查**芯片确是 RL6432 216PIN、
   bin 结构与原厂参考一致**，但我的构建走 skill 的 `auto_link+HexToBin` 只出 ~590KB 代码段，
   原厂 test.bin 是填到满 2MB 的完整镜像。**请用你那套能出完整可用镜像的流程编译**，别用我的。

---

## 4. 备选路：0x6A 调试协议（很可能就是别家用的）

引擎**默认就是 debug 模式、从地址 0x6A**（`g_enumDDCCIDebugMode = _DEBUG_MODE`），独立于活动源。
`ScalerDebug()`（`ScalerCommonFunction/Code/ScalerCommonDebug.c`）的命令直接读写寄存器：
- `case 0x41`：CScalerRead — `MCU_FFF4_SCA_INF_ADDR=addr; ucResult=MCU_FFF5_SCA_INF_DATA`
- `case 0x3A`：`ScalerGetByte((data[2]<<8)+data[1])` 读 flash/MCU 寄存器
- `case 0x3B`：`ScalerSetByte(addr, data[3])` 写 flash/MCU 寄存器

debug 模式的通道 = `_DEBUG_DDC_CHANNEL_SEL`(=`_PCB_DEBUG_DDC`，本板=`_VGA_DDC`)。
**若别家工具走 0x6A，则把 debug 通道设到小板所接的口、或让 debug 模式跨口，即可任意口通**——
请确认别家是发 0x6E 标准 DDCCI 还是 0x6A 调试协议，这决定固件该让哪条路在任意口应答。

---

## 5. 主机侧已就绪（无需你做）

`C:\code\ddcci-host`：Backend B `backends/raw_usb_backend.py`（裸 USB，已修 64 位句柄截断坑）、
`管脚配置-USB小板.bat`（`DDCCI_BACKEND=rawusb`）、pinmux GUI/表（rl6432_pins.json）。
传输已实测能到板（EDID 0xA0 在 D1 读得到）。固件一旦让 0x6E（或 0x6A）在小板所接口应答，
上位机零改动即可工作。
