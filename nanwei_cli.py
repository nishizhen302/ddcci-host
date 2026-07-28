#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""南微协议命令行 —— USB 小板链路自检 / 单条命令收发。

用法:
  py -3 nanwei_cli.py check                  # 链路自检: 读版本 + 四个参数各读一次
  py -3 nanwei_cli.py get all|brightness|contrast|colortemp|gamma
  py -3 nanwei_cli.py set brightness 50      # 值十进制或 0x 十六进制
  py -3 nanwei_cli.py key menu|right|left|exit
  py -3 nanwei_cli.py ver

英伟达机排障 (不建链, 直接问 32 位 helper, 建链失败时先跑这两条):
  py -3 nanwei_cli.py nvscan                 # 列 helper 枚举到的屏 + EDID + 试读亮度
  py -3 nanwei_cli.py nvshort <mask> <0-100> # 发南微短帧亮度 (90 val chk), 抓包同款

后端默认 rawusb (USB 小板); 台式机切显卡通道: set DDCCI_BACKEND=gpu。
从机地址默认 0x5E (南微); 陪练标准 DDC/CI 机型: set DDCCI_SLAVE=0x6E。
每条命令都打印线上帧, 方便和逻辑分析仪对帧。
"""
import os
import sys

from ddcci_core import select_backend
import nanwei_core as nw
from backends import nv32_helper
from backends.raw_usb_backend import (ddc_frame, get_vcp_payload,
                                      parse_vcp_reply, set_vcp_payload)

PARAMS = {
    "brightness": ("亮度", nw.OP_BRIGHTNESS),
    "contrast":   ("对比度", nw.OP_CONTRAST),
    "colortemp":  ("色温", nw.OP_COLORTEMP),
    "gamma":      ("Gamma", nw.OP_GAMMA),
}


def _open():
    name = os.environ.get("DDCCI_BACKEND", "rawusb")
    be = select_backend(name)
    mons = be.enum_monitors()
    print("后端 = %s, 从机 = 0x%02X, 设备 = %s" % (name, be.address, mons[0].description))
    return be, nw.NanweiMonitor(be, mons[0].id)


def _get_one(dev, key):
    label, op = PARAMS[key]
    print("TX  %s" % nw.frame_hex(get_vcp_payload(op), dev.slave))
    r = dev.get(op)
    if r is None:
        print("%-4s (0x%02X): 无应答" % (label, op))
        return False
    print("%-4s (0x%02X): 当前 %d (0x%02X), 最大 %d" % (label, op, r[0], r[0], r[1]))
    return True


def nvscan(slave=None):
    """不建链, 直接问 32 位 helper: 有哪些屏、EDID 是什么、0x5E 读亮度通不通。

    英伟达机上"控制台连不上"时先跑这条: 它把"helper 起没起来 / 屏枚举到没有 /
    哪块屏应答 0x5E"三件事分开, 一眼看出卡在哪一层。
    """
    slave = slave or int(os.environ.get("DDCCI_SLAVE", "0"), 0) or 0x5E
    exe = nv32_helper.find_exe()
    print("helper = %s" % (exe or "(没找到 nvddc32.exe!)"))
    if not exe:
        return 1
    try:
        client = nv32_helper.Nv32Client(exe).start()
    except nv32_helper.Nv32Error as e:
        print("helper 起不来: %s" % e)
        print("  -> 这台机没装英伟达驱动 / 不是英伟达显卡, 请用 USB 小板 (rawusb)")
        return 1
    rc = 1
    try:
        print("枚举到 %d 块屏 (mask): %s"
              % (len(client.masks), " ".join("0x%X" % m for m in client.masks)))
        frame = ddc_frame(get_vcp_payload(nw.OP_BRIGHTNESS), slave=slave)
        for m in client.masks:
            name = nv32_helper.edid_name(client.edid(m)) or "(EDID 读不到)"
            try:
                raw = client.xfer(m, slave, slave | 1, [0x51] + frame, 16, 60)
            except nv32_helper.Nv32Error as e:
                print("  0x%-6X %-20s 收发失败: %s" % (m, name, e))
                continue
            r = parse_vcp_reply(raw, nw.OP_BRIGHTNESS, slave=slave)
            hexs = " ".join("%02X" % b for b in raw)
            if r is None:
                print("  0x%-6X %-20s 0x%02X 无应答  RX %s" % (m, name, slave, hexs))
            else:
                print("  0x%-6X %-20s 0x%02X 亮度=%d/%d  <== 就是这块"
                      % (m, name, slave, r[0], r[1]))
                rc = 0
        if rc:
            print("没有屏在 0x%02X 应答: 换地址试 (set DDCCI_SLAVE=0x6E), 或用 nvshort "
                  "发短帧看屏亮度是否变化" % slave)
    finally:
        client.close()
    return rc


def nvshort(mask, percent):
    """发南微短帧亮度 (0x5E: 90 val chk) —— 抓包里别人工具用的就是这条, 无回读, 看屏。"""
    exe = nv32_helper.find_exe()
    if not exe:
        print("没找到 nvddc32.exe")
        return 1
    val = max(0, min(100, int(percent, 0)))
    payload = [0x90, val]
    chk = 0x5E
    for b in payload:
        chk ^= b
    try:
        client = nv32_helper.Nv32Client(exe).start()
    except nv32_helper.Nv32Error as e:
        print("helper 起不来: %s" % e)
        return 1
    try:
        m = int(mask, 16)
        print("TX  5E %s" % " ".join("%02X" % b for b in payload + [chk]))
        client.write(m, 0x5E, payload + [chk])
        print("已发到 0x%X, 看屏幕亮度有没有变 (无回读)" % m)
        return 0
    except nv32_helper.Nv32Error as e:
        print("发送失败: %s" % e)
        return 1
    finally:
        client.close()


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1].lower()
    # 这两条不建链 (建链失败时正是要用它们查), 放在 _open 之前
    if cmd == "nvscan":
        return nvscan()
    if cmd == "nvshort":
        if len(argv) < 4:
            print("用法: nanwei_cli.py nvshort <maskHex> <0-100>")
            return 2
        return nvshort(argv[2], argv[3])
    try:
        be, dev = _open()
    except RuntimeError as e:
        print("建链失败: %s" % e)
        return 1
    try:
        if cmd == "check":
            print("--- 版本 ---")
            v = dev.versions()
            print("硬件版本: %s   软件版本: %s" % (v["hw"], v["sw"]))
            print("--- 参数 ---")
            ok = sum(_get_one(dev, k) for k in PARAMS)
            print("--- 结论: %d/%d 项应答 %s ---" % (
                ok, len(PARAMS),
                "· 链路 OK" if ok else "· 全无应答, 查从机地址(DDCCI_SLAVE)/接线/机型"))
            return 0 if ok else 1

        if cmd == "ver":
            v = dev.versions()
            print("硬件版本: %s   软件版本: %s" % (v["hw"], v["sw"]))
            return 0

        if cmd == "get":
            which = argv[2].lower() if len(argv) > 2 else "all"
            keys = PARAMS if which == "all" else {which: PARAMS[which]}
            rc = 0
            for k in keys:
                if not _get_one(dev, k):
                    rc = 1
            return rc

        if cmd == "set":
            label, op = PARAMS[argv[2].lower()]
            val = int(argv[3], 0)
            print("TX  %s" % nw.frame_hex(set_vcp_payload(op, val), dev.slave))
            dev.set(op, val)
            r = dev.get(op)
            print("写 %s=%d, 回读 = %s" % (label, val, "%d (0x%02X)" % (r[0], r[0]) if r else "无应答"))
            return 0 if (r and r[0] == (val & 0xFF)) else 1

        if cmd == "key":
            name = argv[2].lower()
            print("TX  %s" % nw.frame_hex(nw.key_payload(nw.KEYS[name]), dev.slave))
            dev.press_key(name)
            print("按键 %s 已发 (无回读, 看屏幕 OSD)" % name)
            return 0

        print("未知命令 %r" % cmd)
        print(__doc__)
        return 2
    finally:
        be.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
