# 外部数据源：前端整合与后端安全加固设计

> 更新日期：2026-09-12
> 定位：设计规格（已评审确认）。与「我的应用真实接口接线」设计（`2026-09-12-my-apps-real-data-design.md`）相互独立。
> 背景：`product-vision.md` §三-13 / §4.4 判定「知识库『外部数据源』弹窗全 mock，真实页面与接口已存在未打通」。本次深挖后修正该判定：真实页面**本身也不可用**，用户触点（弹窗）是 mock。本设计统一为单一真实入口，并补齐后端安全缺口。

## 0. 目标

1. 让用户在知识库页点击「外部数据源」打开的弹窗使用真实接口（列表/创建/授权/同步/解绑）。
2. 消除「真实页面 vs mock 弹窗」的重复实现。
3. 修复后端安全缺口：凭证明文落库、凭证明文经 API 回传、授权不落库。
4. 补齐数据一致性：删除数据源时级联清理其同步产物。
5. 增加定时自动同步；移除名不副实的 `enterprise_knowledge`。

**不在本设计范围**：数据源文档的增量同步（当前为全量重拉）、权限点细化（保持账号归属校验）、对象存储层变更。

## 1. 已确认决策

| 项 | 决策 |
| --- | --- |
| 入口整合 | **删除**独立页面 `external-data-sources/ListView.vue` 及其路由；**保留**知识库页内嵌弹窗 `ExternalDataSourceModal.vue` 作为唯一入口，并接线为真实接口 |
| `enterprise_knowledge` | **移除**（后端枚举 + 连接器工厂 + 前端选项/表单/i18n 键） |
| 自动同步 | **新增** Celery 定时任务，扫描已授权数据源自动同步 |
| 授权流程 | 复用「创建时提交凭证」；弹窗「去授权」调真实授权接口（`auth_config` 允许为空，凭证取自已落库的 config） |
| 凭证加密 | 复用 `tool_credential_encryptor` 的 Fernet 方案，对 `config` 中**约定敏感 key** 加密 |
| 冗余工具 | **删除** `external_data_retrieval_tool.py`（已核实其能力被既有知识库检索工具覆盖） |
| DI 显式绑定 | **不做**（实测 `knowledge_vector_service` 已正常注入；知识库系服务均未显式绑定，单独加反而破坏一致性） |

## 2. 现状（代码验证）

| 层 | 现状 | 证据 |
| --- | --- | --- |
| 模型/枚举 | ✅ `external_data_source` 表；5 种 source_type、4 种授权状态、4 种同步状态 | `api/internal/model/knowledge.py`；`api/internal/entity/knowledge_entity.py` |
| 路由 | ✅ 6 个 CRUD 路由已注册 | `api/app/http/knowledge_mcp_routes.py`；注册于 `asgi_app.py` |
| 连接器 | ✅ lark / notion / github **真实调 API**；drive 为本地文件夹（语义正确） | `api/internal/service/connectors/*.py`；`ConnectorFactory` |
| 同步入库 | ✅ 写 `KnowledgeDocument` + `KnowledgeSegment` + pgvector | `external_data_source_service.manual_sync` |
| 独立真实页面 | ❌ **本身不可用**（见 §2.1） | `ui/src/views/external-data-sources/ListView.vue` |
| 用户触点弹窗 | ❌ 全 mock | `ui/src/views/space/datasets/components/ExternalDataSourceModal.vue` |

### 2.1 需修复的既有缺陷（按严重度）

1. 🔴 **凭证明文经 API 回传**：`ExternalDataSourceResp.config = fields.Dict()` 把 `config` 原样返回前端；而 `config` 内含 `app_secret` / `integration_token` 等明文密钥 → 查看列表即泄漏到浏览器。
2. 🔴 **授权不落库**：`authorize_data_source` 仅改 `authorization_status`，**不把 `auth_config` 写回 `config`** → 「先创建（无凭证）再授权」的流程同步时凭证为空。
3. 🔴 **凭证明文落库**：`config` JSONB 直接存明文密钥，未复用既有 Fernet 加密能力。
4. 🟠 **列表响应对不上**：后端返回 `{ items, total }`（`ExternalDataSourceListResp`），而独立页面按数组消费 `res.data || []` → 该页从未真正跑通。
5. 🟠 **级联清理缺失**：`physical_delete_external_data_source` / `purge_external_data_source` 只删主记录，遗留同步产生的 `knowledge_document` / `knowledge_segment` / 向量孤儿数据。
6. 🟡 **`enterprise_knowledge` 名不副实**：复用本地文件夹连接器。
7. 🟡 **无定时同步**：仅 `manual_sync` HTTP 触发。
8. 🟡 **冗余工具**：`external_data_retrieval_tool.py` 无任何调用点。

### 2.2 关于「同步的文档能否被 Agent 检索到」的核实结论

**能。** 创建数据源时若未指定知识库，会经 `KnowledgeBaseService.create_user_content_base` 自动建一个 `knowledge_scope='user_content'`、归属该账号、`enabled=true` 的知识库；而首页助手 `_build_assistant_runtime_tools` 已挂载覆盖「账号自己的 + 系统的」全部启用知识库的检索工具。因此同步文档天然可被检索，`external_data_retrieval_tool.py` 属重复实现，删除不影响能力。

## 3. 架构与数据流

```text
知识库页「外部数据源」按钮 → ExternalDataSourceModal（唯一入口）
  ├─ 列表   GET    /external-data-sources          → { items, total }（config 已脱敏）
  ├─ 创建   POST   /external-data-sources          → 自动建/复用 user_content 知识库
  ├─ 授权   POST   /external-data-sources/<id>/authorize
  ├─ 同步   POST   /external-data-sources/<id>/sync
  └─ 解绑   DELETE /external-data-sources/<id>     → 进回收站（快照 + 级联清理同步产物）

Celery beat（每 6 小时）
  └─ run_external_data_source_auto_sync
       扫描 authorization_status=granted 且 sync_status≠syncing
       → 逐个调用 ExternalDataSourceService.manual_sync（复用同一逻辑）

凭证生命周期
  创建/授权：明文 config → encrypt_config()（敏感 key 加密）→ 落库 JSONB
  连接器读取：decrypt_config() → 传给 connector.sync(config=...) 调外部 API
  API 返回：mask_config() → 列表/详情响应（密钥仅回显掩码）
```

## 4. 后端改动

### 4.1 新增 `api/internal/service/external_data_source_credentials.py`

凭证处理集中一处，避免散落：

```python
SENSITIVE_KEYS = frozenset({
    "app_secret", "integration_token", "personal_access_token",
    "api_key", "token", "client_secret",
})

def encrypt_config(config: dict) -> dict:
    """对 SENSITIVE_KEYS 命中的值做 Fernet 加密；已加密（gAAAAA 前缀）跳过（幂等）。"""

def decrypt_config(config: dict) -> dict:
    """解密敏感 key，供连接器调用外部 API 使用；非密文/非敏感 key 原样返回。"""

def mask_config(config: dict) -> dict:
    """脱敏输出：敏感 key 一律返回掩码（复用 _mask_value），不因是否加密而分歧。"""
```

实现要点：
- 复用 `tool_credential_encryptor` 的 `_encrypt_value` / `_decrypt_value` / `_mask_value` / `is_encrypted`。
- 非敏感 key（如 `folder_path` / `owner` / `repo` / `folder_token`）保持明文，保证可读与可查询。
- 解密失败时对**单个 key** 降级为 `""` 并记 warning，不抛异常中断整个同步。

### 4.2 修改 `api/internal/service/external_data_source_service.py`

| 方法 | 改动 |
| --- | --- |
| `create_connection` | `config` 落库前经 `encrypt_config` |
| `authorize_data_source` | ①`auth_config` merge 进 `data_source.config` 并经 `encrypt_config` 落库；②授权判定传 `decrypt_config` 给连接器；③显式 `commit` |
| `manual_sync` | 取 `decrypt_config(data_source.config)`，传给 `connector.sync(data_source, config=decrypted)` |
| 新增 `auto_sync_all()` | 供定时任务调用：扫描候选数据源，逐个复用 `manual_sync` 逻辑，返回统计；单条失败不影响其他 |

### 4.3 修改连接器（签名向后兼容）

**关键前提**：加密后 `data_source.config` 中敏感 key 为密文。而现有连接器在 `authorize` 与 `sync` 中都会回退读取 `data_source.config`（例如 `github_connector` 的 `auth_config.get("token") or data_source.config.get("token")`、`sync` 内 `config = data_source.config`）。因此**两个入口都必须拿到解密后的配置**，否则授权与同步都会因读到密文而失败。

`BaseConnector`：`authorize` 与 `sync` 均增加可选 `config` 形参。

```python
@abstractmethod
def authorize(self, data_source, auth_config, config: dict | None = None) -> str: ...

@abstractmethod
def sync(self, data_source, config: dict | None = None) -> list[dict[str, str]]:
    """config 为空时回退读取 data_source.config（保持既有调用/测试兼容）。"""
```

4 个连接器（`lark` / `notion` / `github` / `local_folder`）统一改造：

- 入口处 `resolved = config if config is not None else (data_source.config or {})`。
- 所有对 `data_source.config` 的读取改为读 `resolved`（含 `authorize` 内的回退取值）。
- 传入的 `auth_config` 优先级仍高于 `resolved`（保持现有语义）。

服务层调用点相应改为传入 `decrypt_config(data_source.config)`（见 §4.2）。

### 4.4 修改 `api/internal/service/external_data_source_connector_factory.py`

移除 `ExternalSourceType.ENTERPRISE_KNOWLEDGE` 注册项。

### 4.5 修改 `api/internal/entity/knowledge_entity.py`

从 `ExternalSourceType` 移除 `ENTERPRISE_KNOWLEDGE = "enterprise_knowledge"`。

> 兼容性：库中若存在该类型的历史数据，连接器工厂将抛「不支持的数据源类型」。迁移中一并清理（见 §5）。

### 4.6 修改 `api/internal/schema/external_data_source_schema.py`

`ExternalDataSourceResp` 的 `config` 改为**输出掩码**。因 marshmallow dump 不会自动转换，采用两种方式之一（实施时统一选 ①）：
1. 在路由序列化前把 ORM 对象替换为已 `mask_config` 的纯 dict（推荐，schema 不变）。
2. 自定义 `fields.Method` 在序列化时 `mask_config`。

**不返回的字段**：`owner_account_id` / `owner_admin_user_id`（内部标识，前端不需要）。

### 4.7 修改 `api/internal/service/recycle_bin_handlers.py`

新增共用清理函数并在 `external_data_source` 的删除路径调用：

```python
def _delete_documents_by_source(source_type: str, source_id: str) -> int:
    """按 source_type + source_id 清理同步产物（文档/分段/向量/上传文件）。
    复用索引 knowledge_document_source_idx；向量清理经 injector 取 KnowledgeVectorService。"""
```

- `physical_delete_external_data_source`：先 `_delete_documents_by_source(...)` 再删主记录。
- `restore_external_data_source`：**不恢复**同步产物（文档可由重新同步再生成），保持只重建主记录；在文档中显式说明该语义。
- `purge_external_data_source`：保持 no-op（物理删除时已清）。

> 注意既有隐患：`physical_delete_knowledge_document` 内 `KnowledgeVectorService()` 无参构造会失败（`@dataclass` 有必填字段）并被 `except` 吞掉，导致向量实为未清理。新的 `_delete_documents_by_source` 必须**经 `injector` 获取服务**，避免重蹈覆辙；不改动既有函数以免扩大范围（作为已知问题记录）。

### 4.8 新增 `api/internal/task/external_data_source_tasks.py`

照 `recycle_bin_tasks.py` 范式：

```python
@shared_task(name="internal.task.external_data_source_tasks.run_external_data_source_auto_sync",
             bind=True, max_retries=2, default_retry_delay=300)
def run_external_data_source_auto_sync(self):
    from app.http.module import injector
    from internal.service.external_data_source_service import ExternalDataSourceService
    service = injector.get(ExternalDataSourceService)
    result = service.auto_sync_all()
    logger.info("外部数据源自动同步完成: %s", result)
    return result
```

注册：
- `celery_app.py` 的 `TASK_MODULES` 追加 `"internal.task.external_data_source_tasks"`。
- beat_schedule 追加 `external-data-source-auto-sync` → `crontab(hour="*/6", minute=15)`。

### 4.9 删除 `api/internal/service/external_data_retrieval_tool.py`

及其单测 `api/test/internal/service/test_external_data_retrieval_tool.py`（该工具无调用点，能力已被既有知识库检索覆盖）。

### 4.10 清理死代码 `api/internal/schema/knowledge_schema.py`

全仓检索确认该文件**无任何 import 引用**（`admin_routes_2.py` 引用的是同名的 `admin_system_knowledge_schema`），且其中含一份**重复且更危险**的 `ExternalDataSourceResp`（同样把 `config` 原样暴露）。为避免与 §4.6 的正确实现混淆、并防止后续被误用，**删除该文件**。

> 删除前需再次全仓确认无动态字符串引用（如 `importlib`/`dynamic_import`）。若发现引用，则改为仅删除其中的 `ExternalDataSource*/KnowledgeBase*` 类。

## 5. 数据迁移

新增 1 个迁移，`down_revision = "l6a7b8c9d0e1"`（当前 head），照 `d5e6f7a8b9c2_encrypt_historical_tool_credentials.py` 范式：

1. **加密历史 config**：遍历 `external_data_source.config` JSONB，对 `SENSITIVE_KEYS` 的明文值加密回填；`gAAAAA` 前缀幂等跳过；只对发生变化的行为执行 `UPDATE`。
2. **清理 enterprise_knowledge 历史数据**：对该类型数据源走与业务一致的删除（进回收站）或直接标记为 `revoked`——**实施时取"直接删除 + 级联清理同步产物"**，以与 §4.5 的移除决策一致；`downgrade` 不可逆。
3. 密钥自检：`_verify_fernet_roundtrip` 加解密样本；`MODEL_KEY_ENCRYPTION_KEY` 未配置则 `RuntimeError` 中止。
4. 迁移脚本**不 import** 运行时加密模块（其 Fernet 为模块级单例，会触发临时密钥），自带 `_load_fernet` 独立实现。
5. `downgrade` 抛 `NotImplementedError` 并提示走备份恢复。

## 6. 前端改动

### 6.1 删除

- `ui/src/views/external-data-sources/ListView.vue`（整个目录）
- `ui/src/router/index.ts` 中 `external-data-sources` 路由注册（name `user-external-data-sources-list`）

### 6.2 `ui/src/services/external-data-source.ts`

- 修正列表返回类型：`getExternalDataSources` 的 data 类型由 `Array<ExternalDataSource>` 改为 `{ items: ExternalDataSource[]; total: number }`。
- `authorizeExternalDataSource` 的 `auth_config` 允许空对象（保持现状，语义明确化）。

### 6.3 `ui/src/views/space/datasets/components/ExternalDataSourceModal.vue`

| 动作 | 说明 |
| --- | --- |
| 删除 mock | 移除 `MOCK_SOURCES`、`MockSource`、`setTimeout` 假流程 |
| 接真实 service | `loadDataSources`→`getExternalDataSources()` 取 `res.data.items`；`handleCreate`→`createExternalDataSource()`；`handleSync`→`syncExternalDataSource()`；`confirmUnbind`→`deleteExternalDataSource()`；「去授权」→`authorizeExternalDataSource(id, {})` |
| 类型对齐 | 使用 service 导出的 `ExternalDataSource` |
| 状态展示 | 保留授权/同步状态徽标；`last_error` 非空时展示失败原因（新增一行提示） |
| 错误处理 | 统一 `getErrorMessage`，替换假成功提示 |
| 移除企业知识库 | 从 `sourceTypeOptions`、`credentialFields`、`typeMeta`、模板图标分支中删除 `enterprise_knowledge` |
| i18n 化 | 硬编码中文（`已绑定数据源`、`N 个已绑定`、`去授权`、`同步于`、`需要补充授权后开始同步`、`确认解绑…`、`绑定新数据源`、`数据仅用于…`、`凭证仅保存在…`、`绑定中…`、`绑定数据源`、`取消`、`确认解绑`、`加载中…`、`关闭`、`例如：…`、`选填`/`*`）迁入 `externalDataSource.*`（zh/en 双侧同步） |

### 6.4 `ui/src/i18n/messages/{zh-CN,en-US}/externalDataSource.ts`

- 追加 §6.3 所需键（两侧同名同结构）。
- **删除** `enterpriseKnowledge` 键（两侧同步）。

## 7. 测试

| 层 | 用例 |
| --- | --- |
| 凭证 | `encrypt_config`/`decrypt_config` 往返；幂等（二次加密不变）；非敏感 key 保持明文；解密失败单 key 降级 |
| 掩码 | `mask_config` 对敏感 key 输出掩码；**断言响应 JSON 不含任何明文密钥** |
| 授权 | `authorize_data_source` 把 `auth_config` 落库（加密后），授权后 `manual_sync` 能取到凭证 |
| 级联 | 删除数据源后，其 `knowledge_document`/`knowledge_segment` 按 source 清理干净；重建同名数据源不受残留影响 |
| 定时任务 | `auto_sync_all` 只挑 `granted` 且非 `syncing` 的数据源；单条失败不影响其他并计入统计 |
| 连接器 | 4 个连接器签名变更后既有单测仍绿；新增「传入显式 config 优先于 data_source.config」用例 |
| 迁移 | 升级后历史 config 敏感 key 已加密且可解密；`enterprise_knowledge` 数据已清理 |
| 前端 | 弹窗以 mock service 渲染真实列表 / 创建 / 授权 / 同步 / 解绑；错误路径提示 |
| i18n | `npx vitest run src/i18n/__tests__/parity.spec.ts` 通过 |

## 8. 验收标准

1. 知识库页打开弹窗，展示当前账号真实已绑定数据源；重新打开数据不变（不再刷新即丢）。
2. 创建数据源后立刻出现在列表；填写的凭证不再以明文出现在任何 API 响应中。
3. 未授权数据源点「去授权」后状态变 `granted`；随后点「同步」能真正拉到外部内容并入库。
4. 解绑后列表移除；其同步产生的文档/分段/向量同步清理，无孤儿数据。
5. 定时任务按周期自动同步已授权数据源；单个失败写 `last_error` 且不阻塞其他。
6. 数据源类型中不再出现「企业知识库」；无 `external_data_retrieval_tool` 残留引用。
7. 无硬编码中英文展示文案；i18n parity 通过；前端与后端测试全绿。

## 9. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 加密迁移误伤：历史非密文被重复加密 | `gAAAAA` 前缀幂等跳过；迁移前 `_verify_fernet_roundtrip` 自检 |
| 密钥变更导致历史密文不可解 | 解密失败单 key 降级为空并记 warning，不中断同步；文档提示需保持 `MODEL_KEY_ENCRYPTION_KEY` 稳定 |
| 移除 `enterprise_knowledge` 影响存量数据 | 迁移中先清理该类数据；前端不再可选 |
| 连接器签名变更破坏既有测试 | 使用可选参数（`config=None`）保持向后兼容 |
| 级联清理误删他源数据 | 严格按 `source_type + source_id` 双条件过滤，仅清理该数据源自身产物 |
| 独立页面删除后用户无入口 | 弹窗仍由知识库页按钮打开，入口不变（本就无侧边栏入口） |

回滚：加密迁移 `downgrade` 不可逆（需备份恢复）；代码侧改动集中于新增文件 + 明确的改造点，可分层 revert（前端整合 / 后端安全 / 定时任务 三组）。
