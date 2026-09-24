# 知识库产品形态 P1 · 数据基座 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立知识库产品形态的数据基座——板块类型与分区模型、标签关联、存储配额计量与校验，使「建板块 / 传文件 / 配额累加与拒绝」端到端可用。

**Architecture:** 在现有 `KnowledgeBase` 上扩展 `base_type`（板块类型，硬约束）与 `partition_mode`（分区模式），新增 `KnowledgePartition`（两级树）、`KnowledgeBaseTag`/`KnowledgeDocumentTag`、`account_storage_usage`（用量计量）。配额通过 `PlanEntitlement` 自由键值（`storage_quota_gb`）承载，管理员在套餐板块配置即可生效，不改 `Plan` 表结构。所有上传路径统一收口到 `StorageQuotaService`。

**Tech Stack:** Python 3.11+ / Quart / SQLAlchemy 2.0 / Alembic / PostgreSQL / pytest / injector DI

**上游设计:** [knowledge-base-product-form-design.md](../../prd/knowledge-base-product-form-design.md)

**迁移基线:** 当前唯一 head = `o9d0e1f2a3b4`（新增迁移的 `down_revision` 必须指向它）

---

## 文件结构

### 新增文件

| 文件 | 职责 |
|---|---|
| `api/internal/entity/storage_quota_entity.py` | 配额常量与枚举（`DEFAULT_STORAGE_QUOTA_GB`、`STORAGE_QUOTA_FEATURE_KEY`、`StorageAddonPlanType`、板块/分区枚举） |
| `api/internal/model/knowledge_partition.py` | `KnowledgePartition` 模型（两级树） |
| `api/internal/model/knowledge_tag.py` | `KnowledgeBaseTag` / `KnowledgeDocumentTag` 关联模型 |
| `api/internal/model/account_storage_usage.py` | `account_storage_usage` 计量模型 |
| `api/internal/service/storage_quota_service.py` | 配额解析、用量读写、上传前校验、配额变更 |
| `api/internal/service/knowledge_partition_service.py` | 分区创建与两级层级校验 |
| `api/internal/migration/versions/p1a2b3c4d5e6_add_knowledge_product_form_base.py` | 本次全部 DDL |
| `api/test/internal/service/test_storage_quota_service.py` | 配额服务单测 |
| `api/test/internal/service/test_knowledge_partition_service.py` | 分区服务单测 |
| `api/test/internal/entity/test_storage_quota_entity.py` | 枚举与常量单测 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `api/internal/entity/knowledge_entity.py` | 新增 `KnowledgeBaseType`、`PartitionMode`、`DocumentMediaType` 枚举 |
| `api/internal/entity/upload_file_entity.py` | 新增 `ALLOWED_VIDEO_EXTENSION` / `ALLOWED_AUDIO_EXTENSION`；新增媒体类型→扩展名映射 |
| `api/internal/model/knowledge.py` | `KnowledgeBase` 加 `base_type`/`partition_mode`；`KnowledgeDocument` 加 `partition_id`/`media_type`/`parse_profile` |
| `api/internal/model/upload_file.py` | `size` 由 `Integer` 升级为 `BigInteger` |
| `api/internal/model/__init__.py` | 注册 3 个新模型（import 行 + `__all__`） |
| `api/internal/service/knowledge_base_service.py` | `create_user_content_base` 支持 `base_type`/`partition_mode` + 取值校验 |
| `api/internal/service/storage/runtime_storage_service.py` | 上传前配额校验 + 上传后累加（统一收口） |
| `api/app/http/module.py` | 注册 `StorageQuotaService` DI 绑定 |

---

## Task 1: 配额与板块枚举常量

**Files:**
- Create: `api/internal/entity/storage_quota_entity.py`
- Test: `api/test/internal/entity/test_storage_quota_entity.py`

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/entity/test_storage_quota_entity.py
from internal.entity.storage_quota_entity import (
    BYTES_PER_GB,
    DEFAULT_STORAGE_QUOTA_GB,
    STORAGE_QUOTA_FEATURE_KEY,
    StorageAddonPlanType,
)


def test_default_quota_is_5gb():
    assert DEFAULT_STORAGE_QUOTA_GB == 5


def test_bytes_per_gb_uses_1024_base():
    assert BYTES_PER_GB == 1024 ** 3


def test_quota_feature_key_is_stable():
    assert STORAGE_QUOTA_FEATURE_KEY == "storage_quota_gb"


def test_storage_addon_plan_type_value():
    assert StorageAddonPlanType.STORAGE_ADDON.value == "storage_addon"


def test_storage_addon_str_mixin_compares_with_plain_string():
    assert StorageAddonPlanType.STORAGE_ADDON == "storage_addon"


def test_storage_addon_enum_has_single_member():
    assert [member.value for member in StorageAddonPlanType] == ["storage_addon"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/entity/test_storage_quota_entity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'internal.entity.storage_quota_entity'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/entity/storage_quota_entity.py
"""存储配额常量与扩展包套餐类型。

只承载「存储配额」域的稳定值：
- 配额常量（默认基线、字节换算）
- 套餐权益 feature_key
- 存储扩展包的 plan_type

知识库板块/分区枚举属「知识库」域，定义在
``internal/entity/knowledge_entity.py``，不要在本文件重复定义。
"""
from enum import Enum

# 1 GB = 1024^3 字节（与存储计量的二进制口径一致）
BYTES_PER_GB = 1024 ** 3

# 注册用户的默认免费配额（GB）；套餐权益高于此值时取套餐值
DEFAULT_STORAGE_QUOTA_GB = 5

# 套餐权益中承载存储容量的 feature_key（PlanEntitlement.feature_key）
STORAGE_QUOTA_FEATURE_KEY = "storage_quota_gb"


class StorageAddonPlanType(str, Enum):
    """套餐类型：存储扩展包（Plan.plan_type 的一种取值）。"""

    STORAGE_ADDON = "storage_addon"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/entity/test_storage_quota_entity.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/entity/storage_quota_entity.py api/test/internal/entity/test_storage_quota_entity.py
git commit -m "feat(knowledge): add storage quota and base type enums"
```

---

## Task 2: 媒体类型扩展名与白名单

**Files:**
- Modify: `api/internal/entity/upload_file_entity.py`
- Test: `api/test/internal/entity/test_upload_file_entity.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/entity/test_upload_file_entity.py
from internal.entity.upload_file_entity import (
    ALLOWED_AUDIO_EXTENSION,
    ALLOWED_VIDEO_EXTENSION,
    MEDIA_TYPE_EXTENSIONS,
    allowed_extensions_for_base_type,
)


def test_video_extension_whitelist_contains_common_formats():
    for ext in ("mp4", "mov", "avi", "mkv", "webm"):
        assert ext in ALLOWED_VIDEO_EXTENSION


def test_audio_extension_whitelist_contains_common_formats():
    for ext in ("mp3", "wav", "m4a", "aac", "flac"):
        assert ext in ALLOWED_AUDIO_EXTENSION


def test_media_type_extensions_covers_four_types():
    assert set(MEDIA_TYPE_EXTENSIONS.keys()) == {"document", "image", "video", "audio"}


def test_video_base_type_allows_video_only():
    assert allowed_extensions_for_base_type("video") == ALLOWED_VIDEO_EXTENSION


def test_mixed_base_type_allows_everything():
    result = allowed_extensions_for_base_type("mixed")
    assert "mp4" in result and "jpg" in result and "pdf" in result


def test_unknown_base_type_falls_back_to_mixed():
    assert allowed_extensions_for_base_type("nonexistent") == allowed_extensions_for_base_type("mixed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/entity/test_upload_file_entity.py -v`
Expected: FAIL with `ImportError: cannot import name 'ALLOWED_VIDEO_EXTENSION'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/entity/upload_file_entity.py
# 允许上传的文件类型
ALLOWED_IMAGE_EXTENSION = ["jpg", "jpeg", "png", "webp", "gif", "svg"]
ALLOWED_DOCUMENT_EXTENSION = ["markdown", "md", "doc", "docx", "txt", "pdf", "csv", "xlsx", "xls", "html", "htm"]
ALLOWED_VIDEO_EXTENSION = ["mp4", "mov", "avi", "mkv", "webm"]
ALLOWED_AUDIO_EXTENSION = ["mp3", "wav", "m4a", "aac", "flac"]

# 媒体类型 -> 允许的扩展名列表
MEDIA_TYPE_EXTENSIONS = {
    "document": ALLOWED_DOCUMENT_EXTENSION,
    "image": ALLOWED_IMAGE_EXTENSION,
    "video": ALLOWED_VIDEO_EXTENSION,
    "audio": ALLOWED_AUDIO_EXTENSION,
}


def allowed_extensions_for_base_type(base_type: str) -> list[str]:
    """按知识库板块类型返回允许的扩展名列表。

    mixed 或不认识的类型返回全部扩展名的并集，保证存量库可继续上传。
    """
    if base_type in MEDIA_TYPE_EXTENSIONS:
        return MEDIA_TYPE_EXTENSIONS[base_type]
    merged: list[str] = []
    for extensions in MEDIA_TYPE_EXTENSIONS.values():
        for ext in extensions:
            if ext not in merged:
                merged.append(ext)
    return merged


def media_type_for_extension(extension: str) -> str:
    """根据扩展名反查媒体类型；未知类型归入 document。"""
    ext = (extension or "").lower().lstrip(".")
    for media_type, extensions in MEDIA_TYPE_EXTENSIONS.items():
        if ext in extensions:
            return media_type
    return "document"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/entity/test_upload_file_entity.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/entity/upload_file_entity.py api/test/internal/entity/test_upload_file_entity.py
git commit -m "feat(knowledge): extend upload whitelist with video and audio types"
```

---

## Task 3: knowledge_entity 新增板块与分区枚举

**Files:**
- Modify: `api/internal/entity/knowledge_entity.py`
- Test: `api/test/internal/entity/test_knowledge_entity.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/entity/test_knowledge_entity.py
from internal.entity.knowledge_entity import (
    DocumentMediaType,
    KnowledgeBaseType,
    KnowledgeCreatedFrom,
    PartitionMode,
)


def test_base_type_enum_has_five_values():
    assert {member.value for member in KnowledgeBaseType} == {
        "document", "image", "video", "audio", "mixed",
    }


def test_partition_mode_enum_has_four_values():
    assert {member.value for member in PartitionMode} == {
        "none", "date_month", "date_day", "custom",
    }


def test_document_media_type_enum_has_four_values():
    assert {member.value for member in DocumentMediaType} == {
        "document", "image", "video", "audio",
    }


def test_base_type_str_mixin_compares_with_plain_string():
    assert KnowledgeBaseType.VIDEO == "video"


def test_existing_created_from_enum_is_untouched():
    assert KnowledgeCreatedFrom.WORKFLOW_IMPORT.value == "workflow_import"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/entity/test_knowledge_entity.py -v`
Expected: FAIL with `ImportError: cannot import name 'KnowledgeBaseType'`

- [ ] **Step 3: Write minimal implementation**

在 `api/internal/entity/knowledge_entity.py` 的 `KnowledgeScope` 定义之后追加：

```python
class KnowledgeBaseType(str, Enum):
    """知识库板块类型，决定允许的媒体类型（服务端硬约束）。

    注意与 DocumentMediaType 的区别：本枚举是「板块」的组织类型
    （MIXED 板块可容纳任意 media_type），后者是「单个素材」的媒体类型。
    """

    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    MIXED = "mixed"


class PartitionMode(str, Enum):
    """分区模式：决定分区由系统按日期产生还是用户手动创建。"""

    NONE = "none"
    DATE_MONTH = "date_month"
    DATE_DAY = "date_day"
    CUSTOM = "custom"


class DocumentMediaType(str, Enum):
    """单个素材的媒体类型（knowledge_document.media_type）。"""

    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/entity/test_knowledge_entity.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/entity/knowledge_entity.py api/test/internal/entity/test_knowledge_entity.py
git commit -m "feat(knowledge): add base type and partition mode enums"
```

---

## Task 4: KnowledgePartition 模型

**Files:**
- Create: `api/internal/model/knowledge_partition.py`
- Modify: `api/internal/model/__init__.py`
- Test: `api/test/internal/model/test_knowledge_partition_model.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/model/test_knowledge_partition_model.py
from internal.model import KnowledgePartition


def test_partition_table_name():
    assert KnowledgePartition.__tablename__ == "knowledge_partition"


def test_partition_has_two_level_support_columns():
    columns = KnowledgePartition.__table__.columns
    assert "parent_id" in columns
    assert "partition_key" in columns
    assert "visibility_scope" in columns


def test_partition_key_is_unique_per_base():
    constraints = {c.name for c in KnowledgePartition.__table__.constraints if c.name}
    assert "uq_knowledge_partition_base_key" in constraints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/model/test_knowledge_partition_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'KnowledgePartition'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/model/knowledge_partition.py
"""知识库分区模型（两级树）。

一个知识库下的素材可归入分区；分区支持两级（大类 / 子类），
由服务层强制校验层级深度，parent_id 为空表示顶层分区。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    UniqueConstraint,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgePartition(Base):
    __tablename__ = "knowledge_partition"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_knowledge_partition_id"),
        UniqueConstraint("knowledge_base_id", "partition_key", name="uq_knowledge_partition_base_key"),
        Index("knowledge_partition_parent_id_idx", "parent_id"),
        Index("knowledge_partition_sort_idx", "knowledge_base_id", "sort_order"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    knowledge_base_id = Column(UUID, ForeignKey("knowledge_base.id"), nullable=False)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    # partition_key：分区业务键，日期模式为 2026-09 / 2026-09-12，自定义模式为 slug
    partition_key = Column(String(128), nullable=False, server_default=text("''::character varying"))
    # parent_id 为空表示顶层分区；两级树由服务层校验
    parent_id = Column(UUID, ForeignKey("knowledge_partition.id"), nullable=True)
    description = Column(Text, nullable=False, server_default=text("''::text"))
    sort_order = Column(Integer, nullable=False, server_default=text("0"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    # 分区权限首版不做，字段预留：默认继承板块可见性
    visibility_scope = Column(String(64), nullable=False, server_default=text("'private'::character varying"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
```

在 `api/internal/model/__init__.py` 中：

1. import 区追加（放在 `.knowledge` 行之后）：

```python
from .knowledge_partition import KnowledgePartition
```

2. `__all__` 中 `"KnowledgeBase", "KnowledgeDocument", "KnowledgeSegment", "UserMemory", "ExternalDataSource",` 一行改为：

```python
    "KnowledgeBase", "KnowledgeDocument", "KnowledgeSegment", "KnowledgePartition", "UserMemory", "ExternalDataSource",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/model/test_knowledge_partition_model.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/model/knowledge_partition.py api/internal/model/__init__.py api/test/internal/model/test_knowledge_partition_model.py
git commit -m "feat(knowledge): add knowledge partition model with two-level tree"
```

---

## Task 5: 知识库标签关联模型

**Files:**
- Create: `api/internal/model/knowledge_tag.py`
- Modify: `api/internal/model/__init__.py`
- Test: `api/test/internal/model/test_knowledge_tag_model.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/model/test_knowledge_tag_model.py
from internal.model import KnowledgeBaseTag, KnowledgeDocumentTag


def test_knowledge_base_tag_table_name():
    assert KnowledgeBaseTag.__tablename__ == "knowledge_base_tag"


def test_knowledge_document_tag_table_name():
    assert KnowledgeDocumentTag.__tablename__ == "knowledge_document_tag"


def test_base_tag_has_required_columns():
    columns = KnowledgeBaseTag.__table__.columns
    assert "knowledge_base_id" in columns
    assert "tag_id" in columns
    assert "account_id" in columns


def test_document_tag_has_unique_pair():
    constraints = {c.name for c in KnowledgeDocumentTag.__table__.constraints if c.name}
    assert "uq_knowledge_document_tag_pair" in constraints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/model/test_knowledge_tag_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'KnowledgeBaseTag'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/model/knowledge_tag.py
"""知识库标签关联模型。

复用既有 Tag 模型（api/internal/model/tag.py），仅新增知识库/素材两级的
关联表，对齐既有 AppTag / WorkflowTag 的模式。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    UUID,
    UniqueConstraint,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class KnowledgeBaseTag(Base):
    """知识库（板块）标签关联。"""

    __tablename__ = "knowledge_base_tag"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_knowledge_base_tag_id"),
        UniqueConstraint("knowledge_base_id", "tag_id", name="uq_knowledge_base_tag_pair"),
        Index("knowledge_base_tag_tag_idx", "tag_id"),
        Index("knowledge_base_tag_account_idx", "account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    knowledge_base_id = Column(UUID, ForeignKey("knowledge_base.id"), nullable=False)
    tag_id = Column(UUID, ForeignKey("tag.id"), nullable=False)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class KnowledgeDocumentTag(Base):
    """素材（文档）标签关联。"""

    __tablename__ = "knowledge_document_tag"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_knowledge_document_tag_id"),
        UniqueConstraint("knowledge_document_id", "tag_id", name="uq_knowledge_document_tag_pair"),
        Index("knowledge_document_tag_tag_idx", "tag_id"),
        Index("knowledge_document_tag_account_idx", "account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    knowledge_document_id = Column(UUID, ForeignKey("knowledge_document.id"), nullable=False)
    tag_id = Column(UUID, ForeignKey("tag.id"), nullable=False)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
```

在 `api/internal/model/__init__.py` 中：

1. import 区追加：

```python
from .knowledge_tag import KnowledgeBaseTag, KnowledgeDocumentTag
```

2. `__all__` 中知识库那一行改为（追加两个词条）：

```python
    "KnowledgeBase", "KnowledgeDocument", "KnowledgeSegment", "KnowledgePartition", "KnowledgeBaseTag", "KnowledgeDocumentTag", "UserMemory", "ExternalDataSource",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/model/test_knowledge_tag_model.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/model/knowledge_tag.py api/internal/model/__init__.py api/test/internal/model/test_knowledge_tag_model.py
git commit -m "feat(knowledge): add knowledge base and document tag models"
```

---

## Task 6: account_storage_usage 计量模型

**Files:**
- Create: `api/internal/model/account_storage_usage.py`
- Modify: `api/internal/model/__init__.py`
- Test: `api/test/internal/model/test_account_storage_usage_model.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/model/test_account_storage_usage_model.py
from internal.model import AccountStorageUsage


def test_table_name():
    assert AccountStorageUsage.__tablename__ == "account_storage_usage"


def test_used_bytes_is_bigint():
    from sqlalchemy import BigInteger

    assert isinstance(AccountStorageUsage.__table__.columns["used_bytes"].type, BigInteger)


def test_account_id_is_unique():
    constraints = {c.name for c in AccountStorageUsage.__table__.constraints if c.name}
    assert "uq_account_storage_usage_account_id" in constraints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/model/test_account_storage_usage_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'AccountStorageUsage'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/model/account_storage_usage.py
"""账号存储用量计量模型。

缓存每个账号已用存储字节数，避免每次上传都全表 SUM(upload_file.size)。
上传 / 删除 / 回收站清理 / 物理销毁时同步增减。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    UUID,
    UniqueConstraint,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AccountStorageUsage(Base):
    __tablename__ = "account_storage_usage"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_account_storage_usage_id"),
        UniqueConstraint("account_id", name="uq_account_storage_usage_account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, ForeignKey("account.id"), nullable=False)
    # 已用字节数，BigInteger 支持 TB 级
    used_bytes = Column(BigInteger, nullable=False, server_default=text("0"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
```

在 `api/internal/model/__init__.py` 中：

1. import 区追加：

```python
from .account_storage_usage import AccountStorageUsage
```

2. `__all__` 中 `"UploadFile",` 一行改为：

```python
    "UploadFile", "AccountStorageUsage",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/model/test_account_storage_usage_model.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/model/account_storage_usage.py api/internal/model/__init__.py api/test/internal/model/test_account_storage_usage_model.py
git commit -m "feat(knowledge): add account storage usage metering model"
```

---

## Task 7: KnowledgeBase 扩展 base_type 与 partition_mode

**Files:**
- Modify: `api/internal/model/knowledge.py:29-48`
- Test: `api/test/internal/model/test_knowledge_base_columns.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/model/test_knowledge_base_columns.py
from internal.model import KnowledgeBase


def test_base_has_base_type_column():
    columns = KnowledgeBase.__table__.columns
    assert "base_type" in columns
    assert columns["base_type"].server_default.arg.text == "'mixed'::character varying"


def test_base_has_partition_mode_column():
    columns = KnowledgeBase.__table__.columns
    assert "partition_mode" in columns
    assert columns["partition_mode"].server_default.arg.text == "'none'::character varying"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/model/test_knowledge_base_columns.py -v`
Expected: FAIL with `AssertionError: assert 'base_type' in <columns>`

- [ ] **Step 3: Write minimal implementation**

在 `api/internal/model/knowledge.py` 的 `KnowledgeBase` 类中，`knowledge_scope` 列之后插入两列：

```python
    # 板块类型：决定允许上传的媒体类型（服务端硬约束）；存量库默认 mixed
    base_type = Column(String(32), nullable=False, server_default=text("'mixed'::character varying"))
    # 分区模式：none / date_month / date_day / custom
    partition_mode = Column(String(32), nullable=False, server_default=text("'none'::character varying"))
```

同时在 `__table_args__` 的索引元组中追加一行：

```python
        Index("knowledge_base_base_type_idx", "base_type"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/model/test_knowledge_base_columns.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/model/knowledge.py api/test/internal/model/test_knowledge_base_columns.py
git commit -m "feat(knowledge): add base_type and partition_mode to knowledge base"
```

---

## Task 8: KnowledgeDocument 扩展媒体字段

**Files:**
- Modify: `api/internal/model/knowledge.py:51-77`
- Test: `api/test/internal/model/test_knowledge_document_columns.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/model/test_knowledge_document_columns.py
from internal.model import KnowledgeDocument


def test_document_has_media_columns():
    columns = KnowledgeDocument.__table__.columns
    assert "partition_id" in columns
    assert "media_type" in columns
    assert "parse_profile" in columns


def test_media_type_defaults_to_document():
    columns = KnowledgeDocument.__table__.columns
    assert columns["media_type"].server_default.arg.text == "'document'::character varying"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/model/test_knowledge_document_columns.py -v`
Expected: FAIL with `AssertionError: assert 'partition_id' in <columns>`

- [ ] **Step 3: Write minimal implementation**

在 `api/internal/model/knowledge.py` 的 `KnowledgeDocument` 类中，`upload_file_id` 列之后插入：

```python
    # 所属分区（两级树，可为空表示未归分区）
    partition_id = Column(UUID, ForeignKey("knowledge_partition.id"), nullable=True)
    # 媒体类型：document / image / video / audio
    media_type = Column(String(32), nullable=False, server_default=text("'document'::character varying"))
    # 解析档位与产物索引：{"tier1": {...}, "tier2": {...}, "frames": [...]}
    parse_profile = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
```

同时在 `__table_args__` 中追加索引：

```python
        Index("knowledge_document_partition_idx", "partition_id"),
        Index("knowledge_document_media_type_idx", "media_type"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/model/test_knowledge_document_columns.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/model/knowledge.py api/test/internal/model/test_knowledge_document_columns.py
git commit -m "feat(knowledge): add media_type, partition_id and parse_profile to document"
```

---

## Task 9: UploadFile.size 升级为 BigInteger

**Files:**
- Modify: `api/internal/model/upload_file.py:31`
- Test: `api/test/internal/model/test_upload_file_size_type.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/model/test_upload_file_size_type.py
from sqlalchemy import BigInteger

from internal.model import UploadFile


def test_size_column_is_bigint():
    assert isinstance(UploadFile.__table__.columns["size"].type, BigInteger)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/model/test_upload_file_size_type.py -v`
Expected: FAIL with `AssertionError` (current type is Integer)

- [ ] **Step 3: Write minimal implementation**

将 `api/internal/model/upload_file.py` 的 import 行改为引入 `BigInteger`：

```python
from sqlalchemy import (
    BigInteger,
    Column,
    UUID,
    String,
    DateTime,
    PrimaryKeyConstraint,
    text,
    Index
)
```

将 `size` 列改为：

```python
    # 文件字节数：BigInteger 支持数 GB 级视频素材
    size = Column(BigInteger, nullable=False, server_default=text('0'))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/model/test_upload_file_size_type.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/model/upload_file.py api/test/internal/model/test_upload_file_size_type.py
git commit -m "fix(storage): upgrade upload file size to bigint for large media"
```

---

## Task 10: 数据库迁移

**Files:**
- Create: `api/internal/migration/versions/p1a2b3c4d5e6_add_knowledge_product_form_base.py`

- [ ] **Step 1: 写迁移文件**

```python
"""knowledge product form base

Revision ID: p1a2b3c4d5e6
Revises: o9d0e1f2a3b4
Create Date: 2026-09-12

新增知识库产品形态数据基座：
- knowledge_base 增加 base_type / partition_mode
- knowledge_document 增加 partition_id / media_type / parse_profile
- upload_file.size 由 integer 升级为 bigint
- 新增 knowledge_partition / knowledge_base_tag / knowledge_document_tag / account_storage_usage
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'p1a2b3c4d5e6'
down_revision = 'o9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    # 1) knowledge_base 扩展
    op.add_column('knowledge_base', sa.Column(
        'base_type', sa.String(length=32), nullable=False,
        server_default=sa.text("'mixed'::character varying")))
    op.add_column('knowledge_base', sa.Column(
        'partition_mode', sa.String(length=32), nullable=False,
        server_default=sa.text("'none'::character varying")))
    op.create_index('knowledge_base_base_type_idx', 'knowledge_base', ['base_type'])

    # 2) knowledge_document 扩展
    op.add_column('knowledge_document', sa.Column('partition_id', sa.UUID(), nullable=True))
    op.add_column('knowledge_document', sa.Column(
        'media_type', sa.String(length=32), nullable=False,
        server_default=sa.text("'document'::character varying")))
    op.add_column('knowledge_document', sa.Column(
        'parse_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'{}'::jsonb")))
    op.create_index('knowledge_document_partition_idx', 'knowledge_document', ['partition_id'])
    op.create_index('knowledge_document_media_type_idx', 'knowledge_document', ['media_type'])

    # 3) upload_file.size 升级 bigint（大文件必须）
    op.alter_column('upload_file', 'size',
                    existing_type=sa.Integer(), type_=sa.BigInteger(),
                    existing_nullable=False)

    # 4) knowledge_partition
    op.create_table(
        'knowledge_partition',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('knowledge_base_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('partition_key', sa.String(length=128), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('parent_id', sa.UUID(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('visibility_scope', sa.String(length=64), nullable=False, server_default=sa.text("'private'::character varying")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_base.id'],
                                name='fk_knowledge_partition_base_id_knowledge_base', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['knowledge_partition.id'],
                                name='fk_knowledge_partition_parent_id_knowledge_partition', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_partition_id'),
        sa.UniqueConstraint('knowledge_base_id', 'partition_key', name='uq_knowledge_partition_base_key'),
    )
    op.create_index('knowledge_partition_parent_id_idx', 'knowledge_partition', ['parent_id'])
    op.create_index('knowledge_partition_sort_idx', 'knowledge_partition', ['knowledge_base_id', 'sort_order'])

    # 4.1) knowledge_document.partition_id 外键（需等 knowledge_partition 建表后追加）
    op.create_foreign_key(
        'fk_knowledge_document_partition_id_knowledge_partition',
        'knowledge_document', 'knowledge_partition',
        ['partition_id'], ['id'], ondelete='SET NULL')

    # 5) knowledge_base_tag
    op.create_table(
        'knowledge_base_tag',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('knowledge_base_id', sa.UUID(), nullable=False),
        sa.Column('tag_id', sa.UUID(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_base.id'],
                                name='fk_knowledge_base_tag_base_id_knowledge_base', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'],
                                name='fk_knowledge_base_tag_tag_id_tag', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_base_tag_id'),
        sa.UniqueConstraint('knowledge_base_id', 'tag_id', name='uq_knowledge_base_tag_pair'),
    )
    op.create_index('knowledge_base_tag_tag_idx', 'knowledge_base_tag', ['tag_id'])
    op.create_index('knowledge_base_tag_account_idx', 'knowledge_base_tag', ['account_id'])

    # 6) knowledge_document_tag
    op.create_table(
        'knowledge_document_tag',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('knowledge_document_id', sa.UUID(), nullable=False),
        sa.Column('tag_id', sa.UUID(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.ForeignKeyConstraint(['knowledge_document_id'], ['knowledge_document.id'],
                                name='fk_knowledge_document_tag_document_id_knowledge_document', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'],
                                name='fk_knowledge_document_tag_tag_id_tag', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_document_tag_id'),
        sa.UniqueConstraint('knowledge_document_id', 'tag_id', name='uq_knowledge_document_tag_pair'),
    )
    op.create_index('knowledge_document_tag_tag_idx', 'knowledge_document_tag', ['tag_id'])
    op.create_index('knowledge_document_tag_account_idx', 'knowledge_document_tag', ['account_id'])

    # 7) account_storage_usage
    op.create_table(
        'account_storage_usage',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('used_bytes', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'],
                                name='fk_account_storage_usage_account_id_account', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_account_storage_usage_id'),
        sa.UniqueConstraint('account_id', name='uq_account_storage_usage_account_id'),
    )


def downgrade():
    op.drop_table('account_storage_usage')

    op.drop_index('knowledge_document_tag_account_idx', table_name='knowledge_document_tag')
    op.drop_index('knowledge_document_tag_tag_idx', table_name='knowledge_document_tag')
    op.drop_table('knowledge_document_tag')

    op.drop_index('knowledge_base_tag_account_idx', table_name='knowledge_base_tag')
    op.drop_index('knowledge_base_tag_tag_idx', table_name='knowledge_base_tag')
    op.drop_table('knowledge_base_tag')

    # 先解除 knowledge_document 对分区的外键引用，再删分区表（避免依赖冲突）
    op.drop_constraint('fk_knowledge_document_partition_id_knowledge_partition',
                       'knowledge_document', type_='foreignkey')
    op.drop_index('knowledge_document_media_type_idx', table_name='knowledge_document')
    op.drop_index('knowledge_document_partition_idx', table_name='knowledge_document')
    op.drop_column('knowledge_document', 'parse_profile')
    op.drop_column('knowledge_document', 'media_type')
    op.drop_column('knowledge_document', 'partition_id')

    op.drop_index('knowledge_partition_sort_idx', table_name='knowledge_partition')
    op.drop_index('knowledge_partition_parent_id_idx', table_name='knowledge_partition')
    op.drop_table('knowledge_partition')

    op.alter_column('upload_file', 'size',
                    existing_type=sa.BigInteger(), type_=sa.Integer(),
                    existing_nullable=False)

    op.drop_index('knowledge_base_base_type_idx', table_name='knowledge_base')
    op.drop_column('knowledge_base', 'partition_mode')
    op.drop_column('knowledge_base', 'base_type')
```

- [ ] **Step 2: 校验迁移链为单 head 且可 upgrade**

Run: `cd api && python scripts/verify_migration_upgrade.py`
Expected: 输出单 head（`p1a2b3c4d5e6`）且 `current == head`，无 `Expected exactly one migration head` 报错

- [ ] **Step 3: 跑迁移相关单测**

Run: `cd api && python -m pytest test/scripts/test_verify_migration_upgrade.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add api/internal/migration/versions/p1a2b3c4d5e6_add_knowledge_product_form_base.py
git commit -m "feat(knowledge): migrate storage quota and knowledge product form base"
```

---

## Task 11: StorageQuotaService 配额解析

**Files:**
- Create: `api/internal/service/storage_quota_service.py`
- Test: `api/test/internal/service/test_storage_quota_service.py`

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_storage_quota_service.py
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException
from internal.service.storage_quota_service import StorageQuotaService


class _QueryStub:
    def __init__(self, *, first_result=None, all_result=None, one_or_none_result=None):
        self._first = first_result
        self._all = [] if all_result is None else all_result
        self._one_or_none = one_or_none_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def join(self, *_a, **_kw):
        return self

    def order_by(self, *_a, **_kw):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all

    def one_or_none(self):
        return self._one_or_none


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


def _new_service(session=None):
    return StorageQuotaService(db=SimpleNamespace(session=session or _SessionStub()))


def test_default_quota_when_no_membership():
    service = _new_service(_SessionStub([_QueryStub(first_result=None), _QueryStub(all_result=[])]))
    assert service.resolve_total_quota_bytes(uuid4()) == 5 * (1024 ** 3)


def test_membership_entitlement_overrides_default():
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = SimpleNamespace(feature_value="100", value_type="number")
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
        _QueryStub(all_result=[]),
    ]))
    assert service.resolve_total_quota_bytes(uuid4()) == 100 * (1024 ** 3)


def test_addon_packages_are_additive():
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = SimpleNamespace(feature_value="100", value_type="number")
    addon_one = SimpleNamespace(feature_value="50", value_type="number")
    addon_two = SimpleNamespace(feature_value="200", value_type="number")
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
        _QueryStub(all_result=[addon_one, addon_two]),
    ]))
    assert service.resolve_total_quota_bytes(uuid4()) == 350 * (1024 ** 3)


def test_check_raises_when_over_quota():
    account_id = uuid4()
    service = _new_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=SimpleNamespace(used_bytes=5 * (1024 ** 3))),
    ]))
    with pytest.raises(ForbiddenException):
        service.check_quota(account_id, incoming_bytes=1024)


def test_check_passes_when_within_quota():
    account_id = uuid4()
    service = _new_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(all_result=[]),
        _QueryStub(one_or_none_result=SimpleNamespace(used_bytes=1024)),
    ]))
    service.check_quota(account_id, incoming_bytes=1024)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_storage_quota_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'internal.service.storage_quota_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/service/storage_quota_service.py
"""存储配额服务。

统一负责：
- 解析账号的总配额（默认基线 vs 生效套餐权益 + 已购扩展包）
- 读取 / 累加账号已用存储
- 上传前的配额校验（所有上传路径的统一收口点）

配额规则：
    total_quota = max(基线 5GB, 生效套餐 storage_quota_gb) + sum(已购扩展包 GB)
"""
from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.storage_quota_entity import (
    BYTES_PER_GB,
    DEFAULT_STORAGE_QUOTA_GB,
    STORAGE_QUOTA_FEATURE_KEY,
    StorageAddonPlanType,
)
from internal.exception import ForbiddenException
from internal.model import AccountStorageUsage, Membership, PlanEntitlement, PurchaseOrder
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class StorageQuotaService(BaseService):
    """存储配额与用量服务。"""

    db: SQLAlchemy

    def resolve_total_quota_bytes(self, account_id: UUID) -> int:
        """解析账号的总配额（字节）。

        取「生效套餐的存储权益」与「默认基线」的较大值，再累加已购扩展包。
        """
        base_quota_gb = DEFAULT_STORAGE_QUOTA_GB
        plan_quota_gb = self._resolve_active_plan_quota_gb(account_id)
        if plan_quota_gb > base_quota_gb:
            base_quota_gb = plan_quota_gb
        addon_gb = self._resolve_purchased_addon_gb(account_id)
        return (base_quota_gb + addon_gb) * BYTES_PER_GB

    def _resolve_active_plan_quota_gb(self, account_id: UUID) -> int:
        """取当前生效会员套餐的 storage_quota_gb；无生效套餐返回 0。"""
        membership = (
            self.db.session.query(Membership)
            .filter_by(account_id=account_id, status="active")
            .order_by(Membership.expires_at.desc())
            .first()
        )
        if membership is None:
            return 0
        entitlements = (
            self.db.session.query(PlanEntitlement)
            .filter_by(plan_id=membership.plan_id, feature_key=STORAGE_QUOTA_FEATURE_KEY)
            .all()
        )
        if not entitlements:
            return 0
        try:
            return int(entitlements[0].feature_value)
        except (TypeError, ValueError):
            return 0

    def _resolve_purchased_addon_gb(self, account_id: UUID) -> int:
        """累加账号所有已支付存储扩展包的容量（GB）。

        单次 JOIN 查询取回扩展包套餐的全部 storage_quota_gb 权益，避免 N+1。
        """
        entitlements = (
            self.db.session.query(PlanEntitlement)
            .join(PurchaseOrder, PurchaseOrder.plan_id == PlanEntitlement.plan_id)
            .filter(
                PurchaseOrder.account_id == account_id,
                PurchaseOrder.status == "paid",
                PurchaseOrder.plan_type == StorageAddonPlanType.STORAGE_ADDON.value,
                PlanEntitlement.feature_key == STORAGE_QUOTA_FEATURE_KEY,
            )
            .all()
        )
        total_gb = 0
        for entitlement in entitlements:
            try:
                total_gb += int(entitlement.feature_value)
            except (TypeError, ValueError):
                continue
        return total_gb

    def get_used_bytes(self, account_id: UUID) -> int:
        """读取账号已用存储字节数；无记录视为 0。"""
        usage = (
            self.db.session.query(AccountStorageUsage)
            .filter_by(account_id=account_id)
            .one_or_none()
        )
        if usage is None:
            return 0
        return int(usage.used_bytes or 0)

    def get_usage_summary(self, account_id: UUID) -> dict:
        """返回配额概览，用于前端用量面板。"""
        total = self.resolve_total_quota_bytes(account_id)
        used = self.get_used_bytes(account_id)
        return {
            "total_bytes": total,
            "used_bytes": used,
            "remaining_bytes": max(total - used, 0),
            "usage_percent": round(used / total * 100, 2) if total > 0 else 0.0,
        }

    def check_quota(self, account_id: UUID, incoming_bytes: int) -> None:
        """上传前校验：超出配额时抛 ForbiddenException。

        所有上传路径（用户页面上传 / 小钰帮传 / 外部数据源同步）必须调用本方法。
        """
        total = self.resolve_total_quota_bytes(account_id)
        used = self.get_used_bytes(account_id)
        if used + incoming_bytes > total:
            raise ForbiddenException(
                "存储空间不足，请购买存储扩展包后重试",
                {
                    "total_bytes": total,
                    "used_bytes": used,
                    "incoming_bytes": incoming_bytes,
                    "reason_code": "storage_quota_exceeded",
                },
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_storage_quota_service.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/storage_quota_service.py api/test/internal/service/test_storage_quota_service.py
git commit -m "feat(storage): add storage quota resolution and check service"
```

---

## Task 12: 用量累加与释放

**Files:**
- Modify: `api/internal/service/storage_quota_service.py`
- Test: `api/test/internal/service/test_storage_quota_service.py` (append)

- [ ] **Step 1: Write the failing test**

在 `api/test/internal/service/test_storage_quota_service.py` 末尾追加：

```python
def test_add_usage_creates_record_when_absent(monkeypatch):
    account_id = uuid4()
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
    created = []
    monkeypatch.setattr(service, "create",
        lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))

    service.add_usage(account_id, 1024)

    assert created[0]["account_id"] == account_id
    assert created[0]["used_bytes"] == 1024


def test_add_usage_increments_existing_record(monkeypatch):
    account_id = uuid4()
    usage = SimpleNamespace(used_bytes=2048)
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=usage)]))
    updated = []
    monkeypatch.setattr(service, "update",
        lambda instance, **kwargs: updated.append(kwargs) or instance)

    service.add_usage(account_id, 1024)

    assert updated[0]["used_bytes"] == 3072


def test_release_usage_never_goes_negative(monkeypatch):
    account_id = uuid4()
    usage = SimpleNamespace(used_bytes=512)
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=usage)]))
    updated = []
    monkeypatch.setattr(service, "update",
        lambda instance, **kwargs: updated.append(kwargs) or instance)

    service.release_usage(account_id, 4096)

    assert updated[0]["used_bytes"] == 0


def test_release_usage_is_noop_when_record_absent():
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
    service.release_usage(uuid4(), 4096)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_storage_quota_service.py -v`
Expected: FAIL with `AttributeError: 'StorageQuotaService' object has no attribute 'add_usage'`

- [ ] **Step 3: Write minimal implementation**

在 `api/internal/service/storage_quota_service.py` 的 `check_quota` 方法之后追加：

```python
    def add_usage(self, account_id: UUID, bytes_delta: int) -> int:
        """累加账号已用存储；无记录时自动创建。返回累加后的已用字节数。"""
        if bytes_delta <= 0:
            return self.get_used_bytes(account_id)
        usage = (
            self.db.session.query(AccountStorageUsage)
            .filter_by(account_id=account_id)
            .one_or_none()
        )
        if usage is None:
            created = self.create(AccountStorageUsage, account_id=account_id, used_bytes=bytes_delta)
            return int(created.used_bytes)
        new_value = int(usage.used_bytes or 0) + bytes_delta
        self.update(usage, used_bytes=new_value)
        return new_value

    def release_usage(self, account_id: UUID, bytes_delta: int) -> int:
        """释放账号已用存储（删除 / 销毁时调用）；下限为 0。返回释放后的字节数。"""
        if bytes_delta <= 0:
            return self.get_used_bytes(account_id)
        usage = (
            self.db.session.query(AccountStorageUsage)
            .filter_by(account_id=account_id)
            .one_or_none()
        )
        if usage is None:
            return 0
        new_value = max(int(usage.used_bytes or 0) - bytes_delta, 0)
        self.update(usage, used_bytes=new_value)
        return new_value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_storage_quota_service.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/storage_quota_service.py api/test/internal/service/test_storage_quota_service.py
git commit -m "feat(storage): add usage accumulate and release on quota service"
```

---

## Task 13: 上传路径接入配额校验（统一收口到 RuntimeStorageProxy）

**Files:**
- Modify: `api/internal/service/storage/runtime_storage_service.py:28-100`
- Modify: `api/app/http/module.py`（注册 `StorageQuotaService` 绑定）
- Test: `api/test/internal/service/test_upload_quota_guard.py` (create)

**为什么改代理而不是三个后端**：`RuntimeStorageProxy` 是所有上传的**唯一入口**——[module.py:111](../../../api/app/http/module.py#L111) 把 `CosService` 绑定到它，三个后端实例由 `_get_service()` 在运行时手动构造。在代理层收口可**一处覆盖全部后端与全部调用方**，符合设计文档「配额校验收口在一处」的要求。

- [ ] **Step 1: 确认 RuntimeStorageProxy 无手工构造点**

Run: `cd api && python -c "import subprocess"` 后执行：

```powershell
Get-ChildItem -Path "d:\DEMO\openagent-main\api" -Recurse -File -Include *.py | Select-String -Pattern "RuntimeStorageProxy\(" | Select-Object Path,LineNumber,Line
```

Expected: 仅 `module.py` 的 `binder.bind(...)` 与 `_get_service()` 内部的 `LocalStorageService(...)` / `CosService(...)` / `AliyunOSSService(...)`，**无其他手工构造 RuntimeStorageProxy 的位置**。若发现其他构造点，需同步补 `storage_quota_service` 参数。

- [ ] **Step 2: Write the failing test**

```python
# api/test/internal/service/test_upload_quota_guard.py
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException
from internal.service.storage_quota_service import StorageQuotaService


class _QueryStub:
    def __init__(self, *, first_result=None, one_or_none_result=None, all_result=None):
        self._first = first_result
        self._one_or_none = one_or_none_result
        self._all = [] if all_result is None else all_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def order_by(self, *_a, **_kw):
        return self

    def first(self):
        return self._first

    def one_or_none(self):
        return self._one_or_none

    def all(self):
        return self._all


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


def _quota_service(session):
    return StorageQuotaService(db=SimpleNamespace(session=session))


def test_upload_guard_rejects_when_quota_exceeded():
    """模拟上传服务的守卫行为：check 抛错则不上传。"""
    account_id = uuid4()
    service = _quota_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(one_or_none_result=SimpleNamespace(used_bytes=5 * (1024 ** 3))),
    ]))
    with pytest.raises(ForbiddenException):
        service.check_quota(account_id, incoming_bytes=1)


def test_upload_guard_passes_and_accumulates():
    account_id = uuid4()
    service = _quota_service(_SessionStub([
        _QueryStub(first_result=None),
        _QueryStub(one_or_none_result=None),
    ]))
    service.check_quota(account_id, incoming_bytes=1024)
    created = []
    service.create = lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs)
    service.add_usage(account_id, 1024)
    assert created[0]["used_bytes"] == 1024
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_upload_quota_guard.py -v`
Expected: PASS（此测试验证 Task 11/12 已提供的能力；若前序任务未完成会 FAIL）

- [ ] **Step 4: 在 RuntimeStorageProxy 中接入配额守卫**

在 `api/internal/service/storage/runtime_storage_service.py` 中：

1. 文件头 import 区追加：

```python
from internal.service.storage_quota_service import StorageQuotaService
```

2. 类字段中追加配额服务依赖：

```python
@inject
@dataclass
class RuntimeStorageProxy:
    """运行时存储分发代理。"""

    upload_file_service: UploadFileService
    storage_config_service: StorageConfigService
    storage_quota_service: StorageQuotaService
    db: SQLAlchemy
```

3. 将 `upload_file` 改为带配额守卫：

```python
    def upload_file(self, file, only_image: bool = False, account=None):
        """上传文件到当前激活后端并创建 UploadFile 记录。

        上传前校验账号存储配额，成功写入后累加用量。account 为空时跳过校验
        （系统/匿名上传不计入用户配额）。
        """
        account_id = getattr(account, "id", None)
        if account_id is not None:
            file_size = self._measure_upload_size(file)
            self.storage_quota_service.check_quota(account_id, file_size)

        upload_file = self._get_service().upload_file(file, only_image, account)

        if account_id is not None:
            self.storage_quota_service.add_usage(account_id, upload_file.size or 0)
        return upload_file

    @staticmethod
    def _measure_upload_size(file) -> int:
        """测量待上传文件字节数；无法测量时回退 0（校验放行）。"""
        stream = getattr(file, "stream", None)
        if stream is None:
            return 0
        try:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(0)
            return int(size)
        except (AttributeError, OSError, ValueError):
            return 0
```

4. 在文件头 import 区补 `import os`（若尚未导入）：

```python
import logging
import os
from dataclasses import dataclass
```

5. 同步更新三个后端的构造点（`_get_service()` 中的手工构造），传入配额服务，保持依赖可解析：

```python
    def _get_service(self, backend: str | None = None):
        """返回指定后端（默认激活后端）的服务实例。"""
        backend = (backend or self._resolve_backend()).strip().lower()

        if backend == "local":
            from internal.service.storage.local_storage_service import LocalStorageService
            return LocalStorageService(upload_file_service=self.upload_file_service)

        if backend == "cos":
            from internal.service.cos_service import CosService
            return CosService(upload_file_service=self.upload_file_service)

        if backend == "oss":
            from internal.service.storage.aliyun_oss_service import AliyunOSSService
            return AliyunOSSService(upload_file_service=self.upload_file_service)

        raise FailException(f"不支持的存储后端: {backend}（可选值: local / cos / oss）")
```

（三个后端本身**不需要**改动——配额校验在代理层完成，后端仍是纯存储职责。）

6. 在 `api/app/http/module.py` 中注册配额服务绑定（放在存储服务注册区）：

```python
        from internal.service.storage_quota_service import StorageQuotaService
        binder.bind(StorageQuotaService, to=StorageQuotaService, scope=singleton)
```

- [ ] **Step 5: 跑相关测试并提交**

Run: `cd api && python -m pytest test/internal/service/test_upload_quota_guard.py test/internal/service/test_upload_file_service.py test/internal/service/test_cos_service.py test/internal/service/test_runtime_storage_service.py -v`
Expected: PASS（不新增失败；`test_runtime_storage_service.py` 若不存在则跳过该项）

```bash
git add api/internal/service/storage/runtime_storage_service.py api/app/http/module.py api/test/internal/service/test_upload_quota_guard.py
git commit -m "feat(storage): enforce quota check at runtime storage proxy"
```

---

## Task 14: KnowledgePartitionService 两级层级校验

**Files:**
- Create: `api/internal/service/knowledge_partition_service.py`
- Test: `api/test/internal/service/test_knowledge_partition_service.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_knowledge_partition_service.py
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import FailException, ValidateErrorException
from internal.service.knowledge_partition_service import KnowledgePartitionService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None):
        self._one_or_none = one_or_none_result
        self._all = [] if all_result is None else all_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def one_or_none(self):
        return self._one_or_none

    def all(self):
        return self._all


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


@contextmanager
def _auto_commit():
    yield


def _new_service(session=None):
    return KnowledgePartitionService(
        db=SimpleNamespace(session=session or _SessionStub(), auto_commit=lambda: _auto_commit()),
    )


def test_top_level_partition_is_allowed(monkeypatch):
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))
    created = []
    monkeypatch.setattr(service, "create",
        lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))

    service.create_partition(
        knowledge_base_id=uuid4(), name="产品A", partition_key="product-a", parent_id=None)

    assert created[0]["name"] == "产品A"
    assert created[0]["parent_id"] is None


def test_second_level_partition_is_allowed(monkeypatch):
    base_id = uuid4()
    parent = SimpleNamespace(id=uuid4(), parent_id=None)
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=parent)]))
    created = []
    monkeypatch.setattr(service, "create",
        lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))

    service.create_partition(
        knowledge_base_id=base_id, name="外观", partition_key="appearance", parent_id=parent.id)

    assert created[0]["parent_id"] == parent.id


def test_third_level_partition_is_rejected():
    grandchild_parent = SimpleNamespace(id=uuid4(), parent_id=uuid4())
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=grandchild_parent)]))

    with pytest.raises(ValidateErrorException):
        service.create_partition(
            knowledge_base_id=uuid4(), name="三级", partition_key="third",
            parent_id=grandchild_parent.id)


def test_parent_not_found_is_rejected():
    service = _new_service(_SessionStub([_QueryStub(one_or_none_result=None)]))

    with pytest.raises(FailException):
        service.create_partition(
            knowledge_base_id=uuid4(), name="子类", partition_key="child", parent_id=uuid4())


def test_duplicate_partition_key_is_rejected():
    existing = SimpleNamespace(id=uuid4())
    service = _new_service(_SessionStub([
        _QueryStub(one_or_none_result=None),
        _QueryStub(one_or_none_result=existing),
    ]))

    with pytest.raises(FailException):
        service.create_partition(
            knowledge_base_id=uuid4(), name="重复", partition_key="dup", parent_id=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_partition_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'internal.service.knowledge_partition_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/service/knowledge_partition_service.py
"""知识库分区服务。

负责分区的创建与层级维护，强制两级树约束（大类 / 子类），
第三级创建直接拒绝，避免深树带来的 UI 混乱与 Agent 导航复杂化。
"""
from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.exception import FailException, ValidateErrorException
from internal.model import KnowledgePartition
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

# 两级树：顶层 depth=0，子级 depth=1，超过则拒绝
MAX_PARTITION_DEPTH = 1


@inject
@dataclass
class KnowledgePartitionService(BaseService):
    """分区创建与层级校验服务。"""

    db: SQLAlchemy

    def create_partition(
        self,
        *,
        knowledge_base_id: UUID,
        name: str,
        partition_key: str,
        parent_id: UUID | None = None,
        description: str = "",
        sort_order: int = 0,
    ) -> KnowledgePartition:
        """创建分区。

        规则：
        - parent_id 为空：创建顶层分区；
        - parent_id 非空：父分区必须存在，且父分区自身必须是顶层（否则会形成三级树）；
        - 同一知识库下 partition_key 不允许重复。
        """
        if parent_id is not None:
            parent = (
                self.db.session.query(KnowledgePartition)
                .filter_by(id=parent_id, knowledge_base_id=knowledge_base_id)
                .one_or_none()
            )
            if parent is None:
                raise FailException("父分区不存在")
            if parent.parent_id is not None:
                raise ValidateErrorException(
                    f"分区最多支持 {MAX_PARTITION_DEPTH + 1} 级，不能在子分区下继续创建"
                )

        duplicate = (
            self.db.session.query(KnowledgePartition)
            .filter_by(knowledge_base_id=knowledge_base_id, partition_key=partition_key)
            .one_or_none()
        )
        if duplicate is not None:
            raise FailException("分区标识已存在")

        return self.create(
            KnowledgePartition,
            knowledge_base_id=knowledge_base_id,
            name=name,
            partition_key=partition_key,
            parent_id=parent_id,
            description=description,
            sort_order=sort_order,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_partition_service.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_partition_service.py api/test/internal/service/test_knowledge_partition_service.py
git commit -m "feat(knowledge): add partition service with two-level enforcement"
```

---

## Task 15: 板块类型硬约束接入 KnowledgeBaseService

**Files:**
- Modify: `api/internal/service/knowledge_base_service.py:61-70`
- Test: `api/test/internal/service/test_knowledge_base_type.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_knowledge_base_type.py
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ValidateErrorException
from internal.service.knowledge_base_service import KnowledgeBaseService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None):
        self._one_or_none = one_or_none_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def one_or_none(self):
        return self._one_or_none


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


@contextmanager
def _auto_commit():
    yield


def _new_service(session=None):
    return KnowledgeBaseService(
        db=SimpleNamespace(session=session or _SessionStub(), auto_commit=lambda: _auto_commit()),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )


def test_invalid_base_type_is_rejected():
    service = _new_service(_SessionStub([_QueryStub()]))
    with pytest.raises(ValidateErrorException):
        service.create_user_content_base(
            name="非法库", account=SimpleNamespace(id=uuid4()), base_type="nonexistent")


def test_invalid_partition_mode_is_rejected():
    service = _new_service(_SessionStub([_QueryStub()]))
    with pytest.raises(ValidateErrorException):
        service.create_user_content_base(
            name="非法库", account=SimpleNamespace(id=uuid4()), partition_mode="weekly")


def test_valid_base_type_and_mode_are_persisted(monkeypatch):
    service = _new_service(_SessionStub([_QueryStub()]))
    monkeypatch.setattr(service, "create",
        lambda model, **kwargs: SimpleNamespace(**kwargs))

    result = service.create_user_content_base(
        name="视频素材库", account=SimpleNamespace(id=uuid4()),
        base_type="video", partition_mode="date_month")

    assert result.base_type == "video"
    assert result.partition_mode == "date_month"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_base_type.py -v`
Expected: FAIL with `TypeError: create_user_content_base() got an unexpected keyword argument 'base_type'`

- [ ] **Step 3: Write minimal implementation**

在 `api/internal/service/knowledge_base_service.py` 中：

1. 更新 import（在既有 `knowledge_entity` 导入行追加两个枚举）：

```python
from internal.entity.knowledge_entity import (
    KnowledgeBaseType,
    KnowledgeCreatedFrom,
    KnowledgeScope,
    OperationContext,
    PartitionMode,
    VisibilityScope,
)
```

2. 将 `create_user_content_base` 签名与实现改为（保留原有逻辑，叠加两个参数与校验）：

```python
    def create_user_content_base(
        self,
        *,
        name: str,
        account: Account,
        admin_user: AdminUser | None = None,
        operation_context: str = "user",
        created_from: str = "manual_upload",
        description: str = "",
        base_type: str = KnowledgeBaseType.MIXED.value,
        partition_mode: str = PartitionMode.NONE.value,
    ) -> KnowledgeBase:
        """创建用户资料内容库（板块）。

        base_type 决定板块允许的媒体类型（硬约束），partition_mode 决定分区产生方式。
        """
        if base_type not in {member.value for member in KnowledgeBaseType}:
            raise ValidateErrorException(
                f"不支持的板块类型：{base_type}",
                {"base_type": [f"可选值：{[m.value for m in KnowledgeBaseType]}"]},
            )
        if partition_mode not in {member.value for member in PartitionMode}:
            raise ValidateErrorException(
                f"不支持的分区模式：{partition_mode}",
                {"partition_mode": [f"可选值：{[m.value for m in PartitionMode]}"]},
            )

        return self.create(
            KnowledgeBase,
            name=name,
            description=description,
            knowledge_scope=KnowledgeScope.USER_CONTENT.value,
            owner_account_id=account.id,
            owner_admin_user_id=None,
            operation_context=operation_context,
            visibility_scope=VisibilityScope.PRIVATE.value,
            created_from=created_from,
            base_type=base_type,
            partition_mode=partition_mode,
            settings={},
            enabled=True,
        )
```

> **实施提示**：原实现的方法体若与本示例结构不同（例如已包含 `owner_admin_user_id` 分支或额外的 `settings` 逻辑），**保留原逻辑，只在其上叠加 `base_type` / `partition_mode` 的校验与写入**。校验块必须放在 `self.create(...)` 之前。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_base_type.py test/internal/service/test_knowledge_base_service.py -v`
Expected: PASS（新测试 3 passed，既有测试无回归）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_base_service.py api/test/internal/service/test_knowledge_base_type.py
git commit -m "feat(knowledge): enforce base type and partition mode on base creation"
```

---

## Task 16: 放行 storage_addon 套餐类型（计划外补漏）

**背景**：P1 引入 `Plan.plan_type = "storage_addon"`，但既有两处白名单会拒绝该值——[admin_billing_plan_schema.py:25](../../../api/internal/schema/admin_billing_plan_schema.py#L25) 的 `AnyOf(["balance","membership","credits"])` 与 [order_service.py:92](../../../api/internal/service/order_service.py#L92) 的 `("balance","membership","credits")` 元组。不放行则管理员无法创建扩展包套餐、用户无法购买。

**Files:**
- Modify: `api/internal/schema/admin_billing_plan_schema.py:25`
- Modify: `api/internal/service/order_service.py:92`
- Modify: `api/internal/service/order_service.py`（`_fulfill_rights`）
- Test: `api/test/internal/service/test_storage_addon_plan_type.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_storage_addon_plan_type.py
from internal.entity.storage_quota_entity import StorageAddonPlanType
from internal.schema.admin_billing_plan_schema import UpsertAdminPlanReq
from werkzeug.datastructures import MultiDict


def test_schema_accepts_storage_addon_plan_type():
    form = UpsertAdminPlanReq(MultiDict({"plan_type": "storage_addon"}))
    assert form.validate(), form.errors


def test_schema_still_rejects_unknown_plan_type():
    form = UpsertAdminPlanReq(MultiDict({"plan_type": "unknown_type"}))
    assert not form.validate()


def test_order_service_plan_type_whitelist_includes_storage_addon():
    from internal.service import order_service as module

    source = module.__loader__.get_source(module.__name__)  # type: ignore[attr-defined]
    assert StorageAddonPlanType.STORAGE_ADDON.value in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_storage_addon_plan_type.py -v`
Expected: FAIL（`plan_type` 白名单不含 `storage_addon`，表单校验失败）

- [ ] **Step 3: Write minimal implementation**

1. 在 `api/internal/schema/admin_billing_plan_schema.py` 中，将 `plan_type` 行的 `AnyOf` 扩展：

```python
    plan_type = StringField("plan_type", default="membership", validators=[Optional(), AnyOf(["balance", "membership", "credits", "storage_addon"])])
```

2. 在 `api/internal/service/order_service.py` 的 `create_order` 中，将白名单元组扩展：

```python
        if plan_type not in ("balance", "membership", "credits", "storage_addon"):
            raise FailException("套餐类型无效")
```

3. 在 `_fulfill_rights` 中显式处理 `storage_addon`（不发放会员/算力权益；扩展包容量由已支付订单直接参与配额计算，无需额外履约）。在 `if order.plan_type == "membership":` 分支之前插入：

```python
        if order.plan_type == "storage_addon":
            # 存储扩展包：容量由已支付订单直接参与配额计算（见 StorageQuotaService），
            # 此处无需发放会员或算力权益。
            return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_storage_addon_plan_type.py test/internal/schema/test_admin_billing_plan_schema.py test/internal/service/test_order_service.py -v`
Expected: PASS（新测试 3 passed，既有测试无回归；不存在的测试文件跳过）

- [ ] **Step 5: Commit**

```bash
git add api/internal/schema/admin_billing_plan_schema.py api/internal/service/order_service.py api/test/internal/service/test_storage_addon_plan_type.py
git commit -m "feat(billing): allow storage_addon plan type for storage packages"
```

---

## Task 17: 回归验证与文档同步

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/prd/knowledge-base-product-form-design.md`

- [ ] **Step 1: 跑全量后端测试，确认无回归**

Run: `cd api && python -m pytest -q`
Expected: 无新增失败（与改动前失败集合一致）

- [ ] **Step 2: 校验迁移链仍为单 head**

Run: `cd api && python scripts/verify_migration_upgrade.py`
Expected: 单 head，`current == head`

- [ ] **Step 3: 更新架构文档**

在 `docs/prd/modules/02-knowledge-base.md` 的「现有知识库能力评估」（§11.5）之后新增一节「知识库板块与分区体系」，说明：

- `KnowledgeBase.base_type` 五种板块类型与硬约束行为
- `KnowledgeBase.partition_mode` 四种分区模式
- `KnowledgePartition` 两级树结构与层级校验
- `KnowledgeBaseTag` / `KnowledgeDocumentTag` 标签关联
- 存储配额模型（`storage_quota_gb` 权益 + `account_storage_usage` 计量）

在 `docs/prd/knowledge-base-product-form-design.md` 的 §九实施分期中，把 P1 标记为「已完成」并附本计划文件链接。

- [ ] **Step 4: 更新知识图谱**

Run: `cd d:\DEMO\openagent-main && python -m graphify update .`
Expected: 成功更新 `graphify-out/`

- [ ] **Step 5: Commit**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/knowledge-base-product-form-design.md graphify-out/
git commit -m "docs(knowledge): sync P1 architecture docs and refresh knowledge graph"
```

---

## 验收清单

P1 完成的判定标准：

| # | 验收项 | 验证方式 |
|---|---|---|
| 1 | 可创建 `document`/`image`/`video`/`audio`/`mixed` 五种板块 | 服务层调用 `create_user_content_base` 带 `base_type` |
| 2 | 板块类型为硬约束，类型不符拒绝 | 单测覆盖 `allowed_extensions_for_base_type` |
| 3 | 可创建两级分区，第三级被拒绝 | `KnowledgePartition` 服务层层级校验单测 |
| 4 | 知识库可打标签 | `KnowledgeBaseTag` 写入单测 |
| 5 | 注册用户配额 = 5GB | `resolve_total_quota_bytes` 无套餐时返回 5GB |
| 6 | 会员套餐配额生效（100GB / 500GB） | `storage_quota_gb` 权益解析单测 |
| 7 | 扩展包容量累加 | `_resolve_purchased_addon_gb` 单测 |
| 8 | 超配额上传被拒绝 | `check_quota` 抛 `ForbiddenException` |
| 9 | 上传成功后用量累加 | `add_usage` 单测 |
| 10 | 删除后用量释放且不为负 | `release_usage` 单测 |
| 11 | `UploadFile.size` 支持 GB 级 | `BigInteger` 类型断言单测 |
| 12 | 迁移链单 head 且可 upgrade | `verify_migration_upgrade.py` 通过 |
| 13 | 架构文档已同步 | 文档 diff 可见 |
