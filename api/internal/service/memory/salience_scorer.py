"""杏仁核显著性评分器（Salience Scorer）。

在事件写入记忆系统前，对事件进行六因子显著性评分，输出综合显著性得分与
写入路径建议（FULL / SUMMARY / SKETCH）。

六因子:
    - emotion_intensity: 情绪强度（LLM）
    - novelty:           新颖性（LLM）
    - goal_relevance:    目标相关性（LLM）
    - outcome_impact:    结果影响力（LLM）
    - rehearsal_boost:   复述强化（Redis 计数器，不调 LLM）
    - explicitness:      显式陈述因子（由 ExplicitStatementDetector 前置层传入，
                          非显式=0.0，拉高路径=0.8，快路径不进入本评分器）

四个 LLM 因子通过 ``concurrent.futures.ThreadPoolExecutor`` 并行计算，
单因子异常时降级为默认值 (0.5) 并记录 warning 日志。

explicitness 因子由调用方（MemoryWriteService）传入，本评分器不负责检测。
"""

import concurrent.futures
import logging
import math
from dataclasses import dataclass
from typing import Any

from injector import inject
from pydantic import BaseModel, Field
from redis import Redis

from internal.config.memory_settings import settings
from internal.model.memory_models import (
    MemoryEvent,
    SalienceResult,
    ScoreFactors,
    WritePath,
)
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.metrics import MetricsCollector

logger = logging.getLogger(__name__)


# ============================================================
# LLM 结构化输出辅助模型
# ============================================================


class _EmotionAnalysis(BaseModel):
    """情绪强度分析结果。"""

    intensity: float = Field(..., ge=0.0, le=1.0, description="情绪强度 0-1")
    valence: str = Field(..., description="positive/negative/neutral")
    reasoning: str = Field(..., description="分析理由")


class _NoveltyAnalysis(BaseModel):
    """新颖性分析结果。"""

    score: float = Field(..., ge=0.0, le=1.0, description="新颖性得分 0-1")
    reasoning: str = Field(..., description="分析理由")


class _GoalRelevanceAnalysis(BaseModel):
    """目标相关性分析结果。"""

    score: float = Field(..., ge=0.0, le=1.0, description="目标相关性得分 0-1")
    reasoning: str = Field(..., description="分析理由")


class _OutcomeImpactAnalysis(BaseModel):
    """结果影响力分析结果。"""

    score: float = Field(..., ge=0.0, le=1.0, description="结果影响力得分 0-1")
    reasoning: str = Field(..., description="分析理由")


# Note: ScoreFactors 已在 memory_models.py 中定义为 BaseModel，直接复用。


# 降级默认值
_DEFAULT_FACTOR_SCORE = 0.5
_DEGRADED_REASON = "LLM调用失败，降级为默认值"

# 单因子 LLM 调用超时（秒）—— DeepSeek-V4-Flash 实际响应 5-15s，需留足时间避免误降级
_LLM_FACTOR_TIMEOUT_SECONDS = 20.0


@inject
@dataclass
class SalienceScorer:
    """杏仁核显著性评分器。

    依赖注入 ``redis_client``；``LanguageModelService`` 通过类方法调用，
    不需要注入。
    """

    redis_client: Redis

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------

    def score(self, event: MemoryEvent, explicitness: float = 0.0) -> SalienceResult:
        """对事件进行六因子显著性评分，返回评分结果与写入路径建议。

        Args:
            event: 待评分的记忆事件
            explicitness: 显式陈述因子 [0, 1]，由 ExplicitStatementDetector 前置层传入。
                - 非显式陈述：0.0（默认）
                - 拉高路径（0.5 ≤ confidence < 0.85）：0.8
                - 快路径（confidence ≥ 0.85）：不进入本评分器，由 MemoryWriteService 直接 FULL 写入
        """
        # 1. 并行计算四个 LLM 因子
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_emotion = executor.submit(self._emotion_intensity, event)
            future_novelty = executor.submit(self._novelty, event)
            future_goal = executor.submit(self._goal_relevance, event)
            future_outcome = executor.submit(self._outcome_impact, event)

            emotion_score, emotion_reason = self._safe_factor_result(
                future_emotion, "emotion_intensity"
            )
            novelty_score, novelty_reason = self._safe_factor_result(
                future_novelty, "novelty"
            )
            goal_score, goal_reason = self._safe_factor_result(
                future_goal, "goal_relevance"
            )
            outcome_score, outcome_reason = self._safe_factor_result(
                future_outcome, "outcome_impact"
            )

        # 2. 复述强化因子（纯 Redis，不调 LLM）
        rehearsal_score = self._rehearsal_boost(event)

        # 3. 组装因子明细（含 explicitness）
        factors = ScoreFactors(
            emotion_intensity=emotion_score,
            novelty=novelty_score,
            goal_relevance=goal_score,
            outcome_impact=outcome_score,
            rehearsal_boost=rehearsal_score,
            explicitness=float(explicitness),
        )

        # 4. 六因子加权求和
        total_score = self._compute_total(factors)

        # 5. 路由决策
        write_path = self.route(total_score)

        # 6. 组装评分理由（调试/审计用）
        reasoning = "; ".join(
            [
                f"emotion={emotion_score:.2f}({emotion_reason})",
                f"novelty={novelty_score:.2f}({novelty_reason})",
                f"goal={goal_score:.2f}({goal_reason})",
                f"outcome={outcome_score:.2f}({outcome_reason})",
                f"rehearsal={rehearsal_score:.2f}",
                f"explicitness={float(explicitness):.2f}",
                f"total={total_score:.2f}->{write_path.value}",
            ]
        )

        return SalienceResult(
            event=event,
            total_score=total_score,
            factors=factors,
            write_path=write_path,
            reasoning=reasoning,
        )

    def route(self, total_score: float) -> WritePath:
        """根据综合得分决定写入路径。"""
        thresholds = settings.salience.thresholds
        if total_score > thresholds["full"]:
            return WritePath.FULL
        if total_score > thresholds["summary"]:
            return WritePath.SUMMARY
        return WritePath.SKETCH

    def _compute_total(self, factors: ScoreFactors) -> float:
        """六因子加权求和。"""
        w = settings.salience.weights
        return (
            w["emotion"] * factors.emotion_intensity
            + w["novelty"] * factors.novelty
            + w["goal_relevance"] * factors.goal_relevance
            + w["outcome_impact"] * factors.outcome_impact
            + w["rehearsal"] * factors.rehearsal_boost
            + w["explicitness"] * factors.explicitness
        )

    # ----------------------------------------------------------
    # 四个 LLM 因子
    # ----------------------------------------------------------

    def _emotion_intensity(self, event: MemoryEvent) -> tuple[float, str]:
        """情绪强度因子（LLM）。"""
        prompt = self._build_prompt(
            role="情绪分析专家",
            task=(
                "请分析以下对话内容的情绪强度。"
                "请评估情绪强度（0=完全中性，1=极度激烈），"
                "并判断情绪效价（positive/negative/neutral）。"
            ),
            event=event,
        )
        result = self._call_llm_structured(prompt, _EmotionAnalysis)
        return float(result.intensity), result.reasoning

    def _novelty(self, event: MemoryEvent) -> tuple[float, str]:
        """新颖性因子（LLM）。"""
        prompt = self._build_prompt(
            role="信息新颖性评估专家",
            task=(
                "请评估以下对话内容的新颖性。"
                "判断该内容是否包含罕见、新鲜或出乎意料的信息"
                "（0=完全常见/已知，1=极度新颖/罕见）。"
            ),
            event=event,
        )
        result = self._call_llm_structured(prompt, _NoveltyAnalysis)
        return float(result.score), result.reasoning

    def _goal_relevance(self, event: MemoryEvent) -> tuple[float, str]:
        """目标相关性因子（LLM）。"""
        prompt = self._build_prompt(
            role="目标相关性评估专家",
            task=(
                "请评估以下对话内容与用户长期目标和当前任务的相关性"
                "（0=完全不相关，1=高度相关）。"
            ),
            event=event,
        )
        result = self._call_llm_structured(prompt, _GoalRelevanceAnalysis)
        return float(result.score), result.reasoning

    def _outcome_impact(self, event: MemoryEvent) -> tuple[float, str]:
        """结果影响力因子（LLM）。"""
        prompt = self._build_prompt(
            role="结果影响力评估专家",
            task=(
                "请评估以下对话内容对未来决策和结果的潜在影响"
                "（0=几乎无影响，1=重大影响）。"
            ),
            event=event,
        )
        result = self._call_llm_structured(prompt, _OutcomeImpactAnalysis)
        return float(result.score), result.reasoning

    # ----------------------------------------------------------
    # Redis 计数器因子（不调 LLM）
    # ----------------------------------------------------------

    def _rehearsal_boost(self, event: MemoryEvent) -> float:
        """复述强化因子（纯 Redis 计数器，不调 LLM）。

        公式: ``boost = min(1.0, log(1 + access_count) / log(100))``
        access_count=0 -> 0.0, 50 -> ~0.85, 99+ -> 1.0
        """
        try:
            key = f"bms:access_count:{event.user_id}"
            # 读取当前累计计数（首次为 None → 0）
            current = self.redis_client.get(key)
            access_count = int(current) if current is not None else 0
            boost = min(1.0, math.log(1 + access_count) / math.log(100))
            # 递增计数，记录本次访问（表示用户重复接触此话题）
            self.redis_client.incr(key)
            return float(boost)
        except Exception as exc:
            logger.warning("rehearsal_boost 计算失败，降级为 0.0: %s", exc)
            return 0.0

    # ----------------------------------------------------------
    # 通用辅助
    # ----------------------------------------------------------

    def _call_llm_structured(self, prompt: str, response_model: type) -> Any:
        """通用结构化 LLM 调用。

        使用 LLMActivityProbe 探针包装，检测模型活性，死机时抛出异常。
        """
        from internal.service.memory.llm_activity_probe import LLMActivityProbe

        llm = LanguageModelService.get_feature_model("memory_salience_scoring")
        result = LLMActivityProbe.invoke_structured_with_probe(
            llm, response_model, prompt, feature_key="memory_salience_scoring"
        )
        self._record_llm_tokens(llm, result, prompt)
        return result

    @staticmethod
    def _record_llm_tokens(llm: Any, result: Any, prompt: str) -> None:
        """从 LLM 响应中提取 token 使用量并记录指标。

        结构化输出可能不携带 usage_metadata，此时按 prompt 长度粗略估算。
        """
        try:
            tokens = 0
            # 尝试从 result 提取 usage_metadata
            usage = getattr(result, "usage_metadata", None)
            if isinstance(usage, dict):
                tokens = int(usage.get("total_tokens", 0))
            if tokens <= 0:
                resp_meta = getattr(result, "response_metadata", None)
                if isinstance(resp_meta, dict):
                    token_usage = resp_meta.get("token_usage", {})
                    tokens = int(token_usage.get("total_tokens", 0))
            if tokens <= 0:
                # 估算：英文约 4 字符/token，中文约 1.5 字符/token
                tokens = max(1, len(prompt) // 4)
            model_name = (
                getattr(llm, "model_name", None)
                or getattr(llm, "model", None)
                or "unknown"
            )
            MetricsCollector.record_llm_tokens(str(model_name), "salience_scoring", tokens)
        except Exception:
            logger.debug("_record_llm_tokens: 提取 token 失败", exc_info=True)

    def _build_prompt(self, role: str, task: str, event: MemoryEvent) -> str:
        """构造包含事件内容与最近 3 条上下文消息的 prompt。"""
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        recent_context = "\n".join(event.context_messages[-3:]) or "(无上下文)"
        template = SystemPromptLibraryService().get_prompt_or_default(
            "memory_salience_prompt"
        )
        return template.format(
            role=role,
            task=task,
            event_content=event.content,
            recent_context=recent_context,
        )

    def _safe_factor_result(
        self, future: concurrent.futures.Future, factor_name: str
    ) -> tuple[float, str]:
        """安全获取因子计算结果，探针终止或异常时降级为默认值 (0.5)。

        降级时不写入记忆（宁可不写也不写垃圾）。
        """
        from internal.service.memory.llm_activity_probe import LLMActivityTimeoutError

        try:
            # 不再使用固定超时，让探针决定何时终止
            return future.result()
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "因子 %s 探针检测到死机，终止写入（不写垃圾）: %s",
                factor_name, exc,
            )
            return (_DEFAULT_FACTOR_SCORE, _DEGRADED_REASON)
        except Exception as exc:
            logger.warning(
                "因子 %s 计算失败（异常），降级为默认值 %s: %s",
                factor_name,
                _DEFAULT_FACTOR_SCORE,
                exc,
            )
            return (_DEFAULT_FACTOR_SCORE, _DEGRADED_REASON)
