# 知识库 P3：检索过滤 + L2 按需解析 + 关键帧视觉向量 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让知识库的取料能力完整——检索可按板块/分区/标签/媒体类型过滤并支持分数阈值；视频补齐 ASR 音轨；关键帧留存并建立视觉向量索引，支持以图搜图与文本跨模态召回。

**Architecture:** 三条工作流按依赖顺序落地。(1) 检索过滤：在既有 `RetrievalService` / `KnowledgeVectorService` 的 SQL JOIN 链上追加 WHERE 条件，标签走新关联表 JOIN，并把过滤参数暴露到 `search_knowledge_base` 工具的 `args_schema`。(2) L2 按需解析：视频 L1 补 ffmpeg 音轨抽取 + ASR；`parse_profile.tier2` 承载 L2 状态。(3) 视觉向量：抽帧改为可留存→上传为 `UploadFile`→写 `parse_profile.frames`；新增 `visual_embedding` 模型类型与 `video_visual_embedding` 表；因 Qwen3-VL-Embedding 的文本与图片映射到**同一语义空间**，文本 query 可直接召回视觉向量，无需双塔融合排序。

**Tech Stack:** Python 3.11 / Quart / SQLAlchemy 2.0 / Alembic / pgvector（HNSW）/ Celery / Vue 3 + TypeScript / Arco Design / pytest / vitest

---

## 关键前置事实（调研实测，勿臆造）

| 事实 | 结论 |
| --- | --- |
| `Qwen/Qwen3-VL-Embedding-8B` 原生维度 | **4096**，支持 MRL 降维 `[64,128,256,512,768,1024,1536,2048,2560,4096]` |
| pgvector 维度上限 | `MAX_SUPPORTED_DIMENSION = 2000` → **必须降到 1536**（本项目主维度） |
| 该模型 embeds 接口入参 | **不是** OpenAI 裸字符串：图片为 `input={"image": "..."}`，混合为 `input=[{"text":...},{"image":...}]` → **不能复用 `OpenAIEmbeddings`** |
| 语义空间 | 文本与图片**共享同一空间**；`qwen3-vl-embedding` 另支持 `enable_fusion` 融合向量 |
| 硅基流动 base_url | `https://api.siliconflow.cn/v1`（**代码中无常量**，一律从 DB `model_provider_config.default_base_url` 取） |
| `SiliconFlow` provider 行 | **代码 seed 中不存在**（仅 TTS 迁移以 `WHERE EXISTS` 依赖它），由运维/管理员在 DB 创建 |
| 模型密钥 | 存 `model_key_config.key_value_encrypted`（Fernet）；**不存在全局/通用 key 回退** |
| `MODEL_TYPES` 副本 | 后端 2 份 + 前端 2 份 + `CONTEXT_LESS_MODEL_TYPES` 2 份，**无一致性测试** |
| 抽帧现状 | 写在 `tempfile.mkdtemp()`，`finally` 里 `shutil.rmtree` 删除，返回 **data URI** → 帧文件即用即弃 |
| `parse_profile` | JSONB，列注释写 `{"tier1":..., "tier2":..., "frames":[...]}`；**tier2/frames 代码零写入** |
| 向量 SQL 已有 JOIN | `knowledge_segment` / `knowledge_base` / `knowledge_document` → `partition_id`/`media_type`/`tags` 过滤的天然落点 |
| 标签 | `KnowledgeBaseTag` / `KnowledgeDocumentTag` 表已建，但**无任何读写代码**；`TagService` 只有 app/workflow 方法 |

---

## File Structure

**新建：**

| 文件 | 职责 |
| --- | --- |
| `api/internal/service/knowledge_tag_service.py` | 知识库/素材标签的关联读写与「按标签查文档」 |
| `api/internal/service/visual_embedding_service.py` | Qwen3-VL-Embedding 调用（文本/图片/混合），独立于 `EmbeddingsService` |
| `api/internal/model/video_visual_embedding.py` | 视觉向量表模型 |
| `api/internal/migration/versions/<rev>_add_video_visual_embedding.py` | 建表 + HNSW 索引 |
| `api/internal/migration/versions/<rev>_seed_siliconflow_vl_embedding.py` | seed provider + 视觉模型（幂等） |
| `api/internal/task/knowledge_l2_tasks.py` | L2 按需解析 Celery 任务 |
| `api/test/...`（多个） | 各任务的测试 |

**修改：**

| 文件 | 改动 |
| --- | --- |
| `api/internal/service/knowledge_vector_service.py` | `search()` 增加过滤参数；新增视觉检索方法 |
| `api/internal/service/retrieval_service.py` | 过滤参数透传；工具 `args_schema` 扩展 |
| `api/internal/core/vision/vision_invoke.py` | 新增「帧留存到指定目录」的函数（不改既有返回类型） |
| `api/internal/service/knowledge_media_extractor_service.py` | 帧留存 + 上传 `UploadFile`；视频补 ASR |
| `api/internal/service/knowledge_indexing_service.py` | 写 `parse_profile.frames`；触发视觉向量索引 |
| `api/app/http/knowledge_mcp_routes.py` | 标签写入/查询路由 |
| `api/internal/core/language_model/entities/model_entity.py` | `ModelType` 加 `VISUAL_EMBEDDING` |
| `api/internal/schema/admin_model_pool_schema.py` / `admin_model_provider_schema.py` | `MODEL_TYPES` 加值 |
| `api/internal/service/admin_model_pool_service.py` | `CONTEXT_LESS_MODEL_TYPES`、维度探测分支 |
| `api/internal/core/language_model/model_class_registry.py` | 注册视觉编码类（若不引入新 SDK 类则避免） |
| `ui/src/views/admin/ModelsView.vue` / `ModelProvidersView.vue` | `ALL_MODEL_TYPES` 同步 |
| `ui/src/i18n/messages/{zh-CN,en-US}/admin/models.ts` | 新模型类型文案（双端同步） |
| `docs/prd/modules/02-knowledge-base.md` 等 | 架构文档同步 |

---

## 工作流 1：检索过滤参数扩展

### Task 1: 知识库标签服务

**Files:**
- Create: `api/internal/service/knowledge_tag_service.py`
- Test: `api/test/internal/service/test_knowledge_tag_service.py`

- [ ] **Step 1: 写失败测试**

```python
"""知识库标签服务测试：关联读写 + 按标签查素材。"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import FailException
from internal.model import KnowledgeBaseTag, KnowledgeDocumentTag
from internal.service.knowledge_tag_service import KnowledgeTagService


class _QueryStub:
    def __init__(self, *, one_or_none=None, all_result=None):
        self._one_or_none = one_or_none
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
    def __init__(self, queries):
        self._queries = list(queries)

    def query(self, *_a, **_kw):
        return self._queries.pop(0) if self._queries else _QueryStub()


def _service(queries=None):
    svc = KnowledgeTagService.__new__(KnowledgeTagService)
    svc.db = SimpleNamespace(session=_SessionStub(queries or []))
    return svc


class TestKnowledgeTagService:
    def test_attach_base_tag_creates_link_when_absent(self, monkeypatch):
        svc = _service([_QueryStub(one_or_none=None)])
        created = []
        monkeypatch.setattr(
            svc, "create",
            lambda model, **kw: created.append((model, kw)) or SimpleNamespace(**kw),
        )

        svc.attach_base_tag(uuid4(), uuid4(), uuid4())

        assert created[0][0] is KnowledgeBaseTag
        assert created[0][1]["tag_id"]

    def test_attach_base_tag_is_idempotent(self, monkeypatch):
        existing = SimpleNamespace(id=uuid4())
        svc = _service([_QueryStub(one_or_none=existing)])
        created = []
        monkeypatch.setattr(svc, "create", lambda *a, **kw: created.append(kw))

        result = svc.attach_base_tag(uuid4(), uuid4(), uuid4())

        assert result is existing
        assert created == []

    def test_attach_document_tag_creates_link(self, monkeypatch):
        svc = _service([_QueryStub(one_or_none=None)])
        created = []
        monkeypatch.setattr(
            svc, "create",
            lambda model, **kw: created.append((model, kw)) or SimpleNamespace(**kw),
        )

        svc.attach_document_tag(uuid4(), uuid4(), uuid4())

        assert created[0][0] is KnowledgeDocumentTag

    def test_detach_document_tag_returns_false_when_absent(self):
        svc = _service([_QueryStub(one_or_none=None)])
        assert svc.detach_document_tag(uuid4(), uuid4()) is False

    def test_detach_document_tag_deletes_when_present(self, monkeypatch):
        link = SimpleNamespace(id=uuid4())
        svc = _service([_QueryStub(one_or_none=link)])
        deleted = []
        monkeypatch.setattr(svc, "delete", lambda instance: deleted.append(instance))

        assert svc.detach_document_tag(uuid4(), uuid4()) is True
        assert deleted == [link]

    def test_document_ids_for_tags_returns_intersection_when_match_all(self):
        """match_all=True 时取同时具备全部标签的文档（用计数实现交集）。"""
        doc_a, doc_b = uuid4(), uuid4()
        rows = [(doc_a, 2), (doc_b, 1)]
        svc = _service([_QueryStub(all_result=rows)])

        ids = svc.document_ids_for_tags([uuid4(), uuid4()], match_all=True)

        assert ids == [doc_a]

    def test_document_ids_for_tags_returns_union_when_any(self):
        doc_a, doc_b = uuid4(), uuid4()
        rows = [(doc_a, 2), (doc_b, 1)]
        svc = _service([_QueryStub(all_result=rows)])

        ids = svc.document_ids_for_tags([uuid4()], match_all=False)

        assert set(ids) == {doc_a, doc_b}

    def test_document_ids_for_tags_returns_empty_for_blank_input(self):
        svc = _service([])
        assert svc.document_ids_for_tags([], match_all=False) == []
        assert svc.document_ids_for_tags([], match_all=True) == []

    def test_list_document_tags_returns_tag_rows(self):
        tag = SimpleNamespace(id=uuid4(), name="产品A")
        svc = _service([_QueryStub(all_result=[tag])])
        assert svc.list_document_tags(uuid4()) == [tag]

    def test_attach_document_tag_rejects_when_document_not_found(self):
        """给不存在的素材打标签应报错，避免产生悬挂关联。"""
        svc = _service([_QueryStub(one_or_none=None)])
        with pytest.raises(FailException):
            svc.attach_document_tag(uuid4(), uuid4(), uuid4(), verify_document=True)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_knowledge_tag_service.py -q --no-header --no-cov`
Expected: FAIL —— `ModuleNotFoundError: No module named 'internal.service.knowledge_tag_service'`

- [ ] **Step 3: 实现服务**

```python
"""知识库标签服务。

复用既有 Tag 模型，仅管理知识库（板块）与素材（文档）两级的关联，
对齐 TagService 的 AppTag / WorkflowTag 写法。
"""
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from sqlalchemy import func

from internal.exception import FailException
from internal.model import KnowledgeBaseTag, KnowledgeDocument, KnowledgeDocumentTag, Tag
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class KnowledgeTagService(BaseService):
    """知识库标签服务"""

    db: SQLAlchemy

    def attach_base_tag(self, account_id: UUID, knowledge_base_id: UUID, tag_id: UUID) -> KnowledgeBaseTag:
        """为板块打标签（幂等）。"""
        existing = (
            self.db.session.query(KnowledgeBaseTag)
            .filter_by(knowledge_base_id=knowledge_base_id, tag_id=tag_id)
            .one_or_none()
        )
        if existing is not None:
            return existing
        return self.create(
            KnowledgeBaseTag,
            account_id=account_id,
            knowledge_base_id=knowledge_base_id,
            tag_id=tag_id,
        )

    def attach_document_tag(
        self,
        account_id: UUID,
        knowledge_document_id: UUID,
        tag_id: UUID,
        verify_document: bool = False,
    ) -> KnowledgeDocumentTag:
        """为素材打标签（幂等）；verify_document=True 时先确认素材存在。"""
        if verify_document:
            exists = (
                self.db.session.query(KnowledgeDocument)
                .filter_by(id=knowledge_document_id)
                .one_or_none()
            )
            if exists is None:
                raise FailException("素材不存在，无法打标签")

        existing = (
            self.db.session.query(KnowledgeDocumentTag)
            .filter_by(knowledge_document_id=knowledge_document_id, tag_id=tag_id)
            .one_or_none()
        )
        if existing is not None:
            return existing
        return self.create(
            KnowledgeDocumentTag,
            account_id=account_id,
            knowledge_document_id=knowledge_document_id,
            tag_id=tag_id,
        )

    def detach_document_tag(self, knowledge_document_id: UUID, tag_id: UUID) -> bool:
        """移除素材标签，返回是否确有移除。"""
        link = (
            self.db.session.query(KnowledgeDocumentTag)
            .filter_by(knowledge_document_id=knowledge_document_id, tag_id=tag_id)
            .one_or_none()
        )
        if link is None:
            return False
        self.delete(link)
        return True

    def list_document_tags(self, knowledge_document_id: UUID) -> list[Tag]:
        """列出某素材的全部标签。"""
        rows = (
            self.db.session.query(KnowledgeDocumentTag)
            .filter_by(knowledge_document_id=knowledge_document_id)
            .all()
        )
        tag_ids = [row.tag_id for row in rows]
        if not tag_ids:
            return []
        return self.db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()

    def document_ids_for_tags(self, tag_ids: list[UUID], match_all: bool = False) -> list[UUID]:
        """按标签查素材 id 列表。

        match_all=True 取交集（须同时具备全部标签），False 取并集。
        用计数实现交集，避免多次子查询。
        """
        if not tag_ids:
            return []

        rows = (
            self.db.session.query(
                KnowledgeDocumentTag.knowledge_document_id,
                func.count(KnowledgeDocumentTag.tag_id).label("matched"),
            )
            .filter(KnowledgeDocumentTag.tag_id.in_(tag_ids))
            .group_by(KnowledgeDocumentTag.knowledge_document_id)
            .all()
        )
        if not match_all:
            return [row[0] for row in rows]
        required = len(set(tag_ids))
        return [row[0] for row in rows if int(row[1]) >= required]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_knowledge_tag_service.py -q --no-header --no-cov`
Expected: PASS（11 passed）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_tag_service.py api/test/internal/service/test_knowledge_tag_service.py
git commit -m "feat(knowledge): add knowledge tag service for base and document tags"
```

---

### Task 2: 向量检索支持结构化过滤

**Files:**
- Modify: `api/internal/service/knowledge_vector_service.py`
- Test: `api/test/internal/service/test_knowledge_vector_service_filters.py`

- [ ] **Step 1: 写失败测试**

```python
"""向量检索过滤参数测试：断言生成的 SQL 含预期 WHERE 条件与绑定参数。"""
from types import SimpleNamespace
from uuid import uuid4

from internal.model import KnowledgeBase
from internal.service.knowledge_vector_service import KnowledgeVectorService


class _ResultStub:
    def __init__(self, rows=None):
        self._rows = rows or []

    def __iter__(self):
        return iter(self._rows)


class _SessionStub:
    def __init__(self):
        self.executed = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        return _ResultStub()

    def commit(self):
        return None

    def rollback(self):
        return None


class _RouterStub:
    def ensure_tables_for_dimension(self, dimension):
        return None

    def get_knowledge_segment_table_name(self, dimension):
        return f"knowledge_segment_embedding_{dimension}"


class _EmbeddingsStub:
    def embed_query(self, text):
        return [0.1, 0.2]


def _service():
    svc = KnowledgeVectorService.__new__(KnowledgeVectorService)
    svc.db = SimpleNamespace(session=_SessionStub())
    svc.embeddings_service = SimpleNamespace(
        get_embeddings_for_model_id=lambda _model_id: (_EmbeddingsStub(), 1024)
    )
    svc.rerank_service = None
    svc._get_router = lambda: _RouterStub()
    return svc


def _base():
    return SimpleNamespace(id=uuid4(), embedding_model_id=uuid4(), knowledge_scope="user_content")


class TestVectorSearchFilters:
    def test_partition_filter_adds_where_clause(self):
        svc = _service()
        svc.search(_base(), "q", top_k=3, partition_id=uuid4())

        sql, params = svc.db.session.executed[-1]
        assert "kd.partition_id = :partition_id" in sql
        assert "partition_id" in params

    def test_media_type_filter_adds_where_clause(self):
        svc = _service()
        svc.search(_base(), "q", top_k=3, media_types=["video"])

        sql, params = svc.db.session.executed[-1]
        assert "kd.media_type IN :media_types" in sql
        assert params["media_types"] == ["video"]

    def test_document_ids_filter_adds_where_clause(self):
        svc = _service()
        doc_ids = [uuid4(), uuid4()]
        svc.search(_base(), "q", top_k=3, document_ids=doc_ids)

        sql, params = svc.db.session.executed[-1]
        assert "kd.id IN :document_ids" in sql
        assert [str(x) for x in params["document_ids"]] == [str(x) for x in doc_ids]

    def test_no_optional_filter_keeps_sql_minimal(self):
        svc = _service()
        svc.search(_base(), "q", top_k=3)

        sql, _params = svc.db.session.executed[-1]
        assert "partition_id" not in sql
        assert "media_type" not in sql

    def test_score_threshold_is_applied_in_sql(self):
        """分数阈值必须在 SQL 侧过滤，避免返回后再截断导致召回数不足。"""
        svc = _service()
        svc.search(_base(), "q", top_k=3, score_threshold=0.5)

        sql, params = svc.db.session.executed[-1]
        assert "score" in sql
        assert params["score_threshold"] == 0.5

    def test_empty_media_types_is_treated_as_no_filter(self):
        svc = _service()
        svc.search(_base(), "q", top_k=3, media_types=[])

        sql, _params = svc.db.session.executed[-1]
        assert "media_type" not in sql
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_knowledge_vector_service_filters.py -q --no-header --no-cov`
Expected: FAIL —— `TypeError: search() got an unexpected keyword argument 'partition_id'`

- [ ] **Step 3: 改造 `search()`**

把 `search` 的签名与 SQL 构建改为（保持既有行为：不传过滤参数时 SQL 与现在等价）：

```python
    def search(
        self,
        knowledge_base: KnowledgeBase,
        query: str,
        top_k: int = 5,
        knowledge_scope: str | None = None,
        partition_id: UUID | None = None,
        media_types: list[str] | None = None,
        document_ids: list[UUID] | None = None,
        score_threshold: float | None = None,
    ) -> list[dict]:
        """在指定知识库中执行向量相似度检索（按维度分表）。

        结构化过滤全部下推到 SQL（而非取回后在 Python 里筛），
        否则 LIMIT 会先把不匹配的行取走，导致召回数量不足。

        Args:
            partition_id: 仅在该分区内检索（分区为组织手段，非权限边界）。
            media_types: 仅检索这些媒体类型（video/image/audio/document）。
            document_ids: 仅在这些素材内检索（用于标签过滤的交集/并集结果）。
            score_threshold: 相似度下限，低于该值的结果不返回。
        """
        try:
            embeddings_client, dimension, table_name = self._resolve_kb_embedding(knowledge_base)
            query_embedding = embeddings_client.embed_query(query)
        except Exception:
            logger.warning("查询向量生成失败 query=%s", query[:100], exc_info=True)
            return []

        sql = f"""
            SELECT ks.id AS segment_id,
                   ks.content,
                   ks.knowledge_document_id,
                   1 - (v.embedding <=> CAST(:embedding AS vector)) AS score
            FROM {table_name} v
            JOIN knowledge_segment ks ON v.segment_id = ks.id
            JOIN knowledge_base kb ON ks.knowledge_base_id = kb.id
            JOIN knowledge_document kd ON ks.knowledge_document_id = kd.id
            WHERE v.knowledge_base_id = :kb_id
              AND ks.enabled = true
              AND kb.enabled = true
              AND kd.status = 'completed'
        """
        params: dict = {
            "kb_id": str(knowledge_base.id),
            "embedding": query_embedding,
        }
        if knowledge_scope is not None:
            sql += " AND kb.knowledge_scope = :scope"
            params["scope"] = knowledge_scope
        if partition_id is not None:
            sql += " AND kd.partition_id = :partition_id"
            params["partition_id"] = str(partition_id)
        if media_types:
            sql += " AND kd.media_type IN :media_types"
            params["media_types"] = list(media_types)
        if document_ids:
            sql += " AND kd.id IN :document_ids"
            params["document_ids"] = [str(doc_id) for doc_id in document_ids]
        if score_threshold is not None:
            sql += " AND 1 - (v.embedding <=> CAST(:embedding AS vector)) >= :score_threshold"
            params["score_threshold"] = float(score_threshold)

        sql += " ORDER BY v.embedding <=> CAST(:embedding AS vector) LIMIT :limit"
        params["limit"] = top_k
        # 其余（执行、组装结果、rerank）保持原样不动
```

同时在文件顶部补 `from uuid import UUID`。

> 注：`kd.id IN :document_ids` 这类写法依赖 SQLAlchemy 的 `text()` 绑定展开。执行时需传 list；若运行期报 `IN` 展开错误，改为 `kd.id = ANY(:document_ids)` 并传 list（PostgreSQL 支持）。**先按 `IN` 实现，测试若暴露问题再切换为 `ANY`**。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_knowledge_vector_service_filters.py test/internal/service/test_knowledge_vector_service.py -q --no-header --no-cov`
Expected: PASS（新旧测试都过；既有测试断言 SQL 含 `knowledge_segment_embedding_1024`，改动不应破坏）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_vector_service.py api/test/internal/service/test_knowledge_vector_service_filters.py
git commit -m "feat(knowledge): push structured filters down into vector search SQL"
```

---

### Task 3: 检索服务透传过滤参数

**Files:**
- Modify: `api/internal/service/retrieval_service.py`
- Test: `api/test/internal/service/test_retrieval_filters.py`

- [ ] **Step 1: 写失败测试**

```python
"""检索服务过滤透传测试。"""
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.documents import Document as LCDocument

from internal.service.retrieval_service import RetrievalService


class _QueryStub:
    def __init__(self, bases):
        self._bases = bases

    def filter(self, *_a, **_kw):
        return self

    def all(self):
        return self._bases

    def update(self, *_a, **_kw):
        return 1


class _SessionStub:
    def __init__(self, bases):
        self._bases = bases

    def query(self, *_a, **_kw):
        return _QueryStub(self._bases)


class _AutoCommit:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _service(bases, semantic_hits):
    svc = RetrievalService.__new__(RetrievalService)
    svc.db = SimpleNamespace(session=_SessionStub(bases), auto_commit=lambda: _AutoCommit())
    captured = {}

    def _fake_search(kb, query, top_k=5, knowledge_scope=None, **kwargs):
        captured.update(kwargs)
        captured["knowledge_scope"] = knowledge_scope
        return semantic_hits

    svc.knowledge_vector_service = SimpleNamespace(search=_fake_search)
    svc.rerank_service = None
    svc.jieba_service = SimpleNamespace(extract_keywords=lambda _t, _n: [])
    return svc, captured


def _base(scope="user_content"):
    return SimpleNamespace(id=uuid4(), knowledge_scope=scope, enabled=True)


class TestRetrievalFilters:
    def test_filters_reach_vector_service(self):
        base = _base()
        svc, captured = _service([base], [])
        partition_id = uuid4()

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="semantic",
            partition_id=partition_id,
            media_types=["video"],
            score_threshold=0.4,
        )

        assert captured["partition_id"] == partition_id
        assert captured["media_types"] == ["video"]
        assert captured["score_threshold"] == 0.4

    def test_document_ids_derived_from_tags(self, monkeypatch):
        """传 tag_ids 时应先解析为 document_ids 再下推到向量检索。"""
        base = _base()
        svc, captured = _service([base], [])
        doc_id = uuid4()
        svc.knowledge_tag_service = SimpleNamespace(
            document_ids_for_tags=lambda tag_ids, match_all: [doc_id]
        )

        svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="semantic",
            tag_ids=[uuid4()],
        )

        assert captured["document_ids"] == [doc_id]

    def test_tag_filter_matching_nothing_short_circuits(self):
        """标签无命中时必须直接返回空，不能退化成"不过滤"（否则会越权召回）。"""
        base = _base()
        svc, _captured = _service([base], [])
        svc.knowledge_tag_service = SimpleNamespace(
            document_ids_for_tags=lambda tag_ids, match_all: []
        )

        result = svc.search_in_knowledge_base(
            [base.id], "q", uuid4(), k=3,
            retrieval_strategy="semantic",
            tag_ids=[uuid4()],
        )

        assert result == []

    def test_default_call_has_no_filters(self):
        base = _base()
        svc, captured = _service([base], [LCDocument(page_content="x", metadata={"segment_id": str(uuid4())})])

        svc.search_in_knowledge_base([base.id], "q", uuid4(), k=3, retrieval_strategy="semantic")

        assert captured.get("partition_id") is None
        assert captured.get("media_types") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_retrieval_filters.py -q --no-header --no-cov`
Expected: FAIL —— `TypeError: search_in_knowledge_base() got an unexpected keyword argument 'partition_id'`

- [ ] **Step 3: 实现透传**

在 `RetrievalService` 上新增一个 `FilterSpec` dataclass 统一承载过滤条件，避免参数在多层间散落：

```python
@dataclass
class RetrievalFilter:
    """检索过滤条件（结构化）。标签会被解析为 document_ids 后下推。"""
    partition_id: UUID | None = None
    media_types: list[str] | None = None
    tag_ids: list[UUID] | None = None
    match_all_tags: bool = False
    score_threshold: float | None = None


def _resolve_filter(self, retrieval_filter: RetrievalFilter | None) -> tuple[dict, bool]:
    """把 RetrievalFilter 解析成向量服务可用的 kwargs。

    Returns:
        (kwargs, short_circuit)：short_circuit 为 True 表示过滤条件必然无命中
        （标签查不到任何素材），调用方应直接返回空，**不得**退化为不过滤。
    """
    if retrieval_filter is None:
        return {}, False

    kwargs: dict = {}
    if retrieval_filter.partition_id is not None:
        kwargs["partition_id"] = retrieval_filter.partition_id
    if retrieval_filter.media_types:
        kwargs["media_types"] = list(retrieval_filter.media_types)
    if retrieval_filter.score_threshold is not None:
        kwargs["score_threshold"] = float(retrieval_filter.score_threshold)

    if retrieval_filter.tag_ids:
        service = getattr(self, "knowledge_tag_service", None)
        if service is None:
            return kwargs, True
        document_ids = service.document_ids_for_tags(
            retrieval_filter.tag_ids, match_all=retrieval_filter.match_all_tags
        )
        if not document_ids:
            return kwargs, True
        kwargs["document_ids"] = document_ids

    return kwargs, False
```

`search_in_knowledge_base` 增加 `retrieval_filter: RetrievalFilter | None = None` 参数；在方法开头解析，若 `short_circuit` 直接 `return []`；把 `kwargs` 继续透传给 `_semantic_search_knowledge_base` / `_hybrid_search_knowledge_base`，这两个方法再原样转给 `knowledge_vector_service.search(...)`。

> 注意：`knowledge_tag_service` 通过 `@inject` 注入会形成循环依赖风险（`KnowledgeTagService` 不依赖 `RetrievalService`，安全）。加为 dataclass 字段：`knowledge_tag_service: KnowledgeTagService = None`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_retrieval_filters.py test/internal/service/test_knowledge_base_retrieval.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/retrieval_service.py api/test/internal/service/test_retrieval_filters.py
git commit -m "feat(knowledge): thread structured retrieval filters through retrieval service"
```

---

### Task 4: 检索工具暴露过滤参数

**Files:**
- Modify: `api/internal/service/retrieval_service.py`（`create_knowledge_retrieval_tool`）
- Modify: `api/internal/service/app_service.py`（`retrieval_config` 键白名单）
- Test: `api/test/internal/service/test_knowledge_retrieval_tool_filters.py`

- [ ] **Step 1: 写失败测试**

```python
"""search_knowledge_base 工具过滤参数测试。"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.retrieval_service import RetrievalService


class _AppStub:
    class app_context:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False


def _service(captured):
    svc = RetrievalService.__new__(RetrievalService)

    def _fake_layered_search(account_id, query, knowledge_base_ids, retrieval_config=None, top_k_per_layer=None):
        captured.update(retrieval_config or {})
        return []

    svc.layered_search = _fake_layered_search
    return svc


class TestRetrievalToolFilters:
    def test_tool_schema_exposes_filter_fields(self):
        svc = _service({})
        tool = svc.create_knowledge_retrieval_tool(_AppStub(), [uuid4()], uuid4())

        schema = tool.args_schema.model_json_schema()
        props = schema["properties"]
        for field in ("query", "partition_id", "media_types", "tags", "score_threshold"):
            assert field in props, f"工具入参缺少 {field}"

    def test_tool_passes_filters_into_retrieval_config(self):
        captured = {}
        svc = _service(captured)
        tool = svc.create_knowledge_retrieval_tool(_AppStub(), [uuid4()], uuid4())

        tool.invoke({
            "query": "找几段讲卖点的视频",
            "media_types": ["video"],
            "score_threshold": 0.3,
        })

        assert captured["media_types"] == ["video"]
        assert captured["score_threshold"] == 0.3

    def test_tool_accepts_omitted_optional_filters(self):
        captured = {}
        svc = _service(captured)
        tool = svc.create_knowledge_retrieval_tool(_AppStub(), [uuid4()], uuid4())

        tool.invoke({"query": "随便搜搜"})

        assert captured.get("media_types") is None
        assert captured.get("score_threshold") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_knowledge_retrieval_tool_filters.py -q --no-header --no-cov`
Expected: FAIL —— 断言 `partition_id`/`media_types`/`tags`/`score_threshold` 不在 props 中

- [ ] **Step 3: 扩展工具入参与透传**

```python
    class KnowledgeRetrievalInput(BaseModel):
        """知识库检索工具接入结构"""
        query: str = Field(description="知识库搜索query语句,类型为字符串")
        partition_id: str | None = Field(
            default=None,
            description="可选，限定在某分区内检索（分区 ID，来自分区树）",
        )
        media_types: list[str] | None = Field(
            default=None,
            description="可选，限定素材类型，取值 image/video/audio/document",
        )
        tags: list[str] | None = Field(
            default=None,
            description="可选，限定素材标签名；多个标签默认取并集",
        )
        score_threshold: float | None = Field(
            default=None,
            description="可选，相似度下限（0~1），低于该值的结果不返回",
        )
```

工具函数体：把非空的可选参数塞进 `retrieval_config` 一起传给 `layered_search`：

```python
        extra: dict = {}
        if partition_id:
            extra["partition_id"] = partition_id
        if media_types:
            extra["media_types"] = list(media_types)
        if tags:
            extra["tags"] = list(tags)
        if score_threshold is not None:
            extra["score_threshold"] = float(score_threshold)
        search_results = self.layered_search(
            account_id=account_id,
            query=query,
            knowledge_base_ids=knowledge_base_ids,
            retrieval_config={"retrieval_strategy": retrieval_strategy, "k": k, **extra},
            top_k_per_layer=top_k_per_layer,
        )
```

同时让 `layered_search` 读取这些新键并组装 `RetrievalFilter`（`tags` → `tag_ids` 需按名字查 `Tag`，通过 `knowledge_tag_service` 或 `TagService` 解析）。

同时改 `api/internal/service/app_service.py` 的 `retrieval_config` 键白名单，允许新键：

```python
_ALLOWED_RETRIEVAL_CONFIG_KEYS = {
    "retrieval_strategy", "k", "score",
    "partition_id", "media_types", "tags", "match_all_tags", "score_threshold",
}
```

> **必须同步改这个白名单**，否则在 App 配置里保存带新键的 retrieval_config 会被拒绝。同时把既有但被丢弃的 `score` 键接上（映射到 `score_threshold`），修复调研中发现的"配置有值但从不生效"断点。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_knowledge_retrieval_tool_filters.py test/internal/service/test_app_service.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/retrieval_service.py api/internal/service/app_service.py api/test/internal/service/test_knowledge_retrieval_tool_filters.py
git commit -m "feat(knowledge): expose partition, media type, tag and score filters on retrieval tool"
```

---

### Task 5: 标签写入与查询路由

**Files:**
- Modify: `api/app/http/knowledge_mcp_routes.py`
- Test: `api/test/app/http/test_knowledge_tag_routes.py`

- [ ] **Step 1: 写失败测试**

```python
"""知识库标签路由测试。"""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import knowledge_mcp_routes, support
from internal.service.knowledge_base_service import KnowledgeBaseService
from internal.service.knowledge_tag_service import KnowledgeTagService

knowledge_mcp_routes.register_routes(asgi_app.quart_app)


class _FakeTagService:
    def __init__(self):
        self.calls = []

    def attach_document_tag(self, account_id, document_id, tag_id, verify_document=False):
        self.calls.append(("attach", document_id, tag_id))
        return SimpleNamespace(id=uuid4())

    def detach_document_tag(self, document_id, tag_id):
        self.calls.append(("detach", document_id, tag_id))
        return True

    def list_document_tags(self, document_id):
        return [SimpleNamespace(id=uuid4(), name="产品A")]


class _FakeKnowledgeBaseService:
    def get_accessible_base(self, knowledge_base_id, account):
        return SimpleNamespace(id=knowledge_base_id)


def _setup(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    tag_svc = _FakeTagService()

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    def _fake_get_service(cls):
        if cls is KnowledgeTagService:
            return tag_svc
        if cls is KnowledgeBaseService:
            return _FakeKnowledgeBaseService()
        return None

    monkeypatch.setattr(knowledge_mcp_routes, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", _fake_get_service)
    return account, tag_svc


class TestKnowledgeTagRoutes:
    def test_routes_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert (
            "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/"
            "<uuid:document_id>/tags" in rules
        )
        assert (
            "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/"
            "<uuid:document_id>/tags/<uuid:tag_id>/delete" in rules
        )

    def test_list_document_tags(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/space/knowledge-bases/{uuid4()}/documents/{uuid4()}/tags"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"][0]["name"] == "产品A"

    def test_attach_tag_requires_tag_id(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{uuid4()}/documents/{uuid4()}/tags", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_attach_tag_with_invalid_uuid_returns_400(self, monkeypatch):
        _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{uuid4()}/documents/{uuid4()}/tags",
                    json={"tag_id": "not-a-uuid"},
                )
                return resp, await resp.json

        resp, _payload = asyncio.run(_run())
        assert resp.status_code == 400

    def test_detach_tag(self, monkeypatch):
        _, svc = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{uuid4()}/documents/{uuid4()}"
                    f"/tags/{uuid4()}/delete"
                )
                return resp, await resp.json

        resp, _payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert svc.calls[0][0] == "detach"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/app/http/test_knowledge_tag_routes.py -q --no-header --no-cov`
Expected: FAIL —— `test_routes_registered` 断言失败（路由不存在）

- [ ] **Step 3: 实现路由**

按 Task 5 之前的既有分区路由写法（`_resolve_account` + `_get_service` + `_to_thread` + `_ok`/`_json_resp`），新增三条：

```python
    @quart_app.get(
        "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/tags"
    )
    async def async_list_document_tags(knowledge_base_id, document_id) -> Response:
        """async 列出素材标签。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.knowledge_tag_service import KnowledgeTagService

        await _to_thread(
            _get_service(KnowledgeBaseService).get_accessible_base, knowledge_base_id, account
        )
        tags = await _to_thread(
            _get_service(KnowledgeTagService).list_document_tags, document_id
        )
        return _ok([{"id": str(tag.id), "name": tag.name} for tag in tags])

    @quart_app.post(
        "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/tags"
    )
    async def async_attach_document_tag(knowledge_base_id, document_id) -> Response:
        """async 为素材打标签。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.knowledge_tag_service import KnowledgeTagService

        payload = await request.get_json(force=True, silent=True) or {}
        tag_id_raw = str(payload.get("tag_id") or "").strip()
        if not tag_id_raw:
            return _json_resp(
                code="validate_error", message="标签标识不能为空",
                data={"tag_id": ["标签标识不能为空"]}, status=400,
            )
        try:
            tag_id = UUID(tag_id_raw)
        except (TypeError, ValueError):
            return _json_resp(
                code="validate_error", message="标签标识非法",
                data={"tag_id": ["标签标识非法"]}, status=400,
            )

        await _to_thread(
            _get_service(KnowledgeBaseService).get_accessible_base, knowledge_base_id, account
        )
        link = await _to_thread(
            _get_service(KnowledgeTagService).attach_document_tag,
            account.id, document_id, tag_id, True,
        )
        return _ok({"id": str(link.id)})

    @quart_app.post(
        "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/"
        "<uuid:document_id>/tags/<uuid:tag_id>/delete"
    )
    async def async_detach_document_tag(knowledge_base_id, document_id, tag_id) -> Response:
        """async 移除素材标签。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.knowledge_base_service import KnowledgeBaseService
        from internal.service.knowledge_tag_service import KnowledgeTagService

        await _to_thread(
            _get_service(KnowledgeBaseService).get_accessible_base, knowledge_base_id, account
        )
        await _to_thread(
            _get_service(KnowledgeTagService).detach_document_tag, document_id, tag_id
        )
        return _ok_msg("移除标签成功")
```

> `attach_document_tag(account.id, document_id, tag_id, True)` 因 `_to_thread` 传位置参数，第 4 个位置参数即 `verify_document=True`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/app/http/test_knowledge_tag_routes.py test/app/http/test_knowledge_partition_routes.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/app/http/knowledge_mcp_routes.py api/test/app/http/test_knowledge_tag_routes.py
git commit -m "feat(knowledge): add document tag attach, detach and list routes"
```

---

## 工作流 2：L2 按需解析

### Task 6: 视频 L1 补 ASR 音轨提取

**Files:**
- Modify: `api/internal/core/vision/vision_invoke.py`（新增音轨抽取，不动抽帧返回类型）
- Modify: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/service/test_video_audio_extraction.py`

- [ ] **Step 1: 写失败测试**

```python
"""视频音轨抽取测试。"""
import os
import subprocess
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService


class _FakeStorage:
    def __init__(self, payload: bytes = b"video-bytes"):
        self._payload = payload

    def download_file(self, key, path):
        with open(path, "wb") as fh:
            fh.write(self._payload)


def _service(storage=None):
    svc = KnowledgeMediaExtractorService.__new__(KnowledgeMediaExtractorService)
    svc.db = SimpleNamespace()
    svc.cos_service = storage or _FakeStorage()
    svc.audio_service = SimpleNamespace(audio_to_text=lambda _fs: "视频里说的话")
    return svc


class TestVideoAudioExtraction:
    def test_extract_audio_track_invokes_ffmpeg(self, monkeypatch, tmp_path):
        from internal.core import vision as vision_mod

        calls = []

        def _fake_run(cmd, **_kwargs):
            calls.append(cmd)
            out = cmd[-1]
            with open(out, "wb") as fh:
                fh.write(b"wav")
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(vision_mod.vision_invoke.subprocess, "run", _fake_run)
        monkeypatch.setattr(vision_mod.vision_invoke, "_ffmpeg_available", lambda: True)
        target = os.path.join(tmp_path, "audio.wav")

        result = vision_mod.vision_invoke.extract_video_audio("in.mp4", target)

        assert result == target
        assert os.path.isfile(target)
        assert any("-vn" in cmd for cmd in calls), "抽音轨必须禁用视频流"

    def test_extract_audio_track_raises_when_ffmpeg_missing(self, monkeypatch, tmp_path):
        from internal.core import vision as vision_mod

        monkeypatch.setattr(vision_mod.vision_invoke, "_ffmpeg_available", lambda: False)
        try:
            import imageio_ffmpeg  # noqa: F401
            has_imageio = True
        except ImportError:
            has_imageio = False
        monkeypatch.setattr(
            vision_mod.vision_invoke, "_resolve_ffmpeg_exe", lambda: (_ for _ in ()).throw(RuntimeError("no ffmpeg"))
        )

        import pytest

        with pytest.raises(RuntimeError):
            vision_mod.vision_invoke.extract_video_audio(
                "in.mp4", os.path.join(tmp_path, "audio.wav")
            )

    def test_video_segments_include_transcript_segment(self, monkeypatch):
        """视频解析应产出「音轨转写」片段，与逐帧片段并存。"""
        svc = _service()
        monkeypatch.setattr(svc, "_extract_frames", lambda _p: ["data:image/jpeg;base64,AAA"])
        monkeypatch.setattr(svc, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(svc, "_extract_audio_track", lambda _p: "/tmp/a.wav")
        monkeypatch.setattr(svc, "_transcribe_audio_file", lambda _p: "视频里说的话")

        segments = svc._extract_video(SimpleNamespace(key="k.mp4", name="k.mp4"))

        contents = [s.content for s in segments]
        assert "视频里说的话" in contents
        assert "画面描述" in contents

    def test_video_skips_transcript_when_asr_returns_blank(self, monkeypatch):
        svc = _service()
        monkeypatch.setattr(svc, "_extract_frames", lambda _p: ["data:image/jpeg;base64,AAA"])
        monkeypatch.setattr(svc, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(svc, "_extract_audio_track", lambda _p: "/tmp/a.wav")
        monkeypatch.setattr(svc, "_transcribe_audio_file", lambda _p: "")

        segments = svc._extract_video(SimpleNamespace(key="k.mp4", name="k.mp4"))

        assert [s.content for s in segments] == ["画面描述"]

    def test_video_continues_when_audio_extraction_fails(self, monkeypatch):
        """音轨抽取失败不得让整个视频解析失败——帧描述仍是有效产物。"""
        svc = _service()
        monkeypatch.setattr(svc, "_extract_frames", lambda _p: ["data:image/jpeg;base64,AAA"])
        monkeypatch.setattr(svc, "_invoke_vision", lambda _uri, _prompt: "画面描述")

        def _boom(_p):
            raise RuntimeError("no audio stream")

        monkeypatch.setattr(svc, "_extract_audio_track", _boom)

        segments = svc._extract_video(SimpleNamespace(key="k.mp4", name="k.mp4"))

        assert [s.content for s in segments] == ["画面描述"]

    def test_transcript_segment_metadata_marks_audio_source(self, monkeypatch):
        svc = _service()
        monkeypatch.setattr(svc, "_extract_frames", lambda _p: ["data:image/jpeg;base64,AAA"])
        monkeypatch.setattr(svc, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(svc, "_extract_audio_track", lambda _p: "/tmp/a.wav")
        monkeypatch.setattr(svc, "_transcribe_audio_file", lambda _p: "视频里说的话")

        segments = svc._extract_video(SimpleNamespace(key="k.mp4", name="k.mp4"))
        transcript = [s for s in segments if s.content == "视频里说的话"][0]

        assert transcript.metadata["media_type"] == "video"
        assert transcript.metadata["source"] == "audio_transcript"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_video_audio_extraction.py -q --no-header --no-cov`
Expected: FAIL —— `AttributeError: module ... has no attribute 'extract_video_audio'`

- [ ] **Step 3: 实现**

`vision_invoke.py` 新增（并抽出 `_resolve_ffmpeg_exe()` 供抽帧与抽音轨共用）：

```python
def _resolve_ffmpeg_exe() -> str:
    """返回可用的 ffmpeg 可执行文件路径；都不可用时抛 RuntimeError。"""
    if _ffmpeg_available():
        return "ffmpeg"
    try:
        import imageio_ffmpeg  # type: ignore
    except ImportError:
        raise RuntimeError(
            "ffmpeg 不可用：容器未安装 ffmpeg，也未安装 imageio-ffmpeg。"
            "请安装 imageio-ffmpeg（pip install imageio-ffmpeg）后重试。"
        )
    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_video_audio(video_path: str, target_path: str) -> str:
    """从视频抽取音轨为单声道 16k WAV（ASR 友好），返回目标路径。

    视频无音轨或抽轨失败时抛异常，由调用方决定是否降级。
    """
    exe = _resolve_ffmpeg_exe()
    cmd = [
        exe, "-y", "-i", video_path,
        "-vn",              # 丢弃视频流
        "-ac", "1",         # 单声道
        "-ar", "16000",     # 16k 采样率（ASR 标准输入）
        "-f", "wav",
        target_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
    if not os.path.isfile(target_path):
        raise RuntimeError("视频音轨抽取未产出文件")
    return target_path
```

`knowledge_media_extractor_service.py` 的 `_extract_video` 改为：抽帧后**在同一临时目录内**抽音轨并转写，音轨失败只告警不中断；转写片段用 `source: "audio_transcript"` 标记。新增两个可替换方法：

```python
    def _extract_audio_track(self, video_path: str) -> str:
        """抽取视频音轨（独立方法便于测试替换）。"""
        target = os.path.join(tempfile.gettempdir(), f"{uuid4().hex}.wav")
        return extract_video_audio(video_path, target)

    def _transcribe_audio_file(self, audio_path: str) -> str:
        """把音轨文件转写为文本（独立方法便于测试替换）。"""
        from io import BytesIO

        from werkzeug.datastructures import FileStorage

        with open(audio_path, "rb") as fh:
            content = fh.read()
        file_storage = FileStorage(
            stream=BytesIO(content),
            filename=os.path.basename(audio_path),
            content_type="audio/wav",
        )
        return str(self.audio_service.audio_to_text(file_storage) or "").strip()
```

`_extract_video` 内新增音轨片段（放在帧片段之前，使「讲什么」优先级更高）：

```python
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            frames = self._extract_frames(file_path)
            transcript = ""
            try:
                audio_path = self._extract_audio_track(file_path)
                transcript = self._transcribe_audio_file(audio_path)
            except Exception:
                logger.warning("视频音轨转写失败，降级为仅帧描述 file=%s",
                               upload_file.name, exc_info=True)
            finally:
                try:
                    os.remove(audio_path)
                except (OSError, UnboundLocalError):
                    pass

        segments: list[MediaSegment] = []
        if transcript:
            segments.append(
                MediaSegment(
                    content=transcript,
                    metadata={
                        "media_type": DocumentMediaType.VIDEO.value,
                        "source": "audio_transcript",
                    },
                )
            )
        # ...原有逐帧循环保持不变，append 到同一 segments
```

> `os.remove` 必须用 try/finally 兜住，且 `audio_path` 可能未定义（抽取就失败时）——用 `UnboundLocalError` 一并捕获。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_video_audio_extraction.py test/internal/service/test_knowledge_media_extractor_service.py test/internal/core/vision/test_vision_invoke.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/vision/vision_invoke.py api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_video_audio_extraction.py
git commit -m "feat(knowledge): extract and transcribe video audio track in L1 parsing"
```

---

## 工作流 3：关键帧留存 + 视觉向量

### Task 7: 关键帧留存为 UploadFile

**Files:**
- Modify: `api/internal/core/vision/vision_invoke.py`（新增「抽帧到指定目录」）
- Modify: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/service/test_frame_persistence.py`

- [ ] **Step 1: 写失败测试**

```python
"""关键帧留存测试。"""
import os
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService


class _FakeStorage:
    def download_file(self, key, path):
        with open(path, "wb") as fh:
            fh.write(b"video-bytes")

    def upload_bytes(self, filename, content, **_kwargs):
        return SimpleNamespace(key=f"frames/{filename}", size=len(content))


def _service():
    svc = KnowledgeMediaExtractorService.__new__(KnowledgeMediaExtractorService)
    svc.db = SimpleNamespace()
    svc.cos_service = _FakeStorage()
    svc.audio_service = SimpleNamespace(audio_to_text=lambda _fs: "")
    svc.upload_file_service = SimpleNamespace(
        create_upload_file=lambda **kw: SimpleNamespace(id=uuid4(), **kw)
    )
    return svc


class TestFramePersistence:
    def test_persist_frame_uploads_and_returns_upload_file(self, tmp_path):
        svc = _service()
        frame = os.path.join(tmp_path, "frame_001.jpg")
        with open(frame, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0jpeg-bytes")

        result = svc._persist_frame(frame, account_id=uuid4(), document_id=uuid4())

        assert result.key.startswith("frames/")
        assert result.size > 0

    def test_extract_video_frames_to_dir_returns_paths(self, tmp_path, monkeypatch):
        from internal.core import vision as vision_mod

        captured = {}

        def _fake_ffmpeg(video_path, frame_count, out_dir):
            paths = []
            for index in range(1, frame_count + 1):
                path = os.path.join(out_dir, f"frame_{index:03d}.jpg")
                with open(path, "wb") as fh:
                    fh.write(b"\xff\xd8\xff\xe0x")
                paths.append(path)
            captured["out_dir"] = out_dir
            return paths

        monkeypatch.setattr(
            vision_mod.vision_invoke, "_extract_frames_to_dir_ffmpeg", _fake_ffmpeg
        )
        out = tmp_path / "frames"

        paths = vision_mod.vision_invoke.extract_video_frames_to_dir(
            "in.mp4", str(out), frame_count=2
        )

        assert len(paths) == 2
        assert all(os.path.isfile(p) for p in paths)
        assert str(out) == captured["out_dir"]

    def test_video_segments_include_frame_urls_metadata(self, monkeypatch, tmp_path):
        """帧留存后，帧片段 metadata 必须带 frame_url，供视觉向量与「改细节」定位。"""
        svc = _service()
        frame_file = tmp_path / "frame_001.jpg"
        with open(frame_file, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0x")
        monkeypatch.setattr(svc, "_extract_frames_to_dir", lambda _p, _d: [str(frame_file)])
        monkeypatch.setattr(svc, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(svc, "_extract_audio_track", lambda _p: "/tmp/a.wav")
        monkeypatch.setattr(svc, "_transcribe_audio_file", lambda _p: "")

        segments = svc._extract_video(
            SimpleNamespace(key="k.mp4", name="k.mp4"),
            account_id=uuid4(), document_id=uuid4(),
        )

        assert segments[0].metadata["frame_url"].startswith("frames/")

    def test_frame_upload_failure_does_not_break_video_parsing(self, monkeypatch, tmp_path):
        svc = _service()
        frame_file = tmp_path / "frame_001.jpg"
        with open(frame_file, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0x")
        monkeypatch.setattr(svc, "_extract_frames_to_dir", lambda _p, _d: [str(frame_file)])
        monkeypatch.setattr(svc, "_invoke_vision", lambda _uri, _prompt: "画面描述")
        monkeypatch.setattr(svc, "_extract_audio_track", lambda _p: "/tmp/a.wav")
        monkeypatch.setattr(svc, "_transcribe_audio_file", lambda _p: "")

        def _boom(*_a, **_kw):
            raise RuntimeError("storage down")

        monkeypatch.setattr(svc, "_persist_frame", _boom)

        segments = svc._extract_video(
            SimpleNamespace(key="k.mp4", name="k.mp4"),
            account_id=uuid4(), document_id=uuid4(),
        )

        assert segments[0].content == "画面描述"
        assert segments[0].metadata["frame_url"] == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_frame_persistence.py -q --no-header --no-cov`
Expected: FAIL —— `AttributeError: 'KnowledgeMediaExtractorService' object has no attribute '_persist_frame'`

- [ ] **Step 3: 实现**

`vision_invoke.py` 新增（保留既有 `extract_video_frames` 返回 data URI 的行为不变，新增一个落到指定目录的版本供留存使用）：

```python
def extract_video_frames_to_dir(video_path: str, out_dir: str, frame_count: int = _DEFAULT_FRAME_COUNT) -> list[str]:
    """抽取关键帧到指定目录，返回帧文件路径列表（供留存/视觉向量使用）。

    与 extract_video_frames 的区别：不删除目录、不转 data URI，
    调用方负责目录生命周期。
    """
    requested = _DEFAULT_FRAME_COUNT if frame_count is None else max(1, int(frame_count))
    os.makedirs(out_dir, exist_ok=True)
    if _ffmpeg_available():
        return _extract_frames_to_dir_ffmpeg(video_path, requested, out_dir)
    try:
        import imageio_ffmpeg  # type: ignore
    except ImportError:
        raise RuntimeError("视频抽帧不可用：未安装 ffmpeg，也未安装 imageio-ffmpeg")
    return _extract_frames_to_dir_imageio(video_path, requested, out_dir)


def _extract_frames_to_dir_ffmpeg(video_path: str, frame_count: int, out_dir: str) -> list[str]:
    """ffmpeg 抽帧到 out_dir（复用时长探测逻辑，失败回落首帧）。"""
    pattern = os.path.join(out_dir, "frame_%03d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", "select='not(mod(n\\,100))'",
        "-frames:v", str(frame_count),
        "-q:v", "4", pattern,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("ffmpeg 抽帧失败: %s", getattr(exc, "stderr", b"")[:200])
    frames = sorted(
        os.path.join(out_dir, name)
        for name in os.listdir(out_dir)
        if name.startswith("frame_") and name.endswith(".jpg")
    )
    if not frames:
        first = os.path.join(out_dir, "frame_001.jpg")
        _dump_first_frame(video_path, first)
        frames = [first]
    return frames[:frame_count]
```

`knowledge_media_extractor_service.py`：

```python
    def _persist_frame(self, frame_path: str, *, account_id, document_id) -> UploadFile:
        """把帧文件上传为 UploadFile，返回持久化记录。

        关键帧必须留存：视觉向量可后补而无需重跑解析（设计稿 §3.4 要求）。
        """
        with open(frame_path, "rb") as fh:
            content = fh.read()
        filename = os.path.basename(frame_path)
        stored = self.cos_service.upload_bytes(filename, content)
        return self.upload_file_service.create_upload_file(
            account_id=account_id,
            name=filename,
            key=stored.key,
            size=len(content),
            extension="jpg",
            mime_type="image/jpeg",
            hash=hashlib.sha3_256(content).hexdigest(),
            storage_backend="local",
        )
```

`_extract_video` 签名扩展为 `(upload_file, account_id=None, document_id=None)`，帧循环内调用 `_persist_frame` 并把结果 key 写入 `metadata["frame_url"]`；`_persist_frame` 抛异常时置 `frame_url=""` 并继续（帧描述本身仍是有效产物）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_frame_persistence.py test/internal/service/test_knowledge_media_extractor_service.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/vision/vision_invoke.py api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_frame_persistence.py
git commit -m "feat(knowledge): persist video keyframes as upload files with frame_url metadata"
```

---

### Task 8: 视觉编码模型类型接入

**Files:**
- Modify: `api/internal/core/language_model/entities/model_entity.py`
- Modify: `api/internal/schema/admin_model_pool_schema.py`
- Modify: `api/internal/schema/admin_model_provider_schema.py`
- Modify: `api/internal/service/admin_model_pool_service.py`
- Modify: `ui/src/views/admin/ModelsView.vue`、`ui/src/views/admin/ModelProvidersView.vue`
- Modify: `ui/src/i18n/messages/zh-CN/admin/models.ts`、`ui/src/i18n/messages/en-US/admin/models.ts`
- Test: `api/test/internal/schema/test_model_type_parity.py`

- [ ] **Step 1: 写失败测试（含防漂移一致性测试）**

```python
"""模型类型定义一致性测试。

MODEL_TYPES 在 backend 有两份副本、前端有两份，历史无任何防漂移守卫。
本测试锁定它们必须包含同一集合，避免新增类型时漏改某一处。
"""
from internal.core.language_model.entities.model_entity import ModelType
from internal.schema.admin_model_pool_schema import MODEL_TYPES as POOL_TYPES
from internal.schema.admin_model_provider_schema import MODEL_TYPES as PROVIDER_TYPES


class TestModelTypeConsistency:
    def test_two_backend_copies_are_identical(self):
        assert POOL_TYPES == PROVIDER_TYPES

    def test_enum_and_schema_lists_are_in_sync(self):
        assert set(POOL_TYPES) == {member.value for member in ModelType}

    def test_visual_embedding_is_registered(self):
        assert ModelType.VISUAL_EMBEDDING.value == "visual_embedding"
        assert "visual_embedding" in POOL_TYPES

    def test_visual_embedding_is_context_less(self):
        """视觉编码模型无上下文窗口概念，必须进 CONTEXT_LESS_MODEL_TYPES。"""
        from internal.service.admin_model_pool_service import CONTEXT_LESS_MODEL_TYPES

        assert "visual_embedding" in CONTEXT_LESS_MODEL_TYPES
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/schema/test_model_type_parity.py -q --no-header --no-cov`
Expected: FAIL —— `AttributeError: VISUAL_EMBEDDING`

- [ ] **Step 3: 实现**

按下表逐处补齐（**照抄现有写法，不引入新机制**）：

| 文件 | 改动 |
| --- | --- |
| `model_entity.py` `ModelType` | 加 `VISUAL_EMBEDDING = "visual_embedding"` |
| `admin_model_pool_schema.py` `MODEL_TYPES` | 追加 `"visual_embedding"` |
| `admin_model_pool_schema.py` `EMBEDDING_DIMENSIONS` | 追加 `2560`（Qwen3-VL-Embedding-8B 的 MRL 档位，≤2000 的用 1536 已存在） |
| `admin_model_provider_schema.py` `MODEL_TYPES` | 追加 `"visual_embedding"` |
| `admin_model_pool_service.py` `CONTEXT_LESS_MODEL_TYPES` | 加入 `"visual_embedding"` |
| `admin_model_pool_service.py` 维度探测分支 | 让 `model_type in {"embedding", "visual_embedding"}` 都走 `_auto_probe_dimension`（否则维度被强制置 0） |
| `ModelsView.vue` `ALL_MODEL_TYPES` / `CONTEXT_LESS_MODEL_TYPES` | 同步追加 |
| `ModelProvidersView.vue` 类型选项 | 同步追加 |
| `zh-CN/admin/models.ts` + `en-US/admin/models.ts` | `modelTypes.visual_embedding` 文案（双端同步） |

`model_class_registry.py`：**不要注册新类**。视觉编码走独立 HTTP 调用（Task 10），不经过 langchain 注册表，避免 `resolve()` 误用 `OpenAIEmbeddings`（其入参格式与该模型不兼容）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/schema/test_model_type_parity.py -q --no-header --no-cov`
再运行：`cd ui && npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected: 都 PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/language_model/entities/model_entity.py api/internal/schema/ api/internal/service/admin_model_pool_service.py ui/src/views/admin/ ui/src/i18n/messages/ api/test/internal/schema/test_model_type_parity.py
git commit -m "feat(model-pool): add visual_embedding model type with drift guards"
```

---

### Task 9: 视觉向量表与迁移

**Files:**
- Create: `api/internal/model/video_visual_embedding.py`
- Create: `api/internal/migration/versions/z1c2d3e4f5a6_add_video_visual_embedding.py`
- Modify: `api/internal/model/__init__.py`
- Test: `api/test/internal/model/test_video_visual_embedding_model.py`

- [ ] **Step 1: 写失败测试**

```python
"""视觉向量表结构测试。"""
from internal.model import VideoVisualEmbedding


class TestVideoVisualEmbeddingModel:
    def test_table_name(self):
        assert VideoVisualEmbedding.__tablename__ == "video_visual_embedding"

    def test_required_columns_exist(self):
        columns = {c.name for c in VideoVisualEmbedding.__table__.columns}
        for name in (
            "id", "knowledge_base_id", "knowledge_document_id", "segment_id",
            "account_id", "frame_url", "scene_index", "embedding", "model_id",
            "updated_at", "created_at",
        ):
            assert name in columns, f"缺少列 {name}"

    def test_dimension_constant_is_within_pgvector_limit(self):
        from internal.model.video_visual_embedding import VISUAL_EMBEDDING_DIMENSION

        assert VISUAL_EMBEDDING_DIMENSION <= 2000

    def test_segment_unique_constraint_exists(self):
        names = {c.name for c in VideoVisualEmbedding.__table__.constraints if c.name}
        assert "uq_video_visual_embedding_segment" in names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/model/test_video_visual_embedding_model.py -q --no-header --no-cov`
Expected: FAIL —— `ImportError: cannot import name 'VideoVisualEmbedding'`

- [ ] **Step 3: 实现模型与迁移**

```python
"""视觉向量表（关键帧跨模态检索）。

独立于 knowledge_segment_embedding_{dim}：视觉编码模型的输入是「图文混合」，
且该表的写入/删除生命周期跟随素材解析，与文本片段向量不同步。
维度固定为 VISUAL_EMBEDDING_DIMENSION（Qwen3-VL-Embedding-8B 经 MRL 降至 1536，
原生 4096 超出 pgvector 上限 2000）。
"""
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint,
    String, UniqueConstraint, UUID, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base

VISUAL_EMBEDDING_DIMENSION = 1536


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class VideoVisualEmbedding(Base):
    """关键帧视觉向量。"""

    __tablename__ = "video_visual_embedding"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_video_visual_embedding_id"),
        UniqueConstraint("segment_id", name="uq_video_visual_embedding_segment"),
        Index("video_visual_embedding_kb_idx", "knowledge_base_id"),
        Index("video_visual_embedding_document_idx", "knowledge_document_id"),
        Index("video_visual_embedding_account_idx", "account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    knowledge_base_id = Column(
        UUID, ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_document_id = Column(
        UUID, ForeignKey("knowledge_document.id", ondelete="CASCADE"), nullable=False
    )
    segment_id = Column(
        UUID, ForeignKey("knowledge_segment.id", ondelete="CASCADE"), nullable=False
    )
    frame_url = Column(String(512), nullable=False, server_default=text("''::character varying"))
    scene_index = Column(Integer, nullable=False, server_default=text("0"))
    model_id = Column(String(36), nullable=True)
    embedding = Column(Vector(VISUAL_EMBEDDING_DIMENSION), nullable=False)
    updated_at = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
```

迁移（`down_revision` 必须指向**已提交**的最新 revision，先 `git ls-files` 确认，并运行 `alembic heads` 校验单 head）：

```python
def upgrade():
    op.create_table(
        "video_visual_embedding",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("account_id", postgresql.UUID(), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(), nullable=False),
        sa.Column("knowledge_document_id", postgresql.UUID(), nullable=False),
        sa.Column("segment_id", postgresql.UUID(), nullable=False),
        sa.Column("frame_url", sa.String(512), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column("scene_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=True),
        sa.Column("embedding", Vector(VISUAL_EMBEDDING_DIMENSION), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP(0)"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP(0)"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_video_visual_embedding_id"),
        sa.UniqueConstraint("segment_id", name="uq_video_visual_embedding_segment"),
    )
    # 外键单独加：便于 downgrade 先删约束再删表
    op.create_foreign_key("fk_vve_kb", "video_visual_embedding", "knowledge_base",
                          ["knowledge_base_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_vve_doc", "video_visual_embedding", "knowledge_document",
                          ["knowledge_document_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_vve_seg", "video_visual_embedding", "knowledge_segment",
                          ["segment_id"], ["id"], ondelete="CASCADE")
    op.create_index("video_visual_embedding_kb_idx", "video_visual_embedding", ["knowledge_base_id"])
    op.create_index("video_visual_embedding_document_idx", "video_visual_embedding", ["knowledge_document_id"])
    op.create_index("video_visual_embedding_account_idx", "video_visual_embedding", ["account_id"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS video_visual_embedding_hnsw_idx "
        "ON video_visual_embedding USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade():
    op.drop_table("video_visual_embedding")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/model/test_video_visual_embedding_model.py test/internal/migration/test_migration_graph_integrity.py -q --no-header --no-cov`
再运行：`python -m alembic -c internal/migration/alembic.ini heads`
Expected: 测试 PASS；alembic 输出**单个** head

- [ ] **Step 5: 提交**

```bash
git add api/internal/model/video_visual_embedding.py api/internal/model/__init__.py api/internal/migration/versions/z1c2d3e4f5a6_add_video_visual_embedding.py api/test/internal/model/test_video_visual_embedding_model.py
git commit -m "feat(knowledge): add video visual embedding table with hnsw index"
```

---

### Task 10: 视觉编码服务（Qwen3-VL-Embedding）

**Files:**
- Create: `api/internal/service/visual_embedding_service.py`
- Test: `api/test/internal/service/test_visual_embedding_service.py`

- [ ] **Step 1: 写失败测试**

```python
"""视觉编码服务测试：请求体格式 + 维度 + 降级。"""
from types import SimpleNamespace

import pytest

from internal.service.visual_embedding_service import VisualEmbeddingService
from internal.model.video_visual_embedding import VISUAL_EMBEDDING_DIMENSION


class _ResponseStub:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _service(post_impl, creds=None):
    svc = VisualEmbeddingService.__new__(VisualEmbeddingService)
    svc._post = post_impl
    svc._credentials = lambda: creds or {
        "api_key": "k", "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen3-VL-Embedding-8B",
    }
    return svc


class TestVisualEmbeddingService:
    def test_embed_text_sends_plain_string_input(self):
        captured = {}

        def _post(url, json, headers, timeout):
            captured.update({"url": url, "json": json, "headers": headers})
            return _ResponseStub({"data": [{"embedding": [0.1] * VISUAL_EMBEDDING_DIMENSION}]})

        svc = _service(_post)
        vector = svc.embed_text("a cat")

        assert captured["json"]["input"] == "a cat"
        assert captured["url"].endswith("/embeddings")
        assert captured["json"]["dimensions"] == VISUAL_EMBEDDING_DIMENSION
        assert len(vector) == VISUAL_EMBEDDING_DIMENSION

    def test_embed_image_uses_image_object_input(self):
        """该模型的图片入参是 {"image": ...}，不是 OpenAI 的字符串数组。"""
        captured = {}

        def _post(url, json, headers, timeout):
            captured.update(json)
            return _ResponseStub({"data": [{"embedding": [0.2] * VISUAL_EMBEDDING_DIMENSION}]})

        svc = _service(_post)
        svc.embed_image("data:image/jpeg;base64,AAAA")

        assert captured["input"] == {"image": "data:image/jpeg;base64,AAAA"}

    def test_embed_returns_empty_on_http_error(self):
        def _post(*_a, **_kw):
            raise RuntimeError("boom")

        svc = _service(_post)
        assert svc.embed_text("x") == []
        assert svc.embed_image("data:image/jpeg;base64,AAAA") == []

    def test_embed_returns_empty_when_api_key_missing(self):
        svc = _service(lambda *_a, **_kw: _ResponseStub({}), creds={"api_key": "", "base_url": "u", "model": "m"})
        assert svc.embed_text("x") == []

    def test_search_visual_ranks_by_cosine_similarity(self):
        """以图搜图：用图片向量与库内视觉向量做余弦相似度排序。"""
        svc = _service(lambda *_a, **_kw: _ResponseStub({}))
        svc.embed_image = lambda _uri: [1.0, 0.0]
        svc._fetch_rows = lambda **_kw: [
            {"segment_id": "s1", "frame_url": "f1", "embedding": [1.0, 0.0]},
            {"segment_id": "s2", "frame_url": "f2", "embedding": [0.0, 1.0]},
        ]

        results = svc.search_by_image(image_uri="data:image/jpeg;base64,AAAA", knowledge_base_id="kb")

        assert [r["segment_id"] for r in results] == ["s1", "s2"]
        assert results[0]["score"] > results[1]["score"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_visual_embedding_service.py -q --no-header --no-cov`
Expected: FAIL —— `ModuleNotFoundError: No module named 'internal.service.visual_embedding_service'`

- [ ] **Step 3: 实现**

```python
"""视觉编码服务（Qwen3-VL-Embedding，硅基流动）。

与 EmbeddingsService 分开的原因：该模型的 embeds 接口入参与 OpenAI 不兼容——
文本传裸字符串，图片传 {"image": ...}，混合传对象数组；用 OpenAIEmbeddings
无法表达，会静默只编码文本。

文本与图片映射到同一语义空间，因此可以用文本 query 直接召回视觉向量。
"""
import logging
from dataclasses import dataclass
from uuid import UUID

import requests
from injector import inject
from sqlalchemy import text

from internal.model.video_visual_embedding import VISUAL_EMBEDDING_DIMENSION
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .language_model_service import LanguageModelService

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30
_VISUAL_MODEL_TYPE = "visual_embedding"


@inject
@dataclass
class VisualEmbeddingService(BaseService):
    """关键帧/图片的视觉向量编码与检索。"""

    db: SQLAlchemy

    def _credentials(self) -> dict:
        """从模型池取视觉编码模型凭证（复用既有 provider 凭证链路）。"""
        return LanguageModelService.get_provider_credentials(model_type=_VISUAL_MODEL_TYPE) or {}

    def _post(self, url, json, headers, timeout):  # 独立方法便于测试替换
        return requests.post(url, json=json, headers=headers, timeout=timeout)

    def _request_embedding(self, payload_input) -> list[float]:
        creds = self._credentials()
        api_key = str(creds.get("api_key") or "")
        base_url = str(creds.get("base_url") or "").rstrip("/")
        model = str(creds.get("model") or "")
        if not api_key or not base_url or not model:
            logger.warning("视觉编码模型未配置（缺少 api_key/base_url/model）")
            return []
        try:
            response = self._post(
                f"{base_url}/embeddings",
                json={
                    "model": model,
                    "input": payload_input,
                    "dimensions": VISUAL_EMBEDDING_DIMENSION,
                },
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = (response.json() or {}).get("data") or []
            if not data:
                return []
            vector = [float(x) for x in data[0].get("embedding") or []]
        except Exception:
            logger.warning("视觉编码请求失败", exc_info=True)
            return []
        if len(vector) != VISUAL_EMBEDDING_DIMENSION:
            logger.warning(
                "视觉编码维度不符：期望 %s 实际 %s", VISUAL_EMBEDDING_DIMENSION, len(vector)
            )
            return []
        return vector

    def embed_text(self, content: str) -> list[float]:
        return self._request_embedding(content)

    def embed_image(self, data_uri: str) -> list[float]:
        return self._request_embedding({"image": data_uri})

    def embed_mixed(self, text: str, data_uri: str) -> list[float]:
        return self._request_embedding([{"text": text}, {"image": data_uri}])

    def _fetch_rows(self, *, knowledge_base_id, partition_id=None, threshold=None, limit=20):
        """读取库内视觉向量（独立方法便于测试替换）。"""
        sql = """
            SELECT segment_id, frame_url, embedding
            FROM video_visual_embedding
            WHERE knowledge_base_id = :kb_id
        """
        params = {"kb_id": str(knowledge_base_id)}
        if partition_id is not None:
            sql += (
                " AND knowledge_document_id IN ("
                "SELECT id FROM knowledge_document WHERE partition_id = :partition_id)"
            )
            params["partition_id"] = str(partition_id)
        result = self.db.session.execute(text(sql), params)
        return [
            {
                "segment_id": str(row.segment_id),
                "frame_url": row.frame_url,
                "embedding": list(row.embedding),
            }
            for row in result
        ]

    def search_by_image(self, *, image_uri: str, knowledge_base_id: UUID, limit: int = 10) -> list[dict]:
        """以图搜图：库内视觉向量按余弦相似度排序（向量量级可控，Python 侧算即可）。"""
        query_vector = self.embed_image(image_uri)
        if not query_vector:
            return []
        return self._rank(query_vector, knowledge_base_id, limit)

    def search_by_text(self, *, query: str, knowledge_base_id: UUID, limit: int = 10) -> list[dict]:
        """跨模态文本召回：文本与图片处在同一语义空间，可直接比对。"""
        query_vector = self.embed_text(query)
        if not query_vector:
            return []
        return self._rank(query_vector, knowledge_base_id, limit)

    def _rank(self, query_vector: list[float], knowledge_base_id: UUID, limit: int) -> list[dict]:
        rows = self._fetch_rows(knowledge_base_id=knowledge_base_id)
        scored = []
        for row in rows:
            score = _cosine_similarity(query_vector, row["embedding"])
            scored.append({"segment_id": row["segment_id"], "frame_url": row["frame_url"], "score": score})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """余弦相似度；任一向量为零向量时返回 0，避免除零。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm_left = sum(a * a for a in left) ** 0.5
    norm_right = sum(b * b for b in right) ** 0.5
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_visual_embedding_service.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/visual_embedding_service.py api/test/internal/service/test_visual_embedding_service.py
git commit -m "feat(knowledge): add visual embedding service for qwen3-vl-embedding"
```

---

### Task 11: 视觉向量索引接入解析链路

**Files:**
- Modify: `api/internal/service/knowledge_indexing_service.py`
- Test: `api/test/internal/service/test_visual_indexing.py`

- [ ] **Step 1: 写失败测试**

```python
"""解析链路写入视觉向量测试。"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_indexing_service import KnowledgeIndexingService


class _QueryStub:
    def filter(self, *_a, **_kw):
        return self

    def delete(self):
        return 1


def _service(segments, visual_results, frame_bytes=b"\xff\xd8\xff\xe0x"):
    svc = KnowledgeIndexingService.__new__(KnowledgeIndexingService)
    svc.visual_embedding_service = SimpleNamespace(
        embed_image=lambda uri: [0.1] * 1536,
        delete_by_document=lambda _doc_id: None,
        index_frame=lambda **kw: visual_results.append(kw) or "id",
    )
    svc.cos_service = SimpleNamespace(
        download_file=lambda _key, path: open(path, "wb").write(frame_bytes)
    )
    return svc, visual_results


class TestVisualIndexing:
    def test_frame_segments_get_visual_vectors(self):
        captured = []
        svc, _ = _service([], captured)
        segment = SimpleNamespace(
            id=uuid4(),
            metadata_={"media_type": "video", "frame_url": "frames/f1.jpg", "scene_index": 1},
        )
        document = SimpleNamespace(id=uuid4(), knowledge_base_id=uuid4(), account_id=uuid4())

        svc._index_visual_vectors(document, [segment])

        assert len(captured) == 1
        assert captured[0]["frame_url"] == "frames/f1.jpg"
        assert captured[0]["scene_index"] == 1

    def test_segments_without_frame_url_are_skipped(self):
        captured = []
        svc, _ = _service([], captured)
        segment = SimpleNamespace(id=uuid4(), metadata_={"media_type": "video", "frame_url": ""})
        document = SimpleNamespace(id=uuid4(), knowledge_base_id=uuid4(), account_id=uuid4())

        svc._index_visual_vectors(document, [segment])

        assert captured == []

    def test_non_video_segments_are_skipped(self):
        captured = []
        svc, _ = _service([], captured)
        segment = SimpleNamespace(
            id=uuid4(), metadata_={"media_type": "document", "frame_url": "x"}
        )
        document = SimpleNamespace(id=uuid4(), knowledge_base_id=uuid4(), account_id=uuid4())

        svc._index_visual_vectors(document, [segment])

        assert captured == []

    def test_rebuild_clears_previous_visual_vectors(self):
        """重解析必须清理旧视觉向量，否则会累积重复行。"""
        cleared = []
        captured = []
        svc, _ = _service([], captured)
        svc.visual_embedding_service.delete_by_document = lambda doc_id: cleared.append(doc_id)
        document = SimpleNamespace(id=uuid4(), knowledge_base_id=uuid4(), account_id=uuid4())

        svc._index_visual_vectors(document, [])

        assert cleared == [document.id]

    def test_frame_download_failure_does_not_break_indexing(self):
        captured = []
        svc, _ = _service([], captured)
        svc.cos_service.download_file = lambda *_a: (_ for _ in ()).throw(RuntimeError("down"))
        segment = SimpleNamespace(
            id=uuid4(), metadata_={"media_type": "video", "frame_url": "frames/f1.jpg"}
        )
        document = SimpleNamespace(id=uuid4(), knowledge_base_id=uuid4(), account_id=uuid4())

        svc._index_visual_vectors(document, [segment])

        assert captured == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_visual_indexing.py -q --no-header --no-cov`
Expected: FAIL —— `AttributeError: _index_visual_vectors`

- [ ] **Step 3: 实现**

`VisualEmbeddingService` 补两个方法：

```python
    def index_frame(self, *, knowledge_base_id, knowledge_document_id, segment_id,
                    account_id, frame_url, scene_index, embedding, model_id=None) -> str:
        """写入（或覆盖）一条帧视觉向量。"""
        self.db.session.execute(
            text("""
                INSERT INTO video_visual_embedding
                    (account_id, knowledge_base_id, knowledge_document_id, segment_id,
                     frame_url, scene_index, model_id, embedding)
                VALUES (:account_id, :kb_id, :doc_id, :segment_id,
                        :frame_url, :scene_index, :model_id, CAST(:embedding AS vector))
                ON CONFLICT (segment_id) DO UPDATE SET
                    frame_url = EXCLUDED.frame_url,
                    scene_index = EXCLUDED.scene_index,
                    model_id = EXCLUDED.model_id,
                    embedding = EXCLUDED.embedding,
                    updated_at = CURRENT_TIMESTAMP(0)
            """),
            {
                "account_id": str(account_id),
                "kb_id": str(knowledge_base_id),
                "doc_id": str(knowledge_document_id),
                "segment_id": str(segment_id),
                "frame_url": frame_url,
                "scene_index": int(scene_index or 0),
                "model_id": str(model_id) if model_id else None,
                "embedding": embedding,
            },
        )
        self.db.session.commit()
        return str(segment_id)

    def delete_by_document(self, knowledge_document_id: UUID) -> None:
        """清理某素材的全部视觉向量（重解析前调用，保证幂等）。"""
        self.db.session.execute(
            text("DELETE FROM video_visual_embedding WHERE knowledge_document_id = :doc_id"),
            {"doc_id": str(knowledge_document_id)},
        )
        self.db.session.commit()
```

`KnowledgeIndexingService` 的 `_finalize_segments` 内、写完文本向量之后调用 `self._index_visual_vectors(document, segments)`：

```python
    def _index_visual_vectors(self, document, segments) -> None:
        """为带 frame_url 的视频帧片段建立视觉向量索引。

        先清空该素材旧视觉向量再重建——素材是「每次完整重新生成」的产物，
        与文本片段保持同一幂等语义。
        """
        service = getattr(self, "visual_embedding_service", None)
        if service is None:
            return
        try:
            service.delete_by_document(document.id)
        except Exception:
            logger.warning("清理旧视觉向量失败 document_id=%s", document.id, exc_info=True)

        for segment in segments:
            metadata = getattr(segment, "metadata_", None) or {}
            if metadata.get("media_type") != DocumentMediaType.VIDEO.value:
                continue
            frame_url = str(metadata.get("frame_url") or "")
            if not frame_url:
                continue
            try:
                import tempfile

                with tempfile.TemporaryDirectory() as temp_dir:
                    local_path = os.path.join(temp_dir, os.path.basename(frame_url))
                    self.cos_service.download_file(frame_url, local_path)
                    data_uri = path_to_data_uri(local_path)
                embedding = service.embed_image(data_uri)
                if not embedding:
                    continue
                service.index_frame(
                    knowledge_base_id=document.knowledge_base_id,
                    knowledge_document_id=document.id,
                    segment_id=segment.id,
                    account_id=document.account_id,
                    frame_url=frame_url,
                    scene_index=int(metadata.get("scene_index") or 0),
                    embedding=embedding,
                )
            except Exception:
                logger.warning(
                    "帧视觉向量写入失败 segment_id=%s frame_url=%s",
                    segment.id, frame_url, exc_info=True,
                )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_visual_indexing.py test/internal/service/test_knowledge_media_ingest.py test/internal/service/test_knowledge_indexing_service.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_indexing_service.py api/internal/service/visual_embedding_service.py api/test/internal/service/test_visual_indexing.py
git commit -m "feat(knowledge): index keyframe visual vectors during document parsing"
```

---

### Task 12: seed 硅基流动 provider 与视觉模型

**Files:**
- Create: `api/internal/migration/versions/z2d3e4f5a6b7_seed_siliconflow_vl_embedding.py`
- Test: `api/test/internal/migration/test_seed_visual_embedding.py`

- [ ] **Step 1: 写失败测试**

```python
"""视觉编码模型 seed 迁移测试（断言迁移文件包含幂等 seed 逻辑）。"""
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "api/internal/migration/versions/z2d3e4f5a6b7_seed_siliconflow_vl_embedding.py"
)


class TestVisualEmbeddingSeedMigration:
    def test_migration_exists(self):
        assert MIGRATION.is_file(), "缺少视觉编码模型 seed 迁移"

    def test_seed_is_idempotent(self):
        """必须用 WHERE NOT EXISTS / ON CONFLICT，重复执行不能插入重复行。"""
        source = MIGRATION.read_text(encoding="utf-8")
        assert "NOT EXISTS" in source or "ON CONFLICT" in source

    def test_seed_declares_model_and_dimension(self):
        source = MIGRATION.read_text(encoding="utf-8")
        assert "Qwen/Qwen3-VL-Embedding-8B" in source
        assert "visual_embedding" in source
        assert "1536" in source

    def test_seed_does_not_create_api_key(self):
        """迁移不得写入密钥——key 由管理员在 admin 配置，禁止把凭据写进代码库。"""
        source = MIGRATION.read_text(encoding="utf-8")
        assert "model_key_config" not in source
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/migration/test_seed_visual_embedding.py -q --no-header --no-cov`
Expected: FAIL —— `缺少视觉编码模型 seed 迁移`

- [ ] **Step 3: 实现迁移**

```python
"""seed 硅基流动 provider 与 Qwen3-VL-Embedding-8B 视觉编码模型。

幂等：provider 与模型都用 WHERE NOT EXISTS 保护，可重复执行。
不写密钥——按仓库规范，密钥由管理员在 admin 模型池配置（model_key_config）。
"""
revision = "z2d3e4f5a6b7"
down_revision = "<改成当前已提交的最新 head，用 git ls-files + alembic heads 确认>"


def upgrade():
    # 1. provider：SiliconFlow（若不存在则建，base_url 指向 /v1）
    op.execute("""
        INSERT INTO model_provider_config (name, label, description, default_base_url,
                                          supported_model_types, status)
        SELECT 'SiliconFlow', '硅基流动', '硅基流动 AI 云（含多模态嵌入与重排序）',
               'https://api.siliconflow.cn/v1',
               '["chat","embedding","tts","asr","rerank","visual_embedding"]'::jsonb,
               'active'
        WHERE NOT EXISTS (SELECT 1 FROM model_provider_config WHERE name = 'SiliconFlow')
    """)

    # 2. 视觉编码模型：维度固定 1536（原生 4096 经 MRL 降到 pgvector 上限内）
    op.execute("""
        INSERT INTO model_pool_config (provider, model_name, display_name, description,
                                       model_type, compatible_api, embedding_dimension,
                                       tier, status, priority)
        SELECT 'SiliconFlow', 'Qwen/Qwen3-VL-Embedding-8B', 'Qwen3-VL-Embedding-8B',
               '多模态嵌入模型（文本/图片共享语义空间），支持以图搜图与跨模态召回',
               'visual_embedding', 'openai', 1536, '2', 'active', 100
        WHERE NOT EXISTS (
            SELECT 1 FROM model_pool_config
            WHERE provider = 'SiliconFlow' AND model_name = 'Qwen/Qwen3-VL-Embedding-8B'
        )
    """)


def downgrade():
    op.execute(
        "DELETE FROM model_pool_config WHERE provider = 'SiliconFlow' "
        "AND model_name = 'Qwen/Qwen3-VL-Embedding-8B'"
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/migration/test_seed_visual_embedding.py test/internal/migration/test_migration_graph_integrity.py -q --no-header --no-cov`
再运行：`python -m alembic -c internal/migration/alembic.ini heads`
Expected: PASS；alembic 单 head

- [ ] **Step 5: 提交**

```bash
git add api/internal/migration/versions/z2d3e4f5a6b7_seed_siliconflow_vl_embedding.py api/test/internal/migration/test_seed_visual_embedding.py
git commit -m "feat(model-pool): seed siliconflow provider and qwen3-vl-embedding visual model"
```

---

### Task 13: L2 按需解析任务

**Files:**
- Create: `api/internal/task/knowledge_l2_tasks.py`
- Modify: `api/app/http/celery_app.py`
- Test: `api/test/internal/task/test_knowledge_l2_tasks.py`

- [ ] **Step 1: 写失败测试**

```python
"""L2 按需解析任务测试。"""
from pathlib import Path

CELERY_APP = (
    Path(__file__).resolve().parents[3] / "api/app/http/celery_app.py"
)
TASK_FILE = (
    Path(__file__).resolve().parents[3] / "api/internal/task/knowledge_l2_tasks.py"
)


class TestKnowledgeL2Tasks:
    def test_task_module_exists(self):
        assert TASK_FILE.is_file()

    def test_task_is_registered_in_celery(self):
        source = CELERY_APP.read_text(encoding="utf-8")
        assert "knowledge_l2_tasks" in source, "任务模块必须登记进 TASK_MODULES"

    def test_task_uses_shared_task_with_explicit_name(self):
        source = TASK_FILE.read_text(encoding="utf-8")
        assert "@shared_task" in source
        assert "internal.task.knowledge_l2_tasks." in source

    def test_task_is_retryable(self):
        source = TASK_FILE.read_text(encoding="utf-8")
        assert "max_retries" in source
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/task/test_knowledge_l2_tasks.py -q --no-header --no-cov`
Expected: FAIL —— `assert TASK_FILE.is_file()`

- [ ] **Step 3: 实现任务与注册**

```python
"""知识库 L2 深度解析任务（按需触发）。

L2 目标：让素材「能被精细修改」——视频逐场景视觉详述与精细时间轴。
L2 回填同一批 Segment 的 content/metadata，不新建 Segment（避免重复）。
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.knowledge_l2_tasks.build_document_l2_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def build_document_l2_task(self, document_id: str):
    """对指定文档执行 L2 深度解析（幂等：重复执行覆盖同一批 Segment）。"""
    from app.http.module import injector
    from internal.service.knowledge_indexing_service import KnowledgeIndexingService

    service = injector.get(KnowledgeIndexingService)
    try:
        return service.build_document_l2(document_id)
    except Exception as exc:
        logger.exception("L2 解析失败 document_id=%s", document_id)
        raise self.retry(exc=exc)
```

`celery_app.py` 三处同步（缺一不可，照 `external_data_source_tasks` 的写法）：
1. `TASK_MODULES` 加 `"internal.task.knowledge_l2_tasks"`
2. 显式 import 语句加一行
3. **不加 beat 条目**——L2 是按需触发（检索命中/用户显式要求），不做定时轮询

`KnowledgeIndexingService` 补 `build_document_l2(document_id)`：把 `parse_profile.tier2` 置 `{"status": "running"}`，执行 L2 增强后置 `{"status": "completed", ...}`，失败置 `{"status": "error", "error": ...}`；增强逻辑本身在首个版本可为「对视频逐帧补一次更详尽的视觉描述并更新 Segment.content」。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/task/test_knowledge_l2_tasks.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/task/knowledge_l2_tasks.py api/app/http/celery_app.py api/test/internal/task/test_knowledge_l2_tasks.py
git commit -m "feat(knowledge): add on-demand L2 parsing celery task"
```

---

### Task 14: 架构文档同步

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/prd/modules/06-file-storage.md`（若涉及帧留存存储）
- Modify: `docs/prd/modules/01-agent-tool-pool.md`（检索工具新参数）
- Modify: `docs/prd/knowledge-base-product-form-design.md`（P3 状态）
- Modify: `docs/prd/execution-roadmap.md`（P3 状态）
- Modify: `docs/prd/product-vision.md`（落地状态）

- [ ] **Step 1: 逐份更新**

| 文档 | 必须写清的内容 |
| --- | --- |
| `02-knowledge-base.md` | 检索过滤的四个参数及其 SQL 下推位置；标签服务的三个方法；L2 任务名与触发方式；`video_visual_embedding` 表结构、维度选择理由（4096→1536 因 pgvector 上限 2000）、HNSW 索引；视觉编码服务的入参格式与 OpenAI 不兼容的事实 |
| `01-agent-tool-pool.md` | `search_knowledge_base` 新增 `partition_id`/`media_types`/`tags`/`score_threshold` 四个可选入参 |
| `knowledge-base-product-form-design.md` | §3.3 表格里「视频 L1」改为含 ASR；§3.4 视觉向量从设计改为已落地并**修正「两个独立空间需融合排序」的表述**（实测同一语义空间，可直接文本召图）；§9.2 P3 行置为已完成 |
| `execution-roadmap.md` | P3 条目状态 |
| `product-vision.md` | 对应能力行的落地状态 |

- [ ] **Step 2: 提交**

```bash
git add docs/
git commit -m "docs(knowledge): record P3 retrieval filters, L2 parsing and visual vectors"
```

---

## 收尾验证

- [ ] **跑全量相关测试**

```bash
cd api
python -m pytest test/internal/service test/internal/core/tools test/internal/model test/internal/schema \
  test/internal/migration test/internal/task test/app/http -q --no-header --no-cov
```

- [ ] **确认迁移图仍为单 head**

```bash
cd api
python -m alembic -c internal/migration/alembic.ini heads
```

- [ ] **前端 i18n 与类型**

```bash
cd ui
npx vitest run src/i18n/__tests__/parity.spec.ts
npx vitest run src/views/admin
```

- [ ] **刷新知识图谱**

```bash
python -m graphify update .
```

---

## 风险与注意事项

1. **标签过滤必须 fail closed**：标签解析出空 `document_ids` 时，`_resolve_filter` 返回 `short_circuit=True`，调用方直接返回空。**绝不能**因标签无命中就退化成"不过滤"——那会在用户以为已按标签收窄范围时越权召回全库。
2. **`consume_quota` 语义**：帧留存会产生额外 `UploadFile`，**不计入用户存储配额**（属解析中间产物，随素材删除）。如需计入，需在 `_persist_frame` 后调 `add_usage` 并在 `purge_knowledge_document` 配对释放——本计划**不计入**，文档需明确。
3. **视觉向量检索在 Python 侧算余弦**：库内帧数量可控（每视频 3 帧）。若未来单库帧数过万，需改为 SQL 侧 pgvector 查询（表已建 HNSW 索引，可直接下推）。
4. **`IN :list` 绑定**：SQLAlchemy `text()` 的 `IN :param` 需 `bindparam(expanding=True)` 才可靠展开。若测试暴露问题，统一改用 PostgreSQL 的 `= ANY(:param)`（传 list）。
5. **模型密钥不在代码**：seed 迁移**不得**写 `model_key_config`。部署后需管理员在 `/admin/models` 为 SiliconFlow 添加 key（若该 provider 的 key 已存在则复用）。
6. **`visual_embedding` 不进 `model_class_registry`**：该模型入参与 `OpenAIEmbeddings` 不兼容，注册了会导致静默只编码文本。
