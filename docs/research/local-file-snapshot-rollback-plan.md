# 本机文件操作增强：快照回滚 + 放开确认 + Codex 移除

> 更新日期：2026-09-08
> 定位：设计方案（已评审决策，待分批实施）。取代 `docs/superpowers/plans/2026-09-08-delete-egress-recycle-only.md`（run_os_task/Codex 删除护栏方案，作废归档）。
> 关联背景：Hermes 文件系统调研（`docs/research/`）；原方案 `docs/research/desktop-sandbox-routing-plan.md` 中的桌面桥/多通道演进方向仍有效，本方案只处理"本机文件操作"这一层。

## 0. 背景与决策

### 0.1 问题

原"Agent 本机删除只进回收站"方案依赖 `run_os_task`（Codex CLI 链路），存在硬伤：
- **Codex 强依赖 OpenAI**（ChatGPT 登录/API key + 地区限制），每个用户都要额外安装 Codex CLI + OpenAI 账号——ToC 产品不可行。
- Windows Codex 沙箱 experimental，真实删除拦截无 OS 级保障。
- 事后检测/明文拦截都无法真正阻止 Codex 进程内自主生成的删除。

### 0.2 决策（2026-09-08 用户拍板）

1. **移除 Codex / run_os_task 链路**：`run_os_task` 工具、worker `/run` 端点、delete_guard、相关测试/文档全部清理。默认文件操作走自研 `os_file_task`（V4A 补丁，纯 Python）+ `os_recycle_bin`（回收站，纯 Python），不依赖任何外部 CLI/云服务。
2. **放开 os_file_task 高风险确认**：os_file_task 移出高风险名单，不再弹确认。替代兜底是"修改可回滚 + 删除可恢复"的机制，而非每次人工确认。
3. **引入修改快照回滚**（本方案核心新增）：每次写文件前做快照，Agent 可一键回滚——删除错从回收站找回；改错了一键回滚到"上一轮用户消息之前"的状态（不直接回滚到原版，避免抹掉用户当天的工作）。
4. **快照存用户本机**（worker 侧隐藏目录），不留云端。
5. **双粒度回滚都要**：单文件精细回滚（改坏当前文件自愈）+ 按用户消息批量回滚（大面积返工）。
6. **快照按留存期自动清理**：默认 7 天一清。
7. **DB 清理**：新增 Alembic 迁移删除 `tool_governance_policy` 中 `builtin:codex_os:run_os_task` 行 + `builtin_tool` 镜像行。

## 1. 目标架构

```text
用户（Web / 桌面客户端内嵌 WebUI）
  │  os_file_task（read/search/patch，V4A）
  │  os_recycle_bin（delete/list/restore/purge）
  │  os_snapshot（rollback_file / rollback_turn，新增）
  ▼
API 容器
  │  OS_AUTOMATION_URL/TOKEN（或 DESKTOP_BRIDGE_URL/TOKEN）
  ▼
宿主机 os_automation_worker.py（纯 Python，无 Codex）
  ├─ /file      → 读/搜/V4A 补丁（写前快照）
  ├─ /recycle   → 回收站（删除/恢复/清空）
  └─ /snapshot  → 快照与回滚（新增端点）
```

## 2. 快照机制设计

### 2.1 存储位置与目录

- 根目录：与安全根同级隐藏目录，或安全根内 `.yuxin_ai_snapshots/`（默认在用户主目录下）。
  - 由 `OS_AUTOMATION_SNAPSHOT_DIR` 环境变量覆盖（默认 `<safe_root>/.yuxin_ai_snapshots`）。
- 目录结构：
  ```
  .yuxin_ai_snapshots/
    manifest.jsonl          # 全量索引（每个快照一行）
    files/<sha256>.snap     # 快照内容（内容寻址，相同内容不重复存）
  ```

### 2.2 快照触发（写前快照）

`/file` 的 patch apply 阶段，`_file_apply_patch` 对**每个将修改的文件**在执行前快照：
- 读原文件 → 算 sha256 → 存 `files/<sha256>.snap`（已存在则跳过）→ manifest 追加一行。
- manifest 条目字段：
  ```json
  {
    "snapshot_id": "<sha256[:16]>-<ts>",
    "path": "绝对路径",
    "relative_path": "相对安全根的路径",
    "content_sha256": "<文件内容的sha256>",
    "mode": "file",              // file|dir
    "source": "os_file_task",    // 触发来源
    "session_id": "",
    "conversation_turn": "<用户消息边界 id，见 2.3>",
    "created_at": 1690000000.0,
    "taken_before": "patch/delete"   // 操作类型
  }
  ```
- 补丁涉及多个文件 → 每个文件一条快照，共享同一 `snapshot_batch_id`（同一次 patch 的原子组，回滚时一起恢复）。

### 2.3 回滚点粒度：conversation_turn

- 平台在每次**用户消息 → Agent 回合**开始时，生成/传递一个 `conversation_turn` id（可用 session_id + 消息序号）。
- worker 的 `/file` 请求带上 `conversation_turn`（工具入参加 `conversation_turn` 字段）。
- **批量回滚**：`rollback_turn(conversation_turn)` → 恢复该 turn **开始前** 的快照状态（manifest 中 `conversation_turn` 为该 turn 的快照，或"该 turn 内所有写操作的前一个快照"）。语义 = 回到这个用户消息发出之前。
- **单文件回滚**：`rollback_file(path)` → 默认取该文件**最新一次**快照回滚；`rollback_file(path, snapshot_id)` 指定快照。

### 2.4 回滚执行

`/snapshot` 端点操作：
- `rollback_file`：把目标文件内容还原为快照内容（写回原路径），保留一个"回滚前"快照（防止回滚本身出错导致二次丢失）。
- `rollback_turn`：批量执行该 turn 涉及的全部文件回滚，逐文件同上。
- 回滚后 manifest 保留历史（不删条目），追加一条 `rolled_back: true` 记录便于审计。

### 2.5 保留与清理

- 快照文件按 `created_at` 留存 **默认 7 天**（`OS_AUTOMATION_SNAPSHOT_RETENTION_DAYS` 覆盖）。
- 清理策略：
  - 启动时 + 每次 /snapshot 操作时惰性触发 `_gc_snapshots()`：删超过留存期的 manifest 条目与对应 `.snap`（内容寻址，需检查无其他条目引用才删）。
  - 单文件最大快照体积上限（默认如 50MB，`OS_AUTOMATION_SNAPSHOT_MAX_BYTES`），超过则跳过快照（记录日志 + 返回提示），避免大文件占满磁盘。

### 2.6 与回收站的关系

- **删除**走 `os_recycle_bin`（已有，V4A Delete File 已走回收站）。
- **修改**走快照（本方案新增）。两者互补，共同构成"Agent 自愈"能力：
  - Agent 误删 → `os_recycle_bin list` + `restore`
  - Agent 改错 → `os_snapshot rollback_file`（当前文件）或 `rollback_turn`（大批量）
- Agent 工具（新增 `os_snapshot` 或并入 os_file_task 的 op）：`op=rollback_file|rollback_turn|list_snapshots`。

## 3. 清理 Codex 链路（实施批次 1）

按调研触点清单（`docs/superpowers/plans/2026-09-08-delete-egress-recycle-only.md` 中调研结论）执行：

### 3.1 删文件
- `codex_os/run_os_task.py`、`run_os_task.yaml`、`delete_guard.py`
- 测试：`test_codex_os_delete_guard.py`、`test_codex_os_tool.py`、`api/scripts/test_os_automation_e2e.py`

### 3.2 worker 摘 Codex 段（api/scripts/os_automation_worker.py）
删 `_find_codex_path`、`_codex_version`、`_build_codex_command`、`_build_prompt`、`_guard_delete_in_task`、`_parse_codex_jsonl`、`_run_codex_task`、`_spill_run_output`/`_read_run_output`/`_run_outputs_dir`、do_GET `/output/` 分支、do_POST `/run` 分支、health 的 codex 字段、main 的 codex 启动检查。
**保留**：`/file`（read/search/patch + `_create_approval`/`_consume_approval`/`APPROVAL_TTL_SECONDS`）、`/recycle` 全套、`_resolve_safe_root`/`_is_path_within`、他人未提交的 file_search 改动。
注：放开 os_file_task 确认后，`/file` patch 的 preview/approval_token 流程是否保留？——**保留 preview 校验**（先验证补丁可应用、展示影响）但 apply 不再要求用户确认（approval_token 改为自动签发/免确认）。见 §4。

### 3.3 注册/提示词/前端/文档
- `codex_os/__init__.py`、`positions.yaml` 去掉 run_os_task
- `assistant_agent_service.py` 预挂载元组去 run_os_task
- `function_call_agent.py` 删 run_os_task 专用执行摘要/确认分支
- `tool_policy_entity.py` 高风险名单删 run_os_task **与 os_file_task**（§4 决策）
- `system_prompts.yaml` 删 run_os_task 指令条
- `chat-stream.ts` + spec 改 run_os_task 引用
- 文档：08-os-automation.md 重写、05-security-risk-decisions.md 摘 run_os_task、plan 文档归档 `docs/archive/`、desktop-sandbox-routing-plan.md 改写

### 3.4 DB 迁移
新增 Alembic 迁移：删 `tool_governance_policy` 的 run_os_task 行 + `builtin_tool`/`builtin_tool_provider` 镜像行。

## 4. 放开确认的精确语义

- `tool_policy_entity._DEFAULT_HIGH_RISK_TOOL_NAMES`：移除 `run_os_task`（删除）与 `os_file_task`（放开）。
- `os_recycle_bin` 本就不在名单（删除天然免确认）。
- 替代兜底（Agent 自愈闭环）：
  1. os_file_task 写前快照（本方案）→ 改错可回滚
  2. V4A Delete → os_recycle_bin → 误删可恢复
- 审计不放开：os_file_task/os_recycle_bin 的动作仍全程审计（谁/哪台设备/什么操作/结果）。
- worker `/file` 的 patch：保留 preview 的**校验**（路径/格式/可应用性），apply 不再需要 approval_token（自动放行）。`_patch_is_pure_delete` 仍可用作审计标记。
- 前端确认卡片：os_file_task 不再触发 ToolConfirmationRequired（因移出高风险名单自动生效）。

## 5. 分批实施路线

| 批次 | 内容 | 交付物 |
|---|---|---|
| **1 清理 Codex** | 删 run_os_task/delete_guard/Codex worker 段/注册/测试/DB 迁移 | worker 无 Codex，测试全绿 |
| **2 快照机制** | `/snapshot` 端点 + 写前快照 + rollback_file/rollback_turn + GC + os_snapshot 工具 | 快照/回滚可用，测试覆盖 |
| **3 放开确认（本批次已完成）** | 高风险名单移除 os_file_task + worker patch 免 approval + 审计保留 | 无确认弹窗，Agent 自愈闭环 |
| **4 文档同步** | 08 文档重写/相关文档/归档 plan | 文档与代码一致，graphify 更新 |

> 批次 1、2 可部分并行（都在 worker）；批次 3 依赖 2（放开确认前必须先有回滚兜底）。

### 批次 3 实施说明（2026-09-08）

- `_DEFAULT_HIGH_RISK_TOOL_NAMES` 移除 `os_file_task`；其余高风险工具不变。
- worker `/file` patch：`apply` 直接执行（不再校验 approval_token）；`preview` 保留为只读
  dry-run 校验，仍签发 `approval_token` 仅为兼容旧客户端响应结构。删除 `_consume_approval`
  与 `_patch_is_pure_delete`（无其他调用方）。
- `os_file_task` 工具描述改为"写前自动快照、默认 apply 直接执行、preview 可做 dry-run"；
  `mode` 字段默认值由 `preview` 改为 `apply`；`approval_token` 保留为历史兼容字段。
- 审计保留：工具调用审计基于 AgentThought/调用记录（与高风险名单解耦），名单只决定是否弹确认，
  因此移除 os_file_task 不影响其动作审计。
- 相关测试更新：worker apply 免 token 直接成功 + 写前快照断言；agent 确认链路用例改用
  send_email 等仍高风险工具；新增"os_file_task 免确认直接执行"用例。

## 6. 关键风险与对策

| 风险 | 对策 |
|---|---|
| 快照占磁盘 | 7 天留存 + 单文件 50MB 上限 + 内容寻址去重 |
| 回滚本身出错 | 回滚前再快照一次（保留回滚前状态） |
| 并发写同一文件 | 每路径锁（借鉴 Hermes file_state），快照与写在同一临界区 |
| 快照隐私 | 全存本机，不上云；路径不在 manifest 外暴露 |
| conversation_turn 传递 | 平台侧消息轮次 id 注入工具参数（当前 executor 已传 requester，扩展同机制） |

## 7. 相关文档
- 原作废方案：`docs/superpowers/plans/2026-09-08-delete-egress-recycle-only.md`（归档）
- Hermes 调研：`docs/research/`（file_tools/file_operations/patch_parser/file_state 借鉴）
- 宿主机自动化模块：`docs/prd/modules/08-os-automation.md`（待重写）
