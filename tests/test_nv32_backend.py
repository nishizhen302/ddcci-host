# -*- coding: utf-8 -*-
"""32 位 nvapi helper 通道的离线单测 —— 用 Python 假 helper 顶替 nvddc32.exe。

真 exe 只有在英伟达机上才跑得起来 (加载 32 位 nvapi.dll), 但行协议、组帧、
后端接线这些都能在开发机上验完。
"""
import ctypes
import os
import sys

import pytest

from backends import gpu_i2c_backend as G
from backends import nv32_helper as H
from backends.raw_usb_backend import ddc_frame, get_vcp_payload

FAKE = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "fake_nvddc32.py")]


@pytest.fixture
def client():
    c = H.Nv32Client(exe=FAKE).start()
    yield c
    c.close()


def test_serve_argv_carries_parent_pid(monkeypatch):
    """helper 必须收到 `serve <我们的 pid>`: 它靠这个在我们崩掉后自杀。

    2026-07-30 回归: 只靠 stdin EOF 时, helper 卡在 nvapi 调用里收不到 EOF,
    任务管理器里攒下一堆 nvddc32.exe。
    """
    seen = {}
    real_popen = H.subprocess.Popen

    def spy(argv, **kw):
        seen["argv"] = list(argv)
        return real_popen(argv, **kw)

    monkeypatch.setattr(H.subprocess, "Popen", spy)
    c = H.Nv32Client(exe=FAKE).start()
    try:
        assert seen["argv"][-2] == "serve"
        assert seen["argv"][-1] == str(os.getpid())
    finally:
        c.close()


def test_client_close_reaps_process(client):
    """close() 之后子进程必须真的没了 (别指望 GC)。"""
    p = client._p
    client.close()
    assert p.poll() is not None
    assert client._p is None


# ---- 纯函数 ----

def test_unhex_and_edid_name():
    assert H._unhex(" 0A FF ".replace(" ", "")) == [0x0A, 0xFF]
    assert H.edid_name([]) is None
    edid = [0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x10, 0xAC] + [0] * 118
    for i, c in enumerate(b"\x00\x00\x00\xfc\x00U2412\n"):
        edid[54 + i] = c
    assert H.edid_name(edid) == "DEL U2412"


def test_find_exe_env_override(tmp_path, monkeypatch):
    p = tmp_path / "nvddc32.exe"
    p.write_bytes(b"")
    monkeypatch.setenv("DDCCI_NVDDC32", str(p))
    assert H.find_exe() == str(p)
    monkeypatch.setenv("DDCCI_NVDDC32", str(tmp_path / "nope.exe"))
    assert H.find_exe() is None


def test_shipped_exe_present():
    """交付物里必须有 helper —— 少了它英伟达机就只剩死路一条。"""
    exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools",
                       "nvddc32.exe")
    assert os.path.isfile(exe)
    with open(exe, "rb") as f:
        blob = f.read(0x200)
    off = int.from_bytes(blob[0x3C:0x40], "little")
    machine = int.from_bytes(blob[off + 4:off + 6], "little")
    assert machine == 0x14C, "helper 必须是 32 位 (0x14C), 64 位的 nvapi 走不通"


# ---- 客户端 / 进程 ----

def test_client_enum_and_edid(client):
    assert client.masks == [0x100, 0x400]
    assert H.edid_name(client.edid(0x400)) == "DEL U2412"


def test_client_error_on_bad_command(client):
    with pytest.raises(H.Nv32Error):
        client.command("nosuchcmd")


def test_client_dead_process_raises(client):
    client.close()
    with pytest.raises(H.Nv32Error):
        client.command("enum")


def test_client_missing_exe():
    with pytest.raises(H.Nv32Error):
        H.Nv32Client(exe=None if H.find_exe() is None else "").start()


# ---- 通道组帧 ----

def test_nv32_channel_write_prefixes_source_addr(client):
    sent = []
    client.command = lambda line: sent.append(line) or "OK"
    ch = G._Nv32Channel(client, 0x400)
    frame = ddc_frame(get_vcp_payload(0x10))
    assert ch.i2c_write(frame)
    # 线上: 从机 0x5E, 数据 = 源地址 0x51 + ddc 帧 (0x51 不作寄存器)
    assert sent[0] == "w 0x400 0x5E " + " ".join("%02X" % b for b in [0x51] + frame)


def test_nv32_channel_read_uses_read_address(client):
    sent = []
    client.command = lambda line: sent.append(line) or "5E88"   # command 已剥掉 OK
    ch = G._Nv32Channel(client, 0x400)
    assert ch.i2c_read(2) == [0x5E, 0x88]
    assert sent[0] == "r 0x400 0x5F 2"


def test_nv32_channel_xfer_roundtrip(client):
    ch = G._Nv32Channel(client, 0x400)
    got = ch.i2c_xfer(ddc_frame(get_vcp_payload(0x10)), 16, 60)
    assert got[:5] == [0x5E, 0x88, 0x02, 0x00, 0x10]


def test_nv32_channel_survives_helper_error(client):
    ch = G._Nv32Channel(client, 0x400)
    client.close()
    assert ch.i2c_write([0x84]) is False      # 不抛异常, 探测据此淘汰该通道
    assert ch.i2c_read(4) == []
    assert ch.i2c_xfer([0x84], 4, 0) == []


# ---- 后端接线 ----

def test_backend_uses_helper_channels(monkeypatch):
    """gpu 后端在只剩 nv32 的机器上, 应该经 helper 探到南微屏并能读写。"""
    monkeypatch.setenv("DDCCI_GPU_CHANNELS", "nv32")
    monkeypatch.setattr(H, "find_exe", lambda: FAKE)
    be = G.GpuI2CBackend(read_settle=0.01, set_settle=0)
    try:
        mons = be.enum_monitors()
        assert len(mons) == 1                     # 0x100 那块不应答 0x5E, 被淘汰
        # UI 文案 = "屏名 (DDC/CI 0x5E)", 不再带 mask/桥类型 (2026-07-30 用户要求)
        assert mons[0].description == "DEL U2412 (DDC/CI 0x5E)"
        assert "0x400" in be._chans[0].desc       # mask 细节仍留在 desc, 供日志排障
        assert be.get_vcp(0, 0x10) == (0x32, 0x64)
        assert be.set_vcp(0, 0x10, 0x40)
        assert be.get_vcp(0, 0x10) == (0x40, 0x64)
    finally:
        be.close()


def test_backend_close_kills_helper(monkeypatch):
    monkeypatch.setenv("DDCCI_GPU_CHANNELS", "nv32")
    monkeypatch.setattr(H, "find_exe", lambda: FAKE)
    be = G.GpuI2CBackend(read_settle=0.01, set_settle=0)
    proc = be._nv32._p
    be.close()
    assert proc.poll() is not None
    assert be._nv32 is None


def test_backend_no_channel_raises_and_cleans_up(monkeypatch):
    monkeypatch.setenv("DDCCI_GPU_CHANNELS", "nv32")
    monkeypatch.setattr(H, "find_exe", lambda: None)
    with pytest.raises(RuntimeError):
        G.GpuI2CBackend(read_settle=0.01)


# ---- 64 位直连通道: 抓包实证的字段形态 ----

def test_nv64_channel_field_shape():
    """0x51 并进 data、regAddrSize=0、handle 用第一屏 mask —— 改一处真机就不通。"""
    seen = {}

    def fake_write(handle, info_ptr):
        info = ctypes.cast(info_ptr, ctypes.POINTER(G._NvI2cInfoV1)).contents
        seen["handle"] = handle
        seen["mask"] = info.displayMask
        seen["addr"] = info.i2cDevAddress
        seen["reg_size"] = info.regAddrSize
        seen["reg_null"] = not bool(info.pbI2cRegAddress)
        seen["speed"] = info.i2cSpeed
        seen["data"] = [info.pbData[i] for i in range(info.cbSize)]
        return 0

    ch = G._NvChannel({"I2CWrite": fake_write}, ctypes.c_void_p(0x100), 0x400, 0)
    frame = ddc_frame(get_vcp_payload(0x10))
    assert ch.i2c_write(frame)
    assert seen["handle"].value == 0x100
    assert seen["mask"] == 0x400
    assert seen["addr"] == 0x5E
    assert seen["reg_size"] == 0 and seen["reg_null"]
    assert seen["speed"] == 0x0A
    assert seen["data"] == [0x51] + frame
