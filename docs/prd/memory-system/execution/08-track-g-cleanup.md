# Track G：旧代码清理 -- 任务执行文档

> **创建日期**：2026-07-09
> **Track**：G（旧代码清理，G1-G12）
> **关联架构**：[01-data-models-and-write-path.md](../../01-data-models-and-write-path.md) | [02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) | [00-overview.md](./00-overview.md)
> **执行原则**：二开阶段，无生产数据，不做向后兼容，旧代码直接删除；每个清理任务标注执行时机（前置条件），未满足前置条件时不得提前执行。

---

## 0. 背景与清理策略

### 0.1 背景

系统当前处于二开阶段，无生产数据需要保护。旧记忆系统代码分散在多个后端 Python 文件、前端 Vue/TS 文件、测试文件以及数据库迁移文件中。新记忆系统（Track A-F）逐项就位后，旧代码需要按依赖顺序逐步删除，避免出现悬空引用、导入错误或测试失败。

### 0.2 清理策略

- **强前置条件**：每个 G 任务都依赖某个 A/B/D/F 任务完成，未完成前置任务时不得执行该 G 任务。
- **成对删除**：源码文件与其对应测试文件成对删除，避免遗留引用失败测试。
- **迁移前向**：删除数据库表通过新建 Alembic 迁移文件实现，不修改历史迁移文件。
- **保留 PG 关系层**：`user_memory` 表由新系统继续用作关系数据持久层，仅 `memory_candidate` 表被彻底废弃。
- **持续清理**：Track G 在 T1 起即可随前置条件达成而分散执行，不是一次性批量删除。

### 0.3 旧代码清单（来自代码搜索）

#### 后端 Python

| # | 文件 | 行数/范围 | 主要内容 |
|---|---|---|---|
| 1 | `api/internal/service/long_term_memory_service.py` | 337 行 | MemoryCandidateExtractor, MemoryConfidenceTracker, UserMemoryConfirmationService, LongTermMemoryService |
| 2 | `api/internal/handler/memory_candidate_handler.py` | 55 行 | MemoryCandidateHandler |
| 3 | `api/internal/schema/memory_candidate_schema.py` | - | ConfirmMemoryCandidateReq, IgnoreMemoryCandidateReq, MemoryCandidateResp, UserMemoryResp |
| 4 | `api/internal/handler/user_memory_handler.py` | 96 行 | UserMemoryHandler |
| 5 | `api/internal/schema/user_memory_schema.py` | - | CreateUserMemoryReq, UpdateUserMemoryReq, UserMemoryListResp, MemorySettingsResp |
| 6 | `api/internal/service/memory_vector_service.py` | 93 行 | MemoryVectorService（pgvector `user_memory.embedding`） |
| 7 | `api/internal/model/knowledge.py` | L128-151 | MemoryCandidate 模型 |
| 8 | `api/internal/service/scoped_knowledge_service.py` | L209-379 | UserMemoryService 类 |
| 9 | `api/internal/service/assistant_agent_service.py` | L404-424 | `_extract_long_term_memory` 方法 |
| 10 | `api/internal/router/router.py` | L1395-1454 | 10 条旧 API 路由 |
| 11 | `api/internal/core/memory/token_buffer_memory.py` | L126 起 | `get_relevant_facts` 方法 |

#### 前端 Vue/TS

| # | 文件 | 行数 | 主要内容 |
|---|---|---|---|
| 12 | `ui/src/components/MemoryConfirmationCard.vue` | 138 行 | 记忆确认卡片组件 |
| 13 | `ui/src/views/settings/MemoryView.vue` | 623 行 | 旧记忆管理页面 |
| 14 | `ui/src/services/user-memory.ts` | 66 行 | 旧前端记忆服务 |
| 15 | `ui/src/models/memory.ts` | 57 行 | 旧前端记忆类型定义 |

#### 测试文件

| # | 文件 | 测试数 | 说明 |
|---|---|---|---|
| 16 | `api/test/internal/service/test_long_term_memory_service.py` | 18 个 | 长期记忆服务测试 |
| 17 | `api/test/internal/handler/test_memory_candidate_handler.py` | 6 个 | 记忆候选 handler 测试 |
| 18 | `api/test/internal/handler/test_user_memory_handler.py` | 5 个 | 用户记忆 handler 测试 |
| 19 | `api/test/internal/service/test_memory_extraction.py` | 11 个 | 记忆抽取测试 |
| 20 | `api/test/internal/core/memory/test_token_buffer_memory.py` | 12 个 | 部分与记忆无关的保留 |

#### 数据库迁移

| # | 迁移文件 | 涉及内容 |
|---|---|---|
| 21 | `d1e2f3a4b5c7`, `e1f2a3b4c5d7`, `j1e2f3a4b5c0`, `r2c3d4e5f6a7` | `memory_candidate` 表相关部分 |

---

## 1. 任务依赖与执行时机总览

```
前置任务       →  可执行的 G 任务
─────────────────────────────────────
A2 完成        →  G4（删除 MemoryVectorService）
A5 完成        →  G1, G2, G5, G11（删除触发链相关旧代码）
B8 完成        →  G9, G10（清理 token_buffer 与 scoped_knowledge）
D4 完成        →  G3, G6（删除旧 CRUD API 与路由）
F1 完成        →  G8（删除旧前端服务与类型）
F5 完成        →  G7（删除 MemoryConfirmationCard）
G5 完成        →  G12（新建迁移删除表）
```

| 任务 | 时机 | 类型 | 前置条件 |
|---|---|---|---|
| G1 | A5 完成后 | 删除文件 | 新触发逻辑就位 |
| G2 | A5 完成后 | 删除文件 | 新触发逻辑就位 |
| G3 | D4 完成后 | 删除文件 | 新 CRUD API 就位 |
| G4 | A2 完成后 | 删除文件 | 新写入用 pgvector |
| G5 | A5 完成后 | 改模型 | 新触发逻辑就位 |
| G6 | D4 完成后 | 改路由 | 新 CRUD API 就位 |
| G7 | F5 完成后 | 删除组件 | 新前端页面就位 |
| G8 | F1 完成后 | 删除文件 | 新前端服务就位 |
| G9 | B8 完成后 | 改代码 | 新检索上下文就位 |
| G10 | B8 完成后 | 改代码 | 新检索上下文就位 |
| G11 | A5 完成后 | 改代码 | 新触发逻辑就位 |
| G12 | G5 完成后 | 新建迁移 | MemoryCandidate 模型已删 |

---

## G1：删除 long_term_memory_service.py

- **执行时机**：A5 完成后（新触发逻辑就位）
- **前置条件**：Track A 的 A5 任务已完成，新的记忆触发链（SalienceScorer → LedgerWriter）已替代 LongTermMemoryService 的全部职责
- **类型**：删除文件

### 任务内容

1. 删除文件 `api/internal/service/long_term_memory_service.py`（337 行）
   - 包含的类：MemoryCandidateExtractor, MemoryConfidenceTracker, UserMemoryConfirmationService, LongTermMemoryService
2. 同时删除测试文件：
   - `api/test/internal/service/test_long_term_memory_service.py`（18 个测试）
   - `api/test/internal/service/test_memory_extraction.py`（11 个测试）

### 验收

- `api/internal/service/long_term_memory_service.py` 不存在
- 两个测试文件不存在
- 全局搜索 `LongTermMemoryService`、`MemoryCandidateExtractor`、`MemoryConfidenceTracker`、`UserMemoryConfirmationService` 仅在 G11 待清理的 `assistant_agent_service.py` 中残留（由 G11 清理）
- `cd api && python -m pytest test/internal/service/ -v` 无导入失败

---

## G2：删除 memory_candidate_handler.py + schema

- **执行时机**：A5 完成后
- **前置条件**：A5 已完成，记忆候选确认流程被自动写入 + 图可视化事后管理替代
- **类型**：删除文件

### 任务内容

1. 删除文件：
   - `api/internal/handler/memory_candidate_handler.py`（55 行）- MemoryCandidateHandler
   - `api/internal/schema/memory_candidate_schema.py`
     - 包含：ConfirmMemoryCandidateReq, IgnoreMemoryCandidateReq, MemoryCandidateResp, UserMemoryResp
2. 同时删除测试文件：
   - `api/test/internal/handler/test_memory_candidate_handler.py`（6 个测试）

### 验收

- 三个文件均不存在
- 全局搜索 `MemoryCandidateHandler`、`ConfirmMemoryCandidateReq`、`IgnoreMemoryCandidateReq` 无残留引用
- `cd api && python -m pytest test/internal/handler/ -v` 无导入失败

---

## G3：删除 user_memory_handler.py + schema

- **执行时机**：D4 完成后（新 CRUD API 就位）
- **前置条件**：Track D 的 D4 任务已完成，新的记忆 CRUD API（PUT/DELETE /memory/{id}）已替代旧 UserMemoryHandler 的全部职责
- **类型**：删除文件

### 任务内容

1. 删除文件：
   - `api/internal/handler/user_memory_handler.py`（96 行）- UserMemoryHandler
   - `api/internal/schema/user_memory_schema.py`
     - 包含：CreateUserMemoryReq, UpdateUserMemoryReq, UserMemoryListResp, MemorySettingsResp
2. 同时删除测试文件：
   - `api/test/internal/handler/test_user_memory_handler.py`（5 个测试）

### 验收

- 三个文件均不存在
- 全局搜索 `UserMemoryHandler`、`CreateUserMemoryReq`、`UpdateUserMemoryReq`、`MemorySettingsResp` 无残留引用
- `cd api && python -m pytest test/internal/handler/ -v` 无导入失败
- 新 CRUD API 测试（D4 产物）全部通过

---

## G4：删除 MemoryVectorService

- **执行时机**：A2 完成后（新写入用 pgvector）
- **前置条件**：Track A 的 A2 任务已完成，LedgerWriter 已使用 pgvector 写入记忆向量
- **类型**：删除文件

### 任务内容

1. 删除文件 `api/internal/service/memory_vector_service.py`（93 行）
   - 类：MemoryVectorService（操作 pgvector `user_memory.embedding` 列）

### 验收

- 文件不存在
- 全局搜索 `MemoryVectorService` 无残留引用
- 知识库向量也在同一 PG 实例（与记忆系统共用 PostgreSQL，不同表）
- `cd api && python -m py_compile internal/service/memory/ledger_writer.py` 通过

---

## G5：删除 MemoryCandidate 模型

- **执行时机**：A5 完成后
- **前置条件**：A5 已完成，且 G1、G2 已执行（无代码引用 MemoryCandidate 模型）
- **类型**：修改模型文件
- **注意**：本任务不直接删除数据库表，表删除由 G12 通过新建迁移完成

### 任务内容

1. 修改 `api/internal/model/knowledge.py`：删除 L128-151 的 `MemoryCandidate` 类定义
2. 检查 `knowledge.py` 中是否还有其他对 MemoryCandidate 的引用（外键、关系字段等），一并清理
3. 不要修改历史迁移文件

### 验收

- `api/internal/model/knowledge.py` 中无 `MemoryCandidate` 类
- `cd api && python -m py_compile internal/model/knowledge.py` 通过
- `cd api && python -m pytest test/internal/model/ -v` 无失败
- 全局搜索 `MemoryCandidate`（除迁移文件外）无残留

---

## G6：删除旧 API 路由

- **执行时机**：D4 完成后
- **前置条件**：D4 已完成，新 CRUD API 已注册到路由；G3 已执行（UserMemoryHandler 已删）
- **类型**：修改路由文件 + 更新测试

### 任务内容

1. 修改 `api/internal/router/router.py`：删除 L1395-1454 的 10 条旧 API 路由
   - 涉及 memory_candidate 与 user_memory 的旧路由
2. 同时更新测试文件中的旧路由断言：
   - `api/test/internal/router/test_router_full_matrix.py`
   - `api/test/internal/router/test_phase1_closure_handler.py`
   - 删除对已废弃路由的断言，新增对新路由（/memory/write, /memory/retrieve, /memory/{id} 等）的断言

### 验收

- `router.py` 中 L1395-1454 范围的 10 条旧路由已删除
- 全局搜索旧路由路径（如 `/memory/candidates`, `/user/memory` 等）无残留
- `cd api && python -m pytest test/internal/router/ -v` 全部通过
- 新路由测试覆盖完整

---

## G7：删除 MemoryConfirmationCard.vue

- **执行时机**：F5 完成后
- **前置条件**：Track F 的 F5 任务已完成，新的 MemoryView.vue（重写版）不再使用 MemoryConfirmationCard 组件（自动写入替代逐条确认）
- **类型**：删除组件 + 清理引用

### 任务内容

1. 删除文件 `ui/src/components/MemoryConfirmationCard.vue`（138 行）
2. 清理所有引用该组件的地方：
   - 全局搜索 `MemoryConfirmationCard` 找到所有 import 与模板引用
   - 删除对应的 import 语句和 `<MemoryConfirmationCard />` 模板标签
   - 检查 `ui/src/views/settings/MemoryView.vue` 是否还有引用（若 F5 已重写则应已无引用）

### 验收

- 文件不存在
- 全局搜索 `MemoryConfirmationCard` 无残留
- `cd ui && npx vue-tsc --noEmit` 通过
- `cd ui && npx vitest run` 通过

---

## G8：删除旧前端服务 + 类型

- **执行时机**：F1 完成后
- **前置条件**：Track F 的 F1 任务已完成，新的 `services/memory-graph.ts` 和 `models/memory-graph.ts` 已替代旧服务
- **类型**：删除文件 + 清理 import

### 任务内容

1. 删除文件：
   - `ui/src/services/user-memory.ts`（66 行）
   - `ui/src/models/memory.ts`（57 行）
2. 清理所有 import 引用：
   - 全局搜索 `from '@/services/user-memory'` 和 `from '@/models/memory'`
   - 替换为对应的新服务 import：`from '@/services/memory-graph'` 和 `from '@/models/memory-graph'`
   - 注意类型名映射：旧 `UserMemory` → 新 `MemoryNode`，旧 `MemorySettings` → 新类型（若存在）

### 验收

- 两个文件不存在
- 全局搜索 `user-memory` 和 `models/memory`（不含 `memory-graph`）无残留 import
- `cd ui && npx vue-tsc --noEmit` 通过
- `cd ui && npx vitest run` 通过

---

## G9：修改 token_buffer_memory.py

- **执行时机**：B8 完成后
- **前置条件**：Track B 的 B8 任务已完成，新的 MemoryRetriever 已提供上下文检索能力
- **类型**：修改代码 + 更新测试
- **重要**：本任务只删 facts 部分，保留 recent_messages 和 distant_summary 逻辑

### 任务内容

1. 修改 `api/internal/core/memory/token_buffer_memory.py`：
   - 删除 `get_relevant_facts` 方法（L126 起）及其对 UserMemoryService 的依赖
   - 修改 `build_context` 方法：移除 facts 部分的拼装逻辑
   - 保留 `recent_messages` 和 `distant_summary` 相关逻辑不动
   - 移除文件顶部的 `UserMemoryService` import（若仅此方法使用）
2. 更新测试文件 `api/test/internal/core/memory/test_token_buffer_memory.py`（12 个测试）：
   - 保留与 `recent_messages` 和 `distant_summary` 相关的测试
   - 删除与 `get_relevant_facts` 和 facts 上下文相关的测试
   - 确保 `build_context` 测试不再断言 facts 字段

### 验收

- `token_buffer_memory.py` 中无 `get_relevant_facts` 方法
- `token_buffer_memory.py` 中无 `UserMemoryService` import
- `build_context` 输出不再包含 facts 部分
- `recent_messages` 和 `distant_summary` 逻辑保持原样
- `cd api && python -m pytest test/internal/core/memory/test_token_buffer_memory.py -v` 通过

---

## G10：清理 scoped_knowledge_service.py

- **执行时机**：B8 完成后
- **前置条件**：B8 已完成，且 G9 已执行（UserMemoryService 不再被 token_buffer_memory 引用）
- **类型**：修改代码
- **重要**：保留 SystemKnowledgeService 和 UserContentKnowledgeService

### 任务内容

1. 修改 `api/internal/service/scoped_knowledge_service.py`：
   - 删除 `UserMemoryService` 类（L209-379）
   - 删除常量：
     - `DEFAULT_MEMORY_SETTINGS`
     - `MEMORY_SETTINGS_MARKER_TYPE`
     - `MEMORY_SETTINGS_MARKER_SCOPE`
   - 保留 `SystemKnowledgeService` 和 `UserContentKnowledgeService` 类不动
   - 清理文件顶部仅被 UserMemoryService 使用的 import

### 验收

- `scoped_knowledge_service.py` 中无 `UserMemoryService` 类
- 文件中无 `DEFAULT_MEMORY_SETTINGS`、`MEMORY_SETTINGS_MARKER_TYPE`、`MEMORY_SETTINGS_MARKER_SCOPE` 常量
- `SystemKnowledgeService` 和 `UserContentKnowledgeService` 保持原样
- 全局搜索 `UserMemoryService` 无残留（G9 已清理 token_buffer_memory 侧引用）
- `cd api && python -m pytest test/internal/service/test_scoped_knowledge_service.py -v` 通过

---

## G11：清理 assistant_agent_service.py

- **执行时机**：A5 完成后
- **前置条件**：A5 已替换了 `_extract_long_term_memory`，且 G1 已执行（LongTermMemoryService 文件已删）
- **类型**：修改代码
- **说明**：A5 已经替换了 `_extract_long_term_memory` 的实现，本任务做最终清理，移除所有对旧服务的残留引用

### 任务内容

1. 修改 `api/internal/service/assistant_agent_service.py`（L404-424 区域）：
   - 移除所有对 `LongTermMemoryService` 的 import
   - 移除对 LongTermMemoryService 的依赖注入（构造函数参数、属性赋值等）
   - 移除 `QueueEvent.MEMORY_CANDIDATE_PROMPT` 相关代码（事件发布、handler 注册等）
   - 确认 A5 替换后的新触发逻辑（SalienceScorer 调用）正常工作

### 验收

- `assistant_agent_service.py` 中无 `LongTermMemoryService` import
- 文件中无 `QueueEvent.MEMORY_CANDIDATE_PROMPT` 相关代码
- 新的 SalienceScorer 触发逻辑保持工作
- `cd api && python -m pytest test/internal/service/test_assistant_agent_service.py -v` 通过
- 集成测试中 assistant agent 流程不报错

---

## G12：清理数据库迁移

- **执行时机**：G5 完成后
- **前置条件**：G5 已执行（MemoryCandidate 模型已从 `knowledge.py` 删除）
- **类型**：新建迁移文件
- **重要**：不修改历史迁移文件；不删除 user_memory 表（新系统仍用 PG 做关系数据持久层）

### 任务内容

1. 创建新 Alembic 迁移文件：`drop_memory_candidate_table`
   - 命令示例：`cd api && alembic revision -m "drop memory_candidate table"`
   - 在 `upgrade()` 中执行：`op.drop_table('memory_candidate')`
   - 在 `downgrade()` 中：因二开阶段无生产数据，downgrade 可留空或仅写 `pass`（不做向后兼容）
2. 不需要删除 `user_memory` 表（新系统继续使用 PG 作为关系数据持久层）
3. 历史迁移文件（`d1e2f3a4b5c7`, `e1f2a3b4c5d7`, `j1e2f3a4b5c0`, `r2c3d4e5f6a7` 中的 memory_candidate 部分）保持原样不修改

### 验收

- 新迁移文件存在于 `api/migrations/versions/` 目录
- `cd api && alembic upgrade head` 成功执行
- 数据库中 `memory_candidate` 表已删除
- `user_memory` 表仍然存在
- `cd api && python -m pytest test/internal/ -v` 无迁移相关失败

---

## 2. 全局验收（Track G 完成后）

执行以下检查确认 Track G 全部完成：

```bash
# 后端：旧代码无残留
cd api
grep -r "LongTermMemoryService" internal/ || echo "OK: 无残留"
grep -r "MemoryCandidateHandler" internal/ || echo "OK: 无残留"
grep -r "UserMemoryHandler" internal/ || echo "OK: 无残留"
grep -r "MemoryVectorService" internal/ || echo "OK: 无残留"
grep -r "class MemoryCandidate" internal/ || echo "OK: 无残留"
grep -r "UserMemoryService" internal/ || echo "OK: 无残留"
grep -r "MEMORY_CANDIDATE_PROMPT" internal/ || echo "OK: 无残留"

# 前端：旧代码无残留
cd ui
grep -r "MemoryConfirmationCard" src/ || echo "OK: 无残留"
grep -r "user-memory" src/ || echo "OK: 无残留"
grep -r "models/memory['\"]" src/ || echo "OK: 无残留"

# 全量测试
cd api && python -m pytest test/internal/ -v
cd ui && npx vue-tsc --noEmit && npx vitest run

# 数据库迁移
cd api && alembic upgrade head
```

### 完成标志

- 上述所有 grep 命令均输出 "OK: 无残留"
- 后端全量测试通过
- 前端类型检查与单元测试通过
- Alembic 迁移成功执行到 head
- `memory_candidate` 表已从数据库删除
