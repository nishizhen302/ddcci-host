#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DDC/CI 上位机 CLI —— 通过 DDC/CI 控制 Realtek RL6432 显示器。

(实现已抽到 ddcci_core + backends/; 本文件是命令行薄壳。)

用法:
  py -3 ddcci.py list                 列出物理显示器
  py -3 ddcci.py caps [idx]           读 capabilities 字符串(看支持哪些 VCP)
  py -3 ddcci.py get  <vcp> [idx]     读 VCP 当前值/最大值   (vcp 可写 0x10 或 16)
  py -3 ddcci.py set  <vcp> <val>     写 VCP 值
  py -3 ddcci.py probe [idx]          链路自检: 读亮度 -> 调暗 -> 调亮 -> 复原
  py -3 ddcci.py gamma <n> [idx]      切 gamma (= set 0x72 n), 需固件支持后才生效
  (所有命令末尾可带显示器序号 idx, 默认 0; 用 list 看序号)
"""
import sys

from ddcci_core import select_backend

# ---- VCP 常量 (与固件 UserCommonDdcciDefine.h 对应) ----
VCP_BACKLIGHT = 0x10   # 固件映射到背光/亮度
VCP_CONTRAST  = 0x12
VCP_COLOR_PRESET = 0x14
VCP_GAMMA     = 0x72

GAMMA_NAMES = {0: "OFF", 1: "1.8", 2: "2.0", 3: "2.2", 4: "2.4"}


def _parse_code(s):
    return int(s, 16) if s.lower().startswith("0x") else int(s, 0) if not s.isdigit() else int(s)


def _need(be, idx):
    """枚举 + 范围校验, 复用原 CLI 文案。返回 Monitor 列表。"""
    mons = be.enum_monitors()
    if not mons:
        sys.exit("没有找到物理显示器。检查: 板子是否通过 HDMI/DP 接到本机显卡, 显卡驱动 DDC/CI 是否开启。")
    if idx < 0 or idx >= len(mons):
        sys.exit("显示器序号 %d 超范围 (共 %d 个), 用 list 查看。" % (idx, len(mons)))
    return mons


# ---------------- 子命令 ----------------

def cmd_list():
    with select_backend() as be:
        mons = be.enum_monitors()
        if not mons:
            print("(无) 没有可用物理显示器。")
            return
        for m in mons:
            print("[%d] %s" % (m.id, m.description))


def cmd_caps(idx):
    with select_backend() as be:
        _need(be, idx)
        caps = be.read_caps(idx)
        print(caps if caps else "(读不到 capabilities, 该显示器可能不支持或 DDC/CI 未开)")


def cmd_get(code, idx):
    with select_backend() as be:
        _need(be, idx)
        r = be.get_vcp(idx, code)
        if r is None:
            print("VCP 0x%02X: 读失败 (该 VCP 可能不被支持)" % code)
        else:
            print("VCP 0x%02X: current=%d  max=%d" % (code, r[0], r[1]))


def cmd_set(code, value, idx):
    with select_backend() as be:
        _need(be, idx)
        ok = be.set_vcp(idx, code, value)
        print("VCP 0x%02X <- %d : %s" % (code, value, "OK" if ok else "失败"))


def cmd_probe(idx):
    """链路自检: 用亮度 0x10 做 set/get 往返, 屏幕应可见亮度变化。"""
    import time
    with select_backend() as be:
        mons = _need(be, idx)
        print("目标显示器: %s" % mons[idx].description)
        r = be.get_vcp(idx, VCP_BACKLIGHT)
        if r is None:
            print("✗ 读亮度(0x10)失败 —— 链路没通, 或固件没响应该 VCP。")
            return
        cur, mx = r
        print("✓ 读到亮度: current=%d max=%d" % (cur, mx))
        for v in (max(0, cur - 30), min(mx, cur + 30), cur):
            be.set_vcp(idx, VCP_BACKLIGHT, v)
            print("  设亮度 -> %d (看屏幕应变化)" % v)
            time.sleep(1.0)
        print("✓ 链路打通: DDC/CI set/get 往返成功。平台就绪, 可以加 gamma 协议了。")


def cmd_gamma(n, idx):
    with select_backend() as be:
        _need(be, idx)
        ok = be.set_vcp(idx, VCP_GAMMA, n)
        name = GAMMA_NAMES.get(n, "?")
        print("gamma(VCP 0x72) <- %d (%s) : %s%s" % (
            n, name, "OK" if ok else "失败",
            "" if ok else "  (若固件还没接 0x72, 这里失败是正常的)"))
        if ok:
            r = be.get_vcp(idx, VCP_GAMMA)
            if r is not None:
                print("  读回确认: gamma = %d (%s)" % (r[0], GAMMA_NAMES.get(r[0], "?")))


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    cmd = a[0].lower()
    try:
        if cmd == "list":
            cmd_list()
        elif cmd == "caps":
            cmd_caps(int(a[1]) if len(a) > 1 else 0)
        elif cmd == "get":
            cmd_get(_parse_code(a[1]), int(a[2]) if len(a) > 2 else 0)
        elif cmd == "set":
            cmd_set(_parse_code(a[1]), int(a[2]), int(a[3]) if len(a) > 3 else 0)
        elif cmd == "probe":
            cmd_probe(int(a[1]) if len(a) > 1 else 0)
        elif cmd == "gamma":
            cmd_gamma(int(a[1]), int(a[2]) if len(a) > 2 else 0)
        else:
            print("未知命令 %r\n" % cmd)
            print(__doc__)
    except IndexError:
        print("参数不足。\n")
        print(__doc__)


if __name__ == "__main__":
    main()
