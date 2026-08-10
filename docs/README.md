# 钰心AI 文档导航

> 本文档索引当前生效的架构与设计文档。历史执行记录、已废弃的 OpenAgent 规划文档已清理，不再维护。

## 项目文档

- [架构设计](prd/architecture-design.md)：核心架构、模块设计与目标演进方向
- [演进任务与执行路线](prd/execution-roadmap.md)：阶段任务与完成状态
- [扩展性设计](prd/extensibility-design.md)：第三方能力接入机制
- [工作流与应用编排路线图](prd/orchestration-system-roadmap.md)
- [知识库系统路线图](prd/knowledge-system-roadmap.md)
- [管理后台重构计划](prd/admin-refactor-plan.md)
- [记忆写入优化设计](prd/memory-write-optimization-design.md)

## 子模块文档

- [Agent 池与工具池](prd/modules/01-agent-tool-pool.md)
- [知识库双层设计](prd/modules/02-knowledge-base.md)
- [模型路由、Orchestrator 与可观测性](prd/modules/03-orchestration-infra.md)
- [社交社区与创作者经济](prd/modules/04-social-creator.md)
- [安全要求与风险决策](prd/modules/05-security-risk-decisions.md)
- [文件存储与对象存储](prd/modules/06-file-storage.md)
- [公共 AI 资源配置](prd/modules/07-public-ai-config.md)

## 记忆系统

- [概览](prd/memory-system/00-overview.md)
- [数据模型与写入路径](prd/memory-system/01-data-models-and-write-path.md)
- [存储层与读取路径](prd/memory-system/02-storage-and-retrieval.md)
- [巩固引擎、技能池、Policy 层与 API](prd/memory-system/03-consolidation-skill-policy-api.md)
- [执行文档](prd/memory-system/execution/00-overview.md)

## 说明

项目已由 OpenAgent 更名为 **钰心AI**，全量品牌迁移已完成。旧 `openagent-app` / `openagent-workflow` 导入格式仅作为兼容入口保留。
