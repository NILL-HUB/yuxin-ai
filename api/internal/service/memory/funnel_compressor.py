"""五层漏斗压缩器（FunnelCompressor）。

将大量召回结果通过 RAW → DEDUP → SCORED → EVIDENCE → COMPRESSED → FINAL
五层处理，压缩为可注入的结构化摘要。在 Early Stop 条件满足时跳过 LLM 调用
以节省成本。

五层漏斗:
    - Layer 0→1 DEDUP:       相似度 > 0.85 去重
    - Layer 1→2 RE_SCORE:    综合原始分数与时间新鲜度重排序
    - Layer 2→3 EVIDENCE:    候选转证据条目，限制最大数量
    - Layer 3-4 EARLY_STOP:  置信度足够高时跳过 LLM
    - Layer 4→5 LLM_COMPRESS: LLM 压缩到 budget_tokens

降级策略:
    - LLM 异常时回退为格式化证据文本
    - 空候选输入返回空字符串

设计参考:
    docs/prd/memory-system/02-storage-and-retrieval.md §6.4
    docs/prd/memory-system/execution/03-track-b-storage-retrieval.md B5
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from internal.config.memory_settings import settings
from internal.model.memory_models import EvidenceItem, FunnelConfig, RetrievalResult
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.llm_activity_probe import (
    LLMActivityProbe,
    LLMActivityTimeoutError,
)

logger = logging.getLogger(__name__)


class FunnelCompressor:
    """五层漏斗压缩器。

    不使用 ``@inject``：无注入依赖，配置从 ``settings.funnel`` 读取，
    LLM 通过 ``LanguageModelService.get_cheap_chat_model()`` 静态调用。
    """

    def __init__(self, config: Optional[FunnelConfig] = None) -> None:
        """初始化漏斗压缩器。

        Args:
            config: FunnelConfig 实例，None 时使用 settings.funnel
        """
        self._config = config or settings.funnel

    # =========================================================
    # 主入口
    # =========================================================

    def compress(
        self,
        candidates: list[RetrievalResult],
        budget_tokens: int = 2000,
    ) -> str:
        """主压缩入口，五层漏斗压缩为结构化摘要。

        Args:
            candidates: 候选检索结果列表
            budget_tokens: 输出 token 预算

        Returns:
            压缩后的结构化摘要文本
        """
        if not candidates:
            return ""

        # Layer 0→1: 去重
        deduped = self._deduplicate(candidates)
        if not deduped:
            return ""

        # Layer 1→2: 重排序
        scored = self._re_score(deduped)

        # Layer 2→3: 证据累积
        evidence = self._evidence_accumulation(scored)
        if not evidence:
            return ""

        # Layer 3-4: 早停检查
        if self._check_early_stop(evidence):
            return self._format_evidence(evidence[: self._config.early_stop_min_items])

        # Layer 4→5: LLM 压缩
        return self._llm_compress(evidence, budget_tokens)

    # =========================================================
    # Layer 1: 去重
    # =========================================================

    def _deduplicate(self, candidates: list[RetrievalResult]) -> list[RetrievalResult]:
        """Layer 1：相似度 > 阈值的候选去重（保留先出现者）。

        使用 Jaccard 集合交并比作为文本相似度度量。
        """
        threshold = self._config.dedup_similarity_threshold
        kept: list[RetrievalResult] = []
        seen_token_sets: list[set[str]] = []

        for candidate in candidates:
            tokens = set(candidate.content.lower().split())
            is_dup = False
            for seen_tokens in seen_token_sets:
                similarity = self._jaccard_similarity(tokens, seen_tokens)
                if similarity >= threshold:
                    is_dup = True
                    break

            if not is_dup:
                kept.append(candidate)
                seen_token_sets.append(tokens)

        return kept

    # =========================================================
    # Layer 2: 重排序
    # =========================================================

    def _re_score(self, candidates: list[RetrievalResult]) -> list[RetrievalResult]:
        """Layer 2：综合原始分数与时间新鲜度重排序。

        公式: score = score * (0.7 + 0.3 * freshness)
        其中 freshness = 0.99 ** hours_age
        """
        now = datetime.now(timezone.utc)
        result = []

        for candidate in candidates:
            hours_age = self._hours_since(candidate.timestamp, now)
            freshness = 0.99 ** hours_age
            new_score = candidate.score * (0.7 + 0.3 * freshness)
            # 创建新对象，避免修改原始
            re_scored = RetrievalResult(
                memory_id=candidate.memory_id,
                content=candidate.content,
                score=new_score,
                source=candidate.source,
                timestamp=candidate.timestamp,
                metadata=candidate.metadata,
                evidence_chain=candidate.evidence_chain,
                score_breakdown=candidate.score_breakdown,
            )
            result.append(re_scored)

        result.sort(key=lambda x: x.score, reverse=True)
        return result

    # =========================================================
    # Layer 3: 证据累积
    # =========================================================

    def _evidence_accumulation(
        self, candidates: list[RetrievalResult]
    ) -> list[EvidenceItem]:
        """Layer 3：候选转证据条目，限制最大数量。"""
        max_items = self._config.evidence_max_items
        evidence = []

        for candidate in candidates[:max_items]:
            evidence.append(
                EvidenceItem(
                    content=candidate.content,
                    source=candidate.source or "unknown",
                    score=candidate.score,
                    relevance=f"memory_id={candidate.memory_id}",
                )
            )

        return evidence

    # =========================================================
    # Layer 3-4: 早停检查
    # =========================================================

    def _check_early_stop(self, evidence: list[EvidenceItem]) -> bool:
        """Layer 3-4：置信度 > 阈值且条目数达标时触发早停。

        条件:
            - 条目数 <= early_stop_min_items 返回 True
            - Top-1 分数 >= early_stop_confidence 且条目数 <= 2 * early_stop_min_items 返回 True
            - 否则返回 False
        """
        min_items = self._config.early_stop_min_items
        confidence_threshold = self._config.early_stop_confidence

        if len(evidence) <= min_items:
            return True

        if not evidence:
            return True

        top_score = evidence[0].score
        if top_score >= confidence_threshold and len(evidence) <= 2 * min_items:
            return True

        return False

    # =========================================================
    # Layer 4: LLM 压缩
    # =========================================================

    def _llm_compress(
        self,
        evidence: list[EvidenceItem],
        budget_tokens: int,
    ) -> str:
        """Layer 4：LLM 压缩到 budget_tokens。

        异常时回退为格式化证据文本。
        """
        evidence_text = self._format_evidence_for_llm(evidence)
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        prompt = SystemPromptLibraryService().get_prompt_or_default(
            "memory_funnel_compression_prompt"
        ).format(
            budget=budget_tokens,
            evidence=evidence_text,
        )

        try:
            llm = LanguageModelService.get_feature_model("memory_compression")
            result = LLMActivityProbe.invoke_with_probe(
                llm, prompt, feature_key="memory_compression"
            )
            # LangChain 返回的对象，取 content
            content = getattr(result, "content", None)
            if content is None:
                content = str(result)
            return content
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "_llm_compress: LLM 探针检测到死机，回退为格式化证据（不写垃圾）: %s",
                exc,
            )
            return self._format_evidence(evidence[:10])
        except Exception:
            logger.warning(
                "_llm_compress: LLM 压缩失败，回退为格式化证据",
                exc_info=True,
            )
            return self._format_evidence(evidence[:10])

    # =========================================================
    # 辅助方法
    # =========================================================

    @staticmethod
    def _jaccard_similarity(a: set[str], b: set[str]) -> float:
        """计算两个集合的 Jaccard 相似度。"""
        if not a and not b:
            return 1.0
        intersection = a & b
        union = a | b
        if not union:
            return 0.0
        return len(intersection) / len(union)

    @staticmethod
    def _hours_since(timestamp: datetime, now: datetime) -> float:
        """计算从 timestamp 到 now 的小时数（最小为 0）。"""
        ts = timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        delta = (now - ts).total_seconds()
        return max(delta / 3600.0, 0.0)

    def _format_evidence(self, evidence: list[EvidenceItem]) -> str:
        """格式化证据为可读文本（早停/回退用）。"""
        if not evidence:
            return ""
        lines = []
        for item in evidence:
            lines.append(f"- [{item.source}|{item.score:.2f}] {item.content[:300]}")
        return "\n".join(lines)

    def _format_evidence_for_llm(self, evidence: list[EvidenceItem]) -> str:
        """格式化证据为 LLM prompt 文本。"""
        if not evidence:
            return "(无证据)"
        lines = []
        for i, item in enumerate(evidence, 1):
            lines.append(f"{i}. [来源:{item.source} 得分:{item.score:.2f}] {item.content[:500]}")
        return "\n".join(lines)
