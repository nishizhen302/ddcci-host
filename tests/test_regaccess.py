from tests.fakes import FakeBackend


def test_fake_records_sets():
    be = FakeBackend()
    be.set_vcp(0, 0xE0, 0x7BA2)
    assert be.sets == [(0, 0xE0, 0x7BA2)]
