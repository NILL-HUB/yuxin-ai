from __future__ import annotations

import re
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import tiktoken

from internal.core.agent.entities.queue_entity import QueueEvent


_ENCODING = tiktoken.get_encoding("cl100k_base")
_DATA_URL_PATTERN = re.compile(
    r"data:[^;]+;base64,[A-Za-z0-9+/=]+",
    re.IGNORECASE,
)


def _to_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _to_non_negative_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _get_event_value(event: Any) -> str:
    return str(getattr(event, "value", event) or "")


def normalize_usage_text(value: Any) -> str:
    """归一化用于 token 估算的文本，避免把 base64 图片内容计入 token。"""
    text = str(value or "")
    if not text:
        return ""
    return _DATA_URL_PATTERN.sub("data:image/...;base64,[base64]", text)


@dataclass(slots=True)
class AgentUsageSummary:
    total_token_count: int = 0
    total_price: float = 0.0
    latency: float = 0.0


def summarize_agent_thoughts(agent_thoughts: Iterable[Any]) -> AgentUsageSummary:
    """聚合消息级 token / price / latency。

    说明：
    - token 与 price 直接按已去重 thought 列表求和。
    - latency 对 deep_complete 做去重处理；该事件是深度阶段总耗时摘要，
      若与各 deep_step 一起累加会明显高估总耗时。
    """
    total_token_count = 0
    total_price = 0.0
    regular_latency = 0.0
    deep_phase_step_latency = 0.0
    deep_phase_complete_latency = 0.0
    max_latency = 0.0

    for agent_thought in agent_thoughts:
        total_token_count += _to_non_negative_int(getattr(agent_thought, "total_token_count", 0))
        total_price += _to_non_negative_float(getattr(agent_thought, "total_price", 0.0))

        latency = _to_non_negative_float(getattr(agent_thought, "latency", 0.0))
        max_latency = max(max_latency, latency)
        event = _get_event_value(getattr(agent_thought, "event", ""))
        if event == QueueEvent.DEEP_COMPLETE.value:
            deep_phase_complete_latency = max(deep_phase_complete_latency, latency)
        elif event in {
            QueueEvent.DEEP_THINKING.value,
            QueueEvent.DEEP_STEP.value,
            QueueEvent.DEEP_ARTIFACT_CREATED.value,
        }:
            deep_phase_step_latency += latency
        else:
            regular_latency += latency

    total_latency = regular_latency + (
        deep_phase_complete_latency or deep_phase_step_latency
    )

    return AgentUsageSummary(
        total_token_count=total_token_count,
        total_price=total_price,
        latency=total_latency or max_latency,
    )


@dataclass(slots=True)
class LanguageModelUsageTracker:
    """在不依赖 provider usage metadata 的情况下，估算 LLM 调用成本。"""

    input_price: float = 0.0
    output_price: float = 0.0
    price_unit: float = 0.0
    total_token_count: int = 0
    total_price: float = 0.0
    _patched_models: dict[int, dict[str, Any]] = field(default_factory=dict)

    def patch_model(self, model: Any) -> Any:
        if model is None:
            return model

        model_id = id(model)
        if model_id in self._patched_models:
            return model

        originals: dict[str, Any] = {}
        for method_name in ("invoke", "stream", "bind_tools", "with_structured_output", "bind"):
            original = getattr(model, method_name, None)
            if callable(original):
                originals[method_name] = original

        if not originals:
            return model

        self._patched_models[model_id] = {
            "model": model,
            "originals": originals,
        }

        if "invoke" in originals:
            original_invoke = originals["invoke"]

            def invoke_wrapper(*args, **kwargs):
                result = original_invoke(*args, **kwargs)
                self.record(args[0] if args else kwargs.get("input", ""), result)
                return result

            object.__setattr__(model, "invoke", invoke_wrapper)

        if "stream" in originals:
            original_stream = originals["stream"]

            def stream_wrapper(*args, **kwargs):
                gathered = None
                for chunk in original_stream(*args, **kwargs):
                    if gathered is None:
                        gathered = chunk
                    else:
                        try:
                            gathered += chunk
                        except Exception:
                            gathered = chunk
                    yield chunk

                if gathered is not None:
                    self.record(args[0] if args else kwargs.get("input", ""), gathered)

            object.__setattr__(model, "stream", stream_wrapper)

        for method_name in ("bind_tools", "with_structured_output", "bind"):
            if method_name not in originals:
                continue
            original_method = originals[method_name]

            def binder_wrapper(*args, __original=original_method, **kwargs):
                bound_model = __original(*args, **kwargs)
                return self.patch_model(bound_model)

            object.__setattr__(model, method_name, binder_wrapper)

        return model

    def restore(self) -> None:
        for payload in reversed(list(self._patched_models.values())):
            model = payload["model"]
            for method_name, original in payload["originals"].items():
                object.__setattr__(model, method_name, original)
        self._patched_models.clear()

    def record(self, model_input: Any, model_output: Any) -> None:
        input_token_count = len(_ENCODING.encode(normalize_usage_text(model_input)))
        output_token_count = len(_ENCODING.encode(normalize_usage_text(model_output)))
        self.total_token_count += input_token_count + output_token_count
        self.total_price += (
            input_token_count * self.input_price + output_token_count * self.output_price
        ) * self.price_unit


@contextmanager
def track_language_model_usage(model: Any):
    get_pricing = getattr(model, "get_pricing", None)
    pricing = get_pricing() if callable(get_pricing) else (0.0, 0.0, 0.0)
    tracker = LanguageModelUsageTracker(
        input_price=_to_non_negative_float(pricing[0] if len(pricing) > 0 else 0.0),
        output_price=_to_non_negative_float(pricing[1] if len(pricing) > 1 else 0.0),
        price_unit=_to_non_negative_float(pricing[2] if len(pricing) > 2 else 0.0),
    )
    tracker.patch_model(model)
    try:
        yield tracker
    finally:
        tracker.restore()


def extract_token_usage(response) -> dict | None:
    """从 LangChain LLM response 对象提取 token usage。

    支持多种格式：
    - response.response_metadata.token_usage（OpenAI 兼容）
    - response.usage_metadata（LangChain v0.2+）
    - response.response_metadata.usage

    Returns:
        {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
        或 None（无法提取时）
    """
    # 1. 尝试 response_metadata.token_usage（OpenAI 兼容格式）
    metadata = getattr(response, "response_metadata", None) or {}
    usage = metadata.get("token_usage") or metadata.get("usage") or {}
    if usage:
        return {
            "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
            "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
            "total_tokens": usage.get("total_tokens", 0),
        }

    # 2. 尝试 usage_metadata（LangChain v0.2+ AIMessage）
    usage_meta = getattr(response, "usage_metadata", None) or {}
    if usage_meta:
        return {
            "prompt_tokens": usage_meta.get("input_tokens", 0),
            "completion_tokens": usage_meta.get("output_tokens", 0),
            "total_tokens": usage_meta.get("total_tokens", 0),
        }

    return None


def extract_token_usage_from_stream(chunks: list) -> dict | None:
    """从 LangChain 流式调用的 chunk 列表中提取 token usage。

    流式调用中，最后一个 chunk 通常携带 usage_metadata。

    Args:
        chunks: llm.stream() 返回的所有 chunk 列表

    Returns:
        与 extract_token_usage 相同格式，或 None
    """
    if not chunks:
        return None

    # 检查最后一个 chunk
    last_chunk = chunks[-1]

    # 1. 检查 usage_metadata
    usage_meta = getattr(last_chunk, "usage_metadata", None) or {}
    if usage_meta:
        return {
            "prompt_tokens": usage_meta.get("input_tokens", 0),
            "completion_tokens": usage_meta.get("output_tokens", 0),
            "total_tokens": usage_meta.get("total_tokens", 0),
        }

    # 2. 检查 response_metadata.token_usage
    metadata = getattr(last_chunk, "response_metadata", None) or {}
    usage = metadata.get("token_usage") or metadata.get("usage") or {}
    if usage:
        return {
            "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
            "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
            "total_tokens": usage.get("total_tokens", 0),
        }

    return None


def charge_for_feature(credit_service, account_id, feature_key: str, token_count: int) -> bool:
    """公共 AI 功能 LLM 调用后扣减用户额度。

    Args:
        credit_service: CreditService 实例（可为 None，None 时不扣费）
        account_id: 用户账户 ID
        feature_key: 公共 AI 功能标识
        token_count: 总 token 数

    Returns:
        True 表示已扣费，False 表示未扣费（credit_service 为 None 或 token_count <= 0）
    """
    if credit_service is None or token_count <= 0:
        return False

    try:
        from internal.service.credit_service import CreditService
        if isinstance(credit_service, CreditService):
            credit_service.consume_for_feature(account_id, feature_key, token_count=token_count)
            return True
    except Exception:
        # 计费失败不应影响主流程
        import logging
        logging.getLogger(__name__).warning(
            "charge_for_feature failed: feature=%s, tokens=%d",
            feature_key, token_count, exc_info=True
        )
    return False


# ---------------------------------------------------------------------------
# LCEL 链式调用 token 用量捕获
# ---------------------------------------------------------------------------

# 优先使用 langchain_community 的 get_openai_callback；若未安装则降级为
# 基于 langchain_core BaseCallbackHandler 的自定义 handler。
try:
    from langchain_community.callbacks import get_openai_callback  # type: ignore
except ImportError:  # pragma: no cover - 环境差异
    get_openai_callback = None  # type: ignore


from langchain_core.callbacks import BaseCallbackHandler


class _UsageTrackingHandler(BaseCallbackHandler):
    """get_openai_callback 不可用时的降级方案：通过回调捕获 token usage。

    使用方式：将实例传入 chain.invoke/stream 的 config={"callbacks": [handler]}，
    调用结束后通过 handler.total_tokens 读取总 token 数。
    """

    def __init__(self) -> None:
        self.total_tokens: int = 0

    def on_llm_end(self, response, **_kwargs) -> None:
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        if token_usage:
            self.total_tokens += int(token_usage.get("total_tokens", 0) or 0)
