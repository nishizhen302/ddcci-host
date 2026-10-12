# -*- coding: utf-8 -*-
import sys
from backends.raw_usb_backend import (RawUsbBackend, board_read_packet,
                                       board_write_packet, ddc_frame, get_vcp_payload)
be = RawUsbBackend()
be.enum_monitors()

# 1) 裸读 EDID via 小板: slave 0xA0, offset 0 -> 应 00 FF FF FF FF FF FF 00
try:
    be._write_bytes(board_read_packet(16, slave=0xA0, sub=0x00))
    edid = be._read_bytes(18)
    print("EDID via board:", " ".join("%02X" % x for x in edid))
except Exception as e:
    print("EDID via board ERR:", e)

# 2) peek 0x103C 的原始回包: 先 SET 0xE5 锁地址, 再发 GET 0xE5 读原始
import time
be.set_vcp(0, 0xE5, 0x103C)
time.sleep(0.15)
be._i2c_write(ddc_frame(get_vcp_payload(0xE5)))
time.sleep(0.2)
raw = be._i2c_read(16)
print("peek raw reply:", " ".join("%02X" % x for x in raw))
