"""fragment 信号子包入口。"""

from app.writing.signals.fragments import detect_fragment, normalize_fragment

__all__ = [
    "build_writing_signals",
    "detect_fragment",
    "normalize_fragment",
]


def build_writing_signals(*args, **kwargs):
    """延迟转发 assemble.build_writing_signals。
    
    参数:
        见 assemble。
    
    返回:
        writing_signals dict。"""
    from app.writing.signals.assemble import build_writing_signals as _fn

    return _fn(*args, **kwargs)
