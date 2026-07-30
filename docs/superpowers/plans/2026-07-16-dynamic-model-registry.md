# 动态模型注册表实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 废弃静态 yaml 注册表，所有模型/供应商配置存入数据库，支持 CRUD 管理和动态懒加载，接入硅基流动等第三方 OpenAI 兼容接口。

**Architecture:** 三表结构（ModelProviderConfig + ModelPoolConfig + ModelKeyConfig），LanguageModelManager 改造为懒加载缓存管理器（TTL 60s + RLock 线程安全），ModelClassRegistry 提供 (compatible_api, model_type) → model_class 二元组映射，CRUD 操作后主动失效缓存。

**Tech Stack:** Flask + SQLAlchemy（同步）+ injector 依赖注入 + Alembic 迁移 + Celery + Vue 3 + Arco Design + TypeScript

**Alembic Head:** `s3d4e5f6a7b8`（drop_memory_candidate_table）

**设计文档:** `docs/superpowers/specs/2026-07-16-dynamic-model-registry-design.md`

---

## File Structure

### 新增文件

| 文件 | 职责 |
|---|---|
| `api/internal/model/model_provider_entity.py` | ModelProviderConfig ORM 实体 |
| `api/internal/core/language_model/model_class_registry.py` | (compatible_api, model_type) → model_class 映射 |
| `api/internal/service/admin_model_provider_service.py` | Provider CRUD service |
| `api/internal/handler/admin_model_provider_handler.py` | Provider HTTP handler |
| `api/internal/schema/admin_model_provider_schema.py` | Provider 请求/响应 schema |
| `api/internal/migration/versions/t6e7f8a9b0c1_create_model_provider_config.py` | 迁移 1：创建 provider 表 |
| `api/internal/migration/versions/u7f8a9b0c1d2_import_builtin_providers.py` | 迁移 2：导入 10 个内置 provider |
| `api/internal/migration/versions/v8a9b0c1d2e3_auto_create_user_providers.py` | 迁移 3：自动创建用户自定义 provider |
| `api/internal/migration/versions/w9b0c1d2e3f4_alter_model_pool_config.py` | 迁移 4：改造 model_pool_config |
| `ui/src/services/admin-model-providers.ts` | Provider API service |
| `ui/src/views/admin/ModelProvidersView.vue` | Provider 管理页 |

### 改造文件

| 文件 | 改动 |
|---|---|
| `api/internal/model/model_pool_entity.py` | ModelPoolConfig 删 base_url，加 model_type/compatible_api |
| `api/internal/core/language_model/language_model_manager.py` | 改造为懒加载缓存 |
| `api/internal/core/language_model/entities/model_entity.py` | 扩展 ModelType 枚举 |
| `api/internal/core/language_model/entities/provider_entity.py` | 移除 yaml 加载逻辑 |
| `api/internal/service/language_model_service.py` | _load_model_components 改造 |
| `api/internal/service/runtime_model_pool_service.py` | build_llm_config 从 Provider 获取 base_url |
| `api/internal/service/admin_model_pool_service.py` | 增加 provider 校验 + 缓存失效 |
| `api/internal/schema/admin_model_pool_schema.py` | 加 model_type/compatible_api，删 base_url |
| `api/internal/service/admin_rbac_service.py` | DEFAULT_PERMISSIONS 加 provider 权限 |
| `api/internal/router/router.py` | 注册 Provider 路由 |
| `api/app/http/app.py` | 启动逻辑改造 |
| `ui/src/views/admin/ModelsView.vue` | 表单改造 |
| `ui/src/views/admin/ModelKeysView.vue` | provider 下拉数据源改造 |
| `ui/src/router/index.ts` | 新增 provider 路由 |
| `ui/src/i18n/messages/zh-CN.ts` | 新增 modelProviders 命名空间 |
| `ui/src/i18n/messages/en-US.ts` | 同上 |

### 删除文件

| 文件 | 说明 |
|---|---|
| `api/internal/core/language_model/providers/` | 整个 yaml 目录（迁移完成后手动删除） |

---

## Task 1: 创建 ModelProviderConfig ORM 实体

**Files:**
- Create: `api/internal/model/model_provider_entity.py`

- [ ] **Step 1: 创建 ORM 实体文件**

```python
# api/internal/model/model_provider_entity.py
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ModelProviderConfig(db.Model):
    """模型供应商配置表 — 存储供应商元数据与统一 base_url"""
    __tablename__ = "model_provider_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_model_provider_config_id"),
        Index("ix_model_provider_config_name", "name", unique=True),
        Index("ix_model_provider_config_status", "status"),
    )

    id = Column(UUID, nullable=False, default=uuid4, server_default=text("uuid_generate_v4()"))
    name = Column(String(128), nullable=False)
    label = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=True)
    icon = Column(String(512), nullable=True)
    background = Column(String(32), nullable=False, server_default=text("'#FFFFFF'::character varying"))
    default_base_url = Column(String(512), nullable=False)
    supported_model_types = Column(JSONB, nullable=False, server_default=text("'[\"chat\"]'::jsonb"))
    status = Column(String(32), nullable=False, server_default=text("'active'::character varying"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/model/model_provider_entity.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/model/model_provider_entity.py
git commit -m "feat: add ModelProviderConfig ORM entity"
```

---

## Task 2: 迁移 1 — 创建 model_provider_config 表

**Files:**
- Create: `api/internal/migration/versions/t6e7f8a9b0c1_create_model_provider_config.py`

- [ ] **Step 1: 创建迁移脚本**

```python
# api/internal/migration/versions/t6e7f8a9b0c1_create_model_provider_config.py
"""create model_provider_config table

Revision ID: t6e7f8a9b0c1
Revises: s3d4e5f6a7b8
Create Date: 2026-07-16 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "t6e7f8a9b0c1"
down_revision = "s3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_provider_config",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=512), nullable=True),
        sa.Column("background", sa.String(length=32), nullable=False, server_default=sa.text("'#FFFFFF'::character varying")),
        sa.Column("default_base_url", sa.String(length=512), nullable=False),
        sa.Column("supported_model_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[\"chat\"]'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'::character varying")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_model_provider_config_id"),
    )
    op.create_index("ix_model_provider_config_name", "model_provider_config", ["name"], unique=True)
    op.create_index("ix_model_provider_config_status", "model_provider_config", ["status"])


def downgrade() -> None:
    op.drop_index("ix_model_provider_config_status", table_name="model_provider_config")
    op.drop_index("ix_model_provider_config_name", table_name="model_provider_config")
    op.drop_table("model_provider_config")
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/migration/versions/t6e7f8a9b0c1_create_model_provider_config.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/migration/versions/t6e7f8a9b0c1_create_model_provider_config.py
git commit -m "feat: add migration to create model_provider_config table"
```

---

## Task 3: 迁移 2 — 导入 10 个内置供应商

**Files:**
- Create: `api/internal/migration/versions/u7f8a9b0c1d2_import_builtin_providers.py`

- [ ] **Step 1: 创建迁移脚本**

```python
# api/internal/migration/versions/u7f8a9b0c1d2_import_builtin_providers.py
"""import 10 builtin providers

Revision ID: u7f8a9b0c1d2
Revises: t6e7f8a9b0c1
Create Date: 2026-07-16 23:01:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "u7f8a9b0c1d2"
down_revision = "t6e7f8a9b0c1"
branch_labels = None
depends_on = None


BUILTIN_PROVIDERS = [
    {
        "name": "atlascloud",
        "label": "Atlas Cloud",
        "default_base_url": "https://api.atlascloud.com/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "deepseek",
        "label": "DeepSeek",
        "default_base_url": "https://api.deepseek.com/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "moonshot",
        "label": "月之暗面",
        "default_base_url": "https://api.moonshot.cn/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "tongyi",
        "label": "通义千问",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "supported_model_types": ["chat", "embedding"],
    },
    {
        "name": "wenxin",
        "label": "文心一言",
        "default_base_url": "https://qianfan.baidubce.com/v2",
        "supported_model_types": ["chat"],
    },
    {
        "name": "ollama",
        "label": "Ollama",
        "default_base_url": "http://localhost:11434/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "google",
        "label": "Google",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "supported_model_types": ["chat"],
    },
    {
        "name": "zhipu",
        "label": "智谱AI",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "supported_model_types": ["chat", "embedding"],
    },
    {
        "name": "grok",
        "label": "xAI Grok",
        "default_base_url": "https://api.x.ai/v1",
        "supported_model_types": ["chat"],
    },
    {
        "name": "openai",
        "label": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "supported_model_types": ["chat", "completion", "embedding"],
    },
]


def upgrade() -> None:
    connection = op.get_bind()
    for provider in BUILTIN_PROVIDERS:
        # 检查是否已存在（幂等）
        existing = connection.execute(
            sa.text("SELECT id FROM model_provider_config WHERE name = :name"),
            {"name": provider["name"]},
        ).fetchone()
        if existing:
            continue
        connection.execute(
            sa.text(
                "INSERT INTO model_provider_config (id, name, label, description, icon, background, "
                "default_base_url, supported_model_types, status, created_at, updated_at) "
                "VALUES (uuid_generate_v4(), :name, :label, '', '', '#FFFFFF', "
                ":default_base_url, CAST(:supported_model_types AS jsonb), 'active', "
                "CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0))"
            ),
            {
                "name": provider["name"],
                "label": provider["label"],
                "default_base_url": provider["default_base_url"],
                "supported_model_types": sa.text(f"'{__import__('json').dumps(provider[\"supported_model_types\"])}'"),
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    names = [p["name"] for p in BUILTIN_PROVIDERS]
    placeholders = ",".join(f":name_{i}" for i in range(len(names)))
    params = {f"name_{i}": names[i] for i in range(len(names))}
    connection.execute(
        sa.text(f"DELETE FROM model_provider_config WHERE name IN ({placeholders})"),
        params,
    )
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/migration/versions/u7f8a9b0c1d2_import_builtin_providers.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/migration/versions/u7f8a9b0c1d2_import_builtin_providers.py
git commit -m "feat: add migration to import 10 builtin providers"
```

---

## Task 4: 迁移 3 — 自动创建用户自定义供应商

**Files:**
- Create: `api/internal/migration/versions/v8a9b0c1d2e3_auto_create_user_providers.py`

- [ ] **Step 1: 创建迁移脚本**

此脚本扫描 `model_pool_config` 表中 `provider` 不在 `model_provider_config` 中的记录，自动为每个缺失的 provider 创建一条记录，`default_base_url` 取该 provider 下第一条记录的 `base_url`。

```python
# api/internal/migration/versions/v8a9b0c1d2e3_auto_create_user_providers.py
"""auto create user custom providers from model_pool_config

Revision ID: v8a9b0c1d2e3
Revises: u7f8a9b0c1d2
Create Date: 2026-07-16 23:02:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "v8a9b0c1d2e3"
down_revision = "u7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """扫描 model_pool_config，为未在 model_provider_config 中的 provider 自动创建记录。
    default_base_url 取该 provider 下第一条非空 base_url，若无则为空字符串。
    注意：此脚本在 base_url 字段删除之前执行。"""
    connection = op.get_bind()

    # 查找 model_pool_config 中存在但 model_provider_config 中不存在的 provider
    missing_providers = connection.execute(
        sa.text(
            "SELECT DISTINCT mpc.provider, "
            "(SELECT mpc2.base_url FROM model_pool_config mpc2 "
            " WHERE mpc2.provider = mpc.provider AND mpc2.base_url IS NOT NULL AND mpc2.base_url != '' "
            " ORDER BY mpc2.created_at ASC LIMIT 1) as base_url "
            "FROM model_pool_config mpc "
            "WHERE mpc.provider NOT IN (SELECT name FROM model_provider_config)"
        )
    ).fetchall()

    for row in missing_providers:
        provider_name = row[0]
        base_url = row[1] or ""
        connection.execute(
            sa.text(
                "INSERT INTO model_provider_config (id, name, label, description, icon, background, "
                "default_base_url, supported_model_types, status, created_at, updated_at) "
                "VALUES (uuid_generate_v4(), :name, :label, '', '', '#FFFFFF', "
                ":default_base_url, '[\"chat\"]'::jsonb, 'active', "
                "CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0))"
            ),
            {
                "name": provider_name,
                "label": provider_name,
                "default_base_url": base_url,
            },
        )


def downgrade() -> None:
    """无法精确回滚自动创建的 provider，仅删除非内置 provider。
    内置 10 个 provider 由迁移 2 管理，此处不删除。"""
    connection = op.get_bind()
    builtin_names = [
        "atlascloud", "deepseek", "moonshot", "tongyi", "wenxin",
        "ollama", "google", "zhipu", "grok", "openai",
    ]
    placeholders = ",".join(f":name_{i}" for i in range(len(builtin_names)))
    params = {f"name_{i}": builtin_names[i] for i in range(len(builtin_names))}
    connection.execute(
        sa.text(f"DELETE FROM model_provider_config WHERE name NOT IN ({placeholders})"),
        params,
    )
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/migration/versions/v8a9b0c1d2e3_auto_create_user_providers.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/migration/versions/v8a9b0c1d2e3_auto_create_user_providers.py
git commit -m "feat: add migration to auto-create user custom providers"
```

---

## Task 5: 迁移 4 — 改造 ModelPoolConfig 表

**Files:**
- Create: `api/internal/migration/versions/w9b0c1d2e3f4_alter_model_pool_config.py`

- [ ] **Step 1: 创建迁移脚本**

此脚本：新增 model_type/compatible_api（nullable）→ 回填默认值 → 设为 NOT NULL → 新增索引 → 删除 base_url 列。

```python
# api/internal/migration/versions/w9b0c1d2e3f4_alter_model_pool_config.py
"""alter model_pool_config: add model_type/compatible_api, drop base_url

Revision ID: w9b0c1d2e3f4
Revises: v8a9b0c1d2e3
Create Date: 2026-07-16 23:03:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "w9b0c1d2e3f4"
down_revision = "v8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 新增字段（nullable）
    op.add_column("model_pool_config", sa.Column("model_type", sa.String(length=32), nullable=True))
    op.add_column("model_pool_config", sa.Column("compatible_api", sa.String(length=32), nullable=True))

    # 2. 回填默认值
    op.execute("UPDATE model_pool_config SET model_type = 'chat' WHERE model_type IS NULL")
    op.execute("UPDATE model_pool_config SET compatible_api = 'openai' WHERE compatible_api IS NULL")

    # 3. 设为 NOT NULL
    op.alter_column("model_pool_config", "model_type", existing_type=sa.String(length=32), nullable=False, server_default=sa.text("'chat'::character varying"))
    op.alter_column("model_pool_config", "compatible_api", existing_type=sa.String(length=32), nullable=False, server_default=sa.text("'openai'::character varying"))

    # 4. 新增索引
    op.create_index("ix_model_pool_config_provider_model", "model_pool_config", ["provider", "model_name"])
    op.create_index("ix_model_pool_config_model_type", "model_pool_config", ["model_type"])

    # 5. 删除 base_url 列
    op.drop_column("model_pool_config", "base_url")


def downgrade() -> None:
    # 恢复 base_url 列
    op.add_column("model_pool_config", sa.Column("base_url", sa.String(length=512), nullable=True))

    # 删除索引
    op.drop_index("ix_model_pool_config_model_type", table_name="model_pool_config")
    op.drop_index("ix_model_pool_config_provider_model", table_name="model_pool_config")

    # 删除字段
    op.drop_column("model_pool_config", "compatible_api")
    op.drop_column("model_pool_config", "model_type")
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/migration/versions/w9b0c1d2e3f4_alter_model_pool_config.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/migration/versions/w9b0c1d2e3f4_alter_model_pool_config.py
git commit -m "feat: add migration to alter model_pool_config (add model_type/compatible_api, drop base_url)"
```

---

## Task 6: 扩展 ModelType 枚举 + 创建 ModelClassRegistry

**Files:**
- Modify: `api/internal/core/language_model/entities/model_entity.py`
- Create: `api/internal/core/language_model/model_class_registry.py`

- [ ] **Step 1: 扩展 ModelType 枚举**

在 `model_entity.py` 中将 ModelType 枚举从 3 种扩展到 11 种（含原有 completion）。

修改 `ModelType` 类：

```python
class ModelType(str, Enum):
    """模型类型枚举"""
    CHAT = "chat"  # 聊天模型
    COMPLETION = "completion"  # 文本生成模型（保留向后兼容）
    EMBEDDING = "embedding"  # 文本嵌入模型
    MULTIMODAL = "multimodal"  # 多模态模型
    IMAGE_GENERATION = "image_generation"  # 图片生成模型
    VIDEO_GENERATION = "video_generation"  # 视频生成模型
    OCR = "ocr"  # OCR 文字识别
    TTS = "tts"  # 语音合成
    ASR = "asr"  # 语音识别
    RERANK = "rerank"  # 重排序模型
```

- [ ] **Step 2: 创建 ModelClassRegistry**

```python
# api/internal/core/language_model/model_class_registry.py
"""(compatible_api, model_type) → model_class 二元组映射注册表"""

from typing import Type

from internal.exception import NotFoundException

from .entities.model_entity import BaseLanguageModel


def _import_class(module_path: str, class_name: str) -> Type[BaseLanguageModel]:
    """动态导入模型类，导入失败时返回 None"""
    try:
        from internal.lib.helper import dynamic_import
        return dynamic_import(module_path, class_name)
    except Exception:
        return None


class ModelClassRegistry:
    """(compatible_api, model_type) → model_class 映射表

    替代原 Provider 中硬编码的 model_class_map，支持通过
    compatible_api + model_type 二元组查找对应的 LangChain 模型类。
    """

    _REGISTRY: dict[tuple[str, str], Type[BaseLanguageModel]] = {
        # OpenAI 兼容协议 — 使用 langchain_openai
        ("openai", "chat"): _import_class("langchain_openai", "ChatOpenAI"),
        ("openai", "multimodal"): _import_class("langchain_openai", "ChatOpenAI"),
        ("openai", "completion"): _import_class("langchain_openai", "OpenAI"),
        ("openai", "embedding"): _import_class("langchain_openai", "OpenAIEmbeddings"),
        # Claude 兼容协议 — 使用 langchain_anthropic
        ("claude", "chat"): _import_class("langchain_anthropic", "ChatAnthropic"),
        ("claude", "multimodal"): _import_class("langchain_anthropic", "ChatAnthropic"),
    }

    @classmethod
    def resolve(cls, compatible_api: str, model_type: str) -> Type[BaseLanguageModel]:
        """根据兼容协议和模型类型查找模型类

        Args:
            compatible_api: 兼容协议标识，如 'openai' / 'claude'
            model_type: 模型类型，如 'chat' / 'embedding' / 'multimodal'

        Returns:
            对应的 LangChain 模型类

        Raises:
            NotFoundException: 不支持的组合
        """
        key = (compatible_api, model_type)
        model_class = cls._REGISTRY.get(key)
        if model_class is None:
            raise NotFoundException(
                f"不支持的模型类型组合: compatible_api={compatible_api}, model_type={model_type}"
            )
        return model_class

    @classmethod
    def is_supported(cls, compatible_api: str, model_type: str) -> bool:
        """检查组合是否支持"""
        return (compatible_api, model_type) in cls._REGISTRY and cls._REGISTRY[(compatible_api, model_type)] is not None

    @classmethod
    def get_supported_combinations(cls) -> list[tuple[str, str]]:
        """获取所有支持的组合列表"""
        return [k for k, v in cls._REGISTRY.items() if v is not None]
```

- [ ] **Step 3: 验证语法**

Run:
```bash
docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/core/language_model/entities/model_entity.py').read()); ast.parse(open('/app/api/internal/core/language_model/model_class_registry.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/internal/core/language_model/entities/model_entity.py api/internal/core/language_model/model_class_registry.py
git commit -m "feat: extend ModelType enum and create ModelClassRegistry"
```

---

## Task 7: 改造 LanguageModelManager 为懒加载缓存

**Files:**
- Modify: `api/internal/core/language_model/language_model_manager.py`

这是核心改造。从静态 yaml 加载改为 DB 懒加载 + TTL 缓存 + RLock 线程安全。

- [ ] **Step 1: 写失败测试**

Create `api/test/internal/core/language_model/test_language_model_manager.py`:

```python
# api/test/internal/core/language_model/test_language_model_manager.py
import time
from unittest.mock import MagicMock, patch

import pytest

from internal.exception import NotFoundException
from internal.core.language_model.language_model_manager import LanguageModelManager


class TestLanguageModelManager:
    def test_get_or_load_provider_cache_hit(self, db):
        """第二次调用不查询 DB"""
        manager = LanguageModelManager(db=db)

        with patch.object(manager, '_db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            mock_query = MagicMock()
            mock_session.query.return_value.filter_by.return_value.first.return_value = MagicMock(
                name="siliconflow",
                label="硅基流动",
                description="",
                icon="",
                background="#FFFFFF",
                default_base_url="https://api.siliconflow.cn/v1",
                supported_model_types=["chat"],
                status="active",
            )
            mock_query.filter_by = mock_session.query.return_value.filter_by

            # 第一次调用
            entity1 = manager.get_or_load_provider("siliconflow")
            assert entity1.name == "siliconflow"

            # 第二次调用应命中缓存
            first_call_count = mock_session.query.call_count
            entity2 = manager.get_or_load_provider("siliconflow")
            assert entity2 is entity1
            assert mock_session.query.call_count == first_call_count  # 无额外 DB 查询

    def test_get_or_load_provider_not_found(self, db):
        """DB 无记录抛 NotFoundException"""
        manager = LanguageModelManager(db=db)

        with patch.object(manager, '_db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            mock_session.query.return_value.filter_by.return_value.first.return_value = None

            with pytest.raises(NotFoundException):
                manager.get_or_load_provider("nonexistent")

    def test_get_or_load_provider_disabled(self, db):
        """status='disabled' 抛 NotFoundException"""
        manager = LanguageModelManager(db=db)

        with patch.object(manager, '_db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            mock_session.query.return_value.filter_by.return_value.first.return_value = None

            with pytest.raises(NotFoundException):
                manager.get_or_load_provider("disabled_provider")

    def test_invalidate_provider_clears_both_levels(self, db):
        """失效 provider 同时清空其下所有 model 缓存"""
        manager = LanguageModelManager(db=db)
        manager._provider_cache["test_provider"] = ("entity", time.time())
        manager._model_cache["test_provider"] = {"model_a": ("entity", time.time())}

        manager.invalidate_provider("test_provider")

        assert "test_provider" not in manager._provider_cache
        assert "test_provider" not in manager._model_cache

    def test_invalidate_model_only_clears_one(self, db):
        """失效单个 model 不影响同 provider 其他 model"""
        manager = LanguageModelManager(db=db)
        manager._model_cache["test_provider"] = {
            "model_a": ("entity_a", time.time()),
            "model_b": ("entity_b", time.time()),
        }

        manager.invalidate_model("test_provider", "model_a")

        assert "model_a" not in manager._model_cache["test_provider"]
        assert "model_b" in manager._model_cache["test_provider"]

    def test_invalidate_all(self, db):
        """全量失效"""
        manager = LanguageModelManager(db=db)
        manager._provider_cache["a"] = ("entity", time.time())
        manager._model_cache["a"] = {"m": ("entity", time.time())}

        manager.invalidate_all()

        assert len(manager._provider_cache) == 0
        assert len(manager._model_cache) == 0

    def test_get_providers_returns_list_from_db(self, db):
        """get_providers 从 DB 查询所有 active provider"""
        manager = LanguageModelManager(db=db)

        with patch.object(manager, '_db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            mock_provider = MagicMock(
                name="openai", label="OpenAI", description="", icon="",
                background="#FFFFFF", default_base_url="https://api.openai.com/v1",
                supported_model_types=["chat"], status="active",
            )
            mock_session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [mock_provider]

            providers = manager.get_providers()
            assert len(providers) == 1
            assert providers[0].name == "openai"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `docker exec llmops-api bash -c "cd /app/api && python -m pytest test/internal/core/language_model/test_language_model_manager.py -v 2>&1" | Select-Object -Last 20`
Expected: FAIL（LanguageModelManager 当前是 pydantic BaseModel，不接受 db 参数）

- [ ] **Step 3: 重写 LanguageModelManager**

完整替换 `api/internal/core/language_model/language_model_manager.py`：

```python
# api/internal/core/language_model/language_model_manager.py
"""语言模型管理器 — 动态懒加载缓存版本

替代原静态 yaml 加载，改为从数据库懒加载 Provider/Model 配置，
TTL 60s 兜底 + CRUD 主动失效缓存 + RLock 线程安全。
"""

import logging
import threading
import time
from typing import Optional

from injector import inject, singleton
from pydantic import BaseModel, Field

from internal.exception import NotFoundException
from internal.model.model_provider_entity import ModelProviderConfig
from internal.model.model_pool_entity import ModelPoolConfig
from .entities.model_entity import ModelEntity, ModelFeature
from .entities.provider_entity import ProviderEntity
from .model_class_registry import ModelClassRegistry
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@singleton
class LanguageModelManager(BaseModel):
    """语言模型管理器 — 数据库驱动的懒加载缓存"""

    # 兼容 pydantic BaseModel 的字段声明（实际通过 __init__ 赋值）
    _db: SQLAlchemy = None
    _provider_cache: dict = Field(default_factory=dict)
    _model_cache: dict = Field(default_factory=dict)
    _lock: threading.RLock = None

    CACHE_TTL_SECONDS: int = 60

    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, db: SQLAlchemy = None, **data):
        super().__init__(**data)
        self._db = db
        self._provider_cache: dict[str, tuple[ProviderEntity, float]] = {}
        self._model_cache: dict[str, dict[str, tuple[ModelEntity, float]]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Provider 懒加载
    # ------------------------------------------------------------------

    def get_or_load_provider(self, provider_name: str) -> ProviderEntity:
        """懒加载供应商实体，命中缓存直接返回

        Args:
            provider_name: 供应商唯一标识

        Returns:
            ProviderEntity 实例

        Raises:
            NotFoundException: 供应商不存在或已禁用
        """
        with self._lock:
            cached = self._provider_cache.get(provider_name)
            if cached and (time.time() - cached[1]) < self.CACHE_TTL_SECONDS:
                return cached[0]

            if self._db is None:
                raise NotFoundException(f"数据库未初始化，无法加载供应商: {provider_name}")

            provider_config = (
                self._db.session.query(ModelProviderConfig)
                .filter_by(name=provider_name, status="active")
                .first()
            )
            if not provider_config:
                raise NotFoundException(f"供应商 {provider_name} 不存在或已禁用")

            entity = self._build_provider_entity(provider_config)
            self._provider_cache[provider_name] = (entity, time.time())
            self._model_cache.setdefault(provider_name, {})
            return entity

    def get_providers(self) -> list[ProviderEntity]:
        """获取所有 active 供应商列表（用于前端下拉）"""
        if self._db is None:
            return []
        configs = (
            self._db.session.query(ModelProviderConfig)
            .filter_by(status="active")
            .order_by(ModelProviderConfig.created_at.asc())
            .all()
        )
        return [self._build_provider_entity(c) for c in configs]

    # ------------------------------------------------------------------
    # Model 懒加载
    # ------------------------------------------------------------------

    def get_or_load_model_entity(self, provider_name: str, model_name: str) -> ModelEntity:
        """懒加载模型实体

        Args:
            provider_name: 供应商唯一标识
            model_name: 模型名称

        Returns:
            ModelEntity 实例

        Raises:
            NotFoundException: 模型不存在或已禁用
        """
        # 确保 provider 已加载
        provider_entity = self.get_or_load_provider(provider_name)

        with self._lock:
            cache = self._model_cache.get(provider_name, {})
            cached = cache.get(model_name)
            if cached and (time.time() - cached[1]) < self.CACHE_TTL_SECONDS:
                return cached[0]

            if self._db is None:
                raise NotFoundException(f"数据库未初始化，无法加载模型: {model_name}")

            model_config = (
                self._db.session.query(ModelPoolConfig)
                .filter_by(provider=provider_name, model_name=model_name, status="active")
                .first()
            )
            if not model_config:
                raise NotFoundException(f"模型 {model_name} 不存在或已禁用")

            entity = self._build_model_entity(model_config, provider_entity)
            self._model_cache.setdefault(provider_name, {})[model_name] = (entity, time.time())
            return entity

    # ------------------------------------------------------------------
    # 缓存失效
    # ------------------------------------------------------------------

    def invalidate_provider(self, provider_name: str) -> None:
        """失效整个供应商缓存（含其下所有模型）"""
        with self._lock:
            self._provider_cache.pop(provider_name, None)
            self._model_cache.pop(provider_name, None)
        logger.info("Provider 缓存失效: name=%s", provider_name)

    def invalidate_model(self, provider_name: str, model_name: str) -> None:
        """失效单个模型缓存"""
        with self._lock:
            if provider_name in self._model_cache:
                self._model_cache[provider_name].pop(model_name, None)
        logger.info("Model 缓存失效: provider=%s, model=%s", provider_name, model_name)

    def invalidate_all(self) -> None:
        """全量失效缓存（启动/调试用）"""
        with self._lock:
            self._provider_cache.clear()
            self._model_cache.clear()
        logger.info("所有模型缓存已清空")

    # ------------------------------------------------------------------
    # 实体构建（从 DB 记录 → pydantic 实体）
    # ------------------------------------------------------------------

    def _build_provider_entity(self, config: ModelProviderConfig) -> ProviderEntity:
        """从 DB 记录构建 ProviderEntity"""
        return ProviderEntity(
            name=config.name,
            label=config.label or config.name,
            description=config.description or "",
            icon=config.icon or "",
            background=config.background or "#FFFFFF",
            default_base_url=config.default_base_url,
            supported_model_types=config.supported_model_types or ["chat"],
        )

    def _build_model_entity(
        self,
        model_config: ModelPoolConfig,
        provider_entity: ProviderEntity,
    ) -> ModelEntity:
        """从 DB 记录构建 ModelEntity（替代从 yaml 构建）"""
        # 将 capabilities 列表转换为 ModelFeature 枚举列表
        raw_features = model_config.capabilities or []
        features = []
        for f in raw_features:
            try:
                features.append(ModelFeature(f))
            except ValueError:
                pass  # 忽略不支持的 feature

        return ModelEntity(
            model=model_config.model_name,
            label=model_config.display_name or model_config.model_name,
            model_type=model_config.model_type,
            features=features,
            context_window=model_config.max_tokens or 4096,
            max_output_tokens=model_config.max_tokens or 4096,
            attributes={
                "model": model_config.model_name,
                "openai_api_base": provider_entity.default_base_url,
                "openai_api_key": "",  # 由 attribute_overrides 运行时注入
            },
            parameters=[],
            metadata={
                "pricing": {
                    "input": float(model_config.price_per_1k_tokens or 0),
                    "output": float(model_config.price_per_1k_tokens or 0),
                    "unit": 0.001,
                },
                "model_type": model_config.model_type,
                "compatible_api": model_config.compatible_api,
                "tier": model_config.tier,
                "priority": model_config.priority,
                "fallback_model_id": model_config.fallback_model_id,
            },
        )

    # ------------------------------------------------------------------
    # 兼容旧接口（逐步迁移）
    # ------------------------------------------------------------------

    def get_provider(self, provider_name: str) -> ProviderEntity:
        """兼容旧接口 — 委托到 get_or_load_provider"""
        return self.get_or_load_provider(provider_name)
```

- [ ] **Step 4: 改造 ProviderEntity 移除 yaml 依赖**

修改 `api/internal/core/language_model/entities/provider_entity.py`，移除 yaml 加载逻辑，添加 `default_base_url` 和 `compatible_api` 字段。完整替换文件内容：

```python
# api/internal/core/language_model/entities/provider_entity.py
from typing import Any, Optional, Type, Union
from pydantic import BaseModel, Field

from .model_entity import BaseLanguageModel, ModelEntity, ModelType


class ProviderEntity(BaseModel):
    """模型提供商实体信息 — 从数据库加载"""
    name: str = ""
    label: str = ""
    description: str = ""
    icon: str = ""
    background: str = "#FFFFFF"
    default_base_url: str = ""
    supported_model_types: list[str] = Field(default_factory=list)
    embedding_models: list[dict[str, Any]] = Field(default_factory=list)


class Provider(BaseModel):
    """大语言模型服务提供商 — 兼容旧接口

    新架构下 Provider 仅作为 ProviderEntity 的薄包装，
    model_entity_map 和 model_class_map 通过 LanguageModelManager 懒加载。
    """
    name: str
    position: int = 0
    provider_entity: ProviderEntity
    model_entity_map: dict[str, ModelEntity] = Field(default_factory=dict)
    model_class_map: dict[str, Union[None, Type[BaseLanguageModel]]] = Field(default_factory=dict)

    def get_model_class(self, model_type: ModelType) -> Optional[Type[BaseLanguageModel]]:
        """根据模型类型获取模型类 — 委托到 ModelClassRegistry"""
        from ..model_class_registry import ModelClassRegistry
        compatible_api = self.provider_entity.default_base_url  # 旧兼容，实际不再使用
        # 优先从 model_class_map 获取（向后兼容）
        model_class = self.model_class_map.get(model_type.value if hasattr(model_type, 'value') else str(model_type), None)
        if model_class is not None:
            return model_class
        raise NotFoundException("该模型类不存在，请核实后重试") if False else model_class

    def get_model_entity(self, model_name: str) -> Optional[ModelEntity]:
        """根据模型名获取模型实体 — 从内存字典查找（兼容旧接口）"""
        model_entity = self.model_entity_map.get(model_name, None)
        return model_entity

    def get_model_entities(self) -> list[ModelEntity]:
        """获取所有模型实体列表"""
        return list(self.model_entity_map.values())
```

- [ ] **Step 5: 运行测试验证通过**

Run: `docker exec llmops-api bash -c "cd /app/api && python -m pytest test/internal/core/language_model/test_language_model_manager.py -v 2>&1" | Select-Object -Last 30`
Expected: 所有 7 个测试 PASS

- [ ] **Step 6: Commit**

```bash
git add api/internal/core/language_model/language_model_manager.py api/internal/core/language_model/entities/provider_entity.py api/test/internal/core/language_model/test_language_model_manager.py
git commit -m "feat: refactor LanguageModelManager to lazy-loading cache, remove yaml dependency"
```

---

## Task 8: 改造 _load_model_components

**Files:**
- Modify: `api/internal/service/language_model_service.py`

- [ ] **Step 1: 读取当前 _load_model_components 和 _instantiate_language_model**

读取 `api/internal/service/language_model_service.py` 的第 560-610 行，了解当前实现。

- [ ] **Step 2: 改造 _load_model_components**

在 `language_model_service.py` 中找到 `_load_model_components` 方法，替换为：

```python
    def _load_model_components(self, model_config: dict[str, Any]) -> tuple[Any, Any, Any]:
        """从数据库懒加载 provider/model 实体和 model_class

        返回 (provider_entity, model_entity, model_class)
        """
        normalized_model_config = deepcopy(model_config or {})
        provider_name = str(normalized_model_config.get("provider", "")).strip()
        model_name = str(normalized_model_config.get("model", "")).strip()

        # 懒加载 provider 和 model entity（从 DB）
        provider_entity = self.language_model_manager.get_or_load_provider(provider_name)
        model_entity = self.language_model_manager.get_or_load_model_entity(provider_name, model_name)

        # 从 model_entity.metadata 获取 compatible_api，再通过 ModelClassRegistry 解析
        compatible_api = model_entity.metadata.get("compatible_api", "openai")
        model_type = model_entity.model_type if isinstance(model_entity.model_type, str) else (
            model_entity.model_type.value if hasattr(model_entity.model_type, 'value') else str(model_entity.model_type)
        )

        from internal.core.language_model.model_class_registry import ModelClassRegistry
        model_class = ModelClassRegistry.resolve(compatible_api, model_type)

        return provider_entity, model_entity, model_class
```

- [ ] **Step 3: 确保 _instantiate_language_model 兼容**

`_instantiate_language_model` 方法不需要大改，因为 `_load_model_components` 返回签名不变。但需确认 `attributes` 中包含 `openai_api_base`。

检查 `_instantiate_language_model` 方法，确保它正确解构返回值。如果原代码是：

```python
    def _instantiate_language_model(self, model_config, attribute_overrides=None):
        _, model_entity, model_class = self._load_model_components(model_config)
        # ...
```

则无需修改。如果使用 `provider` 变量名，改为 `provider_entity`。

- [ ] **Step 4: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/service/language_model_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/language_model_service.py
git commit -m "feat: refactor _load_model_components to use DB lazy-loading and ModelClassRegistry"
```

---

## Task 9: 改造 build_llm_config

**Files:**
- Modify: `api/internal/service/runtime_model_pool_service.py`

- [ ] **Step 1: 改造 build_llm_config**

在 `runtime_model_pool_service.py` 中注入 `LanguageModelManager`，改造 `build_llm_config` 从 Provider 缓存获取 base_url。

修改文件头部，添加 LanguageModelManager 注入：

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from injector import inject

from internal.core.language_model.language_model_manager import LanguageModelManager
from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig
from internal.service.admin_model_pool_service import _decrypt_key_value
from pkg.sqlalchemy import SQLAlchemy


@inject
@dataclass
class RuntimeModelPoolService:
    """桥接 admin 模型池配置与运行时 LLM 调用"""

    db: SQLAlchemy
    language_model_manager: LanguageModelManager
```

替换 `build_llm_config` 方法：

```python
    def build_llm_config(self, model: ModelPoolConfig, key: ModelKeyConfig) -> dict[str, Any]:
        api_key = _decrypt_key_value(key.key_value_encrypted)
        config: dict[str, Any] = {
            "provider": model.provider,
            "model": model.model_name,
            "parameters": {},
            "api_key": api_key,
            "key_id": str(key.id),
            "model_id": str(model.id),
        }
        # 通过 LanguageModelManager 缓存获取 Provider 的 base_url
        try:
            provider_entity = self.language_model_manager.get_or_load_provider(model.provider)
            if provider_entity.default_base_url:
                config["base_url"] = provider_entity.default_base_url
        except Exception:
            pass  # Provider 不存在时降级，不传 base_url
        return config
```

- [ ] **Step 2: 更新测试中的 _service helper**

在 `api/test/internal/service/test_runtime_model_pool_service.py` 中，`_service` 函数需要传入 mock 的 `language_model_manager`：

```python
def _service(db):
    from unittest.mock import MagicMock
    mock_manager = MagicMock()
    mock_manager.get_or_load_provider.return_value = MagicMock(default_base_url="https://api.openai.com/v1")
    return RuntimeModelPoolService(db=db, language_model_manager=mock_manager)
```

- [ ] **Step 3: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/service/runtime_model_pool_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 运行现有测试**

Run: `docker exec llmops-api bash -c "cd /app/api && python -m pytest test/internal/service/test_runtime_model_pool_service.py -v 2>&1" | Select-Object -Last 30`
Expected: 所有测试 PASS

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/runtime_model_pool_service.py api/test/internal/service/test_runtime_model_pool_service.py
git commit -m "feat: refactor build_llm_config to get base_url from Provider cache"
```

---

## Task 10: 改造 ModelPoolConfig ORM（删 base_url，加 model_type/compatible_api）

**Files:**
- Modify: `api/internal/model/model_pool_entity.py`

- [ ] **Step 1: 修改 ModelPoolConfig 类**

在 `model_pool_entity.py` 中：
1. 删除 `base_url` 列
2. 添加 `model_type` 和 `compatible_api` 列
3. 添加新索引

替换 `ModelPoolConfig` 类的 `__table_args__` 和列定义：

```python
class ModelPoolConfig(db.Model):
    __tablename__ = "model_pool_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_model_pool_config_id"),
        Index("model_pool_config_provider_idx", "provider"),
        Index("model_pool_config_status_idx", "status"),
        Index("model_pool_config_tier_idx", "tier"),
        Index("ix_model_pool_config_provider_model", "provider", "model_name"),
        Index("ix_model_pool_config_model_type", "model_type"),
    )

    id = Column(UUID, nullable=False, default=uuid4, server_default=text("uuid_generate_v4()"))
    provider = Column(String(128), nullable=False)
    model_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    tier = Column(String(64), nullable=False, server_default=text("'standard'::character varying"))
    capabilities = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    max_tokens = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    model_type = Column(String(32), nullable=False, server_default=text("'chat'::character varying"))
    compatible_api = Column(String(32), nullable=False, server_default=text("'openai'::character varying"))
    fallback_model_id = Column(String(36), nullable=True)
    priority = Column(Integer, nullable=False, server_default=text("0"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/model/model_pool_entity.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/model/model_pool_entity.py
git commit -m "feat: update ModelPoolConfig ORM (remove base_url, add model_type/compatible_api)"
```

---

## Task 11: 创建 Provider Schema

**Files:**
- Create: `api/internal/schema/admin_model_provider_schema.py`

- [ ] **Step 1: 创建 schema 文件**

```python
# api/internal/schema/admin_model_provider_schema.py
from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, InputRequired, Length, Optional, URL

from internal.schema import DictField, ListField

PROVIDER_STATUSES = ["active", "disabled"]
MODEL_TYPES = [
    "chat", "completion", "embedding", "multimodal",
    "image_generation", "video_generation", "ocr", "tts", "asr", "rerank",
]
COMPATIBLE_APIS = ["openai", "claude"]


class GetAdminModelProvidersReq(FlaskForm):
    search = StringField("search", default="", validators=[Optional(), Length(max=255)])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", *PROVIDER_STATUSES])])
    current_page = IntegerField("current_page", default=1, validators=[Optional()])
    page_size = IntegerField("page_size", default=20, validators=[Optional()])


class CreateAdminModelProviderReq(FlaskForm):
    name = StringField("name", validators=[InputRequired(), Length(min=1, max=128)])
    label = StringField("label", validators=[InputRequired(), Length(min=1, max=255)])
    description = StringField("description", default="", validators=[Optional(), Length(max=2000)])
    icon = StringField("icon", default="", validators=[Optional(), Length(max=512)])
    background = StringField("background", default="#FFFFFF", validators=[Optional(), Length(max=32)])
    default_base_url = StringField("default_base_url", validators=[InputRequired(), Length(min=1, max=512)])
    supported_model_types = ListField(
        StringField("supported_model_types", validators=[Optional(), AnyOf(MODEL_TYPES)])
    )
    status = StringField("status", default="active", validators=[Optional(), AnyOf(PROVIDER_STATUSES)])


class UpdateAdminModelProviderReq(FlaskForm):
    label = StringField("label", validators=[Optional(), Length(min=1, max=255)])
    description = StringField("description", validators=[Optional(), Length(max=2000)])
    icon = StringField("icon", validators=[Optional(), Length(max=512)])
    background = StringField("background", validators=[Optional(), Length(max=32)])
    default_base_url = StringField("default_base_url", validators=[Optional(), Length(min=1, max=512)])
    supported_model_types = ListField(
        StringField("supported_model_types", validators=[Optional(), AnyOf(MODEL_TYPES)])
    )
    status = StringField("status", validators=[Optional(), AnyOf(PROVIDER_STATUSES)])


class SetAdminModelProviderStatusReq(FlaskForm):
    status = StringField("status", validators=[InputRequired(), AnyOf(PROVIDER_STATUSES)])


class AdminModelProviderResp(Schema):
    id = fields.String()
    name = fields.String()
    label = fields.String()
    description = fields.String()
    icon = fields.String()
    background = fields.String()
    default_base_url = fields.String()
    supported_model_types = fields.List(fields.String())
    status = fields.String()
    model_count = fields.Integer()
    created_at = fields.Integer()
    updated_at = fields.Integer()


class AdminModelProviderPageResp(Schema):
    list = fields.List(fields.Nested(AdminModelProviderResp))
    paginator = fields.Dict()


class AdminModelProviderOptionResp(Schema):
    id = fields.String()
    name = fields.String()
    label = fields.String()
    default_base_url = fields.String()
    supported_model_types = fields.List(fields.String())


class AdminModelProviderOptionsResp(Schema):
    options = fields.List(fields.Nested(AdminModelProviderOptionResp))
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/schema/admin_model_provider_schema.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/schema/admin_model_provider_schema.py
git commit -m "feat: add admin model provider schema"
```

---

## Task 12: 创建 AdminModelProviderService

**Files:**
- Create: `api/internal/service/admin_model_provider_service.py`

- [ ] **Step 1: 创建 service 文件**

```python
# api/internal/service/admin_model_provider_service.py
import logging
import math
from datetime import UTC, datetime
from uuid import UUID

from injector import inject

from internal.exception import ConflictException, NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.model_pool_entity import ModelPoolConfig
from internal.model.model_provider_entity import ModelProviderConfig
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
class AdminModelProviderService:
    """模型供应商 CRUD 服务"""

    def __init__(self, session=None, db: SQLAlchemy = None):
        self.session = session or db.session
        self._db = db

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_providers(
        self,
        *,
        search: str = "",
        status: str = "",
        current_page: int = 1,
        page_size: int = 20,
    ) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = self.session.query(ModelProviderConfig)
        search = (search or "").strip()
        if search:
            like_value = f"%{escape_like_pattern(search)}%"
            query = query.filter(
                (ModelProviderConfig.name.ilike(like_value))
                | (ModelProviderConfig.label.ilike(like_value))
            )
        if status:
            query = query.filter(ModelProviderConfig.status == status)
        total = query.count()
        providers = (
            query.order_by(ModelProviderConfig.created_at.asc())
            .offset((current_page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "list": [self._serialize_provider(p) for p in providers],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_provider(self, provider_id: UUID) -> dict:
        return self._serialize_provider(self._get_provider_or_raise(provider_id))

    def list_provider_options(self) -> dict:
        """获取 active 供应商下拉选项"""
        providers = (
            self.session.query(ModelProviderConfig)
            .filter(ModelProviderConfig.status == "active")
            .order_by(ModelProviderConfig.label.asc())
            .all()
        )
        return {
            "options": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "label": p.label,
                    "default_base_url": p.default_base_url,
                    "supported_model_types": p.supported_model_types or [],
                }
                for p in providers
            ]
        }

    # ------------------------------------------------------------------
    # 创建/更新/删除
    # ------------------------------------------------------------------

    def create_provider(self, payload: dict) -> dict:
        name = (payload.get("name") or "").strip()
        if not name:
            raise NotFoundException("供应商 name 不能为空")

        # 唯一性校验
        existing = self.session.query(ModelProviderConfig).filter_by(name=name).first()
        if existing:
            raise ConflictException(f"供应商 {name} 已存在")

        provider = ModelProviderConfig(
            name=name,
            label=payload.get("label") or name,
            description=payload.get("description") or "",
            icon=payload.get("icon") or "",
            background=payload.get("background") or "#FFFFFF",
            default_base_url=payload.get("default_base_url") or "",
            supported_model_types=payload.get("supported_model_types") or ["chat"],
            status=payload.get("status") or "active",
        )
        self.session.add(provider)
        self.session.commit()

        self._invalidate_cache(provider.name)
        return self._serialize_provider(provider)

    def update_provider(self, provider_id: UUID, payload: dict) -> dict:
        provider = self._get_provider_or_raise(provider_id)
        # name 不可改
        if "label" in payload:
            provider.label = payload["label"]
        if "description" in payload:
            provider.description = payload["description"] or ""
        if "icon" in payload:
            provider.icon = payload["icon"] or ""
        if "background" in payload:
            provider.background = payload["background"] or "#FFFFFF"
        if "default_base_url" in payload:
            provider.default_base_url = payload["default_base_url"] or ""
        if "supported_model_types" in payload:
            provider.supported_model_types = payload["supported_model_types"] or ["chat"]
        if "status" in payload:
            provider.status = payload["status"]
        provider.updated_at = self._now()
        self.session.commit()

        self._invalidate_cache(provider.name)
        return self._serialize_provider(provider)

    def delete_provider(self, provider_id: UUID) -> None:
        provider = self._get_provider_or_raise(provider_id)
        # 前置校验：无关联 active 模型
        active_models_count = (
            self.session.query(ModelPoolConfig)
            .filter(
                ModelPoolConfig.provider == provider.name,
                ModelPoolConfig.status == "active",
            )
            .count()
        )
        if active_models_count > 0:
            raise ConflictException(
                f"存在 {active_models_count} 个关联模型，请先删除或禁用模型"
            )
        provider_name = provider.name
        self.session.delete(provider)
        self.session.commit()

        self._invalidate_cache(provider_name)

    def set_provider_status(self, provider_id: UUID, status: str) -> dict:
        provider = self._get_provider_or_raise(provider_id)
        if status == "disabled":
            # 级联禁用所有 active 模型
            affected_models = (
                self.session.query(ModelPoolConfig)
                .filter(
                    ModelPoolConfig.provider == provider.name,
                    ModelPoolConfig.status == "active",
                )
                .all()
            )
            for model in affected_models:
                model.status = "disabled"
                model.updated_at = self._now()
                self._invalidate_model_cache(model.provider, model.model_name)
        provider.status = status
        provider.updated_at = self._now()
        self.session.commit()

        self._invalidate_cache(provider.name)
        return self._serialize_provider(provider)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_provider_or_raise(self, provider_id: UUID) -> ModelProviderConfig:
        provider = self.session.query(ModelProviderConfig).filter_by(id=provider_id).first()
        if provider is None:
            raise NotFoundException("供应商不存在")
        return provider

    def _serialize_provider(self, provider: ModelProviderConfig) -> dict:
        # 查询关联模型数量
        model_count = (
            self.session.query(ModelPoolConfig)
            .filter(ModelPoolConfig.provider == provider.name)
            .count()
        )
        return {
            "id": str(provider.id),
            "name": provider.name,
            "label": provider.label,
            "description": provider.description or "",
            "icon": provider.icon or "",
            "background": provider.background or "#FFFFFF",
            "default_base_url": provider.default_base_url,
            "supported_model_types": provider.supported_model_types or [],
            "status": provider.status,
            "model_count": model_count,
            "created_at": self._timestamp(provider.created_at),
            "updated_at": self._timestamp(provider.updated_at),
        }

    def _invalidate_cache(self, provider_name: str) -> None:
        """失效 LanguageModelManager 中的 provider 缓存"""
        try:
            from internal.core.language_model.language_model_manager import LanguageModelManager
            from injector import Injector
            injector = Injector()
            manager = injector.get(LanguageModelManager)
            manager.invalidate_provider(provider_name)
        except Exception as e:
            logger.debug("缓存失效跳过（可能未初始化）: %s", e)

    def _invalidate_model_cache(self, provider_name: str, model_name: str) -> None:
        """失效单个模型缓存"""
        try:
            from internal.core.language_model.language_model_manager import LanguageModelManager
            from injector import Injector
            injector = Injector()
            manager = injector.get(LanguageModelManager)
            manager.invalidate_model(provider_name, model_name)
        except Exception as e:
            logger.debug("模型缓存失效跳过: %s", e)
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/service/admin_model_provider_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/service/admin_model_provider_service.py
git commit -m "feat: add AdminModelProviderService with CRUD and cache invalidation"
```

---

## Task 13: 创建 Provider Handler

**Files:**
- Create: `api/internal/handler/admin_model_provider_handler.py`

- [ ] **Step 1: 创建 handler 文件**

```python
# api/internal/handler/admin_model_provider_handler.py
from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_model_provider_schema import (
    AdminModelProviderOptionResp,
    AdminModelProviderOptionsResp,
    AdminModelProviderPageResp,
    AdminModelProviderResp,
    CreateAdminModelProviderReq,
    GetAdminModelProvidersReq,
    SetAdminModelProviderStatusReq,
    UpdateAdminModelProviderReq,
)
from internal.service.admin_model_provider_service import AdminModelProviderService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminModelProviderHandler:
    admin_model_provider_service: AdminModelProviderService

    @admin_login_required
    @permission_required("model_provider:read")
    def list_providers(self):
        req = GetAdminModelProvidersReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_model_provider_service.list_providers(
            search=req.search.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminModelProviderPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:read")
    def get_provider(self, provider_id: UUID):
        resp = AdminModelProviderResp()
        return success_json(resp.dump(self.admin_model_provider_service.get_provider(provider_id)))

    @admin_login_required
    @permission_required("model_provider:create")
    def create_provider(self):
        req = CreateAdminModelProviderReq(request.form)
        if not req.validate():
            return validate_error_json(req.errors)
        payload = {
            "name": req.name.data,
            "label": req.label.data,
            "description": req.description.data or "",
            "icon": req.icon.data or "",
            "background": req.background.data or "#FFFFFF",
            "default_base_url": req.default_base_url.data,
            "supported_model_types": req.supported_model_types.data or ["chat"],
            "status": req.status.data or "active",
        }
        result = self.admin_model_provider_service.create_provider(payload)
        resp = AdminModelProviderResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:update")
    def update_provider(self, provider_id: UUID):
        req = UpdateAdminModelProviderReq(request.form)
        if not req.validate():
            return validate_error_json(req.errors)
        payload = {}
        for field in ["label", "description", "icon", "background", "default_base_url", "supported_model_types", "status"]:
            if hasattr(req, field) and getattr(req, field).data is not None:
                payload[field] = getattr(req, field).data
        result = self.admin_model_provider_service.update_provider(provider_id, payload)
        resp = AdminModelProviderResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:delete")
    def delete_provider(self, provider_id: UUID):
        self.admin_model_provider_service.delete_provider(provider_id)
        return success_message("删除成功")

    @admin_login_required
    @permission_required("model_provider:update")
    def set_provider_status(self, provider_id: UUID):
        req = SetAdminModelProviderStatusReq(request.form)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_model_provider_service.set_provider_status(provider_id, req.status.data)
        resp = AdminModelProviderResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:read")
    def list_provider_options(self):
        result = self.admin_model_provider_service.list_provider_options()
        resp = AdminModelProviderOptionsResp()
        return success_json(resp.dump(result))
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/handler/admin_model_provider_handler.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/handler/admin_model_provider_handler.py
git commit -m "feat: add AdminModelProviderHandler with 7 CRUD endpoints"
```

---

## Task 14: 改造 AdminModelPoolService

**Files:**
- Modify: `api/internal/service/admin_model_pool_service.py`

- [ ] **Step 1: 在 create_model 中添加 provider 校验和 model_type/compatible_api 字段**

找到 `create_model` 方法，替换为：

```python
    def create_model(self, payload: dict) -> dict:
        # 校验 provider 存在且 active
        provider_name = payload["provider"]
        from internal.model.model_provider_entity import ModelProviderConfig
        provider = self.session.query(ModelProviderConfig).filter_by(
            name=provider_name, status="active"
        ).first()
        if not provider:
            raise NotFoundException(f"供应商 {provider_name} 不存在或已禁用")

        # 校验同 provider 下 model_name 唯一
        existing = self.session.query(ModelPoolConfig).filter_by(
            provider=provider_name, model_name=payload["model_name"]
        ).first()
        if existing:
            raise ConflictException(f"模型 {payload['model_name']} 在供应商 {provider_name} 下已存在")

        model = ModelPoolConfig(
            provider=payload["provider"],
            model_name=payload["model_name"],
            display_name=payload.get("display_name") or "",
            tier=payload.get("tier") or "standard",
            capabilities=payload.get("capabilities") or [],
            price_per_1k_tokens=self._decimal(payload.get("price_per_1k_tokens")),
            max_tokens=int(payload.get("max_tokens") or 0),
            status=payload.get("status") or "active",
            model_type=payload.get("model_type") or "chat",
            compatible_api=payload.get("compatible_api") or "openai",
            fallback_model_id=payload.get("fallback_model_id") or None,
            priority=int(payload.get("priority") or 0),
        )
        self.session.add(model)
        self.session.commit()

        self._invalidate_model_cache(model.provider, model.model_name)
        return self._serialize_model(model)
```

- [ ] **Step 2: 在 update_model 中添加 model_type/compatible_api 字段，删除 base_url**

找到 `update_model` 方法，将 `if "base_url" in payload:` 行替换为：

```python
        if "model_type" in payload:
            model.model_type = payload["model_type"]
        if "compatible_api" in payload:
            model.compatible_api = payload["compatible_api"]
```

- [ ] **Step 3: 在 delete_model 中添加前置校验和缓存失效**

找到 `delete_model` 方法，替换为：

```python
    def delete_model(self, model_id: UUID) -> None:
        model = self._get_model_or_raise(model_id)
        # 前置校验：无 model_id 精确关联的 Key
        precise_keys_count = (
            self.session.query(ModelKeyConfig)
            .filter(ModelKeyConfig.model_id == str(model.id))
            .count()
        )
        if precise_keys_count > 0:
            raise ConflictException(
                f"存在 {precise_keys_count} 个 model_id 精确关联的 Key，请先删除或解绑"
            )
        provider_name = model.provider
        model_name = model.model_name
        self.session.delete(model)
        self.session.commit()

        self._invalidate_model_cache(provider_name, model_name)
```

- [ ] **Step 4: 在 set_model_status 中添加缓存失效**

找到 `set_model_status` 方法，在 `self.session.commit()` 之后添加：

```python
        self._invalidate_model_cache(model.provider, model.model_name)
```

- [ ] **Step 5: 更新 _serialize_model 移除 base_url，添加 model_type/compatible_api**

找到 `_serialize_model` 方法，将 base_url 行替换为：

```python
            "model_type": model.model_type,
            "compatible_api": model.compatible_api,
```

- [ ] **Step 6: 添加 _invalidate_model_cache 方法**

在类中添加：

```python
    def _invalidate_model_cache(self, provider_name: str, model_name: str) -> None:
        """失效 LanguageModelManager 中的 model 缓存"""
        try:
            from internal.core.language_model.language_model_manager import LanguageModelManager
            from injector import Injector
            injector = Injector()
            manager = injector.get(LanguageModelManager)
            manager.invalidate_model(provider_name, model_name)
        except Exception:
            pass
```

- [ ] **Step 7: 在 create_key 中添加 provider 校验**

找到 `create_key` 方法，在创建 ModelKeyConfig 之前添加：

```python
        # 校验 provider 存在且 active
        from internal.model.model_provider_entity import ModelProviderConfig
        provider = self.session.query(ModelProviderConfig).filter_by(
            name=payload["provider"], status="active"
        ).first()
        if not provider:
            raise NotFoundException(f"供应商 {payload['provider']} 不存在或已禁用")

        # 若填了 model_id，校验模型存在且 provider 一致
        if payload.get("model_id"):
            model = self.session.query(ModelPoolConfig).filter_by(id=payload["model_id"]).first()
            if not model:
                raise NotFoundException("关联模型不存在")
            if model.provider != payload["provider"]:
                raise ConflictException("模型的供应商与 Key 的供应商不一致")
```

- [ ] **Step 8: 添加 ConflictException 导入**

在文件头部 imports 中添加：

```python
from internal.exception import ConflictException, NotFoundException
```

- [ ] **Step 9: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/service/admin_model_pool_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 10: Commit**

```bash
git add api/internal/service/admin_model_pool_service.py
git commit -m "feat: add provider validation, cache invalidation, model_type/compatible_api to AdminModelPoolService"
```

---

## Task 15: 更新 Model Schema

**Files:**
- Modify: `api/internal/schema/admin_model_pool_schema.py`

- [ ] **Step 1: 添加 MODEL_TYPES 和 COMPATIBLE_APIS 常量**

在文件头部常量定义区域添加：

```python
MODEL_TYPES = [
    "chat", "completion", "embedding", "multimodal",
    "image_generation", "video_generation", "ocr", "tts", "asr", "rerank",
]
COMPATIBLE_APIS = ["openai", "claude"]
```

- [ ] **Step 2: 在 GetAdminModelsReq 中添加 model_type 过滤**

```python
class GetAdminModelsReq(FlaskForm):
    search = StringField("search", default="", validators=[Optional(), Length(max=255)])
    provider = StringField("provider", default="", validators=[Optional(), Length(max=128)])
    tier = StringField("tier", default="", validators=[Optional(), AnyOf(["", *MODEL_TIERS])])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", *MODEL_STATUSES])])
    model_type = StringField("model_type", default="", validators=[Optional(), AnyOf(["", *MODEL_TYPES])])
    current_page = IntegerField("current_page", default=1, validators=[Optional()])
    page_size = IntegerField("page_size", default=20, validators=[Optional()])
```

- [ ] **Step 3: 在 CreateAdminModelReq 中添加 model_type/compatible_api，删除 base_url**

找到 `CreateAdminModelReq` 类，删除 `base_url` 字段，添加：

```python
    model_type = StringField("model_type", default="chat", validators=[Optional(), AnyOf(MODEL_TYPES)])
    compatible_api = StringField("compatible_api", default="openai", validators=[Optional(), AnyOf(COMPATIBLE_APIS)])
```

- [ ] **Step 4: 同样修改 UpdateAdminModelReq**

在 `UpdateAdminModelReq` 中删除 `base_url` 字段，添加 `model_type` 和 `compatible_api` 字段。

- [ ] **Step 5: 在 AdminModelResp 的 Schema 中添加 model_type/compatible_api，删除 base_url**

找到 `AdminModelResp` Schema 类，删除 `base_url` 字段，添加：

```python
    model_type = fields.String()
    compatible_api = fields.String()
```

- [ ] **Step 6: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/schema/admin_model_pool_schema.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add api/internal/schema/admin_model_pool_schema.py
git commit -m "feat: update model schema (add model_type/compatible_api, remove base_url)"
```

---

## Task 16: 注册 Provider 路由

**Files:**
- Modify: `api/internal/router/router.py`

- [ ] **Step 1: 在 router.py 中添加 handler 引用**

在 Router 类的 handler 声明区域（约第 108 行附近，与 `admin_model_pool_handler` 同级）添加：

```python
    admin_model_provider_handler: AdminModelProviderHandler
```

并在文件头部的 import 区域添加：

```python
from internal.handler.admin_model_provider_handler import AdminModelProviderHandler
```

- [ ] **Step 2: 注册路由规则**

在 `register_routes` 方法中，找到 admin model 路由注册区域（约第 1196 行），在 `/admin/models` 路由之前添加 Provider 路由：

```python
        # --- Model Provider 路由 ---
        bp.add_url_rule(
            "/admin/model-providers",
            endpoint="admin_model_provider_list",
            methods=["GET"],
            view_func=self.admin_model_provider_handler.list_providers,
        )
        bp.add_url_rule(
            "/admin/model-providers/options",
            endpoint="admin_model_provider_options",
            methods=["GET"],
            view_func=self.admin_model_provider_handler.list_provider_options,
        )
        bp.add_url_rule(
            "/admin/model-providers",
            endpoint="admin_model_provider_create",
            methods=["POST"],
            view_func=self.admin_model_provider_handler.create_provider,
        )
        bp.add_url_rule(
            "/admin/model-providers/<uuid:provider_id>",
            endpoint="admin_model_provider_get",
            methods=["GET"],
            view_func=self.admin_model_provider_handler.get_provider,
        )
        bp.add_url_rule(
            "/admin/model-providers/<uuid:provider_id>",
            endpoint="admin_model_provider_update",
            methods=["PATCH"],
            view_func=self.admin_model_provider_handler.update_provider,
        )
        bp.add_url_rule(
            "/admin/model-providers/<uuid:provider_id>",
            endpoint="admin_model_provider_delete",
            methods=["DELETE"],
            view_func=self.admin_model_provider_handler.delete_provider,
        )
        bp.add_url_rule(
            "/admin/model-providers/<uuid:provider_id>/status",
            endpoint="admin_model_provider_status",
            methods=["POST"],
            view_func=self.admin_model_provider_handler.set_provider_status,
        )
```

注意：`/admin/model-providers/options` 必须在 `/<uuid:provider_id>` 之前注册，避免路由匹配冲突。

- [ ] **Step 3: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/router/router.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/internal/router/router.py
git commit -m "feat: register model provider routes"
```

---

## Task 17: 添加 RBAC 权限

**Files:**
- Modify: `api/internal/service/admin_rbac_service.py`

- [ ] **Step 1: 在 DEFAULT_PERMISSIONS 中添加 provider 权限**

在 `admin_rbac_service.py` 的 `DEFAULT_PERMISSIONS` 列表中，在 `system_knowledge:write` 之后添加：

```python
        {"code": "model_provider:read", "name": "查看模型供应商", "resource": "model_provider", "action": "read", "description": "查看模型供应商配置"},
        {"code": "model_provider:create", "name": "创建模型供应商", "resource": "model_provider", "action": "create", "description": "创建模型供应商"},
        {"code": "model_provider:update", "name": "更新模型供应商", "resource": "model_provider", "action": "update", "description": "更新模型供应商配置"},
        {"code": "model_provider:delete", "name": "删除模型供应商", "resource": "model_provider", "action": "delete", "description": "删除模型供应商"},
        {"code": "model_pool:read", "name": "查看模型池", "resource": "model_pool", "action": "read", "description": "查看模型池配置"},
        {"code": "model_pool:create", "name": "创建模型", "resource": "model_pool", "action": "create", "description": "创建模型配置"},
        {"code": "model_pool:update", "name": "更新模型", "resource": "model_pool", "action": "update", "description": "更新模型配置"},
        {"code": "model_pool:delete", "name": "删除模型", "resource": "model_pool", "action": "delete", "description": "删除模型配置"},
```

- [ ] **Step 2: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/internal/service/admin_rbac_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add api/internal/service/admin_rbac_service.py
git commit -m "feat: add model_provider and model_pool RBAC permissions"
```

---

## Task 18: 改造 app.py 启动逻辑

**Files:**
- Modify: `api/app/http/app.py`

- [ ] **Step 1: 读取当前 app.py 中 LanguageModelManager 的初始化代码**

读取 `api/app/http/app.py`，搜索 `LanguageModelManager` 和 `language_model_manager`。

- [ ] **Step 2: 改造 LanguageModelManager 初始化**

在 app.py 中找到 LanguageModelManager 的初始化位置。当前代码可能是：

```python
language_model_manager = LanguageModelManager()
```

替换为：

```python
language_model_manager = LanguageModelManager(db=db)
```

如果当前代码通过 injector 自动注入，则确保 `db` 被正确绑定到 injector。

- [ ] **Step 3: 添加启动时缓存清空**

在 app.py 的初始化区域（在 LanguageModelManager 创建之后）添加：

```python
    # 启动时清空缓存（首次访问触发懒加载）
    language_model_manager.invalidate_all()
```

- [ ] **Step 4: 验证语法**

Run: `docker exec llmops-api python -c "import ast; ast.parse(open('/app/api/app/http/app.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add api/app/http/app.py
git commit -m "feat: refactor app.py startup to use DB-driven LanguageModelManager"
```

---

## Task 19: 执行迁移 + 重建容器 + 后端验证

**Files:**
- 无文件改动，仅执行命令

- [ ] **Step 1: 执行 Alembic 迁移**

Run:
```bash
docker exec llmops-api bash -c "cd /app/api && flask db upgrade 2>&1"
```
Expected: 输出包含 `Running upgrade s3d4e5f6a7b8 -> t6e7f8a9b0c1` 到 `-> w9b0c1d2e3f4`，无报错。

- [ ] **Step 2: 验证迁移结果**

Run:
```bash
docker exec llmops-api bash -c "cd /app/api && python -c \"
from app.http.app import app
with app.app_context():
    from internal.extension.database_extension import db
    from sqlalchemy import text
    # 检查 provider 表
    count = db.session.execute(text('SELECT COUNT(*) FROM model_provider_config')).scalar()
    print(f'Provider count: {count}')
    # 检查 model_pool_config 新字段
    result = db.session.execute(text('SELECT COUNT(*) FROM model_pool_config WHERE model_type IS NOT NULL AND compatible_api IS NOT NULL')).scalar()
    print(f'Models with new fields: {result}')
    # 检查 base_url 是否已删除
    try:
        db.session.execute(text('SELECT base_url FROM model_pool_config LIMIT 1'))
        print('ERROR: base_url column still exists')
    except Exception:
        print('base_url column dropped: OK')
\""
```
Expected: Provider count ≥ 10，Models with new fields > 0，base_url column dropped: OK

- [ ] **Step 3: 重建 API/Celery/Celery-beat 容器**

Run:
```bash
docker compose up -d --build api celery celery-beat 2>&1
```
Expected: 三个容器重建成功

- [ ] **Step 4: 检查容器启动日志**

Run:
```bash
docker logs llmops-api --tail 30 2>&1
```
Expected: 无 yaml 加载错误，无 LanguageModelManager 初始化错误

- [ ] **Step 5: 验证 Provider API**

Run:
```bash
docker exec llmops-api bash -c "curl -s http://localhost:5000/admin/model-providers/options -H 'Authorization: Bearer test' 2>&1 | head -200"
```
Expected: 返回 JSON，options 非空（如返回 401 则需使用有效 admin token）

- [ ] **Step 6: 重启 Nginx**

Run:
```bash
docker compose restart nginx 2>&1
```
Expected: Nginx 重启成功

- [ ] **Step 7: Commit（如有代码修改）**

```bash
git add -A
git commit -m "chore: run migrations and rebuild containers for dynamic model registry"
```

---

## Task 20: 创建前端 Provider API Service

**Files:**
- Create: `ui/src/services/admin-model-providers.ts`

- [ ] **Step 1: 读取现有 admin-model-pool.ts 了解导入模式**

读取 `ui/src/services/admin-model-pool.ts` 的头部，了解 `get`/`post`/`patch`/`Delete` 函数的导入方式。

- [ ] **Step 2: 创建 service 文件**

```typescript
// ui/src/services/admin-model-providers.ts
import { Delete, get, patch, post } from './common'

export interface ModelProvider {
  id: string
  name: string
  label: string
  description: string
  icon: string
  background: string
  default_base_url: string
  supported_model_types: string[]
  status: 'active' | 'disabled'
  model_count: number
  created_at: number
  updated_at: number
}

export interface ProviderOption {
  id: string
  name: string
  label: string
  default_base_url: string
  supported_model_types: string[]
}

export interface ProviderPageResult {
  list: ModelProvider[]
  paginator: {
    total_record: number
    total_page: number
    current_page: number
    page_size: number
  }
}

export const listModelProviders = (params?: {
  search?: string
  status?: string
  current_page?: number
  page_size?: number
}) => get<ProviderPageResult>('/admin/model-providers', { params })

export const getModelProvider = (id: string) => get<ModelProvider>(`/admin/model-providers/${id}`)

export const createModelProvider = (data: Partial<ModelProvider>) =>
  post<ModelProvider>('/admin/model-providers', { body: data })

export const updateModelProvider = (id: string, data: Partial<ModelProvider>) =>
  patch<ModelProvider>(`/admin/model-providers/${id}`, data)

export const deleteModelProvider = (id: string) => Delete(`/admin/model-providers/${id}`)

export const setModelProviderStatus = (id: string, status: 'active' | 'disabled') =>
  post<ModelProvider>(`/admin/model-providers/${id}/status`, { body: { status } })

export const listProviderOptions = () => get<{ options: ProviderOption[] }>('/admin/model-providers/options')
```

注意：如果现有 `admin-model-pool.ts` 的导入方式不同（如 `import http from './http'`），请调整为一致。

- [ ] **Step 3: 验证 TypeScript**

Run: `docker exec llmops-ui npx vue-tsc --noEmit 2>&1 | Select-String "admin-model-providers"`
Expected: 无该文件相关错误

- [ ] **Step 4: Commit**

```bash
git add ui/src/services/admin-model-providers.ts
git commit -m "feat: add admin model providers API service"
```

---

## Task 21: 添加 i18n 国际化键

**Files:**
- Modify: `ui/src/i18n/messages/zh-CN.ts`
- Modify: `ui/src/i18n/messages/en-US.ts`

- [ ] **Step 1: 在 zh-CN.ts 中添加 modelProviders 命名空间**

在 `admin` 对象中添加 `modelProviders` 子对象：

```typescript
    modelProviders: {
      title: '供应商管理',
      name: '供应商标识',
      label: '显示名称',
      description: '描述',
      icon: '图标',
      background: '背景色',
      defaultBaseUrl: '默认 Base URL',
      supportedModelTypes: '支持的模型类型',
      status: '状态',
      modelCount: '模型数量',
      active: '启用',
      disabled: '禁用',
      create: '新增供应商',
      edit: '编辑供应商',
      delete: '删除供应商',
      deleteConfirm: '确定删除该供应商吗？存在关联模型时无法删除。',
      deleteSuccess: '删除成功',
      createSuccess: '创建成功',
      updateSuccess: '更新成功',
      nameRequired: '请输入供应商标识',
      labelRequired: '请输入显示名称',
      baseUrlRequired: '请输入默认 Base URL',
      nameExists: '供应商标识已存在',
      hasModelsConflict: '存在关联模型，请先删除或禁用模型',
    },
```

- [ ] **Step 2: 在 admin.modelPool 中添加 modelType/compatibleApi 键**

在 `modelPool` 子对象中添加：

```typescript
      modelType: '模型类型',
      compatibleApi: '兼容协议',
      baseUrlFromProvider: 'Base URL（来自供应商）',
      modelTypeOptions: {
        chat: '文本对话',
        completion: '文本生成',
        embedding: '向量嵌入',
        multimodal: '多模态',
        image_generation: '图片生成',
        video_generation: '视频生成',
        ocr: 'OCR 识别',
        tts: '语音合成',
        asr: '语音识别',
        rerank: '重排序',
      },
      compatibleApiOptions: {
        openai: 'OpenAI 兼容',
        claude: 'Claude 兼容',
      },
```

- [ ] **Step 3: 在 en-US.ts 中添加对应英文翻译**

```typescript
    modelProviders: {
      title: 'Provider Management',
      name: 'Provider Name',
      label: 'Display Label',
      description: 'Description',
      icon: 'Icon',
      background: 'Background',
      defaultBaseUrl: 'Default Base URL',
      supportedModelTypes: 'Supported Model Types',
      status: 'Status',
      modelCount: 'Model Count',
      active: 'Active',
      disabled: 'Disabled',
      create: 'Create Provider',
      edit: 'Edit Provider',
      delete: 'Delete Provider',
      deleteConfirm: 'Are you sure to delete this provider? Cannot delete when models are associated.',
      deleteSuccess: 'Deleted successfully',
      createSuccess: 'Created successfully',
      updateSuccess: 'Updated successfully',
      nameRequired: 'Please enter provider name',
      labelRequired: 'Please enter display label',
      baseUrlRequired: 'Please enter default base URL',
      nameExists: 'Provider name already exists',
      hasModelsConflict: 'Associated models exist, please delete or disable them first',
    },
```

- [ ] **Step 4: 验证 TypeScript**

Run: `docker exec llmops-ui npx vue-tsc --noEmit 2>&1 | Select-String "zh-CN|en-US" | Select-Object -First 5`
Expected: 无该文件相关错误

- [ ] **Step 5: Commit**

```bash
git add ui/src/i18n/messages/zh-CN.ts ui/src/i18n/messages/en-US.ts
git commit -m "feat: add i18n keys for model providers and model type/compatible api"
```

---

## Task 22: 创建 ModelProvidersView.vue

**Files:**
- Create: `ui/src/views/admin/ModelProvidersView.vue`

- [ ] **Step 1: 读取现有 ModelsView.vue 了解项目 UI 模式**

读取 `ui/src/views/admin/ModelsView.vue` 的头部（前 100 行），了解：
- template 结构（a-card / a-table / a-modal 模式）
- script setup 导入方式
- API 调用模式
- 权限检查方式

- [ ] **Step 2: 创建 ModelProvidersView.vue**

基于项目现有模式创建。文件内容如下（使用 Arco Design 卡片网格布局）：

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message, Modal } from '@arco-design/web-vue'
import {
  createModelProvider,
  deleteModelProvider,
  listModelProviders,
  setModelProviderStatus,
  updateModelProvider,
  type ModelProvider,
} from '@/services/admin-model-providers'

const { t } = useI18n()

const loading = ref(false)
const providers = ref<ModelProvider[]>([])
const searchKeyword = ref('')
const statusFilter = ref('')

const modalVisible = ref(false)
const modalMode = ref<'create' | 'edit'>('create')
const formLoading = ref(false)
const form = ref({
  id: '',
  name: '',
  label: '',
  description: '',
  icon: '',
  background: '#FFFFFF',
  default_base_url: '',
  supported_model_types: [] as string[],
  status: 'active' as 'active' | 'disabled',
})

const MODEL_TYPE_OPTIONS = [
  'chat', 'completion', 'embedding', 'multimodal',
  'image_generation', 'video_generation', 'ocr', 'tts', 'asr', 'rerank',
]

const filteredProviders = computed(() => {
  return providers.value
})

async function loadData() {
  loading.value = true
  try {
    const resp = await listModelProviders({
      search: searchKeyword.value,
      status: statusFilter.value,
      current_page: 1,
      page_size: 100,
    })
    providers.value = resp.list || []
  } catch (e: any) {
    Message.error(e.message || 'Failed to load providers')
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  modalMode.value = 'create'
  form.value = {
    id: '',
    name: '',
    label: '',
    description: '',
    icon: '',
    background: '#FFFFFF',
    default_base_url: '',
    supported_model_types: [],
    status: 'active',
  }
  modalVisible.value = true
}

function openEditModal(provider: ModelProvider) {
  modalMode.value = 'edit'
  form.value = {
    id: provider.id,
    name: provider.name,
    label: provider.label,
    description: provider.description,
    icon: provider.icon,
    background: provider.background,
    default_base_url: provider.default_base_url,
    supported_model_types: provider.supported_model_types || [],
    status: provider.status,
  }
  modalVisible.value = true
}

async function handleSubmit() {
  if (!form.value.name && modalMode.value === 'create') {
    Message.error(t('admin.modelProviders.nameRequired'))
    return
  }
  if (!form.value.label) {
    Message.error(t('admin.modelProviders.labelRequired'))
    return
  }
  if (!form.value.default_base_url) {
    Message.error(t('admin.modelProviders.baseUrlRequired'))
    return
  }

  formLoading.value = true
  try {
    const payload: Partial<ModelProvider> = {
      name: form.value.name,
      label: form.value.label,
      description: form.value.description,
      icon: form.value.icon,
      background: form.value.background,
      default_base_url: form.value.default_base_url,
      supported_model_types: form.value.supported_model_types,
      status: form.value.status,
    }
    if (modalMode.value === 'create') {
      await createModelProvider(payload)
      Message.success(t('admin.modelProviders.createSuccess'))
    } else {
      await updateModelProvider(form.value.id, payload)
      Message.success(t('admin.modelProviders.updateSuccess'))
    }
    modalVisible.value = false
    await loadData()
  } catch (e: any) {
    Message.error(e.message || 'Operation failed')
  } finally {
    formLoading.value = false
  }
}

async function handleDelete(provider: ModelProvider) {
  Modal.warning({
    title: t('admin.modelProviders.delete'),
    content: t('admin.modelProviders.deleteConfirm'),
    hideCancel: false,
    onOk: async () => {
      try {
        await deleteModelProvider(provider.id)
        Message.success(t('admin.modelProviders.deleteSuccess'))
        await loadData()
      } catch (e: any) {
        Message.error(e.message || t('admin.modelProviders.hasModelsConflict'))
      }
    },
  })
}

async function toggleStatus(provider: ModelProvider) {
  const newStatus = provider.status === 'active' ? 'disabled' : 'active'
  try {
    await setModelProviderStatus(provider.id, newStatus)
    await loadData()
  } catch (e: any) {
    Message.error(e.message || 'Failed to update status')
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="admin-model-providers">
    <a-card :title="t('admin.modelProviders.title')">
      <template #extra>
        <a-space>
          <a-input
            v-model="searchKeyword"
            :placeholder="t('admin.modelProviders.name')"
            allow-clear
            style="width: 200px"
            @press-enter="loadData"
          />
          <a-select
            v-model="statusFilter"
            placeholder="Status"
            allow-clear
            style="width: 120px"
            @change="loadData"
          >
            <a-option value="active">{{ t('admin.modelProviders.active') }}</a-option>
            <a-option value="disabled">{{ t('admin.modelProviders.disabled') }}</a-option>
          </a-select>
          <a-button type="primary" @click="openCreateModal">
            {{ t('admin.modelProviders.create') }}
          </a-button>
        </a-space>
      </template>

      <a-spin :loading="loading" dot>
        <a-row :gutter="[16, 16]">
          <a-col
            v-for="provider in filteredProviders"
            :key="provider.id"
            :xs="24"
            :sm="12"
            :md="8"
            :lg="6"
            :xl="6"
          >
            <a-card hoverable>
              <template #title>
                <a-space>
                  <span>{{ provider.label }}</span>
                  <a-tag :color="provider.status === 'active' ? 'green' : 'red'">
                    {{ provider.status === 'active' ? t('admin.modelProviders.active') : t('admin.modelProviders.disabled') }}
                  </a-tag>
                </a-space>
              </template>
              <template #extra>
                <a-dropdown @select="(_val: any) => {}">
                  <a-button size="small" type="text">
                    <template #icon><icon-more /></template>
                  </a-button>
                  <template #content>
                    <a-doption @click="openEditModal(provider)">
                      {{ t('admin.modelProviders.edit') }}
                    </a-doption>
                    <a-doption @click="toggleStatus(provider)">
                      {{ provider.status === 'active' ? t('admin.modelProviders.disabled') : t('admin.modelProviders.active') }}
                    </a-doption>
                    <a-doption @click="handleDelete(provider)">
                      {{ t('admin.modelProviders.delete') }}
                    </a-doption>
                  </template>
                </a-dropdown>
              </template>

              <div class="provider-info">
                <p><strong>{{ t('admin.modelProviders.name') }}:</strong> {{ provider.name }}</p>
                <p><strong>{{ t('admin.modelProviders.defaultBaseUrl') }}:</strong> {{ provider.default_base_url }}</p>
                <p><strong>{{ t('admin.modelProviders.modelCount') }}:</strong> {{ provider.model_count }}</p>
                <div v-if="provider.supported_model_types?.length">
                  <strong>{{ t('admin.modelProviders.supportedModelTypes') }}:</strong>
                  <a-tag v-for="mt in provider.supported_model_types" :key="mt" size="small">
                    {{ mt }}
                  </a-tag>
                </div>
              </div>
            </a-card>
          </a-col>
        </a-row>
      </a-spin>
    </a-card>

    <!-- Create/Edit Modal -->
    <a-modal
      v-model:visible="modalVisible"
      :title="modalMode === 'create' ? t('admin.modelProviders.create') : t('admin.modelProviders.edit')"
      :ok-loading="formLoading"
      @ok="handleSubmit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="t('admin.modelProviders.name')" required>
          <a-input
            v-model="form.name"
            :disabled="modalMode === 'edit'"
            :placeholder="t('admin.modelProviders.name')"
          />
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.label')" required>
          <a-input v-model="form.label" :placeholder="t('admin.modelProviders.label')" />
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.defaultBaseUrl')" required>
          <a-input v-model="form.default_base_url" :placeholder="t('admin.modelProviders.defaultBaseUrl')" />
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.description')">
          <a-textarea v-model="form.description" :placeholder="t('admin.modelProviders.description')" />
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.supportedModelTypes')">
          <a-select
            v-model="form.supported_model_types"
            multiple
            allow-create
            :placeholder="t('admin.modelProviders.supportedModelTypes')"
          >
            <a-option v-for="mt in MODEL_TYPE_OPTIONS" :key="mt" :value="mt">{{ mt }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.status')">
          <a-select v-model="form.status">
            <a-option value="active">{{ t('admin.modelProviders.active') }}</a-option>
            <a-option value="disabled">{{ t('admin.modelProviders.disabled') }}</a-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<style scoped>
.provider-info p {
  margin: 4px 0;
  word-break: break-all;
}
</style>
```

- [ ] **Step 3: 验证 TypeScript**

Run: `docker exec llmops-ui npx vue-tsc --noEmit 2>&1 | Select-String "ModelProvidersView" | Select-Object -First 5`
Expected: 无该文件相关错误

- [ ] **Step 4: Commit**

```bash
git add ui/src/views/admin/ModelProvidersView.vue
git commit -m "feat: add ModelProvidersView.vue with CRUD UI"
```

---

## Task 23: 改造 ModelsView.vue

**Files:**
- Modify: `ui/src/views/admin/ModelsView.vue`

- [ ] **Step 1: 读取当前 ModelsView.vue 完整代码**

读取整个文件，了解：
- provider 下拉数据源（当前从已加载列表去重）
- base_url 表单字段位置
- 表单提交逻辑

- [ ] **Step 2: 替换 provider 下拉数据源**

找到 provider 选项的计算逻辑（当前从 models 列表去重的代码），替换为从 API 加载：

在 `<script setup>` 中添加：

```typescript
import { listProviderOptions, type ProviderOption } from '@/services/admin-model-providers'

const providerOptions = ref<ProviderOption[]>([])

async function loadProviderOptions() {
  try {
    const resp = await listProviderOptions()
    providerOptions.value = resp.options || []
  } catch (e) {
    providerOptions.value = []
  }
}

onMounted(() => {
  loadProviderOptions()
  // ... 现有加载逻辑
})
```

- [ ] **Step 3: 移除 base_url 表单字段，添加 model_type/compatible_api**

在表单中：
1. 删除 `base_url` 的 `a-form-item`
2. 在 provider 选择后，添加 `default_base_url` 只读展示：

```vue
        <a-form-item :label="t('admin.modelPool.baseUrlFromProvider')">
          <a-input
            :model-value="selectedProviderBaseUrl"
            disabled
          />
        </a-form-item>
```

3. 添加 `model_type` 和 `compatible_api` 选择框：

```vue
        <a-form-item :label="t('admin.modelPool.modelType')">
          <a-select v-model="form.model_type">
            <a-option
              v-for="mt in filteredModelTypeOptions"
              :key="mt"
              :value="mt"
            >
              {{ t(`admin.modelPool.modelTypeOptions.${mt}`) }}
            </a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.modelPool.compatibleApi')">
          <a-select v-model="form.compatible_api">
            <a-option value="openai">{{ t('admin.modelPool.compatibleApiOptions.openai') }}</a-option>
            <a-option value="claude">{{ t('admin.modelPool.compatibleApiOptions.claude') }}</a-option>
          </a-select>
        </a-form-item>
```

- [ ] **Step 4: 添加联动逻辑**

在 `<script setup>` 中添加计算属性：

```typescript
const selectedProvider = computed(() => {
  return providerOptions.value.find(p => p.name === form.value.provider)
})

const selectedProviderBaseUrl = computed(() => {
  return selectedProvider.value?.default_base_url || ''
})

const filteredModelTypeOptions = computed(() => {
  if (!selectedProvider.value) {
    return ['chat', 'completion', 'embedding', 'multimodal', 'image_generation', 'video_generation', 'ocr', 'tts', 'asr', 'rerank']
  }
  return selectedProvider.value.supported_model_types || ['chat']
})
```

- [ ] **Step 5: 在表单数据中添加 model_type/compatible_api，删除 base_url**

在 `form` ref 中：
1. 删除 `base_url` 字段
2. 添加 `model_type: 'chat'` 和 `compatible_api: 'openai'`

- [ ] **Step 6: 验证 TypeScript**

Run: `docker exec llmops-ui npx vue-tsc --noEmit 2>&1 | Select-String "ModelsView" | Select-Object -First 5`
Expected: 无该文件相关错误

- [ ] **Step 7: Commit**

```bash
git add ui/src/views/admin/ModelsView.vue
git commit -m "feat: refactor ModelsView.vue (provider dropdown from API, add model_type/compatible_api, remove base_url)"
```

---

## Task 24: 改造 ModelKeysView.vue

**Files:**
- Modify: `ui/src/views/admin/ModelKeysView.vue`

- [ ] **Step 1: 读取当前 ModelKeysView.vue**

了解 provider 下拉当前数据源。

- [ ] **Step 2: 替换 provider 下拉为从 API 加载**

与 Task 23 Step 2 相同，导入 `listProviderOptions`，在 `onMounted` 中加载。

- [ ] **Step 3: 验证 TypeScript**

Run: `docker exec llmops-ui npx vue-tsc --noEmit 2>&1 | Select-String "ModelKeysView" | Select-Object -First 5`
Expected: 无该文件相关错误

- [ ] **Step 4: Commit**

```bash
git add ui/src/views/admin/ModelKeysView.vue
git commit -m "feat: refactor ModelKeysView.vue provider dropdown to use API"
```

---

## Task 25: 添加前端路由和菜单

**Files:**
- Modify: `ui/src/router/index.ts`

- [ ] **Step 1: 读取当前路由配置**

读取 `ui/src/router/index.ts`，找到 admin 路由区域。

- [ ] **Step 2: 添加 provider 路由**

在 admin 子路由区域（与 `AdminModels` 路由同级）添加：

```typescript
    {
      path: 'model-providers',
      name: 'AdminModelProviders',
      component: () => import('@/views/admin/ModelProvidersView.vue'),
      meta: {
        requiresPermission: 'model_provider:read',
      },
    },
```

- [ ] **Step 3: 添加菜单项**

在菜单配置文件中（可能是 `ui/src/menu/` 或路由 meta 中），在"模型池管理"父菜单下，"模型管理"子菜单之前添加"供应商管理"菜单项。

具体文件位置和格式取决于项目菜单配置模式，需读取现有菜单文件确认。

- [ ] **Step 4: 验证 TypeScript**

Run: `docker exec llmops-ui npx vue-tsc --noEmit 2>&1 | Select-String "router" | Select-Object -First 5`
Expected: 无该文件相关错误

- [ ] **Step 5: Commit**

```bash
git add ui/src/router/index.ts
git commit -m "feat: add model providers route and menu"
```

---

## Task 26: 重建 UI 容器 + 前端验证

**Files:**
- 无文件改动，仅执行命令

- [ ] **Step 1: 完整 vue-tsc 验证**

Run: `docker exec llmops-ui npx vue-tsc --noEmit 2>&1 | Select-Object -Last 10`
Expected: 无错误

- [ ] **Step 2: 重建 UI 容器**

Run: `docker compose up -d --build ui 2>&1`
Expected: UI 容器重建成功

- [ ] **Step 3: 重启 Nginx**

Run: `docker compose restart nginx 2>&1`
Expected: Nginx 重启成功

- [ ] **Step 4: 前端页面验证**

在浏览器中访问管理后台：
- 供应商管理页可见 10+ 个内置供应商（+硅基流动，若已迁移）
- 模型管理页 provider 下拉包含所有 active provider
- 模型管理页表单无 base_url 字段
- 模型管理页 model_type 下拉包含 10 种类型
- 模型管理页 compatible_api 下拉包含 openai/claude
- provider 选择后，model_type 按其 supported_model_types 过滤

- [ ] **Step 5: Commit（如有代码修改）**

```bash
git add -A
git commit -m "chore: rebuild UI container and validate frontend"
```

---

## Task 27: yaml 清理 + 最终端到端验证

**Files:**
- Delete: `api/internal/core/language_model/providers/` 目录下所有 yaml 文件

- [ ] **Step 1: 确认 yaml 文件不再被引用**

Run: `docker exec llmops-api bash -c "grep -r 'providers.yaml\|positions.yaml' /app/api/internal/ --include='*.py' 2>&1 | grep -v __pycache__"`
Expected: 无匹配（LanguageModelManager 已不引用 yaml）

- [ ] **Step 2: 删除 yaml 目录**

```bash
docker exec llmops-api rm -rf /app/api/internal/core/language_model/providers/
```

同时在本地删除：
```bash
Remove-Item -Recurse -Force d:\DEMO\openagent-main\api\internal\core\language_model\providers\
```

- [ ] **Step 3: 重启 API 容器验证无报错**

Run:
```bash
docker compose restart api 2>&1
docker logs llmops-api --tail 20 2>&1
```
Expected: 启动无报错，无 yaml 相关错误

- [ ] **Step 4: 端到端测试 — 使用硅基流动模型**

1. 在供应商管理页确认硅基流动 provider 存在（若数据未迁移，手动新增）
2. 在模型管理页确认硅基流动模型存在且 model_type/compatible_api 正确
3. 在 Key 管理页确认 Key 关联到硅基流动 provider
4. 触发一次 LLM 调用，验证全链路：
   - Provider 懒加载 → DB 查询 → 缓存
   - Model 懒加载 → DB 查询 → 缓存
   - Key 匹配 → 实例化 → 调用成功

Run:
```bash
docker exec llmops-api bash -c "cd /app/api && python -c \"
from app.http.app import app
with app.app_context():
    from internal.core.language_model.language_model_manager import LanguageModelManager
    from injector import Injector
    # 通过 Flask app context 获取单例
    from app.http.app import injector
    manager = injector.get(LanguageModelManager)
    # 测试懒加载
    try:
        provider = manager.get_or_load_provider('openai')
        print(f'Provider loaded: {provider.name}, base_url={provider.default_base_url}')
    except Exception as e:
        print(f'Provider load failed: {e}')
\""
```
Expected: Provider loaded 成功

- [ ] **Step 5: 验证缓存命中**

第二次调用同一 provider，验证不查 DB：

Run:
```bash
docker exec llmops-api bash -c "cd /app/api && python -c \"
from app.http.app import app, injector
with app.app_context():
    from internal.core.language_model.language_model_manager import LanguageModelManager
    manager = injector.get(LanguageModelManager)
    import time
    t1 = time.time()
    manager.get_or_load_provider('openai')
    t2 = time.time()
    manager.get_or_load_provider('openai')
    t3 = time.time()
    print(f'First load: {(t2-t1)*1000:.2f}ms')
    print(f'Cache hit: {(t3-t2)*1000:.2f}ms')
\""
```
Expected: Cache hit 远快于 First load

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: cleanup yaml files and verify end-to-end with siliconflow model"
```

---

## Self-Review Notes

### Spec Coverage

| Spec Section | Plan Task(s) | Status |
|---|---|---|
| 2.1 ModelProviderConfig 表 | Task 1, 2 | ✅ |
| 2.2 ModelPoolConfig 改造 | Task 5, 10 | ✅ |
| 2.3 ModelKeyConfig 不改动 | Task 14 (仅加校验) | ✅ |
| 2.5 model_type 取值 | Task 6 | ✅ |
| 2.6 compatible_api 取值 | Task 6, 15 | ✅ |
| 3.1-3.2 实例化链路改造 | Task 7, 8 | ✅ |
| 3.3 LanguageModelManager 改造 | Task 7 | ✅ |
| 3.4 ModelClassRegistry | Task 6 | ✅ |
| 3.5 _build_model_entity | Task 7 | ✅ |
| 3.6 缓存失效触发点 | Task 12, 14 | ✅ |
| 4.1 Provider CRUD API | Task 12, 13, 16 | ✅ |
| 4.2 Model CRUD API 改造 | Task 14, 15 | ✅ |
| 4.3 Key 管理补充校验 | Task 14 | ✅ |
| 4.4 RBAC 权限 | Task 17 | ✅ |
| 4.5 前置校验规则 | Task 12, 14 | ✅ |
| 5.1-5.4 前端改造 | Task 22, 23, 24 | ✅ |
| 5.5 前端服务文件 | Task 20 | ✅ |
| 5.6 国际化 | Task 21 | ✅ |
| 5.7 路由与菜单 | Task 25 | ✅ |
| 6.1-6.3 迁移脚本 | Task 2, 3, 4, 5 | ✅ |
| 6.4 启动逻辑改造 | Task 18 | ✅ |
| 6.5 yaml 废弃 | Task 27 | ✅ |
| 6.6 部署顺序 | Task 19, 26, 27 | ✅ |
| 7.1-7.5 错误处理 | Task 7, 12, 14 | ✅ |
| 8.4 部署验证清单 | Task 19, 26, 27 | ✅ |

### Placeholder Scan

- 无 "TBD" / "TODO" / "implement later"
- 每个 Step 都有完整代码或精确命令
- Task 25 Step 3 提到"具体文件位置需读取现有菜单文件确认" — 这是因为菜单配置模式未完全确认，执行时需先读取菜单文件

### Type Consistency

- `ModelProviderConfig` 在 Task 1 定义，在 Task 7/12/14 引用 — 字段名一致
- `ProviderEntity.default_base_url` 在 Task 7 定义，在 Task 9 引用 — 一致
- `ModelClassRegistry.resolve(compatible_api, model_type)` 在 Task 6 定义，在 Task 8 引用 — 签名一致
- `invalidate_provider` / `invalidate_model` / `invalidate_all` 在 Task 7 定义，在 Task 12/14 引用 — 方法名一致
- `listProviderOptions` 在 Task 20 定义，在 Task 23/24 引用 — 函数名一致
- `model_type` / `compatible_api` 字段名在 Task 5/10/14/15/23 中一致

### 注意事项

1. **路由顺序**：`/admin/model-providers/options` 必须在 `/<uuid:provider_id>` 之前注册
2. **迁移顺序**：迁移 3（auto-create user providers）必须在迁移 4（drop base_url）之前执行
3. **缓存失效**：先 commit DB 事务，再失效缓存
4. **yaml 删除**：必须在迁移完成且代码改造验证通过后才删除
5. **数据保留**：迁移 3 会自动保留用户已配置的硅基流动模型数据
