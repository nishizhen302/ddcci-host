# -*- coding: utf-8 -*-
r"""32 位 nvapi helper (`tools/nvddc32.exe`) 的客户端 —— 英伟达显卡上的原始 I²C 通道。

为什么要绕这一圈: 实机 (英伟达 + Win7, 2026-07-24 验证) 上 64 位 `nvapi64.dll` 的
I2CWrite/I2CRead 对任何 version、任何 handle 都回 -8 INVALID_HANDLE, 是死路; 只有
32 位 `nvapi.dll` 能通。控制台本体是 64 位 Python, 进程内没法加载 32 位 DLL, 于是把
nvapi 调用隔离进一个 32 位 helper 进程, 本模块负责定位它、常驻它、按行收发命令。

helper 协议 (每行一条命令, 每条回一行 `OK ...` / `ERR ...`, 全 ASCII):
    enum                                    -> OK 0x00000100 0x00000400
    edid <mask>                             -> OK <256 hex>
    w <mask> <addr> <hex 字节...>            -> OK
    r <mask> <addr> <n>                     -> OK <hex>
    x <mask> <waddr> <raddr> <n> <ms> <hex...> -> OK <hex>   (写+延时+读, 一次往返)

`x` 是给 GET VCP 用的: 一次 IPC 干完写-等-读, GUI 拖滑杆时少一半进程往返。
"""
import os
import subprocess
import sys
import threading

EXE_NAME = "nvddc32.exe"
_CREATE_NO_WINDOW = 0x08000000     # 子进程不弹黑框 (GUI 里尤其重要)


def find_exe():
    """定位 nvddc32.exe。顺序: 环境变量 > 冻结后的 exe 同目录/_MEIPASS > 源码树 tools/。"""
    override = os.environ.get("DDCCI_NVDDC32")
    if override:
        return override if os.path.isfile(override) else None
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
        mp = getattr(sys, "_MEIPASS", None)
        if mp:
            roots.append(mp)
            roots.append(os.path.join(mp, "tools"))
    here = os.path.dirname(os.path.abspath(__file__))
    roots.append(os.path.join(here, "..", "tools"))
    roots.append(os.path.join(here, ".."))
    for r in roots:
        p = os.path.join(r, EXE_NAME)
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


class Nv32Error(RuntimeError):
    """helper 不可用 / 回了 ERR。"""


class Nv32Client:
    """一个常驻 helper 进程。线程安全 (GUI 线程 + webview 回调可能并发)。

    构造只是记路径, 真正拉起进程在 `start()`; 拉不起来 (无 exe / 无英伟达 32 位驱动 /
    没枚举到 display) 抛 Nv32Error, 调用方据此判定"这台机没有英伟达通道"。
    """

    def __init__(self, exe=None):
        # exe 也可以是一个 argv 列表 (单测里拿 python 假 helper 顶上)
        self.exe = exe or find_exe()
        self._p = None
        self._lock = threading.Lock()
        self.masks = []

    # ---- 进程生命周期 ----
    def start(self):
        if self._p is not None:
            return self
        if not self.exe:
            raise Nv32Error("找不到 %s (英伟达通道 helper)" % EXE_NAME)
        argv = list(self.exe) if isinstance(self.exe, (list, tuple)) else [self.exe]
        try:
            self._p = subprocess.Popen(
                argv + ["serve"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="ascii",
                errors="replace", bufsize=1, creationflags=_CREATE_NO_WINDOW)
        except OSError as e:
            raise Nv32Error("启动 %s 失败: %s" % (EXE_NAME, e))
        try:
            self.masks = self._parse_masks(self.command("enum"))
        except Nv32Error:
            self.close()
            raise
        if not self.masks:
            self.close()
            raise Nv32Error("helper 没枚举到英伟达 display")
        return self

    def close(self):
        p, self._p = self._p, None
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.write("quit\n")
                p.stdin.flush()
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        finally:
            for s in (p.stdin, p.stdout):
                try:
                    if s:
                        s.close()
                except Exception:
                    pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()
        return False

    # ---- 收发 ----
    def command(self, line):
        """发一行命令, 返回 `OK` 后面的负载 (可能是空串)。helper 回 ERR / 进程已死则抛。"""
        with self._lock:
            p = self._p
            if p is None or p.poll() is not None:
                raise Nv32Error("helper 进程已退出")
            try:
                p.stdin.write(line + "\n")
                p.stdin.flush()
                resp = p.stdout.readline()
            except (OSError, ValueError) as e:
                raise Nv32Error("helper 通信失败: %s" % e)
        if not resp:
            raise Nv32Error("helper 无回应 (进程崩了?)")
        resp = resp.strip()
        if not resp.startswith("OK"):
            raise Nv32Error(resp or "helper 回了空行")
        return resp[2:].strip()

    @staticmethod
    def _parse_masks(payload):
        out = []
        for tok in payload.split():
            try:
                out.append(int(tok, 16))
            except ValueError:
                pass
        return out

    # ---- I²C 原语 (mask = 目标屏的 displayMask) ----
    def write(self, mask, addr, data):
        self.command("w 0x%X 0x%02X %s"
                     % (mask, addr, " ".join("%02X" % (b & 0xFF) for b in data)))
        return True

    def read(self, mask, addr, n):
        return _unhex(self.command("r 0x%X 0x%02X %d" % (mask, addr, n)))

    def xfer(self, mask, waddr, raddr, data, n, delay_ms):
        """写 data 到 waddr, 等 delay_ms, 再从 raddr 读 n 字节。"""
        return _unhex(self.command(
            "x 0x%X 0x%02X 0x%02X %d %d %s"
            % (mask, waddr, raddr, n, delay_ms,
               " ".join("%02X" % (b & 0xFF) for b in data))))

    def edid(self, mask):
        """读 128 字节 EDID; 读不到返回 []。"""
        try:
            return _unhex(self.command("edid 0x%X" % mask))
        except Nv32Error:
            return []


def _unhex(s):
    s = s.strip()
    return [int(s[i:i + 2], 16) for i in range(0, len(s) - 1, 2)]


# ---- EDID 小解析 (只为把通道名字写得像人话: "DEL U2412M (0x400)") ----

def edid_name(edid):
    """从 128 字节 EDID 取 "厂商 型号"; 解析不出返回 None。"""
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
