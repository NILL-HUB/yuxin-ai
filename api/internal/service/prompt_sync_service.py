"""Prompt 模板 YAML→DB 同步服务。

职责：
- 启动时遍历 internal/core/prompts/index.yaml + 各 prompt YAML，upsert 到 DB
- 使用 source="catalog" 标记，admin 自定义的 source="custom" 不会被覆盖
- 计算 content_hash 用于增量更新检测（hash 不变则跳过）
- 不修改 YAML 文件本身（同步是单向的：YAML→DB）

参照 builtin_tool_sync_service.py 的双源保护机制。
"""
import hashlib
import logging
import os
from typing import Any

import yaml
from sqlalchemy.exc import SQLAlchemyError

from internal.extension.database_extension import db
from internal.model.prompt_template import PromptTemplate

logger = logging.getLogger(__name__)


class PromptSyncService:
    """Prompt 模板 YAML→DB 同步服务。"""

    def __init__(self):
        # prompts 目录相对本文件的位置：
        # 本文件: internal/service/prompt_sync_service.py
        # 目标  : internal/core/prompts/
        self._PROMPTS_DIR = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "core", "prompts",
            )
        )
        self.INDEX_YAML_PATH = os.path.join(self._PROMPTS_DIR, "index.yaml")

    def sync_yaml_to_db(self) -> dict:
        """从 YAML 同步 prompt 模板到 DB。

        Returns:
            dict: 同步统计信息，如 {"synced": 1, "skipped": 0, "errors": 0}
        """
        stats = {"synced": 0, "skipped": 0, "errors": 0}

        try:
            index_data = self._load_index_yaml()
        except Exception:
            logger.exception("读取 prompts/index.yaml 失败，跳过 prompt 同步")
            stats["errors"] += 1
            return stats

        for entry in index_data:
            key = entry.get("key")
            category = entry.get("category", "general")
            file_path = entry.get("file")
            if not key or not file_path:
                stats["skipped"] += 1
                continue

            yaml_abs_path = os.path.join(self._PROMPTS_DIR, file_path)
            if not os.path.exists(yaml_abs_path):
                logger.warning("prompt YAML 不存在: %s，跳过", file_path)
                stats["skipped"] += 1
                continue

            try:
                with open(yaml_abs_path, encoding="utf-8") as f:
                    yaml_data = yaml.safe_load(f) or {}

                self._upsert_prompt(yaml_data, source_path=yaml_abs_path)
                stats["synced"] += 1
            except SQLAlchemyError:
                logger.exception("DB 错误，prompt=%s 同步失败", key)
                stats["errors"] += 1
                db.session.rollback()
            except Exception:
                logger.exception("未知错误，prompt=%s 同步失败", key)
                stats["errors"] += 1

        try:
            db.session.commit()
        except Exception:
            logger.exception("提交 prompt 同步事务失败")
            db.session.rollback()
            stats["errors"] += 1

        logger.info("prompt YAML→DB 同步完成: %s", stats)
        return stats

    def _load_index_yaml(self) -> list[dict]:
        """加载 prompts/index.yaml 数据。"""
        with open(self.INDEX_YAML_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or []

    def _upsert_prompt(
        self,
        yaml_data: dict,
        source_path: str,
    ) -> PromptTemplate:
        """upsert 一个 prompt 记录。

        - 已存在且 source="catalog"：content_hash 变化时更新
        - 已存在且 source="custom"：跳过（admin 自定义不被覆盖）
        - 不存在：新建
        """
        prompt_key = yaml_data.get("prompt_key")
        if not prompt_key:
            raise ValueError("prompt_key 不能为空")

        content = yaml_data.get("content", "")
        content_hash = self._compute_content_hash(content)

        existing = (
            db.session.query(PromptTemplate)
            .filter_by(prompt_key=prompt_key)
            .first()
        )

        if existing is None:
            # 新建
            prompt = PromptTemplate(
                prompt_key=prompt_key,
                name=yaml_data.get("name", ""),
                category=yaml_data.get("category", "general"),
                description=yaml_data.get("description", ""),
                content=content,
                variables=yaml_data.get("variables") or {},
                source="catalog",
                source_path=source_path,
                content_hash=content_hash,
                enabled=True,
                version=1,
            )
            db.session.add(prompt)
            return prompt

        # 已存在：只更新 source="catalog" 的记录
        if existing.source == "catalog":
            # content_hash 不变则跳过（增量更新优化）
            if existing.content_hash == content_hash:
                return existing

            existing.name = yaml_data.get("name", existing.name)
            existing.category = yaml_data.get("category", existing.category)
            existing.description = yaml_data.get("description", existing.description)
            existing.content = content
            existing.variables = yaml_data.get("variables") or existing.variables
            existing.source_path = source_path
            existing.content_hash = content_hash
            existing.version = (existing.version or 1) + 1

        return existing

    @staticmethod
    def _compute_content_hash(content: str) -> str:
        """计算 prompt 内容的 SHA256 hash，用于增量更新检测。"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    # =========================================================
    # 运行时读取：供各服务调用获取 prompt 内容
    # =========================================================

    @staticmethod
    def get_prompt(prompt_key: str, **variables) -> str | None:
        """从 DB 读取 prompt 并填充变量。

        优先级：
        1. source="custom" 的记录（admin 自定义覆盖）
        2. source="catalog" 的记录（YAML 同步）
        3. 都不存在返回 None

        Args:
            prompt_key: prompt 业务键
            **variables: 占位符变量，如 max_agents=5

        Returns:
            填充变量后的 prompt 字符串，不存在返回 None
        """
        # prompt_key 是主键，最多一条记录
        prompt = (
            db.session.query(PromptTemplate)
            .filter_by(prompt_key=prompt_key, enabled=True)
            .first()
        )
        if prompt is None:
            return None

        content = prompt.content or ""
        if not variables:
            return content

        try:
            return content.format(**variables)
        except (KeyError, IndexError, ValueError):
            logger.warning(
                "prompt %s 变量填充失败，返回原始内容。variables=%s",
                prompt_key, variables,
                exc_info=True,
            )
            return content

    def list_prompts(self, category: str | None = None) -> list[dict[str, Any]]:
        """列出所有 prompt 模板（供 admin 后台展示）。"""
        query = db.session.query(PromptTemplate).filter_by(enabled=True)
        if category:
            query = query.filter_by(category=category)
        prompts = query.order_by(
            PromptTemplate.category.asc(),
            PromptTemplate.prompt_key.asc(),
        ).all()
        return [
            {
                "prompt_key": p.prompt_key,
                "name": p.name,
                "category": p.category,
                "description": p.description,
                "content": p.content,
                "variables": p.variables or {},
                "source": p.source,
                "version": p.version,
                "updated_at": _to_timestamp(p.updated_at),
            }
            for p in prompts
        ]

    def get_prompt_detail(self, prompt_key: str) -> dict[str, Any] | None:
        """获取单个 prompt 详情。"""
        p = (
            db.session.query(PromptTemplate)
            .filter_by(prompt_key=prompt_key)
            .first()
        )
        if p is None:
            return None
        return {
            "prompt_key": p.prompt_key,
            "name": p.name,
            "category": p.category,
            "description": p.description,
            "content": p.content,
            "variables": p.variables or {},
            "source": p.source,
            "source_path": p.source_path,
            "content_hash": p.content_hash,
            "enabled": p.enabled,
            "version": p.version,
            "updated_at": _to_timestamp(p.updated_at),
            "created_at": _to_timestamp(p.created_at),
        }

    def update_prompt(
        self,
        prompt_key: str,
        *,
        content: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        """更新 prompt（admin 后台编辑）。

        直接在原记录上更新，source 从 catalog 改为 custom。
        不 fork 新记录（prompt_key 是主键，无法重复）。
        YAML 原始内容保留在 source_path 指向的文件中，reset 时重新加载。
        """
        existing = (
            db.session.query(PromptTemplate)
            .filter_by(prompt_key=prompt_key)
            .first()
        )
        if existing is None:
            return None

        if content is not None:
            existing.content = content
            existing.content_hash = self._compute_content_hash(content)
        if description is not None:
            existing.description = description
        if enabled is not None:
            existing.enabled = enabled
        existing.version = (existing.version or 1) + 1
        # 标记为 admin 自定义，后续 YAML 同步不会覆盖
        existing.source = "custom"
        db.session.commit()
        return self.get_prompt_detail(prompt_key)

    def reset_prompt(self, prompt_key: str) -> dict[str, Any] | None:
        """重置 prompt 为 YAML 版本（从 source_path 指向的 YAML 文件重新加载）。

        供 admin 后台"恢复默认"按钮调用。
        """
        existing = (
            db.session.query(PromptTemplate)
            .filter_by(prompt_key=prompt_key)
            .first()
        )
        if existing is None:
            return None

        # 从 YAML 文件重新加载原始内容
        source_path = existing.source_path
        if not source_path or not os.path.exists(source_path):
            logger.warning("reset_prompt: source_path 不存在或无效: %s", source_path)
            return None

        with open(source_path, encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

        existing.content = yaml_data.get("content", "")
        existing.name = yaml_data.get("name", existing.name)
        existing.category = yaml_data.get("category", existing.category)
        existing.description = yaml_data.get("description", "")
        existing.variables = yaml_data.get("variables") or {}
        existing.content_hash = self._compute_content_hash(existing.content)
        existing.source = "catalog"
        existing.enabled = True
        existing.version = (existing.version or 1) + 1
        db.session.commit()
        return self.get_prompt_detail(prompt_key)


def _to_timestamp(dt) -> int:
    """将 datetime 转换为秒级时间戳（兼容 None）"""
    if dt is None:
        return 0
    import datetime as _dt
    if isinstance(dt, _dt.datetime):
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return int(dt)
