# tests/test_vcp_codes.py
import pytest
from phytune import vcp_codes as vc


def test_opcodes_in_reserved_range():
    assert vc.VCP_ADDR_LATCH == 0xE5
    assert vc.VCP_POKE == 0xE6
    assert vc.VCP_OVERRIDE == 0xE7


def test_pack_addr_roundtrip():
    assert vc.pack_addr(0x7B, 0xA2) == 0x7BA2
    assert vc.unpack_addr(0x7BA2) == (0x7B, 0xA2)


def test_pack_addr_rejects_out_of_range():
    with pytest.raises(ValueError):
        vc.pack_addr(0x100, 0x00)
    with pytest.raises(ValueError):
        vc.pack_addr(0x71, -1)


def test_pack_poke_encodes_type_high_byte():
    assert vc.pack_poke(0x3F, type_=0) == 0x003F
    assert vc.pack_poke(0x3F, type_=1) == 0x013F


def test_pack_poke_rejects_bad():
    with pytest.raises(ValueError):
        vc.pack_poke(0x100)
    with pytest.raises(ValueError):
        vc.pack_poke(0x10, type_=2)


def test_pack_override_encodes_op_high_byte():
    assert vc.pack_override(vc.OVERRIDE_OP_PIN, 2) == 0x0002
    assert vc.pack_override(vc.OVERRIDE_OP_CLEAR, 1) == 0x0101
    assert vc.pack_override(vc.OVERRIDE_OP_CLEARALL) == 0x0200


def test_pack_override_rejects_bad():
    with pytest.raises(ValueError):
        vc.pack_override(9, 0)
    with pytest.raises(ValueError):
        vc.pack_override(vc.OVERRIDE_OP_PIN, 0x100)
