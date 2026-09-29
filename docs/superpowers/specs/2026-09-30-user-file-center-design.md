# 用户侧统一文件中心（虚拟目录树）设计（spec）

- 状态：待评审（2026-09-30），评审通过后进入实施计划
- 触发：系统当前**没有面向用户的文件管理面**——回收站、知识库/素材中心各自成面，但「用户上传文件 / Agent 产物 / 渲染成品 / 平台云端存储」没有统一的目录化管理入口；用户只能靠对话内消息或 admin 存储迁移页间接看到文件。此外本机文件（桌面端）无目录浏览。
- 目标一句话：**在既有存储抽象（`RuntimeStorageProxy`）与回收站（`RecycleBinService`）之上，为「我的上传文件 / Agent 产物 / 渲染成品 / 平台云端存储」建一个用户可见的虚拟目录树管理面，并让 Agent 通过 builtin 工具在同一命名空间上操作。**

---

## 1. 现状（实测）

| 面 | 现状 |
|---|---|
| 存储能力层 | `RuntimeStorageProxy`（local/cos/oss 统一切换 + 配额守卫）是**轮胎**，被上传/知识库/产物/冷存储等多处复用（`06-file-storage.md`） |
| 回收站 | `RecycleBinService` + 用户/管理员路由 + UI + Celery 到期销毁是**轮胎**；资源类型含 `upload_file` 等 |
| 知识库/素材中心 | 文档 CRUD/分片上传/预览齐全；`KnowledgeDocument.upload_file_id` 指向底层文件 |
| 渲染成品 | `KnowledgeBase.created_from=render_output`（成品库），经素材中心获得管理面 |
| admin 存储文件面 | `GET /admin/storage/migration/files`（列表+来源标注+去重+kkfileview 预览）、`POST /admin/storage/files/delete`（→回收站） |
| 生成图片 | `image_persistence.persist_remote_image` 走 `upload_bytes_without_record`，**连 `UploadFile` 记录都不建** → 无列表/删除/配额 |
| Agent 文本产物 | `deep_thinking_agent._upload_plain_text_artifact` 有 `UploadFile` 记录（`folder=artifacts`），**无用户列表接口** |
| 沙箱产物 | 云侧无统一产物列表 |
| 本机文件 | `os_file_task` 只有 `read`/`search`/`patch`（**无目录枚举**）；无文件管理 UI；无本机↔平台互传 |

**结论**：存储层与回收站是轮胎；**「面向用户的文件管理面」是空白**，且产物收录割裂（成品→知识库、图片→无记录、文本→有记录无列表、沙箱→无云侧面）。

---

## 2. 目标 / 非目标

**目标**
1. 用户侧统一「文件中心」：一棵**虚拟目录树**，聚合四类来源（`upload` 用户上传 / `artifact` Agent 产物 / `render_output` 渲染成品 / `platform` 平台云端存储）。
2. **复用而非另起**：物理对象仍归 `RuntimeStorageProxy`；删除/恢复仍走 `RecycleBinService`；配额仍走 `StorageQuotaService`。
3. **可被 Agent 使用**：新增 builtin provider `file_center`，Agent 在**与用户同一命名空间**上操作（list/mkdir/move/rename/delete/read/save_artifact），共用权限/配额/回收站。
4. 收编「无记录产物」写入点，使其进入文件中心且计配额。

**非目标**
- 不引入第三方文件管理器（Nextcloud/Alist/Filebrowser 等自带用户/存储体系，会绕过 `storage_config`/配额/回收站 → 平行机制）。
- 不改 `UploadFile` 表结构（知识库等既有引用不动）。
- 不把知识库素材中心（datasets）并入文件中心——两者分工：**文件中心管「文件」，素材中心管「被解析的知识素材」**。
- 阶段 1 不做本机目录浏览与外部云盘（分阶段，见 §4.8）。

---

## 3. 判定（轮胎 vs 补丁，按 AGENTS 规则量化）

| 测量项 | 实测 | 判读 |
|---|---|---|
| 是否已有核心能力层 | `RuntimeStorageProxy`（存储分发+配额）、`RecycleBinService`（删除/恢复）均被多模块复用且强校验 | ✅ 能力层是轮胎 |
| 补丁密度 | 产物写入点分散且口径不一（`upload_bytes` vs `upload_bytes_without_record`），收录割裂 | ⚠️ 散落写入点是补丁，应**收编**而非叠加 |
| 入口是否统一 | 存储=1 个代理；回收站=1 个服务；但**「文件管理面」缺失** | ❌ **管理面空白** |

**结论**：`轮胎 + 缺失的统一管理面`。处置：**在既有存储/回收站之上补「组织层」**（虚拟目录树），并把散落的产物写入点**收编**进 `UploadFile`；**不新建第二套存储或文件体系**。

---

## 4. 设计

### 4.1 命名空间模型

- 每账号一棵目录树，root = 账号根（虚拟，不落库）。
- 节点两类：`folder`（目录）/ `file`（文件节点，**1:1 指向一个 `UploadFile`**）。
- 四类来源并入同一棵树，节点带 `source` 标记：`upload` / `artifact` / `render_output` / `platform`。
- **历史 `upload_file` 的处置（决策 D1）**：文件名中心提供两个视图——
  - 「我的文件夹」：目录树（仅展示已建节点的文件）；
  - 「全部文件」：列出账号**全部** `upload_file`（含已入树与未入树，带来源标注，只读浏览），未入树的提供「导入到文件中心」把文件挂到选定目录并建节点。
  - 即**懒建/按需导入**，不做一次性大迁移。
- **知识库文件（决策 D2）**：`KnowledgeDocument.upload_file_id` 对应的文件**不复制**进文件中心，而是以 `origin=knowledge_base` 出现在「全部文件」并标注来源；该来源**只读**——重命名/移动/删除均禁用（需到素材中心操作），底层同时受**引用保护**（复用 `StorageMigrationService` 既有「被引用文件跳过删除」逻辑）。

### 4.2 数据模型

新增表 `file_center_entry`：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `account_id` | UUID | 账号隔离 |
| `parent_id` | UUID nullable | 父目录；NULL = 账号根 |
| `name` | varchar | 展示名（同目录内唯一） |
| `is_folder` | bool | 目录 / 文件 |
| `upload_file_id` | UUID nullable | 文件节点指向 `UploadFile`；目录为 NULL |
| `source` | varchar | `upload`/`artifact`/`render_output`/`platform` |
| `origin` | varchar nullable | 来源标记（如 `knowledge_base`），用于只读/跳转 |
| `created_at` / `updated_at` | timestamp | |

- 唯一约束：`(account_id, parent_id, name)`（`parent_id IS NOT NULL` 的 partial unique index）+ `(account_id, name)`（`parent_id IS NULL` 的 partial unique index，规避 Postgres 中 NULL 不参与唯一约束的问题）。
- 索引：`(account_id, parent_id)`。
- `UploadFile` **不改结构**。
- 迁移：仅建表 + 索引；`down_revision` 指向当时 head，收敛单 head。

### 4.3 删除 / 恢复语义（复用回收站）

- **文件节点删除**：走 `RecycleBinService.delete_resource(resource_type="upload_file", ...)`（既有语义：快照 + 物理删对象/记录，到期销毁并释放配额）；同时移除 `file_center_entry` 节点。
  - 为使恢复回到**原目录**，回收站快照需附带节点信息（`parent_id` 路径 / `name`）——扩展 `upload_file` 快照 meta（对既有 admin 删除无害）。
- **目录节点删除**：递归处理子树——子树内文件逐一入回收站，目录本身**无物理对象**直接移除（不产生「无对象可恢复」的目录条目）。
- **恢复**：按快照路径**逐级确保父目录存在**后重建节点。
- 本中心**不新建**回收站资源类型与 UI，直接复用 `/space/recycle-bin`。

### 4.4 后端服务与 API

- 服务：`FileCenterService`（`list` / `mkdir` / `rename` / `move` / `delete` / `upload` / `import`），权限与配额复用既有链路。
- 用户端路由 `/space/files/*`：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/space/files?parent_id=` | 列目录（树） |
| GET | `/space/files/all` | 「全部文件」视图（查 `upload_file`，带来源标注） |
| POST | `/space/files/folders` | 建目录 |
| PATCH | `/space/files/<id>` | 重命名 / 移动 |
| DELETE | `/space/files/<id>` | 删除（→回收站） |
| POST | `/space/files/upload` | 上传（经 `RuntimeStorageProxy`，含配额） |
| POST | `/space/files/import` | 导入既有 `upload_file` 到指定目录 |

- 配额：上传经 `RuntimeStorageProxy`（已收口）；删除经回收站（到期释放）。

### 4.5 Agent 工具（满足「被 Agent 使用」）

- 新 builtin provider `file_center`（**决策 D3**），工具：`list_files` / `make_folder` / `move_file` / `rename_file` / `delete_file` / `read_file` / `save_artifact`。
- 落点遵循 `host_os` 范式：`providers/<provider>/*.py + *.yaml + providers.yaml 登记`，运行时在 `assistant_agent_service` 挂载并注入 `requester=account_id`。
- 语义：与用户**同一命名空间**；删除同样进回收站；配额同样收口；**不新造链路**。

### 4.6 产物收录（收编写入点，属「补洞口」）

| 产物 | 现状 | 改法 |
|---|---|---|
| 生成图片 | `upload_bytes_without_record`（无记录） | 改为**建记录**（走 `upload_bytes`），使其在文件中心可见、计配额 |
| Agent 文本产物 | 已建记录（`folder=artifacts`） | 直接进文件中心（建节点或经「全部文件」导入） |
| 沙箱产物 | 云侧无记录 | 落 `UploadFile` 记录后进文件中心 |

逐一核对接线，保证不破坏对话内展示（生成图片当前只在消息内展示）。

### 4.7 前端

- `/space/files`：左目录树 + 右文件列表；建目录 / 上传 / 重命名 / 移动 / 删除；文件预览复用 kkfileview（`/kkfileview/`）。
- i18n 走 `ui/src/i18n/messages/{zh-CN,en-US}/`（zh/en 同步，parity 测试通过）。

### 4.8 分期

- **阶段 1（本 spec）**：§4.1–§4.7（平台存储目录化 + 产物收录 + 回收站复用 + Agent 工具）。
- **阶段 2**：本机目录浏览——给 `os_automation_worker` 补目录枚举/元信息能力 + 桌面端 UI + 本机↔平台互传，作为文件中心「本机」来源。
- **阶段 3**：外部云盘连接器（复用知识库 `external_data_source` 范式），作为「外部云盘」来源。

---

## 5. 收编清单（逐点验证）

| # | 位置 | 改法 |
|---|---|---|
| 1 | 新表 `file_center_entry` + 迁移 | 建表 + partial unique 索引 |
| 2 | `FileCenterService` | 树操作 + 上传/导入；复用配额 |
| 3 | 用户端路由 `/space/files/*` | 7 个端点 |
| 4 | `RecycleBinService` 快照 meta | `upload_file` 快照带文件中心路径，支持原目录恢复 |
| 5 | builtin provider `file_center`（`.py`+`.yaml`+`providers.yaml`） | 7 个工具 + `assistant_agent_service` 挂载点 |
| 6 | `image_persistence.persist_remote_image` | `upload_bytes_without_record` → 建记录 |
| 7 | 前端 `/space/files` + i18n（zh/en） | 目录树 + 文件列表 + 操作 |
| 8 | 文档同步 | `06-file-storage.md` 增「文件中心」章节；登记 `docs/README.md` |

---

## 6. 落地步骤与验收

| 步骤 | 产出 | 验收 |
|---|---|---|
| S1 | 迁移 + 模型 `file_center_entry` | 单测：树操作 / 同级重名冲突 / 账号隔离 |
| S2 | `FileCenterService` + `/space/files/*` | 契约测试：CRUD / 移动成环拒绝 / 越权拒绝 |
| S3 | 回收站快照带路径 + 恢复回原目录 | 单测：删除→恢复回原目录；目录删除递归入站 |
| S4 | Agent provider `file_center` + 挂载 | 挂载测试 + 真实调用：Agent 建目录/存产物/列文件 |
| S5 | 产物收编（图片等建记录） | 生成图片在文件中心可见且计配额；对话内展示不回归 |
| S6 | 前端 + i18n | parity 通过；树/列表/操作可用；kkfileview 预览可用 |
| S7 | 文档同步 | `06-file-storage.md` 章节 + `docs/README.md` 登记 |

**回归基线**：既有上传/知识库/回收站链路行为不变；`UploadFile` 结构不变。

---

## 7. 风险与未决

| 风险 | 处置 |
|---|---|
| 移动/重命名跨后端导致 key 失效 | 本设计**不改物理 key**（虚拟组织层），重命名只改 `name`，物理零改动 |
| 历史 `upload_file` 未入树导致「找不到文件」 | 「全部文件」视图 + 「导入」动作兜底（D1 懒建） |
| 删除被知识库引用的文件 | 复用既有引用保护（`force` 语义），默认跳过 |
| 回收站恢复丢失原目录 | S3 在快照 meta 记录路径，恢复逐级重建父目录 |
| 与素材中心职责重叠 | 明确分工：文件中心=文件，素材中心=被解析素材；知识库来源在文件中心只读 |
| 产物收编破坏对话内展示 | 改 `persist_remote_image` 时保留现有消息渲染路径，回归验证 |

---

## 8. 已确认决策

| 编号 | 决策 | 结论 |
|---|---|---|
| D1 | 存量 `upload_file` 是否自动建树节点 | **懒建/按需导入**（「全部文件」视图 + 导入动作） |
| D2 | 知识库文档是否出现在文件中心 | **出现 + 只读 + 引用保护** |
| D3 | Agent 工具的 provider 命名 | `file_center` |

## 9. 已定的实现细节

- **回收站快照 meta**：`upload_file` 快照新增 `file_center` 字段，记录 `parent_path`（目录路径数组）与 `name`；兼容旧快照（缺该字段时恢复到账号根）。S3 落地。
- **Agent `save_artifact` 默认落点**：账号根下 `产物/`（不存在则自动创建）；允许 Agent 通过参数指定目标目录。
