# -*- coding: utf-8 -*-
"""控制台桥接层的机型切换: 选哪个机型, 就按哪个机型的地址扫描、建哪种设备。"""
import pytest

pytest.importorskip("webview")
import app_nanwei
import nanwei_core as nw


class _Mon:
    def __init__(self, i):
        self.id = i
        self.description = "fake %d" % i


class _Be:
    opened = []

    def __init__(self, name, slave):
        self.name = name
        self.address = slave
        self.raw = []
        _Be.opened.append((name, slave))

    def enum_monitors(self):
        return [_Mon(0)]

    def get_vcp(self, mon_id, code):
        if code == nw.OP_GAMMA and self.address == 0x6E:
            return (4, 0x08)                    # 0x6E 上这台假装是 216pin
        return (1, 0xFF) if code in (nw.OP_BRIGHTNESS, nw.OP_SW_VERSION) else None

    def send_raw(self, mon_id, payload):
        self.raw.append(list(payload))
        return True

    def close(self):
        pass


@pytest.fixture
def settings(tmp_path):
    return str(tmp_path / "settings.json")


@pytest.fixture
def api(monkeypatch, settings):
    _Be.opened = []
    monkeypatch.setattr(app_nanwei, "select_backend",
                        lambda name, slave=0x5E, **kw: _Be(name, slave))
    return app_nanwei.Api(backend_name="rawusb", settings_path=settings)


def test_model_choice_survives_restart(api, settings):
    """localStorage 跨启动存不住 (随机端口 origin), 机型必须由后端记住。"""
    api.select_model("216")
    again = app_nanwei.Api(backend_name="rawusb", settings_path=settings)
    assert again.models()["current"] == "216"


def test_bad_settings_file_falls_back_to_default(settings):
    open(settings, "w", encoding="utf-8").write('{"model": "999"}')
    assert app_nanwei.Api(settings_path=settings).models()["current"] == "156"
    open(settings, "w", encoding="utf-8").write("not json")
    assert app_nanwei.Api(settings_path=settings).models()["current"] == "156"


def test_default_model_is_156_and_scans_both_addresses(api):
    assert api.models()["current"] == "156"
    api.discover_targets()
    assert {s for _, s in _Be.opened} == {0x5E, 0x6E}


def test_scan_tags_each_target_with_detected_model(api):
    targets = api.discover_targets()["targets"]
    by_addr = {t["address"]: t["model"] for t in targets if t["backend"] == "rawusb"}
    assert by_addr == {"0x5E": "156", "0x6E": "216"}


def test_connecting_a_target_switches_to_its_model(api):
    """选下拉框里的目标 = 切到它的机型; 回包带该机型的界面参数, 前端一次切完。"""
    targets = {t["id"]: t for t in api.discover_targets()["targets"]}
    r = api.connect_target(targets["rawusb:0x6E:0"])
    assert r["model"] == "216" and r["meta"]["features"]["hold"] is True
    assert isinstance(api._dev, nw.Monitor216)
    r = api.connect_target(targets["rawusb:0x5E:0"])
    assert r["model"] == "156" and r["meta"]["features"]["macros"] is True
    assert type(api._dev) is nw.NanweiMonitor


def test_select_216_meta_then_connect_216_target(api):
    meta = api.select_model("216")
    assert meta["ok"] and meta["model"] == "216"
    assert meta["features"] == {"macros": False, "hold": True}
    assert [o["value"] for o in meta["colortemp"]] == [o["value"] for o in nw.COLORTEMP_VALUES_216]
    targets = [t for t in api.discover_targets()["targets"] if t["model"] == "216"]
    r = api.connect_target(targets[0])
    assert r["ok"] and r["model"] == "216" and r["versions"] == {"hw": None, "sw": 1}
    assert isinstance(api._dev, nw.Monitor216)


def _connect_216(api):
    t = next(t for t in api.discover_targets()["targets"] if t["model"] == "216")
    return api.connect_target(t)


def test_216_rejects_156_macros(api):
    _connect_216(api)
    assert api.start_aging()["ok"] is False
    assert api.enter_factory()["ok"] is False


def test_216_gamma_set_logs_c0_frame(api):
    _connect_216(api)
    r = api.set_choice("gamma", 2)
    assert r["ok"] and r["tx"].startswith("6E 51 84 C0 91 01 00")


def test_unknown_model_is_error(api):
    assert api.select_model("300")["ok"] is False
    assert api.models()["current"] == "156"


def test_shutdown_releases_held_keys_on_216(api):
    _connect_216(api)
    be = api._be
    api.shutdown()
    assert be.raw[-1] == [0xC0, 0x96, 0xFF, 0x00]
