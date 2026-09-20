# 跨账号会话交接（2026-09-21）

> **用途**：上一个开发账号积分耗尽，切换新账号/新会话继续本仓库开发。本文件是**会话记忆摘要**（项目记忆与用户记忆随账号丢失，仓库内文件完整保留）。**非权威架构文档**——判断系统现状请以 `docs/README.md` 导航下生效文档为准。

---

## 1. 交接时的仓库状态（2026-09-20 收盘）

- **工作树干净**（无未提交/未跟踪改动），HEAD：`1d5e052d`（KB-P5 拆分计划收口）。
- 两条并行工作流均已收口提交：
  - **ADMIN-P4 管理端 Agent 记忆治理与对话入口**——7 个任务全部完成（`24173fbb` gdpr 删除路由 / `50730d1b` 预算闸门 / `e8d3ba5a` 定时任务 admin_agent 通道 / `b114a53c` 记忆读 API / `7ecf9aaf` 前端对话页+i18n / `173e1ccd` 回归修复 / `5ed812db` 文档同步）。
  - **KB-P5 知识库前台与运维**——A 前台页面（`948fef89`~`30271120`）、B 小钰帮传工具（`d571c752`）、C 同步配额（`e884a7e0`）。
- 计划文件：`docs/superpowers/plans/2026-09-20-admin-agent-p4-memory-governance.md`（已执行完）、`2026-09-20-kb-p5-*.md`（已执行完）。

## 2. 验证基线（新会话判断"改坏了没有"的依据）

- **后端全量回归**（在仓库根 `python -m pytest api/test -q`，输出重定向到 `$env:TEMP\*.txt` 再读尾部，避免 coverage 大表刷屏）：
  **5272 passed / 13 skipped / 2 failed**，2 项均为环境性、非代码缺陷：
  - `test_account_service::test_resend_login_challenge_should_reuse_pending_challenge`——SMTP 邮箱通道未配置。
  - `test_cold_storage_owner_scope::test_module_documents_unwired_status`——相对路径依赖 cwd，`cd api` 后单跑通过。
- **i18n parity**：`npx vitest run src/i18n/__tests__/parity.spec.ts` 必须通过（zh/en 键集合一致 + 全部 `t('...')` 字面量可解析）。
- **vue-tsc**：`npm run type-check` 全仓存在 **45 个既有基线错误**（MemoryNodeDetail.vue、LoginForm.vue、AdminMailConfigView.vue、home.spec.ts 等，均非本批文件）；验收只看**本次改动文件零错误**，不要被基线带偏。

## 3. 环境关键信息（会话记忆，仓库内没有，勿重新摸索）

- **Docker 栈全容器运行**：llmops-db / llmops-neo4j / llmops-api / llmops-ui / llmops-redis / llmops-celery / llmops-nginx 等（`docker ps`）。
- **容器不热加载代码**：api 容器 bind-mount 宿主 `api/`，但 Python 进程启动后不 reload。**改后端代码后必须 `docker restart llmops-api`** 并等 `(healthy)`（历史教训：改完不重启，接口返回 404/旧行为）。
- **Grep 工具在环境不可用**（rg not found）：文件内容搜索改用 PowerShell `Select-String -Path ... -Pattern ...`。
- **Neo4j 凭据**：`neo4j / openagent123`（cypher-shell `-u neo4j -p openagent123`）。
- **admin 登录**：`admin / Root123456`（来自 `api/.env` 的 `ADMIN_INITIAL_*`）；登录接口 `POST /admin/auth/login`，返回 JWT 放 `Authorization: Bearer`。
- **真库验证套路**（记忆链路）：登录 → 构造主体 Episode 节点（Neo4j 属性 `admin_user_id` + `agent_id`）→ `GET /admin/agents/<id>/memory/stats` 应非零 → `POST /admin/memory/gdpr-delete`（`subject_type=agent`）→ stats 归零。

## 4. 待办（接替的下一步，优先级以 roadmap 为准）

- **ADMIN-P5**：MCP 动态身份注入（roadmap「未落地」唯一 ADMIN 项）。
- **roadmap UX-1 ~ UX-8**：管理后台 UX 改造（ToolsView 真工具管理 / AppsView 重写 / 资源运营上架下架 / 审计日志跳转 / 商店预览等）。
- **KB-P6**：外部素材获取（yt-dlp，未立项/默认关闭）。
- 每阶段执行前先读对应计划文档（`docs/superpowers/plans/`），若计划过期需先更新。

## 5. 协作规则提醒（AGENTS.md 全文为准，重点摘录）

- **提交纪律**：用**显式 pathspec** `git add <file>...` 提交，避免误收并行工作树；commit message 带阶段标识（如 `（ADMIN-P4 Task N）`）。
- **接线审查（强制）**：宣告完成前逐一回答「新符号的入口在哪」——Celery 任务要有派发点、新表要有读写两路径、builtin 工具要有挂载点、新路由要注册+调用方；只靠单测全绿不算交付。
- **架构文档同步（强制）**：涉及架构的改动完成后同步更新 `docs/prd/` 对应文档 + `docs/README.md` 登记，并运行 `python -m graphify update .`。
- **i18n（强制）**：前端文案只走 i18n 键；zh-CN / en-US 双侧镜像；提交前 parity 测试通过。
- **RBAC**：权限点只增不删，下线功能需迁移清理；`docs/rbac.md` 不逐条抄清单，以 `api/internal/core/rbac.py` 为唯一事实源。
- **诚实披露**：未接线项必须在回复与文档中标注「已提供能力但未接入」，不得含糊写成「已实现」。
