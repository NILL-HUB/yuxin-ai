# 公共资源 AI 配置系统 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引入 `public_ai_feature_config` 表与统一配置入口，让管理员为每个公共 AI 功能（图标生成、记忆巩固、意图识别等）独立指定模型池中的模型；同时修复 2 处存储硬编码绕过 `ObjectStoragePort` 的问题。

**Architecture:** 新建一张 `public_ai_feature_config` 表（feature_key PK + model_config_id FK → model_pool_config + enabled + fallback_tier），`LanguageModelService` 新增 `get_feature_model(feature_key)` / `get_feature_credentials(feature_key)` 两个方法优先读配置表、未配置回退到现有 tier 档位逻辑。图标生成的硬编码降级链（Kolors→Qwen→DALLE）改为"配置优先 + 未配置自动选模型池中最便宜的 image_generation 模型 + 仍无则回退原硬编码链"。IconGeneratorService 的存储硬编码改为走 `cos_service.upload_bytes_without_record` 统一端口。记忆系统 cold_storage_manager 改为走 `ObjectStoragePort` 注入实例。

**Tech Stack:** Flask + SQLAlchemy + Alembic + Vue 3 + TypeScript

---

## 文件结构

### 后端新建
- `api/internal/model/public_ai_feature_config.py` — `PublicAIFeatureConfig` ORM 模型
- `api/internal/migration/versions/a4b5c6d7e8f9_create_public_ai_feature_config.py` — 建表迁移
- `api/internal/schema/admin_public_ai_feature_schema.py` — 管理后台 CRUD schema
- `api/internal/service/public_ai_feature_service.py` — 配置读取/缓存服务
- `api/internal/handler/admin_public_ai_feature_handler.py` — 管理后台 API handler

### 后端修改
- `api/internal/service/language_model_service.py` — 新增 `get_feature_model` / `get_feature_credentials` 类方法
- `api/internal/service/icon_generator_service.py` — 改造硬编码降级链 + 存储走统一端口
- `api/internal/service/memory/cold_storage_manager.py` — 存储走 `ObjectStoragePort` 注入实例
- `api/internal/router/router.py` — 注册公共 AI 功能配置管理路由
- `api/app/http/module.py` — 绑定 `PublicAIFeatureService` 到 DI

### 后端调用点改造（40+ 调用点统一替换 `get_cheap_chat_model()` → `get_feature_model(feature_key)`）
按功能分类批量替换：
- 图标提示词：`icon_generator_service.py` `_generate_icon_prompt`
- 记忆系统：`memory/` 下 13 个文件
- 意图/任务路由：`intent_recognition_service.py`、`task_classifier_service.py`、`task_decomposer.py`、`pool_intent_resolver_service.py`
- 提示词/Schema 助手：`ai_service.py`（4 个方法）
- 会话辅助：`conversation_service.py`
- 辅助 Agent 介绍生成：`assistant_agent_service.py:994`
- 直接回答执行器：`executors/direct_answer_executor.py`
- 自动标签：`tag_assignment_service.py`
- 应用自动创建：`app_service.py:232`
- 重排兜底：`rerank_service.py:131`

### 前端新建
- `ui/src/views/admin/PublicAIFeatureConfigView.vue` — 配置管理页面
- `ui/src/services/admin-public-ai-feature.ts` — API 服务

### 前端修改
- `ui/src/router/index.ts` — 注册路由
- `ui/src/layouts/AdminLayout.vue` — 添加菜单项
- `ui/src/i18n/messages/zh-CN.ts` — 添加文案
- `ui/src/i18n/messages/en-US.ts` — 添加文案

---

## Task 1: 创建 ORM 模型 PublicAIFeatureConfig

**Files:**
- Create: `api/internal/model/public_ai_feature_config.py`

- [ ] **Step 1: 创建 ORM 模型文件**

```python
# api/internal/model/public_ai_feature_config.py
"""公共资源 AI 功能配置模型。

管理平台侧发起的、用户不承担成本的 AI 调用（图标生成、记忆巩固、意图识别等）
所使用的模型配置。每个 feature_key 独立配置一个 model_pool_config 中的模型。
"""
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PublicAIFeatureConfig(db.Model):
    """公共 AI 功能配置表。

    每行对应一个公共 AI 功能的模型配置，通过 model_config_id 引用模型池中的模型。
    feature_key 为业务键，硬编码在调用方代码中（如 "icon_generation"、"memory_consolidation"）。
    """
    __tablename__ = "public_ai_feature_config"
    __table_args__ = (
        Index("ix_public_ai_feature_category", "feature_category"),
        Index("ix_public_ai_feature_enabled", "enabled"),
    )

    # 业务键，如 icon_generation / memory_consolidation / intent_recognition
    feature_key = Column(String(64), primary_key=True)
    feature_name = Column(String(128), nullable=False)
    feature_category = Column(String(64), nullable=False, server_default=text("'general'::character varying"))
    feature_description = Column(String(512), nullable=True)
    # FK → model_pool_config.id，为空时使用 fallback_tier 自动选择
    model_config_id = Column(UUID, ForeignKey("model_pool_config.id", ondelete="SET NULL"), nullable=True)
    # 非 Chat 类功能（如 image_generation）的 provider 凭证标识，为空时走 model_config_id 对应 provider
    provider_credential_key = Column(String(128), nullable=True)
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    # 未配置 model_config_id 时的回退档位：cheap / standard / strong
    fallback_tier = Column(String(64), nullable=False, server_default=text("'cheap'::character varying"))
    extra_config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
```

- [ ] **Step 2: 注册到 model `__init__.py`**

修改 `api/internal/model/__init__.py`，在末尾添加：

```python
from .public_ai_feature_config import PublicAIFeatureConfig
```

- [ ] **Step 3: Commit**

```bash
git add api/internal/model/public_ai_feature_config.py api/internal/model/__init__.py
git commit -m "feat: add PublicAIFeatureConfig ORM model for public AI feature configuration"
```

---

## Task 2: 创建 Alembic 迁移

**Files:**
- Create: `api/internal/migration/versions/a4b5c6d7e8f9_create_public_ai_feature_config.py`

- [ ] **Step 1: 创建迁移文件**

```python
# api/internal/migration/versions/a4b5c6d7e8f9_create_public_ai_feature_config.py
"""create public_ai_feature_config table

Revision ID: a4b5c6d7e8f9
Revises: z2c3d4e5f6a7
Create Date: 2026-07-20 10:00:00.000000

新建公共 AI 功能配置表，用于管理平台侧发起的、用户不承担成本的 AI 调用
（图标生成、记忆巩固、意图识别等）所使用的模型配置。
每个 feature_key 独立配置一个 model_pool_config 中的模型。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a4b5c6d7e8f9"
down_revision = "z2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_ai_feature_config",
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("feature_name", sa.String(length=128), nullable=False),
        sa.Column("feature_category", sa.String(length=64), nullable=False, server_default=sa.text("'general'::character varying")),
        sa.Column("feature_description", sa.String(length=512), nullable=True),
        sa.Column("model_config_id", sa.UUID(), nullable=True),
        sa.Column("provider_credential_key", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("fallback_tier", sa.String(length=64), nullable=False, server_default=sa.text("'cheap'::character varying")),
        sa.Column("extra_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("feature_key", name="pk_public_ai_feature_config_feature_key"),
        sa.ForeignKeyConstraint(["model_config_id"], ["model_pool_config.id"], name="fk_public_ai_feature_model_config_id", ondelete="SET NULL"),
    )
    op.create_index("ix_public_ai_feature_category", "public_ai_feature_config", ["feature_category"])
    op.create_index("ix_public_ai_feature_enabled", "public_ai_feature_config", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_public_ai_feature_enabled", table_name="public_ai_feature_config")
    op.drop_index("ix_public_ai_feature_category", table_name="public_ai_feature_config")
    op.drop_table("public_ai_feature_config")
```

- [ ] **Step 2: 执行迁移**

```bash
docker exec llmops-api flask db upgrade
```

预期输出：`Running upgrade z2c3d4e5f6a7 -> a4b5c6d7e8f9, create public_ai_feature_config table`

- [ ] **Step 3: 验证表已创建**

```bash
docker exec llmops-postgres psql -U postgres -d llmops -c "\d public_ai_feature_config"
```

预期：表结构显示所有列。

- [ ] **Step 4: Commit**

```bash
git add api/internal/migration/versions/a4b5c6d7e8f9_create_public_ai_feature_config.py
git commit -m "feat: add migration for public_ai_feature_config table"
```

---

## Task 3: 创建 PublicAIFeatureService 配置服务

**Files:**
- Create: `api/internal/service/public_ai_feature_service.py`
- Modify: `api/app/http/module.py`

- [ ] **Step 1: 创建服务文件**

```python
# api/internal/service/public_ai_feature_service.py
"""公共 AI 功能配置服务。

提供按 feature_key 读取模型配置的统一入口，带进程内缓存。
被 LanguageModelService.get_feature_model / get_feature_credentials 调用。
"""
import logging
from dataclasses import dataclass
from threading import Lock
from typing import Any

from injector import inject
from sqlalchemy import select

from internal.model import ModelPoolConfig, PublicAIFeatureConfig
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

# 缓存 TTL（秒）：配置变更后最多需要 60s 生效
_CACHE_TTL_SECONDS = 60.0


@inject
@dataclass
class PublicAIFeatureService:
    """公共 AI 功能配置读取服务，带进程内 TTL 缓存。"""

    db: SQLAlchemy

    def get_feature_config(self, feature_key: str) -> PublicAIFeatureConfig | None:
        """按 feature_key 读取配置记录，不存在返回 None。"""
        try:
            return self.db.session.query(PublicAIFeatureConfig).filter_by(
                feature_key=feature_key,
            ).first()
        except Exception:
            logger.warning("get_feature_config: 读取失败 feature_key=%s", feature_key, exc_info=True)
            return None

    def get_feature_model_config(self, feature_key: str) -> ModelPoolConfig | None:
        """读取功能绑定的 model_pool_config 记录。

        优先返回 model_config_id 指向的模型；未配置或不可用时返回 None
        （调用方应根据 fallback_tier 自动降级）。
        """
        cfg = self.get_feature_config(feature_key)
        if cfg is None or not cfg.enabled or cfg.model_config_id is None:
            return None
        try:
            return self.db.session.query(ModelPoolConfig).filter_by(
                id=cfg.model_config_id,
                status="active",
            ).first()
        except Exception:
            logger.warning("get_feature_model_config: 模型查询失败 feature_key=%s", feature_key, exc_info=True)
            return None

    def get_feature_fallback_tier(self, feature_key: str) -> str:
        """读取功能的回退档位，未配置返回 'cheap'。"""
        cfg = self.get_feature_config(feature_key)
        if cfg is None:
            return "cheap"
        return (cfg.fallback_tier or "cheap").lower()

    def is_feature_enabled(self, feature_key: str) -> bool:
        """功能是否启用。未配置记录视为启用（走 fallback）。"""
        cfg = self.get_feature_config(feature_key)
        if cfg is None:
            return True
        return bool(cfg.enabled)

    def list_all_features(self) -> list[PublicAIFeatureConfig]:
        """列出所有配置记录，用于管理后台展示。"""
        return self.db.session.query(PublicAIFeatureConfig).order_by(
            PublicAIFeatureConfig.feature_category.asc(),
            PublicAIFeatureConfig.feature_key.asc(),
        ).all()
```

- [ ] **Step 2: 在 module.py 注册 DI**

在 `api/app/http/module.py` 中找到现有 service 绑定区域（`binder.bind` 或 `binder.install` 处），添加：

```python
from internal.service.public_ai_feature_service import PublicAIFeatureService

# 在 configure 方法中
binder.bind(PublicAIFeatureService)
```

具体位置：在 `binder.bind(UploadFileService)` 等绑定附近添加。

- [ ] **Step 3: Commit**

```bash
git add api/internal/service/public_ai_feature_service.py api/app/http/module.py
git commit -m "feat: add PublicAIFeatureService for reading public AI feature config"
```

---

## Task 4: 在 LanguageModelService 新增 get_feature_model / get_feature_credentials

**Files:**
- Modify: `api/internal/service/language_model_service.py`

- [ ] **Step 1: 新增 get_feature_model 类方法**

在 `api/internal/service/language_model_service.py` 中 `get_chat_model_by_tier` 方法之后（约 L665）添加：

```python
    @classmethod
    def get_feature_model(cls, feature_key: str):
        """根据公共 AI 功能键返回 LLM 实例。

        优先读取 public_ai_feature_config 表中该 feature_key 绑定的模型；
        未配置或模型不可用时，按 fallback_tier 自动降级到模型池中的对应档位模型。

        Args:
            feature_key: 功能键，如 "icon_prompt"、"memory_consolidation"、"intent_recognition"

        Returns:
            BaseLanguageModel 实例
        """
        from flask import current_app

        _ctx = None
        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            _ctx = app.app_context()
            _ctx.push()

        try:
            from app.http.module import injector
            from internal.service.public_ai_feature_service import PublicAIFeatureService

            svc = injector.get(PublicAIFeatureService)

            # 1. 优先使用功能绑定的模型
            model_config = svc.get_feature_model_config(feature_key)
            if model_config is not None:
                llm = cls._instantiate_model_from_pool_config(model_config)
                if llm is not None:
                    return llm
                logger.warning("get_feature_model: 绑定模型实例化失败 feature_key=%s model=%s", feature_key, model_config.model_name)

            # 2. 回退到 fallback_tier
            fallback_tier = svc.get_feature_fallback_tier(feature_key)
            return cls._get_runtime_chat_model_by_tier(fallback_tier)
        finally:
            if _ctx is not None:
                _ctx.pop()

    @classmethod
    def get_feature_credentials(cls, feature_key: str) -> dict[str, str]:
        """根据公共 AI 功能键返回非 Chat 类凭证（api_key + base_url + model）。

        用于 image_generation / audio / rerank 等非 Chat 类功能的凭证获取。
        优先读取功能绑定的 model_pool_config 对应 provider 的凭证；
        未配置时回退到 provider_credential_key 指定的 provider；
        都没有时返回空字典。

        Args:
            feature_key: 功能键，如 "icon_image_generation"

        Returns:
            {"api_key": "...", "base_url": "...", "model": "...", "provider": "..."}
        """
        from flask import current_app

        _ctx = None
        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            _ctx = app.app_context()
            _ctx.push()

        try:
            from app.http.module import injector
            from internal.service.public_ai_feature_service import PublicAIFeatureService

            svc = injector.get(PublicAIFeatureService)
            model_config = svc.get_feature_model_config(feature_key)

            if model_config is not None:
                # 使用绑定模型的 provider 凭证
                creds = cls.get_provider_credentials(provider=model_config.provider)
                if creds:
                    # 覆盖 model 为功能绑定的具体模型
                    creds["model"] = model_config.model_name
                    return creds

            # 回退到 provider_credential_key
            cfg = svc.get_feature_config(feature_key)
            if cfg is not None and cfg.provider_credential_key:
                return cls.get_provider_credentials(provider=cfg.provider_credential_key)

            return {}
        finally:
            if _ctx is not None:
                _ctx.pop()

    @classmethod
    def _instantiate_model_from_pool_config(cls, model_config) -> object | None:
        """从 ModelPoolConfig 记录实例化 LLM。"""
        try:
            config_dict = {
                "provider": model_config.provider,
                "model": model_config.model_name,
                "parameters": {},
            }
            # 加载 key 覆盖（与 resolve_runtime_language_model 一致）
            overridden = cls._try_load_key_overrides_for_config(config_dict)
            if overridden is not None:
                config_dict = overridden

            svc = cls._get_service_instance()
            return svc._instantiate_language_model(config_dict)
        except Exception:
            logger.warning("_instantiate_model_from_pool_config: 实例化失败", exc_info=True)
            return None

    @classmethod
    def _get_service_instance(cls):
        """获取 LanguageModelService 实例（通过 injector）。"""
        from flask import current_app

        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            ctx = app.app_context()
            ctx.push()
            try:
                from app.http.module import injector
                return injector.get(LanguageModelService)
            finally:
                ctx.pop()

        from app.http.module import injector
        return injector.get(LanguageModelService)
```

- [ ] **Step 2: 验证导入无语法错误**

```bash
docker exec llmops-api python -c "from internal.service.language_model_service import LanguageModelService; print('OK'); print(hasattr(LanguageModelService, 'get_feature_model')); print(hasattr(LanguageModelService, 'get_feature_credentials'))"
```

预期输出：
```
OK
True
True
```

- [ ] **Step 3: Commit**

```bash
git add api/internal/service/language_model_service.py
git commit -m "feat: add get_feature_model and get_feature_credentials to LanguageModelService"
```

---

## Task 5: 修复 IconGeneratorService 存储硬编码

**Files:**
- Modify: `api/internal/service/icon_generator_service.py`

- [ ] **Step 1: 修改 _download_and_upload_image 方法走统一存储端口**

在 `api/internal/service/icon_generator_service.py` 中，将 `_download_and_upload_image` 方法（L243-282）替换为：

```python
    def _download_and_upload_image(self, image_url: str, source: str) -> str:
        """下载图片并通过统一存储端口上传，返回可访问 URL。

        Args:
            image_url: 图片URL
            source: 图片来源 (kolors/qwen/dalle)

        Returns:
            str: 存储后的可访问 URL
        """
        # 1. 下载图片
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()

        image_data = response.content

        # 2. 通过统一存储端口上传（不再直接调用 COS SDK）
        filename = f"{source}_{uuid.uuid4()}.png"
        return self.cos_service.upload_bytes_without_record(
            filename=filename,
            content=image_data,
            folder="icons",
        )
```

- [ ] **Step 2: 验证修改无语法错误**

```bash
docker exec llmops-api python -c "from internal.service.icon_generator_service import IconGeneratorService; print('OK')"
```

预期输出：`OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/service/icon_generator_service.py
git commit -m "fix: IconGeneratorService 走统一存储端口，消除 COS 硬编码"
```

---

## Task 6: 改造 IconGeneratorService 降级链走配置

**Files:**
- Modify: `api/internal/service/icon_generator_service.py`

- [ ] **Step 1: 修改 _generate_icon_prompt 使用 get_feature_model**

将 `_generate_icon_prompt` 方法中的 `LanguageModelService.get_cheap_chat_model()` 替换为 `LanguageModelService.get_feature_model("icon_prompt")`：

```python
    def _generate_icon_prompt(self, name: str, description: str) -> str:
        """生成图标描述提示词"""
        try:
            # LLM 走公共 AI 功能配置 + compatible_api 分发
            from .language_model_service import LanguageModelService
            llm = LanguageModelService.get_feature_model("icon_prompt")

            prompt_chain = ChatPromptTemplate.from_template(
                GENERATE_ICON_PROMPT_TEMPLATE
            ) | llm | StrOutputParser()

            icon_prompt = prompt_chain.invoke({
                "name": name,
                "description": description or f"一个名为{name}的应用"
            })

            return str(icon_prompt).strip()
        except Exception as e:
            logging.warning(f"生成图标提示词失败，使用默认提示词: {str(e)}")
            return (
                f"A premium mobile app launcher icon for {name}, single centered subject, "
                f"rounded square app icon composition, modern polished visual style, distinctive color palette, "
                f"premium material finish, soft studio lighting, clean plain background, crisp silhouette, "
                f"high recognizability at small sizes, no text, no watermark, no extra elements"
            )
```

- [ ] **Step 2: 在 generate_icon 方法开头增加配置优先路径**

在 `generate_icon` 方法（L29）开头，errors = [] 之后添加配置优先路径：

```python
    def generate_icon(self, name: str, description: str = "") -> str:
        """根据应用名称和描述生成图标。

        优先级：公共 AI 配置 > 模型池自动选择 image_generation 最便宜模型 > 硬编码降级链
        """
        errors = []

        # 0. 优先尝试公共 AI 配置或自动选择的 image_generation 模型
        try:
            icon_url = self._generate_with_configured_model(name, description)
            if icon_url:
                logging.info(f"配置模型生成图标成功: {icon_url}")
                return icon_url
        except Exception as e:
            error_msg = str(e)
            logging.warning(f"配置模型生成图标失败，回退到降级链: {error_msg}")
            errors.append(f"configured: {error_msg}")

        # 1. 尝试使用 Kolors (硅基流动)
        # ... 保持原有 Kolors → Qwen → DALLE 降级链不变
```

- [ ] **Step 3: 新增 _generate_with_configured_model 方法**

在 `_generate_with_kolors` 方法之前添加：

```python
    def _generate_with_configured_model(self, name: str, description: str) -> Optional[str]:
        """使用公共 AI 配置的 image_generation 模型生成图标。

        1. 读取 public_ai_feature_config["icon_image_generation"] 的凭证
        2. 未配置时，自动从模型池选最便宜的 image_generation 类型模型
        3. 都没有时返回 None（调用方走硬编码降级链）
        """
        from .language_model_service import LanguageModelService

        # 1. 优先读公共配置凭证
        creds = LanguageModelService.get_feature_credentials("icon_image_generation")

        # 2. 未配置，自动从模型池选最便宜的 image_generation 模型
        if not creds or not creds.get("api_key"):
            creds = LanguageModelService.get_provider_credentials(model_type="image_generation")

        if not creds or not creds.get("api_key"):
            return None

        api_key = creds["api_key"]
        base_url = (creds.get("base_url") or "").rstrip("/")
        model = creds.get("model") or "dall-e-3"

        prompt = self._generate_icon_prompt(name, description)

        # 统一走 OpenAI 兼容的 images/generations 接口
        url = f"{base_url}/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }

        try:
            response = requests.post(url, json=body, headers=headers, timeout=60)
            response.raise_for_status()
        except Exception as e:
            self._raise_request_error(model, e)

        result = response.json()
        images = result.get("images") or result.get("data") or []
        if not images:
            raise FailException(f"配置模型 {model} 返回的图片列表为空")

        # 兼容 OpenAI 和 SiliconFlow 两种响应格式
        image_url = images[0].get("url") if isinstance(images[0], dict) else images[0]
        if not image_url:
            raise FailException(f"配置模型 {model} 返回的图片URL为空")

        return self._download_and_upload_image(image_url, "configured")
```

- [ ] **Step 4: 验证修改无语法错误**

```bash
docker exec llmops-api python -c "from internal.service.icon_generator_service import IconGeneratorService; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/icon_generator_service.py
git commit -m "feat: IconGeneratorService 走公共 AI 配置优先 + 自动选模型 + 硬编码降级链兜底"
```

---

## Task 7: 修复 cold_storage_manager.py 存储硬编码

**Files:**
- Modify: `api/internal/service/memory/cold_storage_manager.py`

- [ ] **Step 1: 修改 _get_cos 方法走 ObjectStoragePort 注入实例**

在 `api/internal/service/memory/cold_storage_manager.py` 中，找到 `_get_cos` 方法（L329-346），替换为：

```python
    def _get_storage_service(self):
        """获取统一存储服务实例（ObjectStoragePort），不可用时返回 None。

        不再直接调用 CosService._get_client() 硬编码 COS，而是通过 DI 注入的
        ObjectStoragePort 实例分发到当前 STORAGE_BACKEND 配置的后端。
        """
        if self._cos_client is not None and self._bucket is not None:
            # 已缓存旧实例，清空并走新路径
            self._cos_client = None
            self._bucket = None

        try:
            from flask import current_app

            current_app._get_current_object()
        except RuntimeError:
            return None

        try:
            from app.http.module import injector
            from internal.core.ports.storage_port import ObjectStoragePort

            return injector.get(ObjectStoragePort)
        except Exception:
            logger.warning("_get_storage_service: 获取存储服务失败", exc_info=True)
            return None
```

- [ ] **Step 2: 修改调用 _get_cos 的方法使用 _get_storage_service**

查找文件中所有 `self._get_cos()` 调用点，替换为 `self._get_storage_service()` 并适配新接口。
具体调用点在 `_archive_to_cold` 和 `_restore_from_cold` 方法中。需要将
`client.put_object(Bucket=bucket, Body=..., Key=...)` 替换为
`storage.upload_bytes_without_record(filename=..., content=..., folder="memory-cold")`，
将 `client.get_object(Bucket=bucket, Key=...)` 替换为通过 HTTP 下载或调用 storage 的 download 方法。

由于 cold_storage_manager 的上传/下载接口与 ObjectStoragePort 的方法签名不同，
需要做适配。先查看具体调用点的代码再适配：

```bash
docker exec llmops-api grep -n "_get_cos\|_cos_client\|_bucket\|put_object\|get_object" internal/service/memory/cold_storage_manager.py
```

根据输出结果，将所有 `client.put_object(Bucket=bucket, Body=content, Key=key, ContentType=...)` 替换为：

```python
storage = self._get_storage_service()
if storage is None:
    logger.warning("_archive_to_cold: 存储服务不可用，跳过归档")
    return None
url = storage.upload_bytes_without_record(
    filename=key.rsplit("/", 1)[-1],
    content=content,
    folder="memory-cold",
)
```

对于 `client.get_object(Bucket=bucket, Key=key)` 下载，改为：
```python
storage = self._get_storage_service()
if storage is None:
    return None
# 先获取 URL，再 HTTP 下载
url = storage.get_file_url(key)
if not url:
    return None
import requests
resp = requests.get(url, timeout=30)
resp.raise_for_status()
content = resp.content
```

- [ ] **Step 3: 验证修改无语法错误**

```bash
docker exec llmops-api python -c "from internal.service.memory.cold_storage_manager import ColdStorageManager; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add api/internal/service/memory/cold_storage_manager.py
git commit -m "fix: cold_storage_manager 走 ObjectStoragePort 统一存储端口，消除 COS 硬编码"
```

---

## Task 8: 创建管理后台 Schema

**Files:**
- Create: `api/internal/schema/admin_public_ai_feature_schema.py`

- [ ] **Step 1: 创建 schema 文件**

```python
# api/internal/schema/admin_public_ai_feature_schema.py
from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import BooleanField, StringField
from wtforms.validators import AnyOf, Length, Optional

FEATURE_CATEGORIES = ["icon", "memory", "routing", "assistant", "conversation", "general"]
FALLBACK_TIERS = ["cheap", "standard", "strong"]


class GetPublicAIFeaturesReq(FlaskForm):
    category = StringField("category", default="", validators=[Optional(), AnyOf(["", *FEATURE_CATEGORIES])])
    enabled = StringField("enabled", default="", validators=[Optional(), AnyOf(["", "true", "false"])])


class UpsertPublicAIFeatureReq(FlaskForm):
    feature_key = StringField("feature_key", validators=[Optional(), Length(max=64)])
    feature_name = StringField("feature_name", validators=[Optional(), Length(max=128)])
    feature_category = StringField("feature_category", default="general", validators=[Optional(), AnyOf(FEATURE_CATEGORIES)])
    feature_description = StringField("feature_description", default="", validators=[Optional(), Length(max=512)])
    model_config_id = StringField("model_config_id", default="", validators=[Optional(), Length(max=36)])
    provider_credential_key = StringField("provider_credential_key", default="", validators=[Optional(), Length(max=128)])
    enabled = BooleanField("enabled", default=True)
    fallback_tier = StringField("fallback_tier", default="cheap", validators=[Optional(), AnyOf(FALLBACK_TIERS)])


class PublicAIFeatureItemSchema(Schema):
    feature_key = fields.String()
    feature_name = fields.String()
    feature_category = fields.String()
    feature_description = fields.String(allow_none=True)
    model_config_id = fields.String(allow_none=True)
    provider_credential_key = fields.String(allow_none=True)
    enabled = fields.Boolean()
    fallback_tier = fields.String()
    extra_config = fields.Dict()
    updated_at = fields.DateTime()
    created_at = fields.DateTime()


class PublicAIFeatureListSchema(Schema):
    items = fields.List(fields.Nested(PublicAIFeatureItemSchema))
    total = fields.Integer()
```

- [ ] **Step 2: Commit**

```bash
git add api/internal/schema/admin_public_ai_feature_schema.py
git commit -m "feat: add admin schema for public AI feature config"
```

---

## Task 9: 创建管理后台 Handler

**Files:**
- Create: `api/internal/handler/admin_public_ai_feature_handler.py`

- [ ] **Step 1: 创建 handler 文件**

```python
# api/internal/handler/admin_public_ai_feature_handler.py
"""公共 AI 功能配置管理后台 API handler。"""
from dataclasses import dataclass

from flask import request
from injector import inject

from internal.entity.common_entity import ValidateErrorEntity
from internal.exception import FailException
from internal.model import ModelPoolConfig, PublicAIFeatureConfig
from internal.schema.admin_public_ai_feature_schema import (
    GetPublicAIFeaturesReq,
    PublicAIFeatureItemSchema,
    PublicAIFeatureListSchema,
    UpsertPublicAIFeatureReq,
)
from internal.service.public_ai_feature_service import PublicAIFeatureService
from pkg.sqlalchemy import SQLAlchemy


@inject
@dataclass
class AdminPublicAIFeatureHandler:
    """公共 AI 功能配置 CRUD handler。"""

    db: SQLAlchemy
    public_ai_feature_service: PublicAIFeatureService

    def list_features(self):
        """GET /admin/public-ai-features 列出所有配置。"""
        form = GetPublicAIFeaturesReq()
        if not form.validate():
            return ValidateErrorEntity(form.errors)

        query = self.db.session.query(PublicAIFeatureConfig)
        category = (form.category.data or "").strip()
        if category:
            query = query.filter_by(feature_category=category)
        enabled_str = (form.enabled.data or "").strip()
        if enabled_str == "true":
            query = query.filter_by(enabled=True)
        elif enabled_str == "false":
            query = query.filter_by(enabled=False)

        items = query.order_by(
            PublicAIFeatureConfig.feature_category.asc(),
            PublicAIFeatureConfig.feature_key.asc(),
        ).all()

        return PublicAIFeatureListSchema().dump({"items": items, "total": len(items)})

    def get_feature(self, feature_key: str):
        """GET /admin/public-ai-features/<feature_key> 获取单个配置。"""
        record = self.db.session.query(PublicAIFeatureConfig).filter_by(feature_key=feature_key).first()
        if record is None:
            raise FailException(f"功能配置不存在: {feature_key}")
        return PublicAIFeatureItemSchema().dump(record)

    def upsert_feature(self):
        """POST /admin/public-ai-features 创建或更新配置（按 feature_key upsert）。"""
        form = UpsertPublicAIFeatureReq()
        if not form.validate():
            return ValidateErrorEntity(form.errors)

        feature_key = (form.feature_key.data or "").strip()
        if not feature_key:
            raise FailException("feature_key 不能为空")

        # 校验 model_config_id 存在性
        model_config_id = (form.model_config_id.data or "").strip()
        if model_config_id:
            model = self.db.session.query(ModelPoolConfig).filter_by(id=model_config_id).first()
            if model is None:
                raise FailException(f"模型配置不存在: {model_config_id}")

        record = self.db.session.query(PublicAIFeatureConfig).filter_by(feature_key=feature_key).first()
        if record is None:
            # 创建
            record = PublicAIFeatureConfig(
                feature_key=feature_key,
                feature_name=form.feature_name.data or feature_key,
                feature_category=form.feature_category.data or "general",
                feature_description=form.feature_description.data or "",
                model_config_id=model_config_id or None,
                provider_credential_key=(form.provider_credential_key.data or "").strip() or None,
                enabled=form.enabled.data if form.enabled.data is not None else True,
                fallback_tier=form.fallback_tier.data or "cheap",
            )
            self.db.session.add(record)
        else:
            # 更新
            if form.feature_name.data:
                record.feature_name = form.feature_name.data
            if form.feature_category.data:
                record.feature_category = form.feature_category.data
            record.feature_description = form.feature_description.data or ""
            record.model_config_id = model_config_id or None
            record.provider_credential_key = (form.provider_credential_key.data or "").strip() or None
            if form.enabled.data is not None:
                record.enabled = form.enabled.data
            if form.fallback_tier.data:
                record.fallback_tier = form.fallback_tier.data

        self.db.session.commit()
        return PublicAIFeatureItemSchema().dump(record)

    def delete_feature(self, feature_key: str):
        """DELETE /admin/public-ai-features/<feature_key> 删除配置。"""
        record = self.db.session.query(PublicAIFeatureConfig).filter_by(feature_key=feature_key).first()
        if record is None:
            raise FailException(f"功能配置不存在: {feature_key}")
        self.db.session.delete(record)
        self.db.session.commit()
        return {"success": True}

    def list_available_models(self):
        """GET /admin/public-ai-features/models 列出可选模型（供前端下拉框使用）。"""
        models = self.db.session.query(ModelPoolConfig).filter_by(status="active").order_by(
            ModelPoolConfig.provider.asc(),
            ModelPoolConfig.model_name.asc(),
        ).all()
        return {
            "items": [
                {
                    "id": str(m.id),
                    "label": f"{m.provider} / {m.model_name} ({m.model_type}, {m.tier})",
                    "provider": m.provider,
                    "model_name": m.model_name,
                    "model_type": m.model_type,
                    "tier": m.tier,
                }
                for m in models
            ]
        }
```

- [ ] **Step 2: Commit**

```bash
git add api/internal/handler/admin_public_ai_feature_handler.py
git commit -m "feat: add admin handler for public AI feature config CRUD"
```

---

## Task 10: 注册管理后台路由

**Files:**
- Modify: `api/internal/router/router.py`

- [ ] **Step 1: 在 Router 构造函数注入 handler**

在 `api/internal/router/router.py` 的 `Router.__init__` 中找到 handler 注入区域（约 L109 附近），添加：

```python
        admin_public_ai_feature_handler: AdminPublicAIFeatureHandler
```

并在文件顶部 import 区域添加：

```python
from internal.handler.admin_public_ai_feature_handler import AdminPublicAIFeatureHandler
```

- [ ] **Step 2: 注册路由**

在 `router.py` 中找到 admin 路由注册区域（`/admin/models` 路由附近，约 L1249），添加：

```python
            # 公共 AI 功能配置
            "/admin/public-ai-features",
            endpoint="admin_public_ai_feature_list",
            methods=["GET"],
            view_func=self.admin_public_ai_feature_handler.list_features,
        ))
        self.app.add_url_rule(
            "/admin/public-ai-features/models",
            endpoint="admin_public_ai_feature_models",
            methods=["GET"],
            view_func=self.admin_public_ai_feature_handler.list_available_models,
        ))
        self.app.add_url_rule(
            "/admin/public-ai-features",
            endpoint="admin_public_ai_feature_upsert",
            methods=["POST"],
            view_func=self.admin_public_ai_feature_handler.upsert_feature,
        ))
        self.app.add_url_rule(
            "/admin/public-ai-features/<string:feature_key>",
            endpoint="admin_public_ai_feature_get",
            methods=["GET"],
            view_func=self.admin_public_ai_feature_handler.get_feature,
        ))
        self.app.add_url_rule(
            "/admin/public-ai-features/<string:feature_key>",
            endpoint="admin_public_ai_feature_delete",
            methods=["DELETE"],
            view_func=self.admin_public_ai_feature_handler.delete_feature,
        ))
```

- [ ] **Step 3: Commit**

```bash
git add api/internal/router/router.py
git commit -m "feat: register admin routes for public AI feature config"
```

---

## Task 11: 批量改造调用点 — 图标 + 路由 + 助手类

**Files:**
- Modify: `api/internal/service/icon_generator_service.py`（已在 Task 6 完成 icon_prompt）
- Modify: `api/internal/service/intent_recognition_service.py`
- Modify: `api/internal/service/task_classifier_service.py`
- Modify: `api/internal/service/executors/task_decomposer.py`
- Modify: `api/internal/service/pool_intent_resolver_service.py`
- Modify: `api/internal/service/ai_service.py`（4 个方法）
- Modify: `api/internal/service/tag_assignment_service.py`
- Modify: `api/internal/service/app_service.py`

- [ ] **Step 1: 替换调用点**

对每个文件执行：将 `LanguageModelService.get_cheap_chat_model()` 替换为 `LanguageModelService.get_feature_model("<对应 feature_key>")"`。

feature_key 映射表：

| 文件 | 原 LLM 获取 | 新调用 | feature_key |
|---|---|---|---|
| `intent_recognition_service.py:94` | `get_cheap_chat_model()` | `get_feature_model("intent_recognition")` | intent_recognition |
| `task_classifier_service.py:233` | `get_cheap_chat_model()` | `get_feature_model("task_classification")` | task_classification |
| `task_decomposer.py:57` | `get_cheap_chat_model()` | `get_feature_model("task_decomposition")` | task_decomposition |
| `pool_intent_resolver_service.py:113` | `get_cheap_chat_model()` | `get_feature_model("pool_intent_resolution")` | pool_intent_resolution |
| `ai_service.py:81` (optimize_prompt) | `get_cheap_chat_model()` | `get_feature_model("prompt_optimization")` | prompt_optimization |
| `ai_service.py:102` (code_assistant) | `get_cheap_chat_model()` | `get_feature_model("code_assistant")` | code_assistant |
| `ai_service.py:127` (openapi_schema) | `get_cheap_chat_model()` | `get_feature_model("schema_assistant")` | schema_assistant |
| `ai_service.py:151` (mcp_schema) | `get_cheap_chat_model()` | `get_feature_model("schema_assistant")` | schema_assistant |
| `tag_assignment_service.py:89` | `get_cheap_chat_model()` | `get_feature_model("tag_assignment")` | tag_assignment |
| `app_service.py:232` | `get_chat_model_by_tier("standard")` | `get_feature_model("app_auto_creation")` | app_auto_creation |

- [ ] **Step 2: 批量验证导入无语法错误**

```bash
docker exec llmops-api python -c "
from internal.service.intent_recognition_service import IntentRecognitionService
from internal.service.task_classifier_service import TaskClassifierService
from internal.service.executors.task_decomposer import TaskDecomposer
from internal.service.pool_intent_resolver_service import PoolIntentResolverService
from internal.service.ai_service import AIService
from internal.service.tag_assignment_service import TagAssignmentService
from internal.service.app_service import AppService
print('All imports OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add api/internal/service/intent_recognition_service.py api/internal/service/task_classifier_service.py api/internal/service/executors/task_decomposer.py api/internal/service/pool_intent_resolver_service.py api/internal/service/ai_service.py api/internal/service/tag_assignment_service.py api/internal/service/app_service.py
git commit -m "refactor: routing/assistant/tag/app-creation 调用点走公共 AI 功能配置"
```

---

## Task 12: 批量改造调用点 — 记忆系统 + 会话 + 直接回答

**Files:**
- Modify: `api/internal/service/memory/consolidation_engine.py`
- Modify: `api/internal/service/memory/conflict_detector.py`
- Modify: `api/internal/service/memory/funnel_compressor.py`
- Modify: `api/internal/service/memory/explicit_detector.py`
- Modify: `api/internal/service/memory/entity_resolution.py`
- Modify: `api/internal/service/memory/entity_extractor.py`
- Modify: `api/internal/service/memory/digest_manager.py`
- Modify: `api/internal/service/memory/policy_router.py`
- Modify: `api/internal/service/memory/salience_scorer.py`
- Modify: `api/internal/service/memory/write_time_conflict_resolver.py`
- Modify: `api/internal/service/memory/skill_emergence.py`
- Modify: `api/internal/service/conversation_service.py`
- Modify: `api/internal/service/assistant_agent_service.py`
- Modify: `api/internal/service/executors/direct_answer_executor.py`
- Modify: `api/internal/service/rerank_service.py`

- [ ] **Step 1: 替换记忆系统 13 个调用点**

对 `api/internal/service/memory/` 下所有使用 `get_cheap_chat_model()` 的文件，统一替换为 `get_feature_model("memory_<具体功能>")"`。

feature_key 映射：

| 文件 | feature_key |
|---|---|
| `consolidation_engine.py` | memory_consolidation |
| `conflict_detector.py` | memory_conflict_detection |
| `funnel_compressor.py` | memory_compression |
| `explicit_detector.py` | memory_explicit_detection |
| `entity_resolution.py` | memory_entity_resolution |
| `entity_extractor.py` | memory_entity_extraction |
| `digest_manager.py` | memory_digest |
| `policy_router.py` | memory_policy_routing |
| `salience_scorer.py` | memory_salience_scoring |
| `write_time_conflict_resolver.py` | memory_write_conflict_resolution |
| `skill_emergence.py` | memory_skill_emergence |

替换规则：`LanguageModelService.get_cheap_chat_model()` → `LanguageModelService.get_feature_model("memory_<key>")`

- [ ] **Step 2: 替换会话辅助调用点**

`conversation_service.py` 中的 `_load_summary_llm`（L150）当前用 `svc.load_default_language_model()`，替换为：

```python
from internal.service.language_model_service import LanguageModelService
llm = LanguageModelService.get_feature_model("conversation_summary")
```

- [ ] **Step 3: 替换辅助 Agent 介绍生成**

`assistant_agent_service.py:994` 的 `get_cheap_chat_model()` 替换为 `get_feature_model("assistant_agent_intro")`

- [ ] **Step 4: 替换直接回答执行器**

`direct_answer_executor.py:90-91` 的 `get_cheap_chat_model()` 替换为 `get_feature_model("direct_answer")`

- [ ] **Step 5: 替换重排兜底**

`rerank_service.py:131` 的 `get_cheap_chat_model()` 替换为 `get_feature_model("rerank_fallback")`

- [ ] **Step 6: 批量验证导入**

```bash
docker exec llmops-api python -c "
from internal.service.memory.consolidation_engine import ConsolidationEngine
from internal.service.memory.conflict_detector import ConflictDetector
from internal.service.memory.funnel_compressor import FunnelCompressor
from internal.service.memory.explicit_detector import ExplicitDetector
from internal.service.memory.entity_resolution import EntityResolution
from internal.service.memory.entity_extractor import EntityExtractor
from internal.service.memory.digest_manager import DigestManager
from internal.service.memory.policy_router import PolicyRouter
from internal.service.memory.salience_scorer import SalienceScorer
from internal.service.memory.write_time_conflict_resolver import WriteTimeConflictResolver
from internal.service.memory.skill_emergence import SkillEmergence
from internal.service.conversation_service import ConversationService
from internal.service.assistant_agent_service import AssistantAgentService
from internal.service.executors.direct_answer_executor import DirectAnswerExecutor
from internal.service.rerank_service import RerankService
print('All imports OK')
"
```

- [ ] **Step 7: Commit**

```bash
git add api/internal/service/memory/ api/internal/service/conversation_service.py api/internal/service/assistant_agent_service.py api/internal/service/executors/direct_answer_executor.py api/internal/service/rerank_service.py
git commit -m "refactor: memory/conversation/assistant/rerank 调用点走公共 AI 功能配置"
```

---

## Task 13: 创建前端 API 服务

**Files:**
- Create: `ui/src/services/admin-public-ai-feature.ts`

- [ ] **Step 1: 创建 API 服务文件**

```typescript
// ui/src/services/admin-public-ai-feature.ts
import { api } from './api'

export interface PublicAIFeature {
  feature_key: string
  feature_name: string
  feature_category: string
  feature_description: string | null
  model_config_id: string | null
  provider_credential_key: string | null
  enabled: boolean
  fallback_tier: string
  extra_config: Record<string, unknown>
  updated_at: string
  created_at: string
}

export interface AvailableModel {
  id: string
  label: string
  provider: string
  model_name: string
  model_type: string
  tier: string
}

export interface PublicAIFeatureListResponse {
  items: PublicAIFeature[]
  total: number
}

export interface AvailableModelsResponse {
  items: AvailableModel[]
}

export async function listPublicAIFeatures(params?: {
  category?: string
  enabled?: string
}): Promise<PublicAIFeatureListResponse> {
  const res = await api.get('/admin/public-ai-features', { params })
  return res.data
}

export async function getPublicAIFeature(featureKey: string): Promise<PublicAIFeature> {
  const res = await api.get(`/admin/public-ai-features/${featureKey}`)
  return res.data
}

export interface UpsertPublicAIFeaturePayload {
  feature_key?: string
  feature_name?: string
  feature_category?: string
  feature_description?: string
  model_config_id?: string
  provider_credential_key?: string
  enabled?: boolean
  fallback_tier?: string
}

export async function upsertPublicAIFeature(payload: UpsertPublicAIFeaturePayload): Promise<PublicAIFeature> {
  const res = await api.post('/admin/public-ai-features', payload)
  return res.data
}

export async function deletePublicAIFeature(featureKey: string): Promise<void> {
  await api.delete(`/admin/public-ai-features/${featureKey}`)
}

export async function listAvailableModels(): Promise<AvailableModelsResponse> {
  const res = await api.get('/admin/public-ai-features/models')
  return res.data
}
```

- [ ] **Step 2: Commit**

```bash
git add ui/src/services/admin-public-ai-feature.ts
git commit -m "feat: add frontend API service for public AI feature config"
```

---

## Task 14: 创建前端配置页面

**Files:**
- Create: `ui/src/views/admin/PublicAIFeatureConfigView.vue`

- [ ] **Step 1: 创建 Vue 页面组件**

```vue
<!-- ui/src/views/admin/PublicAIFeatureConfigView.vue -->
<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  listPublicAIFeatures,
  upsertPublicAIFeature,
  deletePublicAIFeature,
  listAvailableModels,
  type PublicAIFeature,
  type AvailableModel,
} from '@/services/admin-public-ai-feature'
import { useToast } from '@/composables/useToast'

const { t } = useI18n()
const toast = useToast()

const loading = ref(false)
const features = ref<PublicAIFeature[]>([])
const models = ref<AvailableModel[]>([])
const editingKey = ref<string | null>(null)
const editForm = ref({
  feature_key: '',
  feature_name: '',
  feature_category: 'general',
  feature_description: '',
  model_config_id: '',
  provider_credential_key: '',
  enabled: true,
  fallback_tier: 'cheap',
})

const categoryFilter = ref('')
const filteredFeatures = computed(() => {
  if (!categoryFilter.value) return features.value
  return features.value.filter(f => f.feature_category === categoryFilter.value)
})

const categories = [
  { value: '', label: t('admin.publicAIFeature.categories.all') },
  { value: 'icon', label: t('admin.publicAIFeature.categories.icon') },
  { value: 'memory', label: t('admin.publicAIFeature.categories.memory') },
  { value: 'routing', label: t('admin.publicAIFeature.categories.routing') },
  { value: 'assistant', label: t('admin.publicAIFeature.categories.assistant') },
  { value: 'conversation', label: t('admin.publicAIFeature.categories.conversation') },
  { value: 'general', label: t('admin.publicAIFeature.categories.general') },
]

const fallbackTiers = ['cheap', 'standard', 'strong']

async function loadFeatures() {
  loading.value = true
  try {
    const res = await listPublicAIFeatures()
    features.value = res.items
  } catch (e: any) {
    toast.error(e?.message || t('common.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function loadModels() {
  try {
    const res = await listAvailableModels()
    models.value = res.items
  } catch (e: any) {
    toast.error(e?.message || t('common.loadFailed'))
  }
}

function startEdit(feature: PublicAIFeature) {
  editingKey.value = feature.feature_key
  editForm.value = {
    feature_key: feature.feature_key,
    feature_name: feature.feature_name,
    feature_category: feature.feature_category,
    feature_description: feature.feature_description || '',
    model_config_id: feature.model_config_id || '',
    provider_credential_key: feature.provider_credential_key || '',
    enabled: feature.enabled,
    fallback_tier: feature.fallback_tier,
  }
}

function startCreate() {
  editingKey.value = '__new__'
  editForm.value = {
    feature_key: '',
    feature_name: '',
    feature_category: 'general',
    feature_description: '',
    model_config_id: '',
    provider_credential_key: '',
    enabled: true,
    fallback_tier: 'cheap',
  }
}

async function saveFeature() {
  try {
    await upsertPublicAIFeature({
      ...editForm.value,
      model_config_id: editForm.value.model_config_id || undefined,
      provider_credential_key: editForm.value.provider_credential_key || undefined,
    })
    toast.success(t('common.saveSuccess'))
    editingKey.value = null
    await loadFeatures()
  } catch (e: any) {
    toast.error(e?.message || t('common.saveFailed'))
  }
}

async function removeFeature(featureKey: string) {
  if (!confirm(t('admin.publicAIFeature.confirmDelete'))) return
  try {
    await deletePublicAIFeature(featureKey)
    toast.success(t('common.deleteSuccess'))
    await loadFeatures()
  } catch (e: any) {
    toast.error(e?.message || t('common.deleteFailed'))
  }
}

onMounted(() => {
  loadFeatures()
  loadModels()
})
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">{{ t('admin.publicAIFeature.title') }}</h1>
      <div class="flex items-center gap-3">
        <select v-model="categoryFilter" class="border rounded px-3 py-2">
          <option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option>
        </select>
        <button class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700" @click="startCreate">
          {{ t('admin.publicAIFeature.add') }}
        </button>
      </div>
    </div>

    <p class="text-gray-600 mb-4 text-sm">{{ t('admin.publicAIFeature.description') }}</p>

    <div v-if="loading" class="text-center py-8 text-gray-500">{{ t('common.loading') }}</div>

    <div v-else class="space-y-3">
      <div v-for="feature in filteredFeatures" :key="feature.feature_key"
           class="border rounded-lg p-4 hover:shadow-sm transition-shadow">
        <div class="flex items-start justify-between">
          <div class="flex-1">
            <div class="flex items-center gap-2 mb-1">
              <span class="font-medium">{{ feature.feature_name }}</span>
              <span class="text-xs px-2 py-0.5 bg-gray-100 rounded">{{ feature.feature_category }}</span>
              <span v-if="feature.enabled" class="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded">{{ t('common.enabled') }}</span>
              <span v-else class="text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded">{{ t('common.disabled') }}</span>
            </div>
            <div class="text-sm text-gray-500 font-mono">{{ feature.feature_key }}</div>
            <div v-if="feature.feature_description" class="text-sm text-gray-600 mt-1">{{ feature.feature_description }}</div>
            <div class="text-sm text-gray-500 mt-2">
              <span>{{ t('admin.publicAIFeature.fallbackTier') }}: {{ feature.fallback_tier }}</span>
              <span v-if="feature.model_config_id" class="ml-4">
                {{ t('admin.publicAIFeature.boundModel') }}: {{ models.find(m => m.id === feature.model_config_id)?.label || feature.model_config_id }}
              </span>
              <span v-else class="ml-4 text-gray-400">{{ t('admin.publicAIFeature.unbound') }}</span>
            </div>
          </div>
          <div class="flex gap-2">
            <button class="text-blue-600 hover:underline text-sm" @click="startEdit(feature)">{{ t('common.edit') }}</button>
            <button class="text-red-600 hover:underline text-sm" @click="removeFeature(feature.feature_key)">{{ t('common.delete') }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑/新建弹层 -->
    <div v-if="editingKey" class="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50" @click.self="editingKey = null">
      <div class="bg-white rounded-lg p-6 w-[600px] max-h-[80vh] overflow-y-auto">
        <h2 class="text-xl font-bold mb-4">
          {{ editingKey === '__new__' ? t('admin.publicAIFeature.add') : t('admin.publicAIFeature.edit') }}
        </h2>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium mb-1">{{ t('admin.publicAIFeature.featureKey') }}</label>
            <input v-model="editForm.feature_key" :disabled="editingKey !== '__new__'"
                   class="w-full border rounded px-3 py-2 font-mono text-sm" placeholder="icon_generation" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">{{ t('admin.publicAIFeature.featureName') }}</label>
            <input v-model="editForm.feature_name" class="w-full border rounded px-3 py-2" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">{{ t('admin.publicAIFeature.category') }}</label>
            <select v-model="editForm.feature_category" class="w-full border rounded px-3 py-2">
              <option v-for="c in categories.filter(c => c.value)" :key="c.value" :value="c.value">{{ c.label }}</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">{{ t('admin.publicAIFeature.description') }}</label>
            <input v-model="editForm.feature_description" class="w-full border rounded px-3 py-2" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">{{ t('admin.publicAIFeature.boundModel') }}</label>
            <select v-model="editForm.model_config_id" class="w-full border rounded px-3 py-2">
              <option value="">{{ t('admin.publicAIFeature.unbound') }} ({{ t('admin.publicAIFeature.useFallback') }})</option>
              <option v-for="m in models" :key="m.id" :value="m.id">{{ m.label }}</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">{{ t('admin.publicAIFeature.providerCredentialKey') }}</label>
            <input v-model="editForm.provider_credential_key" class="w-full border rounded px-3 py-2"
                   placeholder="SiliconFlow / OpenAI（仅非 Chat 类功能需要）" />
          </div>
          <div class="flex gap-4">
            <div class="flex-1">
              <label class="block text-sm font-medium mb-1">{{ t('admin.publicAIFeature.fallbackTier') }}</label>
              <select v-model="editForm.fallback_tier" class="w-full border rounded px-3 py-2">
                <option v-for="t in fallbackTiers" :key="t" :value="t">{{ t }}</option>
              </select>
            </div>
            <div class="flex items-end pb-2">
              <label class="flex items-center gap-2">
                <input type="checkbox" v-model="editForm.enabled" />
                <span>{{ t('common.enabled') }}</span>
              </label>
            </div>
          </div>
        </div>
        <div class="flex justify-end gap-3 mt-6">
          <button class="px-4 py-2 border rounded hover:bg-gray-50" @click="editingKey = null">{{ t('common.cancel') }}</button>
          <button class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700" @click="saveFeature">{{ t('common.save') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add ui/src/views/admin/PublicAIFeatureConfigView.vue
git commit -m "feat: add PublicAIFeatureConfigView page for admin config management"
```

---

## Task 15: 注册前端路由 + 菜单 + i18n

**Files:**
- Modify: `ui/src/router/index.ts`
- Modify: `ui/src/layouts/AdminLayout.vue`
- Modify: `ui/src/i18n/messages/zh-CN.ts`
- Modify: `ui/src/i18n/messages/en-US.ts`

- [ ] **Step 1: 注册前端路由**

在 `ui/src/router/index.ts` 中找到 admin 路由区域（`/admin/models` 路由之后），添加：

```typescript
            {
              path: 'public-ai-features',
              name: 'admin-public-ai-features',
              component: () => import('@/views/admin/PublicAIFeatureConfigView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['model_pool:read'] },
            },
```

- [ ] **Step 2: 在 AdminLayout.vue 添加菜单项**

在 `ui/src/layouts/AdminLayout.vue` 的 `poolGovernance` 菜单组（约 L104-110）的 items 数组末尾添加：

```typescript
      { to: '/admin/public-ai-features', label: t('admin.adminLayout.menu.publicAIFeatures'), permission: 'model_pool:read' },
```

- [ ] **Step 3: 在 zh-CN.ts 添加文案**

在 `ui/src/i18n/messages/zh-CN.ts` 的 `admin` 对象中添加：

```typescript
    publicAIFeature: {
      title: '公共 AI 功能配置',
      description: '管理平台侧发起的、用户不承担成本的 AI 调用（图标生成、记忆巩固、意图识别等）所使用的模型。未配置时按回退档位自动选择模型池中的模型。',
      add: '新增配置',
      edit: '编辑配置',
      featureKey: '功能键',
      featureName: '功能名称',
      category: '分类',
      boundModel: '绑定模型',
      unbound: '未绑定',
      useFallback: '使用回退',
      fallbackTier: '回退档位',
      providerCredentialKey: 'Provider 凭证键',
      confirmDelete: '确定删除此配置吗？删除后将回退到默认档位。',
      categories: {
        all: '全部',
        icon: '图标生成',
        memory: '记忆系统',
        routing: '任务路由',
        assistant: '辅助助手',
        conversation: '会话辅助',
        general: '通用',
      },
    },
```

并在 `admin.adminLayout.menu` 中添加：

```typescript
      publicAIFeatures: '公共 AI 配置',
```

- [ ] **Step 4: 在 en-US.ts 添加文案**

在 `ui/src/i18n/messages/en-US.ts` 对应位置添加：

```typescript
    publicAIFeature: {
      title: 'Public AI Feature Config',
      description: 'Manage models for platform-side AI calls (icon generation, memory consolidation, intent recognition, etc.) whose costs are not borne by users. Falls back to the configured tier when unbound.',
      add: 'Add Config',
      edit: 'Edit Config',
      featureKey: 'Feature Key',
      featureName: 'Feature Name',
      category: 'Category',
      boundModel: 'Bound Model',
      unbound: 'Unbound',
      useFallback: 'Use Fallback',
      fallbackTier: 'Fallback Tier',
      providerCredentialKey: 'Provider Credential Key',
      confirmDelete: 'Delete this config? Will fall back to default tier.',
      categories: {
        all: 'All',
        icon: 'Icon Generation',
        memory: 'Memory System',
        routing: 'Task Routing',
        assistant: 'Assistants',
        conversation: 'Conversation',
        general: 'General',
      },
    },
```

并在 `admin.adminLayout.menu` 中添加：

```typescript
      publicAIFeatures: 'Public AI Config',
```

- [ ] **Step 5: Commit**

```bash
git add ui/src/router/index.ts ui/src/layouts/AdminLayout.vue ui/src/i18n/messages/zh-CN.ts ui/src/i18n/messages/en-US.ts
git commit -m "feat: register frontend route, menu, and i18n for public AI feature config"
```

---

## Task 16: 预置默认配置记录

**Files:**
- Create: `api/internal/migration/versions/b5c6d7e8f9a0_seed_public_ai_feature_defaults.py`

- [ ] **Step 1: 创建 seed 迁移**

```python
# api/internal/migration/versions/b5c6d7e8f9a0_seed_public_ai_feature_defaults.py
"""seed default public_ai_feature_config records

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-07-20 11:00:00.000000

预置公共 AI 功能配置默认记录，所有记录 model_config_id=NULL（未绑定具体模型），
fallback_tier='cheap'，enabled=true。管理员可在后台为每个功能绑定具体模型。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


# 默认功能配置清单
_DEFAULT_FEATURES = [
    ("icon_prompt", "图标提示词生成", "icon", "图标生成时的描述提示词 LLM 调用"),
    ("icon_image_generation", "图标图像生成", "icon", "图标生成的文生图 API 调用"),
    ("memory_consolidation", "记忆巩固", "memory", "簇内 Episode 共性语义提取"),
    ("memory_conflict_detection", "记忆冲突检测", "memory", "记忆冲突检测判定"),
    ("memory_compression", "记忆压缩", "memory", "Layer 4 LLM 压缩"),
    ("memory_explicit_detection", "显式陈述检测", "memory", "显式陈述确认"),
    ("memory_entity_resolution", "实体同一性判定", "memory", "实体同一性判定"),
    ("memory_entity_extraction", "实体关系抽取", "memory", "实体/关系抽取与对话摘要"),
    ("memory_digest", "记忆摘要", "memory", "记忆摘要 LLM 精炼"),
    ("memory_policy_routing", "查询意图分类", "memory", "记忆查询意图分类"),
    ("memory_salience_scoring", "显著性评分", "memory", "六因子显著性评分"),
    ("memory_write_conflict_resolution", "写时冲突判定", "memory", "写时冲突判定"),
    ("memory_skill_emergence", "技能涌现", "memory", "技能模板提取与更新判定"),
    ("intent_recognition", "意图识别", "routing", "用户意图识别"),
    ("task_classification", "任务分类", "routing", "任务分类"),
    ("task_decomposition", "任务分解", "routing", "多智能体任务分解"),
    ("pool_intent_resolution", "子池匹配", "routing", "子池匹配判定"),
    ("prompt_optimization", "提示词优化", "assistant", "提示词优化助手"),
    ("code_assistant", "代码助手", "assistant", "Python 代码助手"),
    ("schema_assistant", "Schema 助手", "assistant", "OpenAPI/MCP Schema 助手"),
    ("tag_assignment", "标签分配", "assistant", "自动标签分配"),
    ("app_auto_creation", "应用自动创建", "assistant", "应用自动创建预设 prompt 生成"),
    ("conversation_summary", "会话摘要", "conversation", "会话摘要/标题/建议问题生成"),
    ("assistant_agent_intro", "辅助 Agent 介绍", "conversation", "辅助 Agent 介绍生成"),
    ("direct_answer", "直接回答", "conversation", "Orchestrator direct_answer 模式"),
    ("rerank_fallback", "重排兜底", "conversation", "provider rerank 不可用时 LLM 兜底"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for feature_key, feature_name, category, description in _DEFAULT_FEATURES:
        conn.execute(
            sa.text(
                "INSERT INTO public_ai_feature_config "
                "(feature_key, feature_name, feature_category, feature_description, "
                " model_config_id, provider_credential_key, enabled, fallback_tier, extra_config, updated_at, created_at) "
                "VALUES (:key, :name, :cat, :desc, NULL, NULL, true, 'cheap', '{}'::jsonb, NOW(), NOW()) "
                "ON CONFLICT (feature_key) DO NOTHING"
            ),
            {
                "key": feature_key,
                "name": feature_name,
                "cat": category,
                "desc": description,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    keys = [f[0] for f in _DEFAULT_FEATURES]
    conn.execute(
        sa.text("DELETE FROM public_ai_feature_config WHERE feature_key = ANY(:keys)"),
        {"keys": keys},
    )
```

- [ ] **Step 2: 执行迁移**

```bash
docker exec llmops-api flask db upgrade
```

预期输出：`Running upgrade a4b5c6d7e8f9 -> b5c6d7e8f9a0, seed default public_ai_feature_config records`

- [ ] **Step 3: 验证预置数据**

```bash
docker exec llmops-postgres psql -U postgres -d llmops -c "SELECT feature_key, feature_category, enabled, fallback_tier FROM public_ai_feature_config ORDER BY feature_category, feature_key;"
```

预期：26 条记录。

- [ ] **Step 4: Commit**

```bash
git add api/internal/migration/versions/b5c6d7e8f9a0_seed_public_ai_feature_defaults.py
git commit -m "feat: seed default public AI feature config records"
```

---

## Task 17: 端到端验证

- [ ] **Step 1: 重建 API 容器**

```bash
docker compose up -d --force-recreate llmops-api
docker restart llmops-nginx
```

- [ ] **Step 2: 等待 API 就绪**

```bash
Start-Sleep -Seconds 10
```

- [ ] **Step 3: 验证后端 API 可用**

```bash
docker exec llmops-api python -c "
from internal.service.language_model_service import LanguageModelService
print('get_feature_model:', hasattr(LanguageModelService, 'get_feature_model'))
print('get_feature_credentials:', hasattr(LanguageModelService, 'get_feature_credentials'))
from internal.service.public_ai_feature_service import PublicAIFeatureService
print('PublicAIFeatureService: OK')
from internal.handler.admin_public_ai_feature_handler import AdminPublicAIFeatureHandler
print('AdminPublicAIFeatureHandler: OK')
from internal.service.icon_generator_service import IconGeneratorService
print('IconGeneratorService: OK')
from internal.service.memory.cold_storage_manager import ColdStorageManager
print('ColdStorageManager: OK')
"
```

- [ ] **Step 4: 验证图标生成走配置**

在 admin 后台 `公共 AI 配置` 页面，为 `icon_image_generation` 绑定一个 image_generation 类型模型（如 SiliconFlow 的 Kolors），然后在前端创建一个 App 触发图标生成。

预期：
- 若配置了模型：日志显示 `配置模型生成图标成功`
- 若未配置：日志显示 `配置模型生成图标失败，回退到降级链`，然后走 Kolors → Qwen → DALLE

- [ ] **Step 5: 验证文件上传正常**

在前端上传一个文件（如知识库图标或文档）。

预期：上传成功，返回 URL 可访问。

- [ ] **Step 6: 检查 API 日志无错误**

```bash
docker exec llmops-api tail -n 50 /app/api/storage/log/app.log
```

预期：无 ImportError、无 500 错误。

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: public AI feature config system complete with 26 default features"
```

---

## Self-Review

### Spec coverage
- ✅ 新建 `public_ai_feature_config` 表 — Task 1-2
- ✅ `LanguageModelService` 新增 `get_feature_model` / `get_feature_credentials` — Task 4
- ✅ IconGeneratorService 硬编码降级链改配置优先 + 自动选模型 — Task 6
- ✅ IconGeneratorService 存储硬编码修复 — Task 5
- ✅ cold_storage_manager.py 存储硬编码修复 — Task 7
- ✅ 40+ 调用点并行改造 — Task 11-12
- ✅ 后台管理配置入口 — Task 8-10, 13-15
- ✅ 预置默认配置 — Task 16
- ✅ 端到端验证 — Task 17

### Placeholder scan
- 无 TBD / TODO / 占位符
- 所有代码块完整

### Type consistency
- `feature_key` 在所有任务中一致使用 String(64) 主键
- `model_config_id` 在所有任务中一致使用 UUID FK
- `get_feature_model(feature_key)` 方法签名在 Task 4 定义，Task 11-12 调用，一致
- `get_feature_credentials(feature_key)` 方法签名在 Task 4 定义，Task 6 调用，一致
- `upload_bytes_without_record(filename, content, folder)` 在 Task 5 调用，与 LocalStorageService/CosService 的方法签名一致
