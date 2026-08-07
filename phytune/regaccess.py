# -*- coding: utf-8 -*-
"""具名寄存器访问: 把 peek/poke 翻译成调试 VCP 序列, 跑在任意 Backend 上。"""
from phytune import vcp_codes as vc


class RegAccess:
    """绑定一个 backend + 显示器号, 提供 peek/poke。"""

    def __init__(self, backend, mon_id):
        self._be = backend
        self._mon = int(mon_id)

    def peek(self, page, offset):
        """读 page/offset 处寄存器低字节; 任一步失败返回 None。"""
        if not self._be.set_vcp(self._mon, vc.VCP_ADDR_LATCH,
                                vc.pack_addr(page, offset)):
            return None
        r = self._be.get_vcp(self._mon, vc.VCP_ADDR_LATCH)
        if r is None:
            return None
        return r[0] & 0xFF

    def poke(self, page, offset, data, type_=0):
        """写 data 到 page/offset; 失败返回 False。"""
        if not self._be.set_vcp(self._mon, vc.VCP_ADDR_LATCH,
                                vc.pack_addr(page, offset)):
            return False
        return self._be.set_vcp(self._mon, vc.VCP_POKE,
                                vc.pack_poke(data, type_))

    def read_scdc(self, page, scdc_offset):
        """SCDC 间接读: 同页 0x39 写 SCDC 偏移选择, 再读 0x3A 数据窗。
        纯 poke/peek 直寄存器即可, 无需改固件。任一步失败返回 None。"""
        if not self.poke(page, 0x39, scdc_offset):
            return None
        return self.peek(page, 0x3A)

    def override_pin(self, page, offset, slot):
        """[P1] 钉住 page/offset 当前值到 override 槽 slot(重锁后固件自动盖回)。
        先锁存地址, 再发 PIN; 固件按锁存地址读现值存槽。失败返回 False。"""
        if not self._be.set_vcp(self._mon, vc.VCP_ADDR_LATCH,
                                vc.pack_addr(page, offset)):
            return False
        return self._be.set_vcp(self._mon, vc.VCP_OVERRIDE,
                                vc.pack_override(vc.OVERRIDE_OP_PIN, slot))

    def override_clear(self, slot):
        """[P1] 清除 override 槽 slot。失败返回 False。"""
        return self._be.set_vcp(self._mon, vc.VCP_OVERRIDE,
                                vc.pack_override(vc.OVERRIDE_OP_CLEAR, slot))

    def override_clearall(self):
        """[P1] 清空整张 override 表。失败返回 False。"""
        return self._be.set_vcp(self._mon, vc.VCP_OVERRIDE,
                                vc.pack_override(vc.OVERRIDE_OP_CLEARALL, 0))
