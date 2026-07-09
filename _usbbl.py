# -*- coding: utf-8 -*-
import sys
from backends.raw_usb_backend import RawUsbBackend
be = RawUsbBackend()
if not be.enum_monitors():
    sys.exit("no USB board on this PC")
if sys.argv[1] == "get":
    print("USB GET backlight 0x10 ->", be.get_vcp(0, 0x10))
else:
    v = int(sys.argv[2])
    ok = be.set_vcp(0, 0x10, v)
    print("USB SET backlight 0x10 <- %d : %s" % (v, ok))
    print("readback ->", be.get_vcp(0, 0x10))
