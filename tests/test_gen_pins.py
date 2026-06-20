# -*- coding: utf-8 -*-
"""gen_pins 解析单测: 片段 -> 断言产出结构。"""
from tools import gen_pins as G

_EXAMPLE = """
#define _PIN_TESTA                 (1 & 0x07) // Page 10-0x20[2:0]
// 0 ~ 2 (0: P4D0i<I>, 1: P4D0o<PP>, 2: P4D0o<OD>)

#define _PIN_TESTB                 (0 & 0x07) // Page 10-0x21[2:0]
// 0 ~ 8 (0: P4D1i<I>, 2: P4D1o<OD>, 8: IICSCL2)

#define _PIN_TESTC                 (0 & 0x07) // Page 10-0x22[2:0]
// 0 ~ 1 (0: P5D0i<I>, 1: VCCK_OFF_EN)

#define _PIN_TESTD                 (0 & 0x07) // Page 10-0x23[2:0]
// 0 ~ 4 (0: P1D0i<I>, 1: reserved, 2: P1D0o<OD>, 3: AUX_P1,
//        4: AUX_N1)
"""

_DEMOD = """
#define _PIN_TESTA                 (2 & 0x07) // Page 10-0x20[2:0]
// 0 ~ 2 (0: P4D0i<I>, 1: P4D0o<PP>, 2: P4D0o<OD>)
"""

_MCU = """
extern volatile BYTE xdata MCU_FE00_PORT40_PIN_REG;
extern volatile BYTE xdata MCU_FE01_PORT41_PIN_REG;
"""


def test_parse_pinshare_fields():
    d = G.parse_pinshare(_EXAMPLE)
    a = d["TESTA"]
    assert a["default"] == 1
    assert a["share"] == {"page": 0x10, "offset": 0x20, "mask": 0x07, "shift": 0}
    assert a["funcs"][0] == {"val": 0, "name": "P4D0i", "kind": "gpio_in"}
    assert a["funcs"][1]["kind"] == "gpio_out_pp"
    assert a["funcs"][2]["kind"] == "gpio_out_od"


def test_parse_pinshare_skips_commented_define():
    # 注释掉的 #define 不能被当真脚解析 (固件头常有注释的备用 pinshare)
    text = """
// #define _PIN_GHOST              (3 & 0x07) // Page 10-0x99[2:0]
// 0 ~ 2 (0: GHOSTi<I>)
#define _PIN_REAL                  (1 & 0x07) // Page 10-0x10[2:0]
// 0 ~ 1 (0: P4D2i<I>, 1: P4D2o<PP>)
"""
    d = G.parse_pinshare(text)
    assert "GHOST" not in d
    assert "REAL" in d


def test_parse_pinshare_single_bit_field():
    # 单 bit [n] -> shift=n, mask=1<<n
    text = """
#define _PIN_SB                    (0 & 0x40) // Page 11-0x05[6]
// 0 ~ 1 (0: off, 1: on)
"""
    s = G.parse_pinshare(text)["SB"]["share"]
    assert s == {"page": 0x11, "offset": 0x05, "mask": 0x40, "shift": 6}


def test_parse_pinshare_sorts_funcs_by_val():
    # 注释里乱序列出, funcs 应按 val 升序
    text = """
#define _PIN_OO                    (0 & 0x07) // Page 10-0x30[2:0]
// (2: P4D9o<OD>, 0: P4D9i<I>, 1: P4D9o<PP>)
"""
    vals = [f["val"] for f in G.parse_pinshare(text)["OO"]["funcs"]]
    assert vals == [0, 1, 2]


def test_parse_pinshare_multiline_comment():
    d = G.parse_pinshare(_EXAMPLE)
    names = [f["name"] for f in d["TESTD"]["funcs"]]
    assert "AUX_N1" in names
    kinds = {f["val"]: f["kind"] for f in d["TESTD"]["funcs"]}
    assert kinds[1] == "reserved"
    assert kinds[3] == "periph"


def test_parse_mcu_map():
    m = G.parse_mcu(_MCU)
    assert m == {"PORT40": 0xFE00, "PORT41": 0xFE01}


def test_gpio_for_maps_port_pin():
    funcs = G.parse_pinshare(_EXAMPLE)["TESTA"]["funcs"]
    g = G.gpio_for(funcs, {"PORT40": 0xFE00})
    assert g == {"name": "P4D0", "data_page": 0xFE, "data_offset": 0x00,
                 "bit": G.GPIO_LEVEL_BIT}


def test_gpio_for_returns_none_when_unmapped():
    funcs = G.parse_pinshare(_EXAMPLE)["TESTD"]["funcs"]
    assert G.gpio_for(funcs, {"PORT40": 0xFE00}) is None


def test_classify_domain():
    d = G.parse_pinshare(_EXAMPLE)
    assert G.classify_domain(d["TESTB"]["funcs"]) == "I2C_DDC"
    assert G.classify_domain(d["TESTC"]["funcs"]) == "POWER_CTRL"
    assert G.classify_domain(d["TESTA"]["funcs"]) == "GPIO"


def test_classify_danger():
    d = G.parse_pinshare(_EXAMPLE)
    dng, reason = G.classify_danger("TESTC", d["TESTC"]["funcs"])
    assert dng is True and reason
    assert G.classify_danger("TESTA", d["TESTA"]["funcs"]) == (False, "")


def test_build_merges_default_from_demod():
    out = G.build(_EXAMPLE, _DEMOD, _MCU)
    assert out["domain_order"][0] == "GPIO"
    pins = {p["ball"]: p for p in out["pins"]}
    assert pins["TESTA"]["default"] == 2
    assert pins["TESTA"]["gpio"]["data_offset"] == 0x00
    assert pins["TESTC"]["danger"] is True
