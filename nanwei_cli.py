#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""南微协议命令行 —— USB 小板链路自检 / 单条命令收发。

用法:
  py -3 nanwei_cli.py check                  # 链路自检: 读版本 + 四个参数各读一次
  py -3 nanwei_cli.py get all|brightness|contrast|colortemp|gamma
  py -3 nanwei_cli.py set brightness 50      # 值十进制或 0x 十六进制
  py -3 nanwei_cli.py key menu|right|left|exit
  py -3 nanwei_cli.py ver

后端默认 rawusb (USB 小板); 台式机切显卡通道: set DDCCI_BACKEND=gpu。
从机地址默认 0x5E (南微); 陪练标准 DDC/CI 机型: set DDCCI_SLAVE=0x6E。
每条命令都打印线上帧, 方便和逻辑分析仪对帧。
"""
import os
import sys

from ddcci_core import select_backend
import nanwei_core as nw
from backends.raw_usb_backend import get_vcp_payload, set_vcp_payload

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


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1].lower()
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
