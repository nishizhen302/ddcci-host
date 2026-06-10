# -*- coding: utf-8 -*-
"""Backend 抽象 —— DDC/CI 通信通道的统一接口。

换通信通道 = 换一个 Backend 实现，上层 (ddcci_core / app / ui) 不变。
- Backend A = dxva2 (Windows 标准 DDC/CI, 地址固定 0x6E, 走独显)   ← 雏形
- Backend B = 硬件调试器 / 低层 I2C (自定义地址 0x5E 等)            ← 未来, 接口预留

显示器以不透明的整数 mon_id 标识 (= 枚举序号)，上层不碰 ctypes 句柄。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Monitor:
    """一台物理显示器。id = 枚举序号(不透明标识), description = 系统描述。"""
    id: int
    description: str


class Backend(ABC):
    """DDC/CI 后端抽象。子类实现四件套 + close。"""

    name = "base"        # 后端标识
    address = None       # I2C 地址 (dxva2 固定 0x6E; 低层后端可自定义)

    @abstractmethod
    def enum_monitors(self) -> list:
        """枚举物理显示器，返回 [Monitor, ...]，按枚举顺序。会刷新内部句柄表。"""
        raise NotImplementedError

    @abstractmethod
    def get_vcp(self, mon_id: int, code: int):
        """读 VCP。返回 (current, maximum)；读不到返回 None。"""
        raise NotImplementedError

    @abstractmethod
    def set_vcp(self, mon_id: int, code: int, value: int) -> bool:
        """写 VCP。成功返回 True。"""
        raise NotImplementedError

    @abstractmethod
    def read_caps(self, mon_id: int):
        """读 capabilities 字符串；读不到返回 None。"""
        raise NotImplementedError

    def close(self):
        """释放资源 (句柄等)。默认空实现。"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
