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
