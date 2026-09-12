# 钰见我 · 产品总纲

> **状态**：核心产品文档（权威）｜**版本**：v1.0｜**日期**：2026-09-11
> **定位**：本文档统一回答「这是什么产品、要做什么、做到哪了、还要做什么」。**产品形态、功能体系、愿景、发展路径以本文为准**；架构实现细节见 [architecture-design.md](./architecture-design.md)，模块细节见 [modules/](./modules/)。
> **真实性原则**：本文档对每个功能标注**经代码验证的落地状态**（含「壳子/断链」判定），并对一切"文档说已实现、实际不通"的情形明确标注，杜绝虚有图表。

---

## 一、产品形态

### 1.1 时代命题：万物智联

互联网形态正在从「**万物互联**」（设备能联网）升级为「**万物智联**」（设备听一句话就自己动）。

- App 会越来越少，最终收敛为**单一 AI 入口**：你说一句话，它替你点外卖、叫车、开空调、下单。
- **谁掌握入口，谁掌握流量**。这是大厂宁可砸钱也要守住生态的根本原因。
- 不具备「开放接口给 AI 入口」能力的软件，在 AI 时代将被淘汰。

### 1.2 系统形态

**钰见我** 是一个 **面向「钰字辈」合伙人的线上生态赋能系统**。

| 维度 | 内容 |
|---|---|
| **品牌名** | 钰见我 |
| **AI 助理身份** | 小钰（系统的统一入口与人格化形象） |
| **服务对象** | 钰字辈合伙人 |
| **核心目的** | 一个人跑断腿帮不了几个人；有小钰在，她能解决所有人电脑上 90% 的问题，并解决工作痛点与流量获取难题 |
| **壁垒设计** | 线下：已跑起来的供应链矩阵（短期无法追赶）；线上：合伙人的数字资产 + 用户生态（无法被抄走） |

### 1.3 差异化定位

> 本系统**不是**「又一个通用 Agent 调度平台」。调度、编排、工具池等能力是**实现生态赋能的技术底座**，不是产品目标本身。（历史表述已归档澄清，见 [architecture-design.md §1](./architecture-design.md)）

---

## 二、功能体系

功能按「小钰能替合伙人干什么」分为四层：

```text
┌─────────────────────────────────────────────────────────┐
│  L4  生态层  合伙人分身 · 内容板块 · 分销体系 · AI+硬件      │
│      （让能力与流量在合伙人之间流转、变现）                   │
├─────────────────────────────────────────────────────────┤
│  L3  入口层  小钰（语音交互 / 页面交互 双模态）              │
│      （统一 AI 入口，自然语言即操作）                        │
├─────────────────────────────────────────────────────────┤
│  L2  能力层  内容生成 · 设备控制 · 知识库 · 生活服务          │
│      （真正替合伙人干活）                                   │
├─────────────────────────────────────────────────────────┤
│  L1  底座层  Agent 编排 · 工具池 · 记忆 · 模型路由 · 计费     │
│      （支撑上述一切的技术基座）                              │
└─────────────────────────────────────────────────────────┘
```

### L2 能力层（替合伙人干活）

| 能力 | 说明 |
|---|---|
| **内容生成** | 做 PPT / 文档 / 表格、改图片、自动做短视频、做小红书图文 |
| **设备控制** | 操作本机（后台优先，不抢焦点）、修软件故障、改系统设置、定时任务 |
| **知识库** | 存所有文件（含视频素材）；做视频时讨论细节→自翻素材→出片预览→改 |
| **生活服务** | 叫滴滴、点外卖、下单购物（美团/高德等接口） |
| **安全兜底** | 回收站 + 快照：改坏回滚、删错找回，且小钰可自主执行 |

### L4 生态层（能力与流量流转）

| 板块 | 说明 |
|---|---|
| **合伙人分身** | 合伙人把特长/经验打包成「分身」上架，他人按需调用并付费；需审核、可自定价、可更新版本 |
| **内容板块** | 合伙人发图文、上新品、展示内容（类小红书），拓展性强 |
| **分销体系** | 会员才有资格；注册绑定上级；**一级分销**（A→B，B→C 与 A 无关）；B 消费 A 拿 20%，满 5 人升 30%（含前 5 人）；佣金可提现或消费 |
| **AI + 硬件** | 接入 AI 手表/空调/热水器等；硬件供应商成为合伙人进入供应链矩阵 |

---

## 三、当前落地状态（经代码验证）

> 判定标准：
> - ✅ **真可用**：端到端链路完整，已验证可跑通
> - ⚠️ **半可用/断链**：有实现但关键环节缺失或不通
> - ⛔ **未实现**：无对应实现
> - 🎭 **壳子**：有 UI 但无真实后端，或前端用假数据冒充

| # | 功能 | 状态 | 说明（证据） |
|---|---|---|---|
| 1 | 注册 → 登录 → 首页助手流式对话 | ✅ 真可用 | 注册/登录/SSE 流式全链路；真实 LLM |
| 2 | 知识库上传 → 解析入库 → RAG 检索 | ✅ 真可用 | pgvector 索引 + hybrid 检索；⚠️ 大文件同步索引会阻塞请求 |
| 3 | 应用商店 → fork → A2A 调用他人应用 | ✅ 真可用 | `fork_public_app` + `route_public_agents` 真实调用 |
| 4 | 定时任务：创建 → 到点执行 | ✅ 真可用 | Celery beat 注册 `run-scheduled-tasks` 每分钟 |
| 5 | 分销：邀请码 → 绑定 → 佣金 → 提现 | ✅ 真可用 | 全链路已实现；受 `ENABLE_DISTRIBUTION` 开关控制（当前 DB 已开启 True） |
| 6 | 内容生成：PPT/文档/表格/改图/短视频 | ✅ 真可用 | 技能与 builtin tool 均已实现 |
| 7 | 语音交互（实时/ASR/TTS） | ✅ 真可用 | realtime_voice + audio_service + TTS |
| 8 | 设备控制：**桌面端面板直接操作**（回收站/快照） | ✅ 真可用 | 桌面端 IPC → 本机 worker |
| 9 | 设备控制：**对话里让小钰操作电脑** | ✅ 真可用 | §4.1 断链已修复：桌面端登录后注册设备，服务端按账号动态解析 bridge（端到端实测通过） |
| 10 | 电脑控制"不打扰本机"（后台控制） | ✅ 真可用 | §4.2 已闭环：桌面端主进程托管 cua-driver daemon + 二进制随包分发（实测背景点击不抢焦点/不动真实光标） |
| 11 | 知识库视频素材 | ⚠️ 半可用 | 仅存储，**不解析/不抽帧/不入库**（设计后置） |
| 12 | 我的应用列表 | ✅ 真可用 | `my-apps/ListView.vue` 已接真实接口 `GET /my/apps`（分配 + 商店添加双来源），mock 数据已移除 |
| 13 | 知识库「外部数据源」弹窗 | ✅ 真可用 | 弹窗已接真实接口；凭证明文落库/回传、授权不落库、级联清理缺失已修复，并新增定时自动同步 |
| 14 | 工作流商店预览 | ⚠️ 断链 | 跳转路由 `store-workflows-preview` 未注册，点击必报错 |
| 15 | 用户共创 Studio | ⛔ 占位页 | `/studio` 仅占位，侧边栏仍给入口 |
| 16 | 合伙人分身：审核/自定价/版本分发 | ⛔ 未实现 | 商店+上传+A2A 已具备，闭环三要素缺失 |
| 17 | 内容板块（图文/上新/展示） | ⛔ 未实现 | 无后端模型与服务 |
| 18 | 小红书图文生成 | ⛔ 未实现 | 无相关能力 |
| 19 | 生活服务：高德 | ✅ 真可用 | gaode_poi_search |
| 20 | 生活服务：滴滴/美团 | ⛔ 未实现 | 无对应接入 |
| 21 | 手机端 | ⛔ 未实现 | Capacitor 壳就绪，能力未做 |
| 22 | AI + 硬件 | ⛔ 未实现 | 远期 |
| 23 | 首页意图推荐（recommended_agents/tools） | ⚠️ **半壳** | 真实 LLM 意图识别后，推荐池/工具池被硬编码为空/`["general"]` |
| 24 | AI 助手计费 | ✅ 真可用 | §4.3 已修复：`account_id` 由路由层显式传入，计费真实触发（含单测覆盖） |

---

## 四、曾经失效的问题（已修复）

> 这几项曾**文档宣称已实现、实际不通或静默失效**，是"皮套壳子"风险的集中区。
> 下列 §4.1 ~ §4.4 已于本轮全部修复并端到端验证。

### 4.1 【最严重】桌面端 ↔ 服务端 Token 断链（✅ 已修复）

**原现象**：在对话里让小钰操作你的电脑（读文件、改配置、回收站），**实际调用不通**。只有桌面端自身面板点按钮能用。

**原根因**：
- 桌面端启动时用 `crypto.randomBytes` **随机生成** worker/bridge token，仅注入本机 worker 环境变量。
- 服务端要通过 `DESKTOP_BRIDGE_URL` / `DESKTOP_BRIDGE_TOKEN` **静态配置**才能调用。
- **随机值无法与静态配置对齐**，且桌面端**从不向服务端上报 token**。

**修复实现**（登录即设备注册，落地 [desktop-sandbox-routing-plan.md](../research/desktop-sandbox-routing-plan.md) §4.1.1 设计）：

| 层 | 改动 |
|---|---|
| 服务端存储 | 新增 `desktop_device` 表（[desktop_device.py](file:///d:/DEMO/openagent-main/api/internal/model/desktop_device.py)）+ 迁移 `l6a7b8c9d0e1`；token 经 Fernet 加密存储 |
| 服务端服务 | [desktop_device_service.py](file:///d:/DEMO/openagent-main/api/internal/service/desktop_device_service.py)：register 幂等 UPSERT / resolve_bridge 按账号取默认在线设备 / list / revoke |
| 服务端解析 | [desktop_bridge_resolver.py](file:///d:/DEMO/openagent-main/api/internal/service/desktop_bridge_resolver.py)：动态（按账号）优先，静态环境变量回退 |
| 工具层 | `os_file_task` / `os_recycle_bin` / `os_snapshot` / `computer_action` 统一经 resolver 解析 bridge；`computer_action` 新增 `requester` 字段并在 [assistant_agent_service.py](file:///d:/DEMO/openagent-main/api/internal/service/assistant_agent_service.py) 注入 `account_id` |
| 服务端路由 | `POST /desktop/devices/register`、`GET /desktop/devices`、`POST /desktop/devices/<id>/revoke` |
| 桌面端 | [device-registry.js](file:///d:/DEMO/openagent-main/desktop/device-registry.js)：持久化稳定 `device_id`、推导桥对外地址（默认 `http://host.docker.internal:9876`）、登录后上报；main.js 在 set-credential 后触发注册 |

**已实测**：容器内经 `host.docker.internal` 可达宿主机回环 bridge（HTTP 实测 200）；端到端（注册设备 → 工具按账号解析 → 命中宿主机 `/control`、`/file` 且 token 正确）全部通过。

### 4.2 电脑控制"不打扰本机"（✅ 已闭环）

cua-driver 后台控制后端**已实现并通过实测**（后台点击时真实光标全程未动、前台窗口未切换，回执 `delivery.mode=background` / `route=synthetic_events`）。本轮补齐了集成三件套：

1. ✅ 桌面端主进程托管 daemon（[cua-driver-host.js](file:///d:/DEMO/openagent-main/desktop/cua-driver-host.js)：`resolveCuaDriverExe` 定位 → `serve` 常驻 → 就绪探测；退出时停 daemon）。
2. ✅ 打包进安装包（[stage-cua-driver.js](file:///d:/DEMO/openagent-main/desktop/scripts/stage-cua-driver.js) + electron-builder `extraResources` → `resources/cua-driver/`；CI 先装再 stage）。
3. ✅ token/设备链路已随 §4.1 打通（worker 由 `COMPUTER_CONTROL_TOKEN` 鉴权，服务端按账号解析 bridge）。

后端选择：`COMPUTER_CONTROL_BACKEND=auto`（默认）在 daemon 可达时用 cua，否则回退 pyautogui（前台全局模拟，会抢焦点）。

### 4.3 AI 计费静默失效（✅ 已修复）

原问题：`ai_service._get_account_id()` 固定返回 `None`，导致 prompt 优化/代码助手/schema 助手的 `charge_for_feature` **永不执行**。
修复：`optimize_prompt` / `code_assistant_chat` / `openapi_schema_assistant_chat` / `mcp_schema_assistant_chat` 四个 classmethod 增加 `account_id` 形参，由路由层传入 `account.id`；已补单测覆盖计费真实触发。

### 4.4 前端 mock 冒充真实功能（✅ 已修复）

- ✅ [my-apps/ListView.vue](file:///d:/DEMO/openagent-main/ui/src/views/space/my-apps/ListView.vue)：原整页 9 条硬编码假应用已删除，`loadApps` 改为真实调用 `GET /my/apps`。
- ✅ [ExternalDataSourceModal.vue](file:///d:/DEMO/openagent-main/ui/src/views/space/datasets/components/ExternalDataSourceModal.vue)：原新建/同步/解绑全走 `setTimeout` 假成功已删除，改为调用真实 `/external-data-sources` 接口；同时删除不可用的独立页面与路由，弹窗成为唯一真实入口。

后端安全与一致性同步加固（本次随外部数据源接线一并完成）：

| 缺口 | 修复 |
|---|---|
| 凭证明文落库/回传 | 新增 `external_data_source_credentials`（Fernet 加密/解密/脱敏）；落库前加密、调连接器前解密、API 返回前脱敏；迁移 `m7b8c9d0e1f2` 回填历史数据 |
| 授权不落库 | `authorize_data_source` 合并 `auth_config` 并加密落库，避免「先创建后授权」丢凭证 |
| 删除数据源留孤儿 | `physical_delete_external_data_source` 按 `source_type + source_id` 级联清理文档/分段/向量/上传文件 |
| 无定时同步 | 新增 Celery 任务 `run_external_data_source_auto_sync`（每 6 小时，单条失败不阻塞） |
| 未实现类型 | 移除 `enterprise_knowledge`（枚举/工厂/前端/i18n） |
| GitHub 授权字段错位 | `authorize` 兼容 `personal_access_token`，前端合并为 `owner/repo` 单栏 |

---

## 五、愿景与发展路径

### 5.1 终局愿景

**小钰成为全国流量入口**。上下两条生态链同时跑起来：

```text
线下：供应链矩阵（短期无法追赶的壁垒）
线上：AI 生态 + 合伙人数字资产 + 已积累的用户生态（无法被抄走）
        ↓
    完整的万物智联闭环
```

### 5.2 分阶段路径

| 阶段 | 目标 | 关键交付 |
|---|---|---|
| **P1 底座夯实**（当前） | 让已有能力**真正可用**，消灭壳子与断链 | ✅ 设备 token 链路；✅ AI 计费；✅ cua-driver 打包托管；✅ my-apps 接通；✅ 外部数据源硬化 |
| **P2 生态闭环** | 打通合伙人变现 | 分身审核流、自定价、版本分发；内容板块（图文/上新/展示） |
| **P3 入口延伸** | 手机端 + 生活服务 | 手机端上线；滴滴/美团等生活服务接入 |
| **P4 万物智联** | AI + 硬件 | AI 手表/空调/热水器接入；硬件供应商进入供应链矩阵 |
| **P5 流量入口** | 成为全国入口 | 私域直播与小钰联动；生态规模化 |

### 5.3 当前阶段（P1）优先级

> 核心原则：**先让已宣称的能力变成真的，再谈新功能。** 一个能用的功能胜过十个壳子。

1. ✅ 修复设备 Token 断链（§4.1）——"小钰能替你操作电脑"已成立
2. ✅ cua-driver 集成与打包（§4.2）——"不打扰本机"已闭环
3. ✅ 修复 AI 计费（§4.3）——计费已真实触发
4. ✅ 前端 my-apps 接通真实接口（§4.4）——已消灭该壳子
5. ✅ 前端外部数据源接通真实接口 + 后端加固（§4.4）——已消灭最后一个显眼壳子
6. 🟠 工作流商店预览路由修复（§三-14）
7. 🟡 首页推荐池真实化（§三-23）
8. 🟡 Studio 占位页处理：要么实现，要么移除侧边栏入口

---

## 六、文档阅读顺序

| 想了解 | 看哪里 |
|---|---|
| 产品是什么、要做什么、做到哪了 | **本文档** |
| 技术架构与模块设计 | [architecture-design.md](./architecture-design.md) |
| 各模块实现细节 | [modules/](./modules/) |
| 记忆系统设计 | [memory-system/](./memory-system/) |
| 接口契约 | [api/](./api/)、[../api/](../api/) |
| 演进任务状态 | [execution-roadmap.md](./execution-roadmap.md) |
