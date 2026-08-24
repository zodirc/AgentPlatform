"""上下文压缩策略阈值（ADR-008 Phase A）。

English: Context compaction policy thresholds (ADR-008 Phase A).

``CompactionPolicy`` 描述模型窗口 token 上限、输出预留、以及 ContextEngine
在 fill 比例达到各档位时触发的 collapse / snip / autocompact 行为。
数值默认来自 ``settings``（fill 0.80 / 0.90 / 0.95，hot_zone 0.35），
也可通过 ``legacy_messages_budget`` 供单测注入紧预算。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompactionPolicy:
    """模型感知的上下文压缩阈值配置（不可变）。

    English: Immutable model-window-aware compaction thresholds.

    字段含义：
    - ``model_window_tokens``：模型上下文窗口总 token 预算
    - ``output_reserve_tokens``：预留给模型输出的 token（不参与 fill 计算分子）
    - ``fill_collapse`` / ``fill_snip`` / ``fill_autocompact``：达到该 fill 比例时
      依次尝试折叠工具历史、snip 最旧消息组、自动摘要压缩
    - ``hot_zone_ratio``：collapse 时保留的「热区」尾部占可用窗口的比例
    """

    model_window_tokens: int = 128_000
    output_reserve_tokens: int = 30_000
    fill_collapse: float = 0.80
    fill_snip: float = 0.90
    fill_autocompact: float = 0.95
    hot_zone_ratio: float = 0.35

    @classmethod
    def from_settings(cls) -> CompactionPolicy:
        """从运行时 ``settings`` 构建策略（窗口与 output reserve 联动缩放）。

        English: Build policy from deployment settings with scaled output reserve.

        返回:
            与当前部署配置一致的 ``CompactionPolicy``。
        """
        from app.model.generation import scaled_output_reserve_tokens
        from app.settings import settings

        window = int(settings.context_window_tokens)
        return cls(
            model_window_tokens=window,
            output_reserve_tokens=scaled_output_reserve_tokens(window),
            fill_collapse=settings.context_fill_collapse,
            fill_snip=settings.context_fill_snip,
            fill_autocompact=settings.context_fill_autocompact,
            hot_zone_ratio=settings.context_hot_zone_ratio,
        )

    def with_window(self, model_window_tokens: int) -> CompactionPolicy:
        """更换模型窗口并重算 output reserve（按 128K→30K 比例缩放）。

        English: Clone with a new window size and rescale output_reserve_tokens.

        参数:
            model_window_tokens: 新的上下文窗口 token 数。

        返回:
            窗口与 reserve 更新、其余 fill 阈值不变的副本。
        """
        from app.model.generation import scaled_output_reserve_tokens

        window = max(1, int(model_window_tokens))
        return CompactionPolicy(
            model_window_tokens=window,
            output_reserve_tokens=scaled_output_reserve_tokens(window),
            fill_collapse=self.fill_collapse,
            fill_snip=self.fill_snip,
            fill_autocompact=self.fill_autocompact,
            hot_zone_ratio=self.hot_zone_ratio,
        )

    @classmethod
    def legacy_messages_budget(cls, messages_budget: int) -> CompactionPolicy:
        """将旧单测 ``token_budget`` 参数映射为紧模型窗口策略。

        English: Map legacy test-only messages_budget to a tight-window policy.

        参数:
            messages_budget: 历史 API 仅限制 messages 部分的 token 预算。

        返回:
            窗口略大于 messages_budget、fill 阈值偏低的测试用策略。
        """
        return cls(
            model_window_tokens=messages_budget + 32,
            output_reserve_tokens=16,
            fill_collapse=0.5,
            fill_snip=0.6,
            fill_autocompact=0.7,
            hot_zone_ratio=0.35,
        )
