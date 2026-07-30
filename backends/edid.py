# -*- coding: utf-8 -*-
"""EDID 小解析 —— 只为把通道名字写得像人话: "JRD UC1190_DVI (DDC/CI 0x5E)"。

各后端 (显卡直连 / 32 位桥 / USB 小板) 都要用, 所以放在这里而不是某个后端里。
"""


def edid_name(edid):
    """从 128 字节 EDID 取"厂商 型号"; 解析不出返回 None。"""
    if len(edid) < 128 or edid[0] != 0x00 or edid[1] != 0xFF:
        return None
    ident = (edid[8] << 8) | edid[9]
    mfr = "".join(chr(ord("A") + ((ident >> s) & 0x1F) - 1) for s in (10, 5, 0))
    model = ""
    for d in range(54, 109, 18):
        if edid[d:d + 4] == [0, 0, 0, 0xFC]:
            for c in edid[d + 5:d + 18]:
                if c in (0x0A, 0x00):
                    break
                model += chr(c)
            break
    name = ("%s %s" % (mfr, model.strip())).strip()
    return name or None
