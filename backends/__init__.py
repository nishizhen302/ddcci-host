"""可插拔通信后端。每个后端实现统一的 Backend 接口。"""
from .base import Backend, Monitor

__all__ = ["Backend", "Monitor"]
