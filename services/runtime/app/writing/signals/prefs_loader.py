"""写作偏好结构。随内核打包，不再按仓库路径探测。"""

from __future__ import annotations

from types import ModuleType

from app.writing import writing_prefs as _prefs


def _module() -> ModuleType:
    """返回偏好模块。保留旧的 ``_module()`` 调用方式。"""
    return _prefs


def __getattr__(name: str):
    return getattr(_prefs, name)
