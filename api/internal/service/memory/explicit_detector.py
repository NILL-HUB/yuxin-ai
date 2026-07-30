"""显式陈述检测器（Explicit Statement Detector）。

三层决策架构的第一层，负责识别用户消息中的显式陈述（如"我喜欢苹果"、
"我习惯早起"、"我擅长 Python"），输出 ExplicitDetectionResult。

设计要点:
    - 7 类正则模式库：preference/habit/identity/aversion/goal/meta_instruction/capability
    - 两阶段判定：正则预筛（快速过滤） → LLM 确认（语义提取）
    - 降级策略：LLM 不可用或超时 → 纯正则结果（confidence=0.6）
    - 输出主体/谓词/客体三元组，作为实体种子与关系边构建依据

决策路径（由 MemoryWriteService 编排）:
    - confidence >= fast_path_threshold (0.85)：快路径，直接 FULL 写入
    - boost_threshold (0.5) <= confidence < fast_path_threshold：拉高路径，
      传入 explicitness=0.8 走 6 因子评分
    - confidence < boost_threshold：非显式，走原 5 因子评分

设计参考:
    docs/prd/memory-write-optimization-design.md §3 三层决策架构
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from injector import inject
from pydantic import BaseModel, Field

from internal.config.memory_settings import settings
from internal.model.memory_models import (
    ExplicitCategory,
    ExplicitDetectionResult,
    ExplicitPolarity,
    MemoryEvent,
)
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.metrics import MetricsCollector

logger = logging.getLogger(__name__)


# =========================================================
# LLM 结构化输出辅助模型
# =========================================================


class _ExplicitLLMResult(BaseModel):
    """LLM 显式陈述确认结果。"""

    is_explicit: bool = Field(..., description="是否为显式陈述")
    category: str = Field(
        ...,
        description="分类：preference/habit/identity/aversion/goal/meta_instruction/capability/none",
    )
    polarity: str = Field(..., description="极性：positive/negative/neutral")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")
    subject: str = Field(..., description="主体（实体，通常是用户关注的事物，如'苹果'、'Python'）")
    predicate: str = Field(..., description="谓词（如喜欢、讨厌、擅长）")
    object: str = Field(default="", description="客体（如有，如具体事物）")
    reasoning: str = Field(..., description="判断理由")


# =========================================================
# 7 类正则模式库
# =========================================================
# 每项为 (正则, 极性)。正则只做粗筛，语义判定与三元组提取交给 LLM。
# 覆盖中文常见显式陈述表达，基于 NLP 语料库常见句式。

_EXPLICIT_PATTERNS: dict[ExplicitCategory, list[tuple[re.Pattern, ExplicitPolarity]]] = {
    ExplicitCategory.PREFERENCE: [
        # 正向偏好
        (re.compile(r"我(?:喜欢|喜爱|爱|偏好|钟爱|偏爱|中意|看好|最爱|挺喜欢|比较喜欢|超喜欢|特别喜欢)"), ExplicitPolarity.POSITIVE),
        (re.compile(r"我(?:的偏好|的喜好|的爱好|的口味|的喜爱)(?:是|为|偏向)"), ExplicitPolarity.POSITIVE),
        # 负向偏好
        (re.compile(r"我(?:不喜欢|不爱|反感|没感觉|不感冒|不感兴趣|不太喜欢|不是很喜欢)"), ExplicitPolarity.NEGATIVE),
    ],
    ExplicitCategory.HABIT: [
        (re.compile(r"我(?:习惯|通常|经常|总是|一般|常常|惯常|习惯性|一向|向来|历来|往常|平日|大抵|多半)"), ExplicitPolarity.NEUTRAL),
        (re.compile(r"我(?:每天|每周|每月|每年|每次|每逢|每天)(?:都|会)?"), ExplicitPolarity.NEUTRAL),
        (re.compile(r"我(?:习惯于|习惯性地)"), ExplicitPolarity.NEUTRAL),
    ],
    ExplicitCategory.IDENTITY: [
        (re.compile(r"我(?:是|叫|名为|名叫|身为|作为)"), ExplicitPolarity.NEUTRAL),
        (re.compile(r"我(?:的身份|职业|角色|岗位|职位|工作|专业|籍贯|性别)(?:是|为)"), ExplicitPolarity.NEUTRAL),
    ],
    ExplicitCategory.AVERSION: [
        # 厌恶
        (re.compile(r"我(?:讨厌|厌恶|憎恶|痛恨|反感|嫌弃|受不了|看不惯|嫌|厌烦)"), ExplicitPolarity.NEGATIVE),
        # 恐惧
        (re.compile(r"我(?:害怕|恐惧|畏惧|惧怕|怕|胆怯|忌惮|发怵)"), ExplicitPolarity.NEGATIVE),
        # 生理排斥
        (re.compile(r"我(?:对|对).{0,10}(?:过敏|不适|反胃|恶心|起疹)"), ExplicitPolarity.NEGATIVE),
        # 厌恶变体（"现在看到菠萝就舌头发麻"类表达）
        (re.compile(r"我(?:现在|现在).{0,5}(?:看到|听到|闻到|吃到|想到).{0,10}(?:就|会|都)(?:麻|吐|烦|腻|反胃|不舒服)"), ExplicitPolarity.NEGATIVE),
    ],
    ExplicitCategory.GOAL: [
        (re.compile(r"我(?:想|要|希望|打算|计划|准备|立志|决心|渴望|期望|盼望|想要|意愿)"), ExplicitPolarity.POSITIVE),
        (re.compile(r"我(?:的目标|计划|愿望|理想|愿景|志向|梦想|心愿)(?:是|为)"), ExplicitPolarity.POSITIVE),
        (re.compile(r"我(?:打算|计划)(?:未来|将来|以后|接下来)"), ExplicitPolarity.POSITIVE),
    ],
    ExplicitCategory.META_INSTRUCTION: [
        (re.compile(r"(?:以后|今后|接下来|往后|日后|以后)(?:请|记得|要|不要|别|默认|总是|一直|务必)"), ExplicitPolarity.NEUTRAL),
        (re.compile(r"(?:记住|别忘了|切记|务必|请始终|请永远|请总是|请默认|请务必)"), ExplicitPolarity.NEUTRAL),
        (re.compile(r"请(?:以后|今后|往后)(?:不要|别|避免)"), ExplicitPolarity.NEGATIVE),
    ],
    ExplicitCategory.CAPABILITY: [
        # 正向能力
        (re.compile(r"我(?:擅长|精通|熟练|会|能|掌握|善于|专长|拿手|在行)"), ExplicitPolarity.POSITIVE),
        (re.compile(r"我(?:的强项|的优势|的特长|的专长|的擅长)(?:是|为)"), ExplicitPolarity.POSITIVE),
        # 负向能力
        (re.compile(r"我(?:不擅长|不精通|不会|不能|没掌握|不善于|不在行|不熟练|不熟)"), ExplicitPolarity.NEGATIVE),
    ],
}


# 降级置信度：LLM 不可用时，正则命中即采用此置信度
_FALLBACK_CONFIDENCE = 0.6
# 降级理由前缀
_FALLBACK_REASON_PREFIX = "LLM降级：正则命中"


# =========================================================
# 主检测器
# =========================================================


@inject
@dataclass
class ExplicitStatementDetector:
    """显式陈述检测器。

    依赖注入：
        无构造函数依赖。LanguageModelService 通过类方法调用，
        Neo4j/pgvector 不参与检测。
    """

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------

    def detect(self, event: MemoryEvent) -> ExplicitDetectionResult:
        """检测事件是否为显式陈述。

        流程:
            1. 配置开关检查：disabled 直接返回非显式
            2. 正则预筛：遍历 7 类模式，记录命中类别
            3. 无命中：返回非显式
            4. LLM 确认（带超时与降级）：语义判定 + 三元组提取
            5. LLM 降级：纯正则结果（confidence=0.6, fallback_used=True）

        Args:
            event: 原始记忆事件

        Returns:
            ExplicitDetectionResult 检测结果
        """
        cfg = settings.explicit_detection
        if not cfg.enabled:
            return self._build_not_explicit(event, reason="显式检测已禁用")

        # 1. 正则预筛
        regex_hits = self._regex_prescan(event.content)
        if not regex_hits:
            return self._build_not_explicit(event, reason="正则未命中")

        # 取命中次数最多的类别作为候选（多类命中时取首个）
        primary_category, primary_polarity = regex_hits[0]
        MetricsCollector.record_explicit_detection(
            category=primary_category.value, stage="regex_hit"
        )

        # 2. LLM 确认（带降级）
        llm_result = self._llm_confirm(event, primary_category)

        if llm_result is None:
            # LLM 降级：纯正则结果
            return self._build_fallback_result(
                event, primary_category, primary_polarity
            )

        # 3. 组装 LLM 确认结果
        return self._build_llm_result(event, llm_result)

    # ----------------------------------------------------------
    # 正则预筛
    # ----------------------------------------------------------

    def _regex_prescan(
        self, content: str
    ) -> list[tuple[ExplicitCategory, ExplicitPolarity]]:
        """正则预筛，返回所有命中的 (类别, 极性) 列表。

        多个类别可能同时命中（如"我喜欢 Python 且擅长它"同时命中
        preference 和 capability），按命中顺序返回。
        """
        hits: list[tuple[ExplicitCategory, ExplicitPolarity]] = []
        for category, patterns in _EXPLICIT_PATTERNS.items():
            for pattern, polarity in patterns:
                if pattern.search(content):
                    hits.append((category, polarity))
                    break  # 同类只记录一次
        return hits

    # ----------------------------------------------------------
    # LLM 确认（带超时与降级）
    # ----------------------------------------------------------

    def _llm_confirm(
        self, event: MemoryEvent, hint_category: ExplicitCategory
    ) -> Optional[_ExplicitLLMResult]:
        """调用 LLM 进行语义确认与三元组提取。

        探针检测到死机或异常时返回 None，触发降级路径。
        降级时不写入任何记忆（宁可不写也不写垃圾）。

        Args:
            event: 原始记忆事件
            hint_category: 正则预筛给出的候选类别（作为 LLM 提示）

        Returns:
            _ExplicitLLMResult 或 None（降级）
        """
        from internal.service.memory.llm_activity_probe import LLMActivityTimeoutError

        cfg = settings.explicit_detection
        if not cfg.llm_fallback_enabled:
            # 配置禁用 LLM，直接走降级
            return None

        prompt = self._build_prompt(event, hint_category)

        try:
            # 使用 LLMActivityProbe 探针包装，检测模型活性
            # 探针每 60s 检测一次，模型仍在产出 token 就继续等待，死机才终止
            return self._call_llm_structured(prompt, _ExplicitLLMResult)
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "explicit_detector: LLM 探针检测到死机，终止写入（不写垃圾）: %s",
                exc,
            )
            return None
        except Exception:
            logger.warning(
                "explicit_detector: LLM 确认异常，降级为纯正则",
                exc_info=True,
            )
            return None

    def _call_llm_structured(
        self, prompt: str, response_model: type
    ) -> Any:
        """通用结构化 LLM 调用（复用 SalienceScorer 模式）。

        使用 LLMActivityProbe 探针包装，检测模型活性，死机时抛出异常。
        """
        from internal.service.memory.llm_activity_probe import (
            LLMActivityProbe,
            LLMActivityTimeoutError,
        )

        llm = LanguageModelService.get_feature_model("memory_explicit_detection")
        result = LLMActivityProbe.invoke_structured_with_probe(
            llm, response_model, prompt, feature_key="memory_explicit_detection"
        )
        self._record_llm_tokens(llm, result, prompt)
        return result

    @staticmethod
    def _record_llm_tokens(llm: Any, result: Any, prompt: str) -> None:
        """从 LLM 响应中提取 token 使用量并记录指标。"""
        try:
            tokens = 0
            usage = getattr(result, "usage_metadata", None)
            if isinstance(usage, dict):
                tokens = int(usage.get("total_tokens", 0))
            if tokens <= 0:
                resp_meta = getattr(result, "response_metadata", None)
                if isinstance(resp_meta, dict):
                    token_usage = resp_meta.get("token_usage", {})
                    tokens = int(token_usage.get("total_tokens", 0))
            if tokens <= 0:
                tokens = max(1, len(prompt) // 4)
            model_name = (
                getattr(llm, "model_name", None)
                or getattr(llm, "model", None)
                or "unknown"
            )
            MetricsCollector.record_llm_tokens(
                str(model_name), "explicit_detection", tokens
            )
        except Exception:
            logger.debug("_record_llm_tokens: 提取 token 失败", exc_info=True)

    def _build_prompt(
        self, event: MemoryEvent, hint_category: ExplicitCategory
    ) -> str:
        """构造 LLM 确认 prompt。"""
        recent_context = "\n".join(event.context_messages[-3:]) or "(无上下文)"
        return (
            "你是显式陈述检测专家。请判断用户消息是否为显式陈述（如偏好、习惯、"
            "身份、厌恶、目标、元指令、能力），并提取主体/谓词/客体三元组。\n\n"
            "分类说明:\n"
            "- preference: 偏好（我喜欢/不喜欢...）\n"
            "- habit: 习惯（我习惯/通常...）\n"
            "- identity: 身份（我是/我叫...）\n"
            "- aversion: 厌恶（我讨厌/害怕/过敏...）\n"
            "- goal: 目标（我想/我打算...）\n"
            "- meta_instruction: 元指令（以后请/记住...）\n"
            "- capability: 能力（我擅长/我会...）\n"
            "- none: 非显式陈述\n\n"
            "极性说明:\n"
            "- positive: 正向（喜欢、想要、擅长）\n"
            "- negative: 负向（讨厌、害怕、不擅长）\n"
            "- neutral: 中性（是、习惯、打算）\n\n"
            f"正则预筛候选类别: {hint_category.value}\n"
            f"用户消息: {event.content}\n"
            f"上下文:\n{recent_context}\n\n"
            "请输出: is_explicit, category, polarity, confidence, "
            "subject(主体实体), predicate(谓词), object(客体,无则空), reasoning"
        )

    # ----------------------------------------------------------
    # 结果组装
    # ----------------------------------------------------------

    def _build_llm_result(
        self, event: MemoryEvent, llm_result: _ExplicitLLMResult
    ) -> ExplicitDetectionResult:
        """组装 LLM 确认结果。"""
        # 解析类别（LLM 可能返回 "none" 或无效值）
        category = self._parse_category(llm_result.category)
        polarity = self._parse_polarity(llm_result.polarity)

        is_explicit = bool(llm_result.is_explicit and category is not None)

        if is_explicit:
            MetricsCollector.record_explicit_detection(
                category=category.value, stage="llm_confirmed"
            )

        return ExplicitDetectionResult(
            is_explicit=is_explicit,
            category=category if is_explicit else None,
            polarity=polarity,
            confidence=float(llm_result.confidence) if is_explicit else 0.0,
            subject=llm_result.subject.strip() if is_explicit and llm_result.subject else None,
            predicate=llm_result.predicate.strip() if is_explicit and llm_result.predicate else None,
            object=llm_result.object.strip() if is_explicit and llm_result.object else None,
            reasoning=llm_result.reasoning,
            fallback_used=False,
        )

    def _build_fallback_result(
        self,
        event: MemoryEvent,
        category: ExplicitCategory,
        polarity: ExplicitPolarity,
    ) -> ExplicitDetectionResult:
        """组装降级结果（纯正则，confidence=0.6）。"""
        MetricsCollector.record_explicit_detection(
            category=category.value, stage="fallback"
        )
        return ExplicitDetectionResult(
            is_explicit=True,
            category=category,
            polarity=polarity,
            confidence=_FALLBACK_CONFIDENCE,
            subject=None,  # 降级时无法提取三元组
            predicate=None,
            object=None,
            reasoning=f"{_FALLBACK_REASON_PREFIX} {category.value}({polarity.value})",
            fallback_used=True,
        )

    def _build_not_explicit(
        self, event: MemoryEvent, reason: str
    ) -> ExplicitDetectionResult:
        """构建非显式结果。"""
        return ExplicitDetectionResult(
            is_explicit=False,
            category=None,
            polarity=ExplicitPolarity.NEUTRAL,
            confidence=0.0,
            subject=None,
            predicate=None,
            object=None,
            reasoning=reason,
            fallback_used=False,
        )

    @staticmethod
    def _parse_category(raw: str) -> Optional[ExplicitCategory]:
        """将 LLM 返回的类别字符串解析为枚举。"""
        try:
            return ExplicitCategory(raw.lower().strip())
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _parse_polarity(raw: str) -> ExplicitPolarity:
        """将 LLM 返回的极性字符串解析为枚举。"""
        try:
            return ExplicitPolarity(raw.lower().strip())
        except (ValueError, AttributeError):
            return ExplicitPolarity.NEUTRAL


__all__ = ["ExplicitStatementDetector"]
