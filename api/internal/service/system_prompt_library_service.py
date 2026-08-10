"""系统提示词库：把散落的硬编码提示词集中管理到「系统提示词库」知识库。

设计（对应需求「硬编码提示词不要留在代码中，收录到系统知识库可管理形式」）：

- 默认文本统一存放在数据文件 ``internal/core/prompts/system_prompts.yaml``（YAML 数据，非代码）；
- 部署 / 数据卷删除重建时，``ensure_seed_prompts()`` 自动把 YAML 内容同步到
  「系统提示词库」（knowledge_base, scope=system），保证核心功能开箱即用；
- 双源保护（与 PromptSyncService 一致）：
  - 文档 metadata.source="catalog"（YAML 同步）：YAML 内容变化时自动更新；
  - 文档 metadata.source="custom"（管理员在知识库后台编辑过）：重新部署不覆盖；
- 运行时读取优先级：知识库文档（可管理版本） > YAML 默认值（兜底）。
  读取不依赖 app context：无 DB 时直接回退 YAML，保证后台线程也能拿到提示词。
"""

import hashlib
import logging
import os

import yaml

from internal.extension.database_extension import db
from internal.model import KnowledgeBase, KnowledgeDocument, KnowledgeSegment

logger = logging.getLogger(__name__)

# 系统提示词库固定名称（用于定位唯一的管理库）
SYSTEM_PROMPT_LIBRARY_BASE_NAME = "系统提示词库"
# 提示词文档的 source_type 标识，便于与其他业务文档区分
SYSTEM_PROMPT_DOC_SOURCE_TYPE = "system_prompt"
# 文档 metadata 中的 source 取值：catalog=YAML 同步（可被更新），custom=管理员编辑（不覆盖）
_SOURCE_CATALOG = "catalog"
_SOURCE_CUSTOM = "custom"
# 内置 seed 来源（YAML 数据文件，非代码；路径相对本文件：
# internal/service/system_prompt_library_service.py -> internal/core/prompts/system_prompts.yaml）
_SYSTEM_PROMPTS_YAML_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "core", "prompts", "system_prompts.yaml",
    )
)


class SystemPromptLibraryService:
    """系统提示词库的读取与种子初始化服务。"""

    # ------------------------------------------------------------------
    # YAML seed 数据加载
    # ------------------------------------------------------------------
    def load_yaml_prompts(self) -> dict[str, str]:
        """从 system_prompts.yaml 加载全部内置默认提示词（key -> content）。"""
        try:
            with open(_SYSTEM_PROMPTS_YAML_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            prompts: dict[str, str] = {}
            for item in data.get("prompts") or []:
                key = item.get("key")
                content = item.get("content")
                if key and content:
                    prompts[key] = content
            return prompts
        except Exception:
            logger.exception("加载 system_prompts.yaml 失败")
            return {}

    # ------------------------------------------------------------------
    # 种子初始化：YAML -> 系统知识库（幂等，部署/数据卷重建时自动恢复）
    # ------------------------------------------------------------------
    def ensure_seed_prompts(self) -> None:
        """把 YAML 中的内置提示词同步到系统提示词库。

        双源保护（对齐 PromptSyncService）：
        - 文档不存在：新建（source=catalog）；
        - 文档存在且 source=catalog：YAML 内容变化（hash 不同）时更新；
        - 文档存在且 source=custom：跳过（管理员在知识库后台编辑过，不覆盖）。
        无 source 标记的旧文档视为 catalog，便于既有 seed 数据随 YAML 升级。
        """
        yaml_prompts = self.load_yaml_prompts()
        if not yaml_prompts:
            logger.warning("系统提示词 YAML 为空或读取失败，跳过 seed")
            return
        try:
            base = self._get_library_base()
            if base is None:
                base = self._create_library_base()
                db.session.commit()
                logger.info("已创建系统提示词库 base_id=%s", base.id)
            for prompt_key, content in yaml_prompts.items():
                doc = self._get_prompt_document(base.id, prompt_key)
                if doc is None:
                    self._create_prompt_document(base.id, prompt_key, content)
                    logger.info("已导入系统提示词文档 key=%s", prompt_key)
                    continue
                self._sync_catalog_document(doc, content, prompt_key)
            db.session.commit()
        except Exception:
            # seed 失败不阻断主流程：运行时 get_prompt 会回退到 YAML 默认值
            db.session.rollback()
            logger.exception("系统提示词库 seed 失败，回退到 YAML 默认提示词")

    def _sync_catalog_document(self, doc: KnowledgeDocument, content: str, prompt_key: str) -> None:
        """按双源保护规则更新单个提示词文档。"""
        meta = dict(doc.metadata_ or {})
        if meta.get("source") == _SOURCE_CUSTOM:
            return
        segment = (
            db.session.query(KnowledgeSegment)
            .filter(
                KnowledgeSegment.knowledge_document_id == doc.id,
                KnowledgeSegment.enabled.is_(True),
            )
            .order_by(KnowledgeSegment.position.asc())
            .first()
        )
        if segment is None:
            return
        new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        current_hash = meta.get("content_hash") or hashlib.sha256(
            (segment.content or "").encode("utf-8")
        ).hexdigest()
        if current_hash == new_hash:
            return
        segment.content = content
        segment.character_count = len(content)
        meta["source"] = _SOURCE_CATALOG
        meta["content_hash"] = new_hash
        doc.metadata_ = meta
        logger.info("已更新系统提示词文档 key=%s（YAML 版本升级）", prompt_key)

    # ------------------------------------------------------------------
    # 运行时读取
    # ------------------------------------------------------------------
    def get_prompt(self, prompt_key: str) -> str:
        """读取系统提示词库中的可管理版本；未命中返回空串。"""
        try:
            base = self._get_library_base()
            if base is None:
                return ""
            doc = self._get_prompt_document(base.id, prompt_key)
            if doc is None:
                return ""
            segment = (
                db.session.query(KnowledgeSegment)
                .filter(
                    KnowledgeSegment.knowledge_document_id == doc.id,
                    KnowledgeSegment.enabled.is_(True),
                )
                .order_by(KnowledgeSegment.position.asc())
                .first()
            )
            if segment is None:
                return ""
            return segment.content or ""
        except Exception:
            logger.warning("读取系统提示词失败 key=%s，回退到 YAML 默认值", prompt_key, exc_info=True)
            return ""

    def get_prompt_or_default(self, prompt_key: str) -> str:
        """读取可管理版本；未命中回退到 YAML 内置默认文本。"""
        managed = self.get_prompt(prompt_key)
        if managed:
            return managed
        return self.load_yaml_prompts().get(prompt_key, "")

    # ------------------------------------------------------------------
    # 后台管理：列表 / 详情 / 更新 / 重置（供 /admin/prompt-templates 复用）
    # ------------------------------------------------------------------
    def list_managed_prompts(self, category: str | None = None) -> list[dict]:
        """列出系统提示词库全部提示词（含 YAML 元数据 + 知识库可管理内容）。

        与 PromptSyncService.list_prompts 返回结构保持一致，便于管理界面合并展示。
        已停用（enabled=False）的提示词也返回，供界面重新启用。
        """
        yaml_prompts = self.load_yaml_prompts()
        base = self._get_library_base()
        items: list[dict] = []
        for key, content in yaml_prompts.items():
            cat = self._infer_category(key)
            if category and cat != category:
                continue
            items.append(self._build_managed_item(key, content, base))
        return items

    def get_managed_prompt_detail(self, prompt_key: str) -> dict | None:
        """获取单个系统内置提示词详情；key 不存在返回 None。"""
        yaml_prompts = self.load_yaml_prompts()
        if prompt_key not in yaml_prompts:
            return None
        base = self._get_library_base()
        return self._build_managed_item(prompt_key, yaml_prompts[prompt_key], base, detail=True)

    def update_managed_prompt(
        self,
        prompt_key: str,
        *,
        content: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
    ) -> dict | None:
        """更新系统内置提示词（admin 后台编辑）。

        直接更新系统提示词库中的文档内容，并标记 source=custom，
        重新部署 / 数据卷重建时不会被 YAML 覆盖（custom 保护）。
        """
        yaml_prompts = self.load_yaml_prompts()
        if prompt_key not in yaml_prompts:
            return None
        base = self._get_library_base()
        if base is None:
            base = self._create_library_base()
            db.session.commit()
        doc = self._get_prompt_document(base.id, prompt_key)
        if doc is None:
            self._create_prompt_document(base.id, prompt_key, yaml_prompts[prompt_key])
            db.session.flush()
            doc = self._get_prompt_document(base.id, prompt_key)
        seg = self._get_first_segment(doc.id)
        if seg is None:
            return None
        meta = dict(doc.metadata_ or {})
        if content is not None:
            seg.content = content
            seg.character_count = len(content)
            meta["source"] = _SOURCE_CUSTOM
            meta["content_hash"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if enabled is not None:
            seg.enabled = bool(enabled)
        if description is not None:
            meta["description"] = description
        doc.metadata_ = meta
        seg.metadata_ = meta
        db.session.commit()
        return self.get_managed_prompt_detail(prompt_key)

    def reset_managed_prompt(self, prompt_key: str) -> dict | None:
        """重置系统内置提示词为 YAML 默认版本（恢复 catalog，重新启用）。"""
        yaml_prompts = self.load_yaml_prompts()
        if prompt_key not in yaml_prompts:
            return None
        base = self._get_library_base()
        if base is None:
            return None
        doc = self._get_prompt_document(base.id, prompt_key)
        if doc is None:
            return None
        seg = self._get_first_segment(doc.id)
        if seg is None:
            return None
        content = yaml_prompts[prompt_key]
        seg.content = content
        seg.character_count = len(content)
        seg.enabled = True
        meta = {"prompt_key": prompt_key, "source": _SOURCE_CATALOG,
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()}
        doc.metadata_ = meta
        seg.metadata_ = meta
        db.session.commit()
        return self.get_managed_prompt_detail(prompt_key)

    def delete_managed_prompt(
        self,
        prompt_key: str,
        *,
        deleted_by=None,
        retention_days: int | None = None,
    ) -> bool:
        """删除系统内置提示词（进入回收站，留存期到期后彻底销毁）。

        删除后运行时自动回退到 YAML 内置默认文本；
        恢复时文档从回收站快照重建（custom 内容一并恢复）。
        """
        yaml_prompts = self.load_yaml_prompts()
        if prompt_key not in yaml_prompts:
            return False
        detail = self.get_managed_prompt_detail(prompt_key)
        from internal.service.recycle_bin_service import RecycleBinService
        deleted = RecycleBinService().delete_resource(
            resource_type="system_prompt",
            resource_id=prompt_key,
            resource_key=prompt_key,
            resource_name=detail.get("name") or prompt_key,
            deleted_by=deleted_by,
            retention_days=retention_days,
        )
        if not deleted:
            return False
        db.session.commit()
        return True

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------
    def _build_managed_item(self, key: str, default_content: str, base, detail: bool = False) -> dict:
        """把 YAML 默认值 + 知识库可管理内容组装为管理界面条目。"""
        item = {
            "prompt_key": key,
            "name": self._yaml_prompt_meta(key).get("name", key),
            "category": self._infer_category(key),
            "description": self._yaml_prompt_meta(key).get("description", ""),
            "content": default_content,
            "variables": self._extract_variables(default_content),
            "source": _SOURCE_CATALOG,
            "version": 1,
            "enabled": True,
            "updated_at": 0,
        }
        if detail:
            item["source_path"] = _SYSTEM_PROMPTS_YAML_PATH
            item["content_hash"] = hashlib.sha256(default_content.encode("utf-8")).hexdigest()
            item["created_at"] = 0
        if base is None:
            return item
        doc = self._get_prompt_document(base.id, key)
        if doc is None:
            return item
        seg = self._get_first_segment(doc.id)
        meta = dict(doc.metadata_ or {})
        if seg is not None:
            item["content"] = seg.content or default_content
            item["enabled"] = bool(seg.enabled)
            item["updated_at"] = self._to_timestamp(seg.updated_at)
            if detail:
                item["content_hash"] = meta.get("content_hash") or hashlib.sha256(
                    (seg.content or "").encode("utf-8")).hexdigest()
                item["created_at"] = self._to_timestamp(seg.created_at)
        if meta.get("source"):
            item["source"] = meta["source"]
        if meta.get("description"):
            item["description"] = meta["description"]
        item["version"] = 2 if item["source"] == _SOURCE_CUSTOM else 1
        item["variables"] = self._extract_variables(item["content"])
        return item

    def _get_first_segment(self, document_id):
        """取文档第一条 segment（管理操作使用，不过滤 enabled，含停用记录）。

        注意：运行时读取提示词请使用 get_prompt（其内部按 enabled=True 过滤），
        保证停用的提示词回退到 YAML 默认值。
        """
        return (
            db.session.query(KnowledgeSegment)
            .filter(KnowledgeSegment.knowledge_document_id == document_id)
            .order_by(KnowledgeSegment.position.asc())
            .first()
        )

    def _yaml_prompt_meta(self, key: str) -> dict:
        try:
            with open(_SYSTEM_PROMPTS_YAML_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for item in data.get("prompts") or []:
                if item.get("key") == key:
                    return {"name": item.get("name", key), "description": item.get("description", "")}
        except Exception:
            logger.debug("读取 system_prompts.yaml 元数据失败 key=%s", key, exc_info=True)
        return {"name": key, "description": ""}

    @staticmethod
    def _infer_category(key: str) -> str:
        """按 key 前缀推断管理分类（agent/assistant/routing/memory/general）。"""
        if key.startswith(("agent_", "deep_thinking_", "react_", "max_iteration")):
            return "agent"
        if key.startswith(("assistant_", "direct_answer")):
            return "assistant"
        if key.startswith(("tool_selector", "task_classifier", "public_agent_router",
                           "pool_intent_resolver", "workflow_intent_classifier", "conductor")):
            return "routing"
        if key.startswith(("memory_", "conversation_", "context_compression", "intent_recognition")):
            return "memory"
        return "general"

    @staticmethod
    def _extract_variables(content: str) -> dict[str, str]:
        """提取内容中的 {var} 占位符（排除 {{ }} 字面花括号）。"""
        import re
        return {name: "" for name in re.findall(r"(?<!\{)\{(\w+)\}(?!\})", content or "")}

    @staticmethod
    def _to_timestamp(dt) -> int:
        if dt is None:
            return 0
        from datetime import datetime as _datetime, timezone as _timezone
        if isinstance(dt, _datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_timezone.utc)
            return int(dt.timestamp())
        return int(dt)

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------
    def _get_library_base(self) -> KnowledgeBase | None:
        return (
            db.session.query(KnowledgeBase)
            .filter(
                KnowledgeBase.name == SYSTEM_PROMPT_LIBRARY_BASE_NAME,
                KnowledgeBase.knowledge_scope == "system",
            )
            .first()
        )

    def _create_library_base(self) -> KnowledgeBase:
        base = KnowledgeBase(
            name=SYSTEM_PROMPT_LIBRARY_BASE_NAME,
            description="系统级可管理提示词库：内置提示词的默认文本在此维护，管理员可编辑对应文档覆盖运行时的 system prompt。",
            knowledge_scope="system",
            owner_account_id=None,
            owner_admin_user_id=None,
            operation_context="admin",
            visibility_scope="internal",
            enabled=True,
            created_from="system_prompt_library",
            settings={"operation_context": "admin"},
        )
        db.session.add(base)
        db.session.flush()
        return base

    def _get_prompt_document(self, base_id, prompt_key: str) -> KnowledgeDocument | None:
        return (
            db.session.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.knowledge_base_id == base_id,
                KnowledgeDocument.name == prompt_key,
                KnowledgeDocument.source_type == SYSTEM_PROMPT_DOC_SOURCE_TYPE,
            )
            .first()
        )

    def _create_prompt_document(self, base_id, prompt_key: str, content: str) -> KnowledgeDocument:
        doc = KnowledgeDocument(
            knowledge_base_id=base_id,
            owner_account_id=None,
            name=prompt_key,
            content_type="document",
            source_type=SYSTEM_PROMPT_DOC_SOURCE_TYPE,
            source_id=prompt_key,
            metadata_={"prompt_key": prompt_key, "source": _SOURCE_CATALOG},
            character_count=len(content),
            status="completed",
        )
        db.session.add(doc)
        db.session.flush()
        segment = KnowledgeSegment(
            knowledge_base_id=base_id,
            knowledge_document_id=doc.id,
            owner_account_id=None,
            position=1,
            content=content,
            keywords=[],
            metadata_={"prompt_key": prompt_key, "source": _SOURCE_CATALOG},
            character_count=len(content),
            status="completed",
            enabled=True,
        )
        db.session.add(segment)
        db.session.flush()
        return doc
