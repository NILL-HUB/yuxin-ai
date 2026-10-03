# 归档文档

> 本目录存放**已完成并落地**的规划/路线图与执行历史快照。归档文档不代表系统现状——判断当前架构请以 [docs/README.md](../README.md) 导航下的生效文档为准。

## 已归档清单

| 文档 | 原位置 | 归档原因 |
| --- | --- | --- |
| [orchestration-system-roadmap.md](./orchestration-system-roadmap.md) | docs/prd/ | 工作流/编排规划已全部落地（TaskPlan + ExecutionCoordinatorService 统一） |
| [knowledge-system-roadmap.md](./knowledge-system-roadmap.md) | docs/prd/ | 知识库双层检索规划已全部落地 |
| [admin-refactor-plan.md](./admin-refactor-plan.md) | docs/prd/ | admin 端独立页面重构已落地；剩余为愿景设计 |
| [2026-09-08-delete-egress-recycle-only.md](./2026-09-08-delete-egress-recycle-only.md) | docs/superpowers/plans/ | run_os_task/Codex 删除护栏方案——run_os_task 链路已整体移除，方案作废，由 `docs/archive/research-completed/local-file-snapshot-rollback-plan.md`（os_file_task 快照回滚 + os_recycle_bin）取代 |
| [memory-system-execution/](./memory-system-execution/) | docs/prd/memory-system/execution/ | 记忆系统 10 阶段执行历史快照（A-H track） |
| [cleanup-reports/](./cleanup-reports/) | docs/cleanup-reports/ | 每日代码整洁度清理报告（一次性执行记录，2026-08-13 ~ 08-17） |
| [research-completed/](./research-completed/) | docs/research/ | 已完成落地/已作废的调研快照（执行历史，非当前参考）。第一批 2026-09-11 归档；**第二批 2026-10-03 归档**：`better-harness`（未采用）、`deepseek-harness`（PoC 未启动）、`headroom`（设计已落地为 `api/internal/core/context_compression/`）、`hermes-agent-v0-20-comparison` 与 `hermes-v0.20-capability-deep-dive`（含 `run_os_task`/访客通道等已移除事实，被现状取代）、`hermes-v0.20.5-saas-evaluation`（评估方向未采用）、`stablyai-orca`（未采用）、`vibevoice-adoption`（未采用）、`cli-anything`（CLI 工具池已改自研，方案作废） |
| [2026-09-21-account-handoff.md](./2026-09-21-account-handoff.md) | 会话交接 | 跨账号切换的会话记忆摘要（仓库状态/验证基线/环境信息/待办）；新账号 Agent 接手必读 |
| [superpowers-plans/](./superpowers-plans/) | docs/superpowers/plans/ | 已落地/已作废的实施计划（distribution / billing / pricing / auth / KB-P1~P6 / admin-agent P1a~P5 / UX 系列 / global-control-config / tool-credential / scrapling / user-tool-chain-routing-hardening / user-file-center 系列（backend·recycle-restore·agent-tools·artifact-collection·frontend）等），功能均已落地或方案已被取代；2026-09-24 归档，Scrapling 2026-09-27 归档，用户端工具链与路由硬化 2026-09-29 归档，用户文件中心 2026-09-30 归档，**2026-10-03 归档：CUA observe-act 回路接入、管理端 Agent 治理域 UI 翻新、管理员 Agent 定时任务统一、CLI 工具池、CLI 管理端管理页、本机终端工具（cmd/gitbash + 删除命令守卫）**（均已落地） |
| [superpowers-specs/](./superpowers-specs/) | docs/superpowers/specs/ | **已落地**的设计规格（distribution / billing / auth / pricing / desktop-client / login-routing / external-data-source / my-apps / app-assignment / video-p4 / video-timeline / scrapling / user-tool-chain-routing-hardening / sandbox-config-multi-backend），能力均已实现；2026-09-24 归档，Scrapling 2026-09-27 归档，用户端工具链与路由硬化、沙箱配置多后端热切换 2026-09-29 归档，**2026-10-03 归档：CUA observe-act 回路设计、管理员 Agent 定时任务统一设计、第三方工具凭证收编 admin 设计、CLI 工具池设计、CLI 管理页设计、MCP 配置表单化（批次 1）设计**（核心范围已落地）；**2026-10-04 归档：会话级工作区授权设计**（worker 授权根校验 + session_workspace_scope 表 + os_workspace_scope 授权工具，已落地） |

> 说明：`docs/superpowers/plans/`、`docs/superpowers/specs/` 存放**尚未落地或仍在途**的计划与规格；已落地的计划/规格移入本目录。2026-10-03 复核后仍在原地的为：文件中心（阶段 2 桌面端 UI/互传、阶段 3 云盘未做）、L2 全模态与 Qwen 多模态插件（未实现）、管理端 Agent 治理（`apply_draft` 前端页、`verify_principal_token` 消费方、`EntityResolver` 接线三处仍未闭合）。
