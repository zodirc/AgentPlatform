"""写作工具的说明与参数。与服务器 ``build_registry()`` 的同名工具保持一致。"""

from __future__ import annotations

import json

from app.tools.writing_specs_a import RAW as _RAW_A
from app.tools.writing_specs_b import RAW as _RAW_B

SPECS: dict[str, dict] = {**json.loads(_RAW_A), **json.loads(_RAW_B)}
