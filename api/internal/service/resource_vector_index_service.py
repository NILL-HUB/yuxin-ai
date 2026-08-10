"""资源向量索引服务。

负责将模型/MCP工具/Skill/内置工具/API工具索引到 resource_vector_index 表，
并提供带子池过滤的向量检索能力。

使用者：
- 指挥官：查 model 索引，精确选模型
- Agent：查 mcp_tool/skill/builtin_tool/api_tool 索引，选工具
"""
import hashlib
import json
import logging
from typing import Any

from sqlalchemy import text as sa_text

from internal.extension.database_extension import db
from internal.model.resource_vector_index import (
    RESOURCE_TYPE_API_TOOL,
    RESOURCE_TYPE_BUILTIN_TOOL,
    RESOURCE_TYPE_MCP_TOOL,
    RESOURCE_TYPE_MODEL,
    RESOURCE_TYPE_SKILL,
    RESOURCE_VECTOR_DIMENSION,
    ResourceVectorIndex,
)

logger = logging.getLogger(__name__)


class ResourceVectorIndexService:
    """资源向量索引服务：索引构建 + 语义检索。"""
    def __init__(self, session=None):
        self._session = session or db.session
        self._embeddings_service = None

    @property
    def embeddings_service(self):
        """懒加载 EmbeddingsService（通过 injector 获取，避免循环导入）。"""
        if self._embeddings_service is None:
            from app.http.module import injector
            from internal.service.embeddings_service import EmbeddingsService
            self._embeddings_service = injector.get(EmbeddingsService)
        return self._embeddings_service

    # ── 索引构建 ──────────────────────────────────────────────────

    def _build_index_text(
        self,
        resource_type: str,
        name: str,
        description: str,
        capabilities: list | None,
        metadata: dict | None,
    ) -> str:
        """构建用于向量化的文本，包含名称、描述、能力标签等语义信息。"""
        parts = [f"名称: {name}"]
        if description:
            parts.append(f"描述: {description}")
        if capabilities:
            parts.append(f"能力: {', '.join(str(c) for c in capabilities)}")
        # 模型类型补充语义
        if resource_type == RESOURCE_TYPE_MODEL and metadata:
            model_type = metadata.get("model_type", "")
            if model_type:
                parts.append(f"类型: {model_type}")
            tier = metadata.get("tier", "")
            if tier:
                parts.append(f"档位: {tier}")
        return "。".join(parts)

    @staticmethod
    def _compute_content_hash(description: str, capabilities: list, sub_pool: str, metadata: dict) -> str:
        payload = json.dumps(
            {"d": description, "c": capabilities, "s": sub_pool, "m": metadata},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _upsert_index(
        self,
        resource_type: str,
        resource_id: str,
        name: str,
        description: str,
        capabilities: list | None,
        sub_pool: str,
        metadata: dict | None,
    ) -> bool:
        """增量更新单条索引。content_hash 未变则跳过，返回是否更新。"""
        capabilities = capabilities or []
        metadata = metadata or {}
        content_hash = self._compute_content_hash(description, capabilities, sub_pool, metadata)

        existing = self._session.query(ResourceVectorIndex).filter_by(
            resource_type=resource_type, resource_id=resource_id,
        ).first()

        if existing and existing.content_hash == content_hash:
            return False

        # 生成向量
        index_text = self._build_index_text(resource_type, name, description, capabilities, metadata)
        try:
            embedding = self.embeddings_service.embeddings.embed_query(index_text)
        except Exception as exc:
            logger.warning("生成向量失败 resource_type=%s resource_id=%s: %s", resource_type, resource_id, exc)
            return False

        # 维度校验（降维保护）
        if len(embedding) != RESOURCE_VECTOR_DIMENSION:
            logger.warning(
                "向量维度不匹配 expected=%s actual=%s resource_id=%s，跳过",
                RESOURCE_VECTOR_DIMENSION, len(embedding), resource_id,
            )
            return False

        if existing:
            existing.resource_name = name
            existing.description = description
            existing.capabilities = capabilities
            existing.sub_pool = sub_pool
            existing.metadata_ = metadata
            existing.embedding = embedding
            existing.content_hash = content_hash
            existing.enabled = True
        else:
            record = ResourceVectorIndex(
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=name,
                description=description,
                capabilities=capabilities,
                sub_pool=sub_pool,
                metadata_=metadata,
                embedding=embedding,
                content_hash=content_hash,
                enabled=True,
            )
            self._session.add(record)
        self._session.commit()
        return True

    def index_all_models(self) -> dict[str, int]:
        """索引所有 active 模型。"""
        from internal.model.model_pool_entity import ModelPoolConfig
        models = self._session.query(ModelPoolConfig).filter_by(status="active").all()
        updated = 0
        for model in models:
            # 根据 capabilities 推断子池
            sub_pool = self._infer_model_sub_pool(model.capabilities or [], model.model_type or "chat")
            metadata = {
                "model_type": model.model_type,
                "tier": model.tier,
                "price_per_1k_tokens": str(model.price_per_1k_tokens),
                "compatible_api": model.compatible_api,
                "max_tokens": (model.max_input_tokens or 0) + (model.max_output_tokens or 0),
                "max_input_tokens": model.max_input_tokens or 0,
                "max_output_tokens": model.max_output_tokens or 0,
            }
            if self._upsert_index(
                RESOURCE_TYPE_MODEL,
                str(model.id),
                model.display_name or model.model_name,
                model.description or "",
                model.capabilities or [],
                sub_pool,
                metadata,
            ):
                updated += 1
        return {"total": len(models), "updated": updated}

    def index_all_mcp_tools(self) -> dict[str, int]:
        """索引所有启用的 MCP 工具。"""
        from internal.model.mcp import McpTool, McpProvider
        tools = (
            self._session.query(McpTool)
            .join(McpProvider, McpTool.provider_id == McpProvider.id)
            .filter(McpTool.enabled.is_(True), McpProvider.is_public.is_(True))
            .all()
        )
        updated = 0
        for tool in tools:
            provider = tool.provider
            sub_pool = self._infer_tool_sub_pool(provider.task_keywords if provider else [])
            metadata = {
                "provider_name": provider.name if provider else "",
                "provider_label": provider.label if provider else "",
                "input_schema": tool.input_schema,
                "output_schema": tool.output_schema,
            }
            if self._upsert_index(
                RESOURCE_TYPE_MCP_TOOL,
                str(tool.id),
                tool.title or tool.name,
                tool.description or "",
                tool.task_keywords or [],
                sub_pool,
                metadata,
            ):
                updated += 1
        return {"total": len(tools), "updated": updated}

    def index_all_skills(self) -> dict[str, int]:
        """索引所有启用的 Skill。"""
        from internal.model.skill import SkillPackage
        skills = self._session.query(SkillPackage).filter_by(enabled=True).all()
        updated = 0
        for skill in skills:
            sub_pool = self._infer_tool_sub_pool(skill.tags or [])
            metadata = {
                "version": skill.current_version,
                "tags": skill.tags or [],
            }
            if self._upsert_index(
                RESOURCE_TYPE_SKILL,
                str(skill.id),
                skill.name,
                skill.description or "",
                skill.capabilities or [],
                sub_pool,
                metadata,
            ):
                updated += 1
        return {"total": len(skills), "updated": updated}

    def index_all_builtin_tools(self) -> dict[str, int]:
        """索引所有启用的内置工具。"""
        from internal.model.builtin_tool import BuiltinTool
        tools = self._session.query(BuiltinTool).filter_by(enabled=True).all()
        updated = 0
        for tool in tools:
            sub_pool = self._infer_tool_sub_pool(tool.task_keywords or [])
            metadata = {
                "provider_id": str(tool.provider_id) if tool.provider_id else "",
                "params": tool.params,
            }
            if self._upsert_index(
                RESOURCE_TYPE_BUILTIN_TOOL,
                str(tool.id),
                tool.name,
                tool.description or "",
                tool.task_keywords or [],
                sub_pool,
                metadata,
            ):
                updated += 1
        return {"total": len(tools), "updated": updated}

    def index_all_api_tools(self) -> dict[str, int]:
        """索引所有 API 工具（ApiTool 无 enabled 字段，全量索引）。"""
        from internal.model.api_tool import ApiTool
        tools = self._session.query(ApiTool).all()
        updated = 0
        for tool in tools:
            sub_pool = self._infer_tool_sub_pool(tool.task_keywords or [])
            metadata = {
                "provider_id": str(tool.provider_id) if tool.provider_id else "",
                "parameters": tool.parameters,
            }
            if self._upsert_index(
                RESOURCE_TYPE_API_TOOL,
                str(tool.id),
                tool.name,
                tool.description or "",
                tool.task_keywords or [],
                sub_pool,
                metadata,
            ):
                updated += 1
        return {"total": len(tools), "updated": updated}

    def rebuild_all(self) -> dict[str, Any]:
        """全量重建所有资源向量索引。"""
        # 清空旧索引
        self._session.query(ResourceVectorIndex).delete()
        self._session.commit()
        results = {}
        for name, method in [
            ("models", self.index_all_models),
            ("mcp_tools", self.index_all_mcp_tools),
            ("skills", self.index_all_skills),
            ("builtin_tools", self.index_all_builtin_tools),
            ("api_tools", self.index_all_api_tools),
        ]:
            try:
                results[name] = method()
            except Exception as exc:
                logger.exception("索引 %s 失败: %s", name, exc)
                results[name] = {"error": str(exc)}
        return results

    # ── 向量检索 ──────────────────────────────────────────────────

    def search(
        self,
        resource_type: str,
        query: str,
        top_k: int = 5,
        sub_pool: str | None = None,
    ) -> list[dict[str, Any]]:
        """向量检索：返回 top_k 最相关资源。

        Args:
            resource_type: 资源类型（model/mcp_tool/skill/builtin_tool/api_tool）
            query: 查询文本（自然语言描述需求）
            top_k: 返回数量
            sub_pool: 可选子池过滤（不传则不过滤）

        Returns:
            [{"resource_id", "resource_name", "description", "capabilities",
              "sub_pool", "metadata", "score"}]
        """
        try:
            query_vec = self.embeddings_service.embeddings.embed_query(query)
        except Exception as exc:
            logger.exception("检索向量生成失败: %s", exc)
            return []

        # 维度校验
        if len(query_vec) != RESOURCE_VECTOR_DIMENSION:
            logger.warning("检索向量维度不匹配 expected=%s actual=%s", RESOURCE_VECTOR_DIMENSION, len(query_vec))
            return []

        # 构建 SQL（顺序扫描，数据量小不需要 HNSW）
        sql = sa_text("""
            SELECT resource_id, resource_name, description, capabilities,
                   sub_pool, metadata,
                   1 - (embedding <=> CAST(:query_vec AS vector)) AS score
            FROM resource_vector_index
            WHERE resource_type = :resource_type
              AND enabled = true
              AND embedding IS NOT NULL
              [AND sub_pool = :sub_pool]
            ORDER BY embedding <=> CAST(:query_vec AS vector)
            LIMIT :top_k
        """)

        params: dict[str, Any] = {
            "query_vec": str(query_vec),
            "resource_type": resource_type,
            "top_k": top_k,
        }
        final_sql = str(sql)
        if sub_pool:
            final_sql = final_sql.replace("[AND sub_pool = :sub_pool]", "AND sub_pool = :sub_pool")
            params["sub_pool"] = sub_pool
        else:
            final_sql = final_sql.replace("[AND sub_pool = :sub_pool]", "")

        rows = self._session.execute(sa_text(final_sql), params).fetchall()
        return [
            {
                "resource_id": row.resource_id,
                "resource_name": row.resource_name,
                "description": row.description,
                "capabilities": row.capabilities or [],
                "sub_pool": row.sub_pool,
                "metadata": row.metadata or {},
                "score": float(row.score) if row.score is not None else 0.0,
            }
            for row in rows
        ]

    def remove_resource(self, resource_type: str, resource_id: str) -> None:
        """删除单条资源索引。"""
        self._session.query(ResourceVectorIndex).filter_by(
            resource_type=resource_type, resource_id=resource_id,
        ).delete()
        self._session.commit()

    # ── 子池推断 ──────────────────────────────────────────────────

    _CODING_KEYWORDS = {"coding", "code", "编程", "代码", "vibe", "deployment", "deploy", "部署", "debug", "排错"}
    _RESEARCH_KEYWORDS = {"research", "研究", "analysis", "分析", "search", "搜索", "rag", "检索"}
    _OFFICE_KEYWORDS = {"office", "办公", "document", "文档", "excel", "word", "ppt", "pdf"}
    _DATA_KEYWORDS = {"data", "数据", "sql", "visualization", "可视化", "analytics", "bi"}
    _CREATIVE_KEYWORDS = {"image", "video", "creative", "创意", "tts", "asr", "ocr", "image_generation", "video_generation"}

    def _infer_model_sub_pool(self, capabilities: list, model_type: str) -> str:
        """根据模型能力标签和类型推断子池。"""
        caps_lower = {str(c).lower() for c in capabilities}
        # 非对话类模型按类型归类
        if model_type in ("image_generation", "video_generation", "tts", "asr", "ocr"):
            return "creative"
        if model_type == "embedding":
            return "general"
        if model_type == "rerank":
            return "research"
        # 对话类模型按能力标签推断
        if caps_lower & self._CODING_KEYWORDS:
            return "coding"
        if caps_lower & self._RESEARCH_KEYWORDS:
            return "research"
        return "general"

    def _infer_tool_sub_pool(self, keywords: list) -> str:
        """根据工具关键词推断子池。"""
        kw_lower = {str(k).lower() for k in keywords}
        if kw_lower & self._CODING_KEYWORDS:
            return "coding"
        if kw_lower & self._RESEARCH_KEYWORDS:
            return "research"
        if kw_lower & self._OFFICE_KEYWORDS:
            return "office"
        if kw_lower & self._DATA_KEYWORDS:
            return "data"
        if kw_lower & self._CREATIVE_KEYWORDS:
            return "creative"
        return "general"
