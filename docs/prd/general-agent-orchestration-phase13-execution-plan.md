# Phase 13：外部数据源连接与同步 执行计划

> **目标：** 将用户资料内容库从手动上传扩展为连接用户授权的业务知识源和外部协作系统，同步后的文档可被知识检索工具召回。

**架构：** 以 `ExternalDataSource` 模型为核心，实现飞书/本地文件夹试点连接器，通过 OAuth 授权连接后手动同步，同步走 `build_documents` 切片/向量化流水线生成 `KnowledgeSegment`，接入 `RetrievalService` 使外部文档可被 agent 检索。

**技术栈：** Python 3.11 / Flask / SQLAlchemy / LangChain / Vue 3 / Arco Design Vue

---

## 1. 现状基线

### 已有基础设施（复用）

| 模块 | 状态 | 文件 |
|------|------|------|
| ExternalDataSource 模型 + migration | 已实现 | `api/internal/model/knowledge.py:144` |
| ExternalSourceType/AuthorizationStatus/SyncStatus 枚举 | 已实现 | `api/internal/entity/knowledge_entity.py` |
| ExternalDataSourceService（含 manual_sync） | 部分实现 | `api/internal/service/external_data_source_service.py` |
| ExternalDataSourceHandler（create/sync） | 已实现 | `api/internal/handler/external_data_source_handler.py` |
| KnowledgeBase/KnowledgeDocument/KnowledgeSegment 模型 | 已实现 | `api/internal/model/knowledge.py` |
| MockExternalConnector | 已实现 | `api/internal/service/external_data_source_service.py` |
| 文件上传/处理流水线（build_documents） | 已实现 | `api/internal/service/document_service.py` |
| RetrievalService + 向量检索 | 已实现 | `api/internal/service/retrieval_service.py` |

### 关键未闭环点（Phase 13 核心任务）

1. **last_error 字段缺失**：`ExternalDataSource` 模型没有 `last_error` 字段，但 service 第 67/71/89 行引用了它，运行时会 AttributeError
2. **无真实连接器**：只有 `MockExternalConnector`，无飞书/Notion/GitHub/Drive 连接器
3. **无 OAuth 授权流程**：`authorization_status` 字段存在但无授权回调逻辑
4. **同步未走切片/向量化**：`manual_sync` 直接把 `KnowledgeDocument.status` 写成 "completed"，跳过了 embedding 流程
5. **新版知识库未接入检索**：检索工具仅接入旧版 Dataset，新版 KnowledgeBase 体系未接入，外部同步文档无法被检索
6. **schema 重复定义**：`external_data_source_schema.py` 和 `knowledge_schema.py` 各定义了一份 `CreateExternalDataSourceReq`，字段不一致

---

## 2. 文件结构

### 需要修改的文件

| 文件 | 职责 | 改动 |
|------|------|------|
| `api/internal/model/knowledge.py` | ExternalDataSource 模型 | 新增 `last_error` 字段 |
| `api/internal/service/external_data_source_service.py` | 同步服务 | 接入真实连接器 + 切片流水线 |
| `api/internal/handler/external_data_source_handler.py` | handler | 新增 list/get/delete/authorize 接口 |
| `api/internal/schema/external_data_source_schema.py` | schema | 统一 schema，新增响应 schema |
| `api/internal/router/router.py` | 路由 | 注册新路由 |
| `api/internal/service/retrieval_service.py` | 检索服务 | 接入新版 KnowledgeBase 体系 |

### 需要新建的文件

| 文件 | 职责 |
|------|------|
| `api/internal/migration/versions/d1e2f3a4b5d5_add_last_error_to_external_data_source.py` | 新增 last_error 列 |
| `api/internal/service/connectors/base_connector.py` | 连接器基类 |
| `api/internal/service/connectors/lark_connector.py` | 飞书连接器 |
| `api/internal/service/connectors/local_folder_connector.py` | 本地文件夹连接器 |
| `api/internal/service/external_data_source_connector_factory.py` | 连接器工厂 |
| `api/test/internal/service/test_external_data_source_connector.py` | 连接器测试 |
| `api/test/internal/handler/test_external_data_source_crud.py` | CRUD 接口测试 |
| `api/test/internal/service/test_external_data_source_sync_pipeline.py` | 同步流水线测试 |

---

## 3. 任务分解

### 任务 0：基线确认

- [ ] 跑后端全量测试 `docker compose exec llmops-api pytest -q --no-cov`，确认 2189 passed
- [ ] 跑前端全量测试 `npm run test:unit`，确认 368 passed
- [ ] 确认 migration head 为 `d1e2f3a4b5d4`

### 任务 1：ExternalDataSource 模型补 last_error 字段

**Files:**
- Create: `api/internal/migration/versions/d1e2f3a4b5d5_add_last_error_to_external_data_source.py`
- Modify: `api/internal/model/knowledge.py` (ExternalDataSource 模型)

- [ ] **Step 1: 创建 migration** - revision `d1e2f3a4b5d5`，down_revision `d1e2f3a4b5d4`

```python
def upgrade():
    op.add_column('external_data_source', sa.Column('last_error', sa.Text(), nullable=False, server_default=text("''::text")))
def downgrade():
    op.drop_column('external_data_source', 'last_error')
```

- [ ] **Step 2: 更新模型** - 新增 `last_error = Column(Text, nullable=False, server_default=text("''::text"))`

- [ ] **Step 3: 跑 migration** - `flask db upgrade --directory internal/migration`

- [ ] **Step 4: 跑现有 external_data_source 测试确认通过**

### 任务 2：连接器基类 + 工厂

**Files:**
- Create: `api/internal/service/connectors/base_connector.py`
- Create: `api/internal/service/connectors/__init__.py`
- Create: `api/internal/service/external_data_source_connector_factory.py`
- Test: `api/test/internal/service/test_external_data_source_connector.py`

- [ ] **Step 1: 写失败测试** - 验证工厂能根据 source_type 返回正确的连接器

```python
def test_factory_should_return_lark_connector_for_lark_source():
    factory = ConnectorFactory()
    connector = factory.get_connector(ExternalSourceType.LARK.value)
    assert isinstance(connector, LarkConnector)

def test_factory_should_return_local_folder_connector_for_drive_source():
    factory = ConnectorFactory()
    connector = factory.get_connector(ExternalSourceType.DRIVE.value)
    assert isinstance(connector, LocalFolderConnector)
```

- [ ] **Step 2: 实现基类**

```python
from abc import ABC, abstractmethod
from internal.model.knowledge import ExternalDataSource

class BaseConnector(ABC):
    @abstractmethod
    def authorize(self, data_source: ExternalDataSource, auth_config: dict) -> str:
        """授权连接，返回 authorization_status"""
        ...

    @abstractmethod
    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        """同步文档，返回 [{title, content, source_url}] 列表"""
        ...
```

- [ ] **Step 3: 实现工厂** - 根据 source_type 返回对应连接器

- [ ] **Step 4: 跑测试确认通过**

### 任务 3：飞书连接器 + 本地文件夹连接器

**Files:**
- Create: `api/internal/service/connectors/lark_connector.py`
- Create: `api/internal/service/connectors/local_folder_connector.py`

- [ ] **Step 1: 实现本地文件夹连接器** - 读取指定目录下的 .md/.txt 文件

```python
class LocalFolderConnector(BaseConnector):
    def authorize(self, data_source, auth_config):
        folder_path = auth_config.get("folder_path", "")
        if not os.path.isdir(folder_path):
            raise ValueError("文件夹路径无效")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(self, data_source):
        folder_path = data_source.config.get("folder_path", "")
        documents = []
        for filename in os.listdir(folder_path):
            if filename.endswith((".md", ".txt")):
                with open(os.path.join(folder_path, filename), "r") as f:
                    documents.append({"title": filename, "content": f.read(), "source_url": ""})
        return documents
```

- [ ] **Step 2: 实现飞书连接器（Mock 版本）** - 第一阶段先返回配置中预设的文档列表，后续接入真实 API

- [ ] **Step 3: 写测试验证连接器行为**

### 任务 4：同步走切片/向量化流水线

**Files:**
- Modify: `api/internal/service/external_data_source_service.py` (manual_sync 方法)

- [ ] **Step 1: 写失败测试** - 验证同步后 KnowledgeDocument 的 status 不是直接 completed，而是经过切片处理

- [ ] **Step 2: 修改 manual_sync** - 同步后对每个文档调用切片服务，生成 KnowledgeSegment

```python
def manual_sync(self, data_source_id: UUID, account: Account) -> dict:
    data_source = self._get_owned_data_source(data_source_id, account)
    if data_source.authorization_status != ExternalAuthorizationStatus.GRANTED.value:
        raise ValueError("数据源未授权")

    connector = self.connector_factory.get_connector(data_source.source_type)
    documents = connector.sync(data_source)

    for doc in documents:
        knowledge_doc = KnowledgeDocument(
            knowledge_base_id=data_source.knowledge_base_id,
            title=doc["title"],
            content=doc["content"],
            source_url=doc.get("source_url", ""),
            status="processing",
        )
        self.db.session.add(knowledge_doc)
        self.db.session.flush()

        segments = self._split_document(doc["content"])
        for idx, segment_text in enumerate(segments):
            segment = KnowledgeSegment(
                knowledge_document_id=knowledge_doc.id,
                content=segment_text,
                position=idx,
                hash=hashlib.sha256(segment_text.encode()).hexdigest(),
            )
            self.db.session.add(segment)

        knowledge_doc.status = "completed"

    data_source.sync_status = ExternalSyncStatus.SUCCESS.value
    data_source.last_synced_at = datetime.now(UTC)
    data_source.last_error = ""
    self.db.session.commit()
    return {"synced_count": len(documents)}
```

- [ ] **Step 3: 实现 _split_document** - 简单按段落切片（每段约 500 字）

- [ ] **Step 4: 跑测试确认通过**

### 任务 5：CRUD + 授权接口完善

**Files:**
- Modify: `api/internal/handler/external_data_source_handler.py`
- Modify: `api/internal/schema/external_data_source_schema.py`
- Modify: `api/internal/router/router.py`
- Test: `api/test/internal/handler/test_external_data_source_crud.py`

- [ ] **Step 1: 写失败测试** - 验证 list/get/delete/authorize 接口

- [ ] **Step 2: 实现 schema** - 统一 CreateExternalDataSourceReq，新增 ExternalDataSourceResp 和 ListResp

- [ ] **Step 3: 实现 handler** - list（按 owner 过滤）、get、delete、authorize（调用连接器的 authorize 方法）

- [ ] **Step 4: 注册路由** - GET /external-data-sources, GET /external-data-sources/<id>, DELETE /external-data-sources/<id>, POST /external-data-sources/<id>/authorize

- [ ] **Step 5: 跑测试确认通过**

### 任务 6：新版知识库接入检索

**Files:**
- Modify: `api/internal/service/retrieval_service.py`

- [ ] **Step 1: 写失败测试** - 验证检索能召回 KnowledgeSegment 的内容

- [ ] **Step 2: 在 RetrievalService 新增检索 KnowledgeBase 的方法** - 根据 knowledge_base_id 查询 KnowledgeSegment，做向量相似度检索

- [ ] **Step 3: 接入知识检索工具** - 让 agent 的 dataset_retrieval 工具能检索新版 KnowledgeBase

- [ ] **Step 4: 跑测试确认通过**

### 任务 7：前端外部数据源管理页面

**Files:**
- Create: `ui/src/views/external-data-sources/ListView.vue`
- Modify: `ui/src/router/index.ts`
- Modify: `ui/src/views/layouts/components/LayoutSidebar.vue`
- Create: `ui/src/services/external-data-source.ts`
- Modify: `ui/src/i18n/messages/zh-CN.ts` + `en-US.ts`

- [ ] **Step 1: 新建 API service** - list/get/create/delete/sync/authorize

- [ ] **Step 2: 新建列表页面** - 展示数据源列表（名称、类型、授权状态、同步状态、最后同步时间、操作）

- [ ] **Step 3: 注册路由** - `/external-data-sources`

- [ ] **Step 4: 侧边栏新增入口**

- [ ] **Step 5: i18n 完整**

- [ ] **Step 6: 跑前端测试确认无回归**

### 任务 8：最终全量测试与文档同步

- [ ] 跑后端全量测试
- [ ] 跑前端全量测试 + type-check + lint
- [ ] 跑 migration 验证
- [ ] 更新 PRD 当前状态为"Phase 1-13 已提交"
- [ ] 更新 Phase 13 执行计划完成状态
- [ ] git commit

---

## 4. 验收标准（对齐 PRD 16.14）

1. 用户必须授权后才能连接外部数据源 ✅ authorize 接口 + authorization_status 校验
2. 同步数据按用户、团队、项目或租户作用域隔离 ✅ owner_account_id + knowledge_base_id 隔离
3. 手动同步结果可追踪状态和错误原因 ✅ sync_status + last_error + last_synced_at
4. 同步后的文本和结构化资料可被动态知识检索工具召回 ✅ KnowledgeSegment 接入检索
5. 外部数据源不会污染系统级知识库 ✅ 外部文档写入用户级 KnowledgeBase，不写入系统级

---

## 5. 推荐执行顺序

1. 任务 0：基线确认
2. 任务 1：last_error 字段 + migration（前置，修复 AttributeError）
3. 任务 2：连接器基类 + 工厂
4. 任务 3：飞书 + 本地文件夹连接器
5. 任务 4：同步走切片流水线（核心）
6. 任务 5：CRUD + 授权接口完善
7. 任务 6：新版知识库接入检索
8. 任务 7：前端管理页面
9. 任务 8：最终全量测试与文档同步

---

## 6. 风险与约束

| 风险 | 应对 |
|------|------|
| 飞书 API 需要 app_id/app_secret | 第一阶段用 Mock 实现，配置中预设文档列表 |
| 向量检索需要 embedding | 复用现有 EmbeddingsService（CacheBackedEmbeddings + RedisStore） |
| 切片质量影响检索效果 | 第一阶段用简单段落切片，后续可接入 ProcessRule 配置 |
| 两套知识库体系并存 | 检索服务同时支持旧版 Dataset 和新版 KnowledgeBase |
