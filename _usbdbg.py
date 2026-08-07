# -*- coding: utf-8 -*-
# RK3576 DDC 波形诊断: 用 USB 小板 peek 固件 0xFExx 诊断缓冲
#   python _usbdbg.py reset   # 清零诊断缓冲(RK3576发命令前先跑这个)
#   python _usbdbg.py dump    # 读出诊断(RK3576发完命令后跑)
# 关键看 "ChanStart per ch": USB小板(D1)和RK3576(D2)走不同通道, RK3576那通道的值=真实START次数
import sys
from backends.raw_usb_backend import RawUsbBackend

DBG = 0xE5   # peek 地址锁存 opcode

be = RawUsbBackend()
if not be.enum_monitors():
    sys.exit("no USB board on this PC")

def peek(addr):
    be.set_vcp(0, DBG, addr)
    r = be.get_vcp(0, DBG)
    return (r[0] if r else None)

def b(x):
    return "--" if x is None else ("%02X" % x)

cmd = sys.argv[1] if len(sys.argv) > 1 else "dump"

if cmd == "reset":
    print("reset ->", b(peek(0xFEFF)))
    sys.exit(0)

print("StartCnt=%s DataCnt=%s LogIdx=%s" % (b(peek(0xFE00)), b(peek(0xFE01)), b(peek(0xFE02))))
cs = [peek(0xFE40 + i) for i in range(8)]
cd = [peek(0xFE50 + i) for i in range(8)]
print("ChanStart per ch:", " ".join(b(x) for x in cs))
print("ChanData  per ch:", " ".join(b(x) for x in cd))
log = [peek(0xFE10 + i) for i in range(24)]
print("Log raw:", " ".join(b(x) for x in log))
print("--- decoded events (START=新事务首字节, data=后续字节) ---")
for i in range(0, 24, 2):
    tag, val = log[i], log[i + 1]
    if tag is None:
        break
    kind = "START" if (tag & 0x80) else "data "
    print("  %s ch%d byte=%s" % (kind, tag & 0x07, b(val)))
