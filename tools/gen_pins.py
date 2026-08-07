# -*- coding: utf-8 -*-
"""管脚表 generator: 解析固件 PINSHARE×2 + McuCommon -> phytune/rl6432_pins.json。

换板/换 PCB 只需改输入路径重跑。纯文本解析, 不依赖固件能编译。
"""
import argparse
import json
import os
import re

# 电平在每脚独立 PIN_REG 内的 bit (RTD 惯例 bit0; Task 3 实机核实)
GPIO_LEVEL_BIT = 0

DOMAIN_ORDER = ["GPIO", "I2C_DDC", "AUX_DP", "LVDS_DISP", "PWM_BL",
                "FLASH_SPI", "POWER_CTRL", "TEST_DBG", "OTHER"]

# 域分类: 按序首个命中者胜 (names = 大写功能名串)
DOMAIN_RULES = [
    ("I2C_DDC", ("IIC", "DDC", "SCL", "SDA")),
    ("AUX_DP", ("AUX", "HPD", "HOTPLUG", "MHL")),
    ("PWM_BL", ("PWM", "BACKLIGHT", "DIMMING")),
    ("FLASH_SPI", ("FLASH", "SPI", "SF_")),
    ("POWER_CTRL", ("VCCK", "VCC", "POWER", "_EN", "RESET")),
    ("LVDS_DISP", ("LVDS", "PANEL", "TCON", "VSYNC", "HSYNC")),
    ("TEST_DBG", ("TEST", "UART", "DEBUG", "TDO", "TDI", "TCK")),
]

# 危险脚: 命中即标 danger (从严, 宁可多标); 可被 DANGER_OVERRIDE 强制
DANGER_RULES = [
    ("LVDS/显示", ("LVDS", "PANEL", "TCON")),
    ("电源/使能", ("VCCK", "VCC", "POWER", "_EN", "RESET")),
    ("Flash", ("FLASH", "SF_")),
    ("DDC 控制口", ("DDC",)),
]
DANGER_OVERRIDE = {}   # {ball: reason} 实机发现的额外危险脚手填

_PIN_RE = re.compile(
    r"#define\s+_PIN_(\w+)\s+\(\s*(\d+)\s*&\s*0x([0-9A-Fa-f]+)\s*\)"
    r"\s*//\s*Page\s*([0-9A-Fa-f]+)\s*-\s*0x([0-9A-Fa-f]+)\s*\[(\d+)(?::(\d+))?\]")
_FUNC_RE = re.compile(r"(\d+)\s*:\s*([^,()]+)")
_MCU_RE = re.compile(r"MCU_(FE[0-9A-Fa-f]{2})_PORT([0-9])([0-9])_PIN_REG")
_GPIO_NAME_RE = re.compile(r"^(P[0-9A-Fa-f]D[0-9])[io]?$", re.I)
_TAG_RE = re.compile(r"<([^>]+)>")


def _kind_and_name(raw):
    """功能名原文 -> (kind, 清理后的名)。"""
    raw = raw.strip()
    if raw.lower() == "reserved":
        return "reserved", "reserved"
    m = _TAG_RE.search(raw)
    tag = m.group(1).upper() if m else ""
    name = _TAG_RE.sub("", raw).strip()
    if tag == "I":
        return "gpio_in", name
    if tag == "PP":
        return "gpio_out_pp", name
    if tag == "OD":
        return "gpio_out_od", name
    up = name.upper()
    if any(k in up for k in ("IIC", "DDC", "SCL", "SDA")):
        return "i2c", name
    return "periph", name


def parse_pinshare(text):
    """-> {ball: {default, share{page,offset,mask,shift}, funcs[{val,name,kind}]}}。"""
    lines = text.splitlines()
    out = {}
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        # 跳过注释掉的 #define (固件头常有注释的备用 PCB pinshare, 不能当真脚解析)
        if not stripped.startswith("#define"):
            i += 1
            continue
        m = _PIN_RE.search(stripped)
        if not m:
            i += 1
            continue
        ball, dflt, maskhex, pg, off, hi, lo = m.groups()
        # 位域 [hi:lo] 或单 bit [n]; 用 min/max 兼容偶发反写 [lo:hi], 不至于负位移崩溃
        a = int(hi)
        b = int(lo) if lo is not None else a
        shift = min(a, b)
        # 掩码以固件实际写掩码 (& 0xNN, 已定位) 为准, 而非注释 [hi:lo] 位宽:
        # 本系 PINSHARE 对 DDC/I²C 脚注释误标 [2:0], 但字段实为 4bit(默认值 8 需 bit3),
        # 固件统一用 & 0x0F 写回; 若信注释会把 mux 值 8 读/写截成 0, DDC 脚切复用失效.
        mask = int(maskhex, 16)
        j = i + 1
        comment = []
        while j < len(lines) and lines[j].lstrip().startswith("//"):
            comment.append(lines[j].lstrip()[2:])
            j += 1
        funcs = []
        for fm in _FUNC_RE.finditer(" ".join(comment)):
            kind, name = _kind_and_name(fm.group(2))
            funcs.append({"val": int(fm.group(1)), "name": name, "kind": kind})
        funcs.sort(key=lambda f: f["val"])   # 按复用值排序, 使下拉/索引稳定
        out[ball] = {
            "default": int(dflt),
            "share": {"page": int(pg, 16), "offset": int(off, 16),
                      "mask": mask, "shift": shift},
            "funcs": funcs,
        }
        i = j
    return out


def parse_mcu(text):
    """-> {"PORT<y><z>": 0xFExx}。"""
    out = {}
    for m in _MCU_RE.finditer(text):
        out["PORT" + m.group(2) + m.group(3)] = int(m.group(1), 16)
    return out


def gpio_for(funcs, mcu_map):
    """从功能名里找 P<n>D<b> -> PORT<n><b> -> 数据寄存器映射; 找不到返回 None。"""
    for f in funcs:
        m = _GPIO_NAME_RE.match(f["name"])
        if not m:
            continue
        base = m.group(1).upper()
        key = "PORT" + base[1] + base[3]
        if key in mcu_map:
            addr = mcu_map[key]
            return {"name": base, "data_page": (addr >> 8) & 0xFF,
                    "data_offset": addr & 0xFF, "bit": GPIO_LEVEL_BIT}
    return None


def classify_domain(funcs):
    names = " ".join(f["name"].upper() for f in funcs)
    for dom, kws in DOMAIN_RULES:
        if any(k in names for k in kws):
            return dom
    if any(f["kind"].startswith("gpio") for f in funcs):
        return "GPIO"
    return "OTHER"


def classify_danger(ball, default_name):
    """按本板**默认功能**判危险(别拆正在干活的脚); 只看默认功能名, 不看备选。
    default_name = 该脚默认复用值对应的功能名。"""
    if ball in DANGER_OVERRIDE:
        return True, DANGER_OVERRIDE[ball]
    up = (default_name or "").upper()
    for reason, kws in DANGER_RULES:
        if any(k in up for k in kws):
            return True, reason + " (默认功能), 改动可能黑屏/断链路"
    return False, ""


def build(example_text, demod_text, mcu_text):
    ex = parse_pinshare(example_text)
    dm = parse_pinshare(demod_text)
    mcu = parse_mcu(mcu_text)
    pins = []
    for ball in sorted(ex):
        e = ex[ball]
        funcs = e["funcs"]
        default = dm[ball]["default"] if ball in dm else e["default"]
        default_name = next((f["name"] for f in funcs if f["val"] == default), "")
        danger, reason = classify_danger(ball, default_name)
        pins.append({
            "ball": ball, "share": e["share"], "default": default,
            "domain": classify_domain(funcs), "funcs": funcs,
            "gpio": gpio_for(funcs, mcu),
            "danger": danger, "danger_reason": reason,
        })
    return {"domain_order": DOMAIN_ORDER, "pins": pins}


_FW = r"C:\Users\61093\Desktop\monitor firmware\New STD Code II 1P SVN2860"
_DEF_EXAMPLE = _FW + r"\Pcb\RL6432\LQFP_216\RL6432_PCB_EXAMPLE_216_PIN_PINSHARE.h"
_DEF_DEMOD = _FW + r"\Pcb\RL6432\LQFP_216\RL6432_2785_A2_216PIN_1A2H1DP1DVI_LVDS_PINSHARE.h"
_DEF_MCU = _FW + r"\Kernel\Scaler\RL6432_Series_Scaler\Header\RL6432_Series_McuCommonInclude.h"
_DEF_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "phytune", "rl6432_pins.json")


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--example", default=_DEF_EXAMPLE)
    ap.add_argument("--demod", default=_DEF_DEMOD)
    ap.add_argument("--mcu", default=_DEF_MCU)
    ap.add_argument("--out", default=_DEF_OUT)
    a = ap.parse_args()
    for opt, val in (("example", a.example), ("demod", a.demod), ("mcu", a.mcu)):
        if not os.path.exists(val):
            ap.error("--%s 路径不存在: %r — 本机请显式传入正确路径" % (opt, val))
    data = build(_read(a.example), _read(a.demod), _read(a.mcu))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    n = len(data["pins"])
    ng = sum(1 for p in data["pins"] if p["gpio"])
    nd = sum(1 for p in data["pins"] if p["danger"])
    print("pins=%d  gpio_mapped=%d  danger=%d  -> %s" % (n, ng, nd, a.out))


if __name__ == "__main__":
    main()
