# KB-P5 前台与运维 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: 本计划为拆分层 roadmap。每个子计划（KB-P5-A / KB-P5-B / KB-P5-C）选定后，用 superpowers:writing-plans 深化为带完整代码与 TDD 步骤的独立实施计划，再以 subagent-driven-development 或 executing-plans 分任务执行。

**Goal:** 让用户能管理自己的知识库数据：板块详情与分区树导航、素材网格与素材详情、用量面板与扩容入口；让「小钰帮传」（对话内 Agent 上传素材）可用；把外部数据源同步纳入存储配额校验。

**Architecture:** 后端 API 大部分已就绪（板块/分区/文档/segments/external-data-source/chunked-upload/commerce 全套），本阶段补齐三个真实缺口：① 用户端用量 API 路由（`get_usage_summary` 已有实现但未暴露）；② 对话内上传素材的 builtin 工具（tools 池只有 `create_knowledge_base`，无上传工具）；③ `external_data_source_service.sync()` 的配额校验（现零配额调用）。前端补齐四个页面缺口。三块互相独立、可各自独立验证。

**Tech Stack:** Python 3.12 / Quart / pytest / Vue 3 + TypeScript（Ant Design Vue）/ i18n（zh-CN/en-US 双字典，强制 parity）

---

## 现状核对（2026-09-20 实测）

### 后端已有（无需新建）

| 能力 | 入口 |
| --- | --- |
| 板块列表/详情/更新/删除 | `GET/POST /space/knowledge-bases`、`GET /space/knowledge-bases/<id>`、`POST .../delete`（[knowledge_mcp_routes.py](../../../api/app/http/knowledge_mcp_routes.py)） |
| 分区列表/创建 | `GET/POST /space/knowledge-bases/<id>/partitions` |
| 素材列表/详情/上传/删除 | `GET .../documents`、`GET .../documents/<id>`、`POST .../documents/upload`、`POST .../documents/<id>/delete` |
| L2 触发 / 分段列表 / 召回测试 | `POST .../documents/<id>/l2`、`GET .../documents/<id>/segments`、`POST .../hit` |
| 分片上传全套 | `/space/chunked-uploads/{init,chunk,status,complete,instant,abort}`（[chunked_upload_routes.py](../../../api/app/http/chunked_upload_routes.py)）；`chunked_upload_service` 已接入 `check_quota` + `consume_quota` |
| 外部数据源全套 | `/external-data-sources` + `.../authorize` + `.../sync` |
| 用量计算 | `StorageQuotaService.get_usage_summary()` 返回 `total_bytes/used_bytes/remaining_bytes/usage_percent`（[storage_quota_service.py](../../../api/internal/service/storage_quota_service.py)）——**但无用户端路由暴露** |
| 扩容下单链路 | `GET /plans`、`POST /orders`、`GET /orders/<order_no>`、`POST /orders/<order_no>/mock-paid`（[commerce_routes.py](../../../api/app/http/commerce_routes.py)；`storage_addon` 套餐与履约分支已落地） |
| 对话工具挂载点 | `assistant_agent_service._build_assistant_runtime_tools`（L872），已挂 `create_knowledge_base` / `render_video` / `video_trim` 等 |

### 前端已有

- 板块列表卡片页：`ui/src/views/space/datasets/ListView.vue`（卡片网格 + 统计行 + 新建按钮）
- 素材列表：`ui/src/views/space/datasets/documents/ListView.vue`（a-table 表格 + 分页，无网格切换）
- 分段列表：`ui/src/views/space/datasets/documents/segments/ListView.vue`（卡片）
- 外部数据源弹窗：`ui/src/views/space/datasets/components/ExternalDataSourceModal.vue`
- 分片上传封装：`ui/src/services/chunked-upload.ts`（`uploadFileChunked(knowledgeBaseId, file)`，秒传/断点续传/session 缓存）
- 路由：`ui/src/router/index.ts` 已注册 `my-knowledge`（→ datasets/ListView.vue）、`space-datasets-documents-list`（→ documents/ListView.vue）、分段列表页

### 缺口（本计划补齐）

| # | 缺口 | 归属 |
| --- | --- | --- |
| 1 | 板块详情页（分区树导航）——后端分区 API 有，前端无详情页 | KB-P5-A |
| 2 | 素材网格视图 + 素材详情页——现为 a-table，无网格、无详情 | KB-P5-A |
| 3 | 用量面板 + 扩容入口——`get_usage_summary` 无路由；前端无用量展示、无跳扩容下单 | KB-P5-A |
| 4 | 小钰帮传——对话工具池无「上传素材到知识库」工具 | KB-P5-B |
| 5 | 外部数据源同步配额——`external_data_source_service.sync()` 零配额调用 | KB-P5-C |

---

## 子计划划分

三个子计划互不依赖，可独立执行、独立验收：

### KB-P5-A：前台页面（板块详情 / 素材网格 / 素材详情 / 用量面板）

**文件（前端为主 + 1 个后端路由）：**

| 文件 | 职责 |
| --- | --- |
| Modify: `api/app/http/knowledge_mcp_routes.py` | 新增 `GET /space/storage/usage`（调 `StorageQuotaService.get_usage_summary`）——用量面板唯一数据源 |
| Modify: `api/test/app/http/test_knowledge_mcp_routes.py` | usage 路由用例 |
| Create: `ui/src/services/storage-usage.ts` | 调 `GET /space/storage/usage`；`resolveUpgradeUrl()` 指向 `/plans`（`storage_addon`） |
| Create: `ui/src/views/space/datasets/detail/IndexView.vue` | 板块详情页容器：基本信息 + 分区树导航（左树右内容）+ 素材网格 |
| Create: `ui/src/views/space/datasets/detail/components/PartitionTreeNav.vue` | 分区树（`GET .../partitions`），点击分区过滤素材网格 |
| Create: `ui/src/views/space/datasets/detail/components/MaterialGrid.vue` | 素材网格卡片（缩略/时长/解析状态/媒体类型图标），支持分区过滤、a-table ⇄ 网格切换 |
| Create: `ui/src/views/space/datasets/detail/components/MaterialDetailDrawer.vue` | 素材详情抽屉（`GET .../documents/<id>` + segments 列表 + L2 触发按钮 + 删除） |
| Create: `ui/src/views/space/datasets/detail/components/UsagePanel.vue` | 用量概览卡（total/used/remaining/percent + 进度条 + 扩容按钮跳 `/plans`） |
| Modify: `ui/src/router/index.ts` | 注册 `space-datasets-detail`（→ detail/IndexView.vue，query 携带 kb_id） |
| Modify: `ui/src/views/space/datasets/ListView.vue` | 卡片点击改跳 detail 页；顶部加用量入口 |
| Modify: `ui/src/views/space/datasets/documents/ListView.vue` | 迁移/复用为 detail 页面素材列表，或保留下钻 routes 兼容 |
| Modify: `ui/src/i18n/messages/zh-CN/` + `en-US/` | 新增 `space.datasets.detail.*` 相关字典（双侧同步，跑 parity spec） |

**Task 划分（TDD，每 Task 完成即 commit）：**

- Task A1: 后端 `GET /space/storage/usage` 路由 + 测试
- Task A2: 前端 `storage-usage.ts` + 单测（fetch mock）+ i18n
- Task A3: UsagePanel.vue + 单测 + 扩容跳转
- Task A4: PartitionTreeNav.vue + 单测（mock 分区 API）
- Task A5: MaterialGrid.vue（网格 + 表格切换 + 分区过滤）+ 单测
- Task A6: MaterialDetailDrawer.vue（详情 + segments + L2 + 删除）+ 单测
- Task A7: detail/IndexView.vue 组装 + 路由注册 + 板块列表跳转改造
- Task A8: 前端回归（`npx vitest run`）+ i18n parity + 后端全量回归 + graphify + 文档同步 + commit

**验收口径：** 板块列表点进详情 → 分区树可导航过滤素材 → 素材网格可切网格/表格 → 点素材出详情抽屉（含分段/L2/删除）→ 用量面板显示真实配额并可跳扩容下单 → i18n parity 通过。

### KB-P5-B：小钰帮传（对话内上传素材到知识库）

**文件：**

| 文件 | 职责 |
| --- | --- |
| Create: `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/upload_to_knowledge_base.py` | 工具：参数（knowledge_base_id / file_uri(本地绝对路径或已上传文件 id) / name 可选 / partition_id 可选）→ 校验归属 → 调既有上传链路 |
| Create: `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/upload_to_knowledge_base.yaml` | 工具声明 + task_keywords（帮传/上传到知识库/传文件） |
| Modify: `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/positions.yaml` | 登记新工具 |
| Modify: `api/internal/core/tools/builtin_tools/providers.yaml` | 确保 provider 已登记（knowledge_base_tools 已有 create_knowledge_base） |
| Modify: `api/internal/service/assistant_agent_service.py` `_build_assistant_runtime_tools` | 挂载点加 `upload_to_knowledge_base`（注入 account_id/message_id/conversation_id） |
| Create: `api/test/internal/core/tools/test_upload_to_knowledge_base_tool.py` | 工具单测（参数校验/派发/错误可读化/上下文透传） |
| Modify: `api/test/internal/service/test_assistant_agent_service.py` | 挂载点单测（工具出现在 runtime tools） |

**复用（不新建）：** 归属校验 `KnowledgeBaseService.get_user_content_base` / `get_document_detail`；上传走知识库既有「UploadFile + 建档」链路服务方法（实现时核对 `knowledge_base_service` 上传方法签名）；配额由该链路既有 `check_quota/consume_quota` 兜住。

**接线注意：** 工具参数若涉及语音/文本/图片内容需先经 `upload_file_service` 成 UploadFile（`file_uri` 只接受平台已生成的 UploadFile/URL，不接受任意本地路径——安全边界在计划深化时明确）；挂载点必须注入会话上下文，否则成品/素材回填断链（复用 KB-P4 的工具测试范式锁定）。

**Task 划分（TDD）：**

- Task B1: 工具失败测试 → 实现 → 过（参数校验/派发）
- Task B2: yaml + positions.yaml + provider 加载测试（`test_provider_loader_discovers_all_tools` 类用例）
- Task B3: 挂载点接入 + 测试
- Task B4: 后端全量回归 + 接线自检（工具→挂载点→上传链路生产调用方）+ graphify + 文档同步 + commit

**验收口径：** 对话中说「把这个文件传到知识库」→ 工具被挂载、参数可解析、派发成功、素材入库后可上 KB-P5-A 素材网格看到。

### KB-P5-C：外部数据源同步纳入配额校验

**文件：**

| 文件 | 职责 |
| --- | --- |
| Modify: `api/internal/service/external_data_source_service.py` | `sync()` 中在写库/写矢量/写 UploadFile 前对增量字节调 `StorageQuotaService.check_quota(account_id, incoming)`；写入产物按实际字节 `add_usage`（复用与 chunked_upload_service 相同的「预检 + 累加」口径，避免超卖可改用 `consume_quota`） |
| Modify: `api/test/internal/service/test_external_data_source_service.py` | 新增用例：配额不足抛 ForbiddenException；正常同步增加 used_bytes |
| Modify: `api/test/internal/service/test_storage_quota_service.py` | 如口径变化补测 |

**核对点（实现时）：** `sync()` 的产物写入（文档/分段/向量/UploadFile）具体走哪些服务方法；配额口径对齐 `chunked_upload_service` 的 `consume_quota(reserve_bytes=…)`；失败同步是否回滚已预占用量（与同步任务幂等设计一致）。

**Task 划分（TDD）：**

- Task C1: 写失败测试（配额不足拒绝 + 正常累加）
- Task C2: 实现 sync 配额接入
- Task C3: 回归 + graphify + 文档同步（02-knowledge-base.md §外部数据源 / roadmap KB-P5 状态）+ commit

**验收口径：** 配额不足时同步被拒且不产生孤儿产物；同步成功后用量正确累加；既有同步用例不回归。

---

## 总接线自检（三个子计划完成后逐项核对）

| 新符号 | 入口 |
| --- | --- |
| `GET /space/storage/usage` | 前端 `storage-usage.ts`（唯一）→ UsagePanel |
| 前端 detail 四个组件 | 路由 `space-datasets-detail` + 板块列表卡片跳转（唯一）→ detail/IndexView.vue |
| `upload_to_knowledge_base` 工具 | `.yaml` + `positions.yaml` + `providers.yaml` 登记 + `_build_assistant_runtime_tools` 挂载点（对话内唯一入口） |
| sync 配额校验 | `external_data_source_service.sync()` 内（唯一），触发入口 `POST /external-data-sources/<id>/sync`（既有） |

**收尾（每子计划完成时）：** `python -m graphify update .`；同步 `docs/prd/modules/02-knowledge-base.md`、`docs/prd/execution-roadmap.md`（KB-P5 各行状态）、`docs/prd/knowledge-base-product-form-design.md`（§9.2 KB-P5 行 + 双击「落地」列）、`docs/prd/product-vision.md`（如需）。前端 i18n 必须双侧同步 + `npx vitest run src/i18n/__tests__/parity.spec.ts` 通过。