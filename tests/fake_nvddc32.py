# -*- coding: utf-8 -*-
"""假的 nvddc32 helper —— 用 Python 复刻 tools/nvddc32.c 的行协议, 供单测顶替真 exe。

模拟一台南微屏 (mask 0x400, 亮度 0x32) + 一块普通屏 (mask 0x100, 不应答 0x5E)。
只实现 serve 模式里测试用得到的命令。
"""
import sys

MASKS = [0x100, 0x400]
NANWEI = 0x400
_STATE = {"brightness": 0x32}

# 一段能被 nv32_helper.edid_name 解出 "DEL U2412" 的最小 EDID
_EDID = [0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x10, 0xAC] + [0] * 118
for _i, _c in enumerate(b"\x00\x00\x00\xfc\x00U2412\n"):
    _EDID[54 + _i] = _c


def _reply(cur, mx=0x64, code=0x10):
    frame = [0x5E, 0x88, 0x02, 0x00, code, 0x00, (mx >> 8) & 0xFF, mx & 0xFF,
             (cur >> 8) & 0xFF, cur & 0xFF]
    chk = 0x50
    for b in frame:
        chk ^= b
    return frame + [chk & 0xFF]


def _hex(data):
    return "".join("%02X" % b for b in data)


def _handle(argv):
    cmd = argv[0].lower()
    if cmd == "enum":
        return "OK " + " ".join("0x%08X" % m for m in MASKS)
    if cmd == "edid" and len(argv) >= 2:
        return "OK " + _hex(_EDID)
    if cmd == "w" and len(argv) >= 4:
        mask = int(argv[1], 16)
        data = [int(x, 16) for x in argv[3:]]
        # SET VCP 亮度: 51 84 03 10 hi lo chk
        if mask == NANWEI and data[1:4] == [0x84, 0x03, 0x10]:
            _STATE["brightness"] = data[5]
        return "OK"
    if cmd == "r" and len(argv) >= 4:
        mask, n = int(argv[1], 16), int(argv[3])
        if mask != NANWEI:
            return "OK " + _hex([0] * n)
        return "OK " + _hex((_reply(_STATE["brightness"]) + [0] * n)[:n])
    if cmd == "x" and len(argv) >= 7:
        mask, n = int(argv[1], 16), int(argv[4])
        if mask != NANWEI:
            return "OK " + _hex([0] * n)
        return "OK " + _hex((_reply(_STATE["brightness"]) + [0] * n)[:n])
    return "ERR bad command"


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "serve":
        print("ERR only serve implemented")
        return 2
    for line in sys.stdin:
        argv = line.split()
        if not argv:
            continue
        if argv[0].lower() in ("quit", "exit"):
            break
        sys.stdout.write(_handle(argv) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
