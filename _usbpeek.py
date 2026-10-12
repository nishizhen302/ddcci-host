# -*- coding: utf-8 -*-
# USB 小板 peek/poke 自检: 读已知寄存器, 看 DDC/CI 引擎+handler 到底通不通
import sys
from backends.raw_usb_backend import RawUsbBackend

be = RawUsbBackend()
mons = be.enum_monitors()
if not mons:
    sys.exit("no USB board")
idx = mons[0].id
print("target:", mons[0].description.encode("ascii","replace").decode())

def peek(addr):
    be.set_vcp(idx, 0xE5, addr)   # lock page<<8|offset
    r = be.get_vcp(idx, 0xE5)     # read back value
    return r

for addr in (0x103C, 0x103D, 0x0000, 0x0001, 0xFF23):
    r = peek(addr)
    print("peek 0x%04X -> %r" % (addr, r))

# poke test: write 0x55 to a scratch then read (use 0xFF26? no). just report peeks above.
