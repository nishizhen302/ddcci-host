# -*- coding: utf-8 -*-
# USB 小板直连 probe: 读背光 -> set 低/高/复原, 看屏幕变不变。验证固件 VCP 路。
import sys, time
from backends.raw_usb_backend import RawUsbBackend

be = RawUsbBackend()
mons = be.enum_monitors()
if not mons:
    sys.exit("没找到 USB 小板 (RTUsb)。检查小板是否插好、插在某个 DDC 口。")
idx = mons[0].id
print("目标:", mons[0].description)

r = be.get_vcp(idx, 0x10)
print("GET 背光 0x10 ->", r)

for v in (0, 100, 50):
    ok = be.set_vcp(idx, 0x10, v)
    print("SET 背光 -> %d : %s (看屏幕)" % (v, "OK" if ok else "失败"))
    time.sleep(1.2)

print("---- 再试电源 0xD6: 熄(4) 3秒 开(1) ----")
be.set_vcp(idx, 0xD6, 4); time.sleep(3); be.set_vcp(idx, 0xD6, 1)
print("done")
