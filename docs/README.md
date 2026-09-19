# 钰见我 文档导航

> 本文档索引当前生效的架构与设计文档。历史执行记录、已完成规划的路线图已移入 [docs/archive](./archive/README.md)，不再出现在导航中；导航内的每篇文档都应与真实代码保持一致（AGENTS.md「架构文档同步」规则强制）。

## 从这里开始

- [**产品总纲**](prd/product-vision.md)：产品形态、功能体系、**经代码验证的落地状态**（含壳子/断链判定）、愿景与发展路径 —— **产品问题的第一入口**

## 项目文档

- [架构设计](prd/architecture-design.md)：核心架构、模块设计、产品形态与生态蓝图
- [演进任务与执行路线](prd/execution-roadmap.md)：阶段任务与完成状态（唯一仍在维护的 roadmap）
- [扩展性设计](prd/extensibility-design.md)：第三方能力接入机制（工具池/治理/OS 自动化）
- [知识库产品形态设计](prd/knowledge-base-product-form-design.md)：素材中心 / 分级解析 / 容量商业化（KB-P1、KB-P2A、KB-P2B、KB-P3 已落地；KB-P3.5–P3.8 为增量；KB-P4 部分完成、KB-P5 未开始）
- [记忆写入优化设计](prd/memory-write-optimization-design.md)

## 子模块文档

- [Agent 池与工具池](prd/modules/01-agent-tool-pool.md)
- [知识库双层设计](prd/modules/02-knowledge-base.md)
- [Conductor 编排、执行协调与可观测性](prd/modules/03-orchestration-infra.md)
- [合伙人分身与内容板块（生态赋能）](prd/modules/04-social-creator.md)
- [安全要求与风险决策](prd/modules/05-security-risk-decisions.md)
- [文件存储与对象存储](prd/modules/06-file-storage.md)
- [公共 AI 资源配置](prd/modules/07-public-ai-config.md)
- [OS 自动化与设备 Agent](prd/modules/08-os-automation.md)
- [Windows 桌面客户端（设备 Agent 宿主壳）](prd/modules/09-desktop-client.md)

## 记忆系统

- [概览](prd/memory-system/00-overview.md)
- [数据模型与写入路径](prd/memory-system/01-data-models-and-write-path.md)
- [存储层与读取路径](prd/memory-system/02-storage-and-retrieval.md)
- [巩固引擎、技能池、Policy 层与 API](prd/memory-system/03-consolidation-skill-policy-api.md)

## 接口与规范

- [RBAC 权限模型](rbac.md)
- [单机 4C4G 部署与资源规划](deployment-single-node.md)：服务裁减清单、渲染资源分配与闸门、内存超卖风险（含实测数值）
- [分销/余额/订单 API](api/commerce-distribution-api.md)
- [审计日志 API](api/audit-log-api.md)
- [管理端 Agent API](api/admin-agents-api.md)

## 调研与计划归档

- [调研文档](research/)：外部项目调研（Hermes 等）与内部审计快照，结论供参考、不代表当前实现
  - [渲染架构与多租户扩容方案评估](research/render-distribution-and-multi-tenant-scaling.md)：渲染算力成本模型、官方分布式方案、桌面端本机渲染可行性（设计稿）
- [已完成计划的归档](archive/)：已落地的 roadmap / 执行历史（orchestration / knowledge / admin-refactor / memory-system execution）
- [superpowers plans & specs](superpowers/)：近期功能的实现计划与规格（distribution / billing / pricing / auth）

## 说明

项目已由 OpenAgent 更名为 **钰见我**，全量品牌迁移已完成。旧 `openagent-app` / `openagent-workflow` 导入格式仅作为兼容入口保留。根目录不维护 `CONTEXT.md` / `docs/adr/`；领域事实以本导航下文档 + 代码为准。
