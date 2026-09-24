# 归档文档

> 本目录存放**已完成并落地**的规划/路线图与执行历史快照。归档文档不代表系统现状——判断当前架构请以 [docs/README.md](../README.md) 导航下的生效文档为准。

## 已归档清单

| 文档 | 原位置 | 归档原因 |
| --- | --- | --- |
| [orchestration-system-roadmap.md](./orchestration-system-roadmap.md) | docs/prd/ | 工作流/编排规划已全部落地（TaskPlan + ExecutionCoordinatorService 统一） |
| [knowledge-system-roadmap.md](./knowledge-system-roadmap.md) | docs/prd/ | 知识库双层检索规划已全部落地 |
| [admin-refactor-plan.md](./admin-refactor-plan.md) | docs/prd/ | admin 端独立页面重构已落地；剩余为愿景设计 |
| [2026-09-08-delete-egress-recycle-only.md](./2026-09-08-delete-egress-recycle-only.md) | docs/superpowers/plans/ | run_os_task/Codex 删除护栏方案——run_os_task 链路已整体移除，方案作废，由 `docs/research/local-file-snapshot-rollback-plan.md`（os_file_task 快照回滚 + os_recycle_bin）取代 |
| [memory-system-execution/](./memory-system-execution/) | docs/prd/memory-system/execution/ | 记忆系统 10 阶段执行历史快照（A-H track） |
| [cleanup-reports/](./cleanup-reports/) | docs/cleanup-reports/ | 每日代码整洁度清理报告（一次性执行记录，2026-08-13 ~ 08-17） |
| [research-completed/](./research-completed/) | docs/research/ | 已完成落地的调研/验证快照（执行历史，非当前参考；2026-09-11 归档） |
| [2026-09-21-account-handoff.md](./2026-09-21-account-handoff.md) | 会话交接 | 跨账号切换的会话记忆摘要（仓库状态/验证基线/环境信息/待办）；新账号 Agent 接手必读 |
| [superpowers-plans/](./superpowers-plans/) | docs/superpowers/plans/ | 48 份**已落地/已作废**的实施计划（distribution / billing / pricing / auth / KB-P1~P6 / admin-agent P1a~P5 / UX 系列 / global-control-config / tool-credential 等），功能均已落地或方案已被取代；2026-09-24 归档 |
| [superpowers-specs/](./superpowers-specs/) | docs/superpowers/specs/ | 11 份**已落地**的设计规格（distribution / billing / auth / pricing / desktop-client / login-routing / external-data-source / my-apps / app-assignment / video-p4 / video-timeline），能力均已实现；2026-09-24 归档 |

> 说明：`docs/superpowers/plans/`、`docs/superpowers/specs/` 现只保留**尚未落地或仍在途**的计划与规格（当前为 2 份计划）；`2026-09-15-admin-agent-governance-design.md` 因仍含未闭合缺口（`apply_draft` 前端页、`verify_principal_token` 消费方、`EntityResolver` 接线）而留在原地。
