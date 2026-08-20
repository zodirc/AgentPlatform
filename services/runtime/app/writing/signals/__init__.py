"""Writing fragment signals: account prefs, scoring, tool handlers."""

from app.writing.signals.fragments import detect_fragment, normalize_fragment

__all__ = [
    "build_writing_signals",
    "detect_fragment",
    "normalize_fragment",
]


def build_writing_signals(*args, **kwargs):
    from app.writing.signals.assemble import build_writing_signals as _fn

    return _fn(*args, **kwargs)
