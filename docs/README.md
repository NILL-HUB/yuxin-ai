# 钰见我 文档导航

> 本文档索引当前生效的架构与设计文档。历史执行记录、已完成规划的路线图已移入 [docs/archive](./archive/README.md)，不再出现在导航中；导航内的每篇文档都应与真实代码保持一致（AGENTS.md「架构文档同步」规则强制）。

## 从这里开始

- [**产品总纲**](prd/product-vision.md)：产品形态、功能体系、**经代码验证的落地状态**（含壳子/断链判定）、愿景与发展路径 —— **产品问题的第一入口**

## 项目文档

- [架构设计](prd/architecture-design.md)：核心架构、模块设计、产品形态与生态蓝图
- [主动式 Agent 生态设计](prd/proactive-agent-ecosystem.md)：Instinct 对标与本土化——主动式形态要点、目标环境差异变量与变体矩阵、独立 App 入口决策、优劣势与警戒线、国内外水土与合规差异
- [演进任务与执行路线](prd/execution-roadmap.md)：阶段任务与完成状态（唯一仍在维护的 roadmap）
- [扩展性设计](prd/extensibility-design.md)：第三方能力接入机制（工具池/治理/OS 自动化）
- [知识库产品形态设计](prd/knowledge-base-product-form-design.md)：素材中心 / 分级解析 / 容量商业化（KB-P1、KB-P2A、KB-P2B、KB-P3 已落地；KB-P3.5–P3.8 为增量；KB-P4、KB-P5 已完成）
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
- [沙箱运行时（admin 统一配置与多后端热切换）](prd/modules/10-sandbox-runtime.md)

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
  - [**AI 支付生态接入评估**](research/2026-10-02-ai-payment-ecosystem-access-assessment.md)：微信 AI 支付（SkillHub/SkillPay）与支付宝 Agent Pay 的准入门槛、技术集成路径、合规边界，以及钰我见「供给侧接入」落地建议（调研结论，未实现）
  - [**能力可用性与用户链路体检（Web 环境）**](research/2026-09-29-capability-and-user-path-audit.md)：**当前最优参考**——Web 环境「真能干什么/不能干什么」、云端与本地客户端依赖矩阵、生产就绪度缺陷清单与修复路径（含真实用户链路实测）
  - [渲染架构与多租户扩容方案评估](research/render-distribution-and-multi-tenant-scaling.md)：渲染算力成本模型、官方分布式方案、桌面端本机渲染可行性（设计稿）
  - [配置治理：admin 统一化审计清单](research/config-inventory.md)：env 读取点分级（已修复/死代码/合理保留/待评估），存储 configs 接入入口
- [已完成计划的归档](archive/)：已落地的 roadmap / 执行历史 / 计划与规格（orchestration / knowledge / admin-refactor / memory-system execution / superpowers-plans / superpowers-specs / research-completed）
- [superpowers plans & specs](superpowers/)：**仅保留尚未落地或仍在途**的实现计划与规格
  - [手机端遥控与多设备协作设计](superpowers/specs/2026-10-03-mobile-remote-control-multi-device-design.md)：手机端精简遥控面（设备自动发现/显式选设备/任务卡/审批/系统级推送）+ 设备网关（子项目 B）+ 执行位置路由 + 审批挂起-复活模型 + 消息准入三途径；**设计稿，未实现**（推送已定：友盟+个推双通道 admin 热切换）
  - [手机端遥控 P0 实施计划](superpowers/plans/2026-10-03-mobile-p0-device-list-and-binding.md)：设备管理接口、会话级设备绑定与按设备解析 bridge、设备定向推送房间、设备列表页、Capacitor 壳与遥控面骨架；**P0 已落地（2026-10-04）**——系统推送、设备网关（WS 下行）与审批挂起待 P1
  - [设备网关 P1 实施计划](superpowers/plans/2026-10-04-device-gateway-p1.md)：云端→设备常驻下行通道（`/device` 命名空间 + bridge_token 鉴权 + Redis 关联等待 + 设备 HTTP 回传 + `gateway_mode` 路由）；**进行中**
  - [用户侧统一文件中心（虚拟目录树）设计](superpowers/specs/2026-09-30-user-file-center-design.md)：用户可见的文件目录树管理面 + 可被 Agent 使用的 `file_center` 工具集（阶段 1 已落地；阶段 2 服务端已落地、桌面端 UI 与互传未做；阶段 3 外部云盘未实现——见 §10 落地状态）
  - [L2 全模态（说话人切分/OCR 块）实现计划](superpowers/plans/2026-09-24-kb-l2-omni-diarization.md)：未实现
  - [Qwen 多模态插件 + 助手 Omni 计划](superpowers/plans/2026-09-24-qwen-mm-plugins-assistant-omni.md)：未实现
  - [管理端 Agent 治理设计](superpowers/specs/2026-09-15-admin-agent-governance-design.md)：P1–P5 核心已落地；`apply_draft` 前端页、`verify_principal_token` 消费方、`EntityResolver` 接线三处仍未闭合

> **归档判定**：计划/规格对应的功能已落地，或已被后续方案取代、或对应模块已下线，即移入 `docs/archive/superpowers-plans/`、`docs/archive/superpowers-specs/`，避免留在外面误导 Agent。当前仍留在 `superpowers/` 的均为未完成/在途项。
> **2026-10-03 归档**：CLI 工具池（source_type=cli）、管理端 CLI 管理页相关 2 计划 + 2 规格，以及 MCP 配置表单化（批次 1）设计，均已落地并归档（见 `archive/superpowers-{plans,specs}/`）。
> **2026-10-04 归档**：用户文件中心前端翻新 + 统一按钮组件（AppButton）与主题贯通修复（已落地；文件中心 spec 本身仍留在 `superpowers/specs/`，因阶段 2 桌面端 UI/互传、阶段 3 云盘未做）。

## 说明

项目已由 OpenAgent 更名为 **钰见我**，全量品牌迁移已完成。旧 `openagent-app` / `openagent-workflow` 导入格式仅作为兼容入口保留。根目录不维护 `CONTEXT.md` / `docs/adr/`；领域事实以本导航下文档 + 代码为准。
