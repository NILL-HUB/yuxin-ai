"""LLM 实体/关系抽取与摘要生成器。

为记忆写入路径（FULL / SUMMARY）提供：
    - 实体与三元组关系抽取（供 LedgerWriter 写入 Neo4j TKG）
    - 内容摘要生成（SUMMARY 路径用）

降级策略:
    LLM 调用失败时返回空列表或空字符串，主流程不中断。
    SKETCH 路径仅抽取实体名（轻量），不调摘要生成。
"""

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from internal.service.language_model_service import LanguageModelService

logger = logging.getLogger(__name__)


# LLM 调用超时（秒）—— 实体抽取比简单确认更耗时，留 30s
_LLM_TIMEOUT_SECONDS = 30.0


# ============================================================
# LLM 结构化输出辅助模型
# ============================================================


class _EntityItem(BaseModel):
    """单个实体抽取结果。"""

    name: str = Field(..., min_length=1, description="实体名称")
    type: str = Field(default="unknown", description="实体类型（人/组织/概念/地点等）")
    summary: str = Field(default="", description="实体简要描述")


class _RelationItem(BaseModel):
    """单个三元组关系。"""

    subject: str = Field(..., description="主体实体名称")
    relation: str = Field(..., description="关系类型（大写字母+下划线，如 WORKS_AT）")
    object: str = Field(..., description="客体实体名称")


class _ExtractionResult(BaseModel):
    """实体/关系抽取结构化输出。"""

    entities: list[_EntityItem] = Field(default_factory=list, description="抽取的实体列表")
    relations: list[_RelationItem] = Field(default_factory=list, description="抽取的关系列表")


class _SummaryResult(BaseModel):
    """摘要生成结构化输出。"""

    summary: str = Field(..., description="内容摘要（不超过 200 字）")


# ============================================================
# 实体抽取器
# ============================================================


class MemoryEntityExtractor:
    """LLM 驱动的实体/关系抽取与摘要生成。

    无外部依赖注入，``LanguageModelService`` 通过类方法调用获取 LLM。
    遵循项目同步调用模式，使用带兜底的结构化输出实现实体提取。
    """

    def _call_llm_structured_with_timeout(
        self, llm: Any, response_model: type, prompt: str, timeout: float = _LLM_TIMEOUT_SECONDS
    ) -> Any:
        """带探针的 LLM 结构化调用。

        使用 LLMActivityProbe 探针包装，检测模型活性，死机时抛出 LLMActivityTimeoutError。
        由调用方 catch 后走降级路径（返回空列表/空字符串，不写入垃圾）。
        """
        from internal.service.memory.llm_activity_probe import LLMActivityProbe

        return LLMActivityProbe.invoke_structured_with_probe(
            llm, response_model, prompt, feature_key="memory_entity_extraction"
        )

    def extract_entities_and_relations(
        self,
        text: str,
        max_entities: Optional[int] = None,
    ) -> tuple[list[dict], list[dict]]:
        """从文本中抽取实体与三元组关系。

        Args:
            text: 待抽取的文本内容（对话内容或摘要）。
            max_entities: 实体数量上限（SUMMARY 路径传 5），None 表示不截断。

        Returns:
            ``(entities, relations)`` 二元组，每项为字典列表：
            - entities: ``[{"name", "type", "summary"}, ...]``
            - relations: ``[{"subject", "relation", "object"}, ...]``
            LLM 失败时返回空列表。
        """
        if not text or not text.strip():
            return [], []

        from internal.service.system_prompt_library_service import SystemPromptLibraryService
        prompt = SystemPromptLibraryService().get_prompt_or_default(
            "memory_entity_extraction_prompt"
        ).format(text=text)

        try:
            llm = LanguageModelService.get_feature_model("memory_entity_extraction")
            result: _ExtractionResult = self._call_llm_structured_with_timeout(
                llm, _ExtractionResult, prompt
            )
        except Exception:
            logger.warning("实体/关系抽取失败，返回空列表", exc_info=True)
            return [], []

        entities = [
            {
                "name": e.name,
                "type": e.type or "unknown",
                "summary": e.summary or "",
            }
            for e in result.entities
        ]
        relations = [
            {
                "subject": r.subject,
                "relation": r.relation,
                "object": r.object,
            }
            for r in result.relations
        ]

        if max_entities is not None and len(entities) > max_entities:
            entities = entities[:max_entities]
            # 截断关系：仅保留两端实体均在截断后列表中的关系
            valid_names = {e["name"] for e in entities}
            relations = [
                r
                for r in relations
                if r["subject"] in valid_names and r["object"] in valid_names
            ][:max_entities]

        return entities, relations

    def generate_summary(self, text: str) -> str:
        """生成文本摘要（SUMMARY 路径用）。

        Args:
            text: 原始对话内容。

        Returns:
            不超过 200 字的摘要；LLM 失败时返回空字符串。
        """
        if not text or not text.strip():
            return ""

        from internal.service.system_prompt_library_service import SystemPromptLibraryService
        prompt = SystemPromptLibraryService().get_prompt_or_default(
            "memory_entity_summary_prompt"
        ).format(text=text)

        try:
            llm = LanguageModelService.get_feature_model("memory_entity_extraction")
            result: _SummaryResult = self._call_llm_structured_with_timeout(
                llm, _SummaryResult, prompt
            )
            return result.summary or ""
        except Exception:
            logger.warning("摘要生成失败，返回空字符串", exc_info=True)
            return ""
