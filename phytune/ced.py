# -*- coding: utf-8 -*-
"""HDMI 2.0 SCDC 字符误码检测 (CED) 读取 —— 调试方向的客观判据。

CED 计数器是 sink(本 RL6410 芯片)硬件实时统计的每通道字符误码数, 标准 HDMI 2.0
功能, 经 SCDC 间接寄存器暴露: 同页 0x39 写 SCDC 偏移选择, 0x3A 读数据窗
(固件已设 SCDC 端口不自增, 故每次显式选偏移再读最稳)。

三通道 R/G/B = Ch0/Ch1/Ch2, 每通道 15bit:
  LSB(偶 offset)=低 8 位; MSB(奇 offset) bit7=有效标志(valid), bits6:0=高 7 位。

要点(现场判读):
  • 仅在 HDMI 2.0 加扰高速链路(TMDS 字符率 >340M)下统计; 低速/不加扰时
    valid=0、计数恒为 0 —— 但 SSC 点不亮恰是高速场景, 正好可用。
  • SCDC 语义为"读后清零", 故定时轮询拿到的是该间隔内的误码增量 = 误码率。
  • 数越小越好; 某通道在涨 = 那条 lane 有 ISI/抖动, 去加它对应的 LE/Tap1。
"""

SCDC_SEL = 0x39    # SCDC 偏移选择寄存器 (同页)
SCDC_DATA = 0x3A   # SCDC 数据窗
SCDC_PAGE_BASE = 0x71  # SCDC 在频检/控制页: D2=0x71, 每端口 +1

# 通道名 -> (LSB SCDC 偏移, MSB SCDC 偏移)
CED_CHANNELS = (("ch0", 0x50, 0x51), ("ch1", 0x52, 0x53), ("ch2", 0x54, 0x55))
CH_LABELS = {"ch0": "R", "ch1": "G", "ch2": "B"}


def parse_ced(lsb, msb):
    """LSB + MSB -> {'count': 15bit 误码数, 'valid': bool}。MSB bit7 = 有效标志。"""
    valid = bool(msb & 0x80)
    count = (lsb & 0xFF) | ((msb & 0x7F) << 8)
    return {"count": count, "valid": valid}


def scdc_page(port=2):
    """SCDC 所在页随 HDMI 端口偏移: D2=0x71 D3=0x72 D4=0x73 D5=0x74。"""
    port = int(port)
    if not (2 <= port <= 5):
        raise ValueError("port 只能 2~5(D2~D5): %r" % (port,))
    return SCDC_PAGE_BASE + (port - 2)


def read_ced(ra, port=2):
    """读三通道 CED。任一字节读失败返回 None; 否则返回
    {'channels': [{'name','label','count','valid'} x3], 'valid': 任一通道有效}。"""
    page = scdc_page(port)
    chans = []
    any_valid = False
    for name, lo, hi in CED_CHANNELS:
        l = ra.read_scdc(page, lo)
        h = ra.read_scdc(page, hi)
        if l is None or h is None:
            return None
        info = parse_ced(l, h)
        any_valid = any_valid or info["valid"]
        chans.append({"name": name, "label": CH_LABELS[name],
                      "count": info["count"], "valid": info["valid"]})
    return {"channels": chans, "valid": any_valid}
