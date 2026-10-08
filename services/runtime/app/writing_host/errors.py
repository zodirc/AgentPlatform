"""宿主协议错误。每类带一条可直接展示的中文说明。"""

from __future__ import annotations


class HostError(Exception):
    code = "internal"
    user_message = "写作内核遇到内部错误，请稍后重试。"

    def __init__(self, user_message: str | None = None, *, detail: str = "") -> None:
        self.user_message = user_message or type(self).user_message
        self.detail = detail
        super().__init__(self.user_message)


class AuthError(HostError):
    code = "auth"
    user_message = "模型密钥无效或无权访问该模型。"


class RateLimited(HostError):
    code = "rate_limited"
    user_message = "模型服务限流，请稍后再试。"


class QuotaExceeded(HostError):
    code = "quota"
    user_message = "模型额度已用尽。"


class ContextOverflow(HostError):
    code = "context_overflow"
    user_message = "上下文超出模型窗口，请缩短稿件或提高窗口。"


class NetworkError(HostError):
    code = "network"
    user_message = "无法连接模型服务，请检查网络和地址。"


class BudgetExhausted(HostError):
    code = "budget"
    user_message = "本回合预算已用完。"


class Cancelled(HostError):
    code = "cancelled"
    user_message = "回合已取消。"


class ResumeIncompatible(HostError):
    code = "resume_incompatible"
    user_message = "断点由更新的内核写成，当前版本无法恢复。"


class InternalError(HostError):
    code = "internal"
    user_message = "写作内核遇到内部错误，请稍后重试。"


def classify_model_error(exc: BaseException) -> HostError:
    """把模型层异常收成宿主错误。"""
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or "connect" in text or "timed out" in text:
        return NetworkError(detail=str(exc))
    if "insufficient_quota" in text or "quota" in text or status == 402:
        return QuotaExceeded(detail=str(exc))
    if status in {401, 403} or "unauthorized" in text or "invalid api key" in text:
        return AuthError(detail=str(exc))
    if status == 429 or "rate limit" in text:
        return RateLimited(detail=str(exc))
    if status == 413 or "context length" in text or "maximum context" in text or "too many tokens" in text:
        return ContextOverflow(detail=str(exc))
    if isinstance(exc, HostError):
        return exc
    return InternalError(detail=str(exc))
