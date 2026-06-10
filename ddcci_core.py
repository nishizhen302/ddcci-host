# -*- coding: utf-8 -*-
"""DDC/CI 语义核心 —— 选定后端, 提供统一 API。无 CLI / 无界面, 可独立单测。

上层 (app.py / CLI) 拿一个 Backend 实例, 经此模块的语义函数操作。
本模块只懂 DDC/CI 语义 (VCP / caps), 不懂界面, 也不绑死某条物理通道。
"""
import re

from backends.base import Backend, Monitor
from backends.dxva2_backend import Dxva2Backend

# 后端注册表。Backend B (硬件调试器/低层 I2C) 落地后在此登记即可。
_BACKENDS = {
    "dxva2": Dxva2Backend,
}


def available_backends():
    """可用后端名列表。"""
    return list(_BACKENDS)


def select_backend(name="dxva2") -> Backend:
    """按名取后端实例。未知名抛 ValueError。"""
    try:
        return _BACKENDS[name]()
    except KeyError:
        raise ValueError("未知后端 %r, 可选: %s" % (name, ", ".join(_BACKENDS)))


def parse_caps(caps_str):
    """解析 capabilities 串。

    返回 {raw, model, type, vcp_codes, vcp_values}。
    - vcp_codes  = vcp(...) 顶层列出的 VCP code 集合 (int)。
    - vcp_values = {code: [允许值, ...]}，即嵌套括号内的离散允许值
                   (如 14(01 02 04 ...) -> {0x14:[1,2,4,...]})；
                   连续值 VCP (如 10 亮度) 无括号, 值列表为空。
    """
    result = {"raw": caps_str or "", "model": None, "type": None,
              "vcp_codes": set(), "vcp_values": {}}
    if not caps_str:
        return result

    m = re.search(r"model\(([^)]*)\)", caps_str)
    if m:
        result["model"] = m.group(1).strip()
    t = re.search(r"type\(([^)]*)\)", caps_str)
    if t:
        result["type"] = t.group(1).strip()

    # 扫 vcp( ... ) 段:
    #   depth==1 的 token = VCP code; 其后紧跟的 (...) 内 (depth==2) = 该 code 的允许值。
    i = caps_str.find("vcp(")
    if i >= 0:
        state = {"depth": 1, "cur": "", "last": None}

        def flush():
            cur = state["cur"]
            state["cur"] = ""
            if not cur:
                return
            try:
                val = int(cur, 16)
            except ValueError:
                return
            if state["depth"] == 1:
                result["vcp_codes"].add(val)
                result["vcp_values"].setdefault(val, [])
                state["last"] = val
            elif state["depth"] == 2 and state["last"] is not None:
                result["vcp_values"][state["last"]].append(val)

        for c in caps_str[i + 4:]:
            if c == "(":
                flush()              # depth1: cur 是 code, flush 后设 last
                state["depth"] += 1
            elif c == ")":
                flush()              # flush 当前层末 token (无尾随空格的情况)
                state["depth"] -= 1
                if state["depth"] == 0:
                    break
            elif c.isspace():
                flush()
            else:
                state["cur"] += c

    return result


def pick_default_monitor(backend, prefer_model="RTK"):
    """枚举显示器, 优先认 model 含 prefer_model 的那块板 (RL6432 板 caps = model(RTK))。

    返回 mon_id; 没有显示器返回 None。注意: 物理序号会随接线变, 靠 caps 的 model 认更稳。
    """
    mons = backend.enum_monitors()
    if not mons:
        return None
    for m in mons:
        info = parse_caps(backend.read_caps(m.id))
        if info["model"] and prefer_model.upper() in info["model"].upper():
            return m.id
    return mons[0].id
