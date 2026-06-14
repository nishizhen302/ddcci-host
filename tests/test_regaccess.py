from tests.fakes import FakeBackend
from phytune.regaccess import RegAccess
from phytune import vcp_codes as vc


def test_peek_latches_then_reads_low_byte():
    be = FakeBackend(get_returns={(0, vc.VCP_ADDR_LATCH): (0x3F, 0xFF)})
    ra = RegAccess(be, mon_id=0)
    val = ra.peek(0x71, 0xEC)
    assert be.sets == [(0, vc.VCP_ADDR_LATCH, 0x71EC)]
    assert val == 0x3F


def test_peek_returns_none_when_latch_fails():
    be = FakeBackend()
    be.set_result = False
    ra = RegAccess(be, mon_id=0)
    assert ra.peek(0x71, 0xEC) is None


def test_peek_returns_none_when_get_fails():
    be = FakeBackend(get_returns={})
    ra = RegAccess(be, mon_id=0)
    assert ra.peek(0x71, 0xEC) is None


def test_poke_latches_then_writes():
    be = FakeBackend()
    ra = RegAccess(be, mon_id=0)
    ok = ra.poke(0x7B, 0xA2, 0x8C)
    assert ok is True
    assert be.sets == [
        (0, vc.VCP_ADDR_LATCH, 0x7BA2),
        (0, vc.VCP_POKE, 0x008C),
    ]


def test_poke_dataport_type_sets_high_byte():
    be = FakeBackend()
    ra = RegAccess(be, mon_id=0)
    ra.poke(0x71, 0xC9, 0x12, type_=1)
    assert be.sets[-1] == (0, vc.VCP_POKE, 0x0112)


def test_poke_false_when_latch_fails():
    be = FakeBackend()
    be.set_result = False
    ra = RegAccess(be, mon_id=0)
    assert ra.poke(0x7B, 0xA2, 0x8C) is False
