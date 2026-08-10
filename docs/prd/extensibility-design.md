# 系统可扩展性设计：统一能力接入机制

> **定位**：本文档定义 钰心AI 平台的第三方能力集成架构，解决"如何快速集成 GitHub 上新发布的 Agent 项目/工具/能力"的扩展性问题。
>
> **主文档**：[architecture-design.md](./architecture-design.md)
> **关联模块**：[modules/01-agent-tool-pool.md](./modules/01-agent-tool-pool.md) | [modules/03-orchestration-infra.md](./modules/03-orchestration-infra.md)

---

## 1. 背景与目标

### 1.1 问题陈述

系统已基本脱离 钰心AI，成为自研架构的多租户 Agent 平台，功能依托第三方模型 API 实现。当前需要提升可扩展性，使新发布的 GitHub Agent 项目能快速集成进来实现功能复现。

### 1.2 设计目标

- 任何第三方能力（MCP / REST API / SDK）能在最少代码改动下接入 Agent 工具池
- MCP 和 API 型接入零代码（配置即用）
- SDK 型接入少量代码（~100 行 Provider）
- 复用现有工具治理框架（ToolPolicyFilter + ToolRanker + RuntimeToolMountService），不重造轮子

### 1.3 非目标

- **不做完整第三方应用托管**（AppHost / docker 嵌入 / iframe）：经评估成本过重，且 iframe 模式存在 UI 割裂、付费/账号治理复杂、Agent 无法编排纯前端应用等问题，明确放弃
- **不重构现有 Agent 引擎**：不引入第二套 Agent 框架（如直接融入 OpenClaw 这类 agent 框架会导致双引擎冲突）
- **不做统一插件契约**：不同颗粒度的项目用不同策略，强行统一抽象会让简单工具变重、大颗粒被裁剪

---

## 2. 现状评估

### 2.1 现有五层扩展能力

| 层 | 定位 | 扩展机制 | 可复用资产 | 关键缺口 |
|---|---|---|---|---|
| App 层 | LLM Agent 应用载体（4 种 AppType 全是 LLM 形态） | AppType 枚举 | token 鉴权、发布流程 | 无外部 URL/容器字段；执行链路强耦合 Agent 引擎 |
| 工作流层 | DAG 编排（14 种固定节点） | NodeType 枚举 + NodeExecutor Protocol | graph_engine、VariablePool | 无"调用外部应用"节点；tool 节点仅支持 builtin/api |
| 工具治理层 | 统一采集 7 类来源为 BaseTool | ToolSourceType 枚举 + ToolCandidateCollector | ToolPolicyFilter + ToolRanker + RuntimeToolMountService（**最成熟**） | 4 个工厂无统一接口；采集器 `_collect_*` 硬编码方法列表 |
| Agent 层 | BaseAgent + LangGraph | 继承 BaseAgent | 基类清晰、SSE 流式 | `create_runtime_agent` 是 if/else，无注册式接入 |
| 远端能力 | MCP/Skill/A2A | 已有远端调用实践 | MCP streamable_http、Skill SCF 执行器、A2A 协议 | 仅限"工具"维度 |

### 2.2 核心判断

工具治理层是**最成熟的可复用资产**。`ToolCandidateCollector` + `ToolPolicyFilter` + `ToolRanker` + `RuntimeToolMountService` 这套治理框架已能统一处理 7 类来源，再加一类成本很低。**核心缺口是采集入口硬编码**——新增工具来源必须改 `tool_inventory_service.py` 加新方法，没有注册式发现机制。

---

## 3. 集成决策框架

不同形态的第三方项目，集成策略不同。不存在单一策略覆盖全谱系。

### 3.1 三个判断维度

| 维度 | 判断 | 集成策略 |
|---|---|---|
| **它是框架/库还是完整应用？** | 框架/库 → 融入或 MCP 接入；完整应用 → docker 托管（本次不做） | 决定集成深度 |
| **它和你系统是竞争还是互补？** | 竞争（如 agent 引擎）→ 只取能力作工具；互补（如视频编辑）→ 可整体托管 | 决定是否整体拉入 |
| **它暴露接口了吗？** | 有 MCP/API → 走现有工厂；只有前端 → AppHost 兜底（本次不做） | 决定接入路径 |

### 3.2 第三方能力接入优先级

| 优先级 | 条件 | 接入方式 | 代码改动 |
|---|---|---|---|
| **首选** | 应用暴露 MCP | 现有 MCP 工厂（McpToolFactory） | 零代码，admin 配置即用 |
| **次选** | 应用有 REST API | 现有 API Tool 工厂（ApiProviderManager） | 零代码，admin 配置即用 |
| **兜底** | 应用只有 SDK/库 | 实现 ToolProvider 协议 + 注册 | ~100 行 |

### 3.3 典型项目集成示例

**OpenClaw（AI Agent 执行框架，25 万 star）**：
- 形态：框架/库，与系统 Agent 引擎**竞争**
- 策略：**只取能力作工具**，不整体拉入（避免双引擎冲突）
- 接入：若暴露 MCP → admin 配 MCP Provider，零代码；若只有 SDK → 写 OpenClawToolProvider

**OpenCut（视频编辑器，64k star）**：
- 形态：完整 GUI 应用，与系统**互补**
- 策略：本次不做整体托管（AppHost 已明确放弃）。若 OpenCut 未来暴露 MCP，则其结构化操作（剪切/导出/转码）可通过 MCP 接入 Agent

---

## 4. 核心设计：ToolProvider 统一接口

### 4.1 ToolProvider 协议

定义工具来源的统一接口。所有第三方能力通过实现此协议接入工具池。

```python
# api/internal/core/tools/tool_provider.py

from typing import Protocol
from uuid import UUID
from api.internal.entity.tool_inventory_entity import ToolSourceType


class ToolProvider(Protocol):
    """工具来源的统一接口。

    所有第三方能力通过实现此接口接入工具池。
    现有 8 个 _collect_* 方法将提取为实现此接口的 Provider 类。
    """

    @property
    def source_type(self) -> ToolSourceType:
        """此 Provider 提供的工具来源类型。"""
        ...

    def collect(self, account_id: UUID, session) -> list[dict[str, object]]:
        """采集候选工具。

        返回格式与现有 ToolCandidateCollector._collect_* 方法一致：
        list[dict]，每个 dict 包含 id/name/description/source_type/
        provider_id/inputs/metadata/visibility/enabled/task_keywords 等字段。

        Args:
            account_id: 用户/租户 ID，用于隔离
            session: 数据库会话

        Returns:
            候选工具字典列表
        """
        ...
```

**设计决策：返回值保持 `list[dict]`，不引入强类型。**

理由：
1. 现有 8 个采集方法都返回 dict，强制改强类型会引发大面积改动，违背渐进式原则
2. dict 格式已被 `normalize_tool_metadata` + `ToolPolicyFilter` + `ToolRanker` 验证过，稳定可用
3. 后续可在稳定后渐进引入 `RuntimeToolDescriptor` 强类型，不阻塞当前设计

### 4.2 ToolProviderRegistry 注册表

替换硬编码方法列表，实现注册式发现。

```python
# api/internal/core/tools/tool_provider_registry.py

import logging
from uuid import UUID
from api.internal.core.tools.tool_provider import ToolProvider

logger = logging.getLogger(__name__)


class ToolProviderRegistry:
    """工具来源注册表：注册式发现，替换硬编码 _collect_* 方法列表。

    使用方式：
    1. 启动时注册所有内置 Provider（ApiToolProvider, McpToolProvider 等）
    2. 第三方 SDK 型能力实现 ToolProvider 后调用 register() 注册
    3. ToolCandidateCollector.collect() 改为调用 registry.collect_all()
    """

    def __init__(self):
        self._providers: list[ToolProvider] = []

    def register(self, provider: ToolProvider) -> None:
        """注册一个工具来源 Provider。"""
        self._providers.append(provider)
        logger.info(f"ToolProvider registered: {provider.source_type}")

    def collect_all(self, account_id: UUID, session) -> list[dict[str, object]]:
        """遍历所有已注册 Provider 采集候选工具。

        单个 Provider 失败不影响其他 Provider，降级记录日志。
        """
        candidates = []
        for provider in self._providers:
            try:
                candidates.extend(provider.collect(account_id, session))
            except Exception:
                logger.warning(
                    f"Provider {provider.source_type} collect failed",
                    exc_info=True,
                )
        return candidates

    def list_providers(self) -> list[dict[str, str]]:
        """列出所有已注册 Provider（供 admin 展示）。"""
        return [
            {"source_type": p.source_type.value, "class": type(p).__name__}
            for p in self._providers
        ]
```

### 4.3 现有采集方法提取为 Provider

把 `ToolCandidateCollector` 的 8 个 `_collect_*` 方法提取为独立 Provider 类，**逻辑不变，只是从方法提取为类**。

| 现有方法 | 提取为 | source_type | 文件位置 |
|---|---|---|---|
| `_collect_api_tools` | `ApiToolProvider` | API | `providers/api_tool_provider.py` |
| `_collect_mcp_tools` | `McpToolProvider` | MCP | `providers/mcp_tool_provider.py` |
| `_collect_builtin_tools` | `BuiltinToolProvider` | BUILTIN | `providers/builtin_tool_provider.py` |
| `_collect_knowledge_tools` | `KnowledgeToolProvider` | KNOWLEDGE | `providers/knowledge_tool_provider.py` |
| `_collect_user_memory_tools` | `UserMemoryToolProvider` | USER_MEMORY（新增枚举） | `providers/user_memory_tool_provider.py` |
| `_collect_external_data_tools` | `ExternalDataToolProvider` | EXTERNAL_DATA（新增枚举） | `providers/external_data_tool_provider.py` |
| `_collect_skill_tools` | `SkillToolProvider` | SKILL | `providers/skill_tool_provider.py` |
| `_collect_workflow_tools` | `WorkflowToolProvider` | WORKFLOW | `providers/workflow_tool_provider.py` |

**每个 Provider 的 collect 逻辑与原 `_collect_*` 方法逐行一致**，只是：
- 从 `ToolCandidateCollector` 的方法 → 独立类的 `collect` 方法
- 依赖（如 `builtin_tool_service`、`inventory`）通过构造函数注入
- 可逐个迁移、逐个验证，不一次性全改

### 4.4 ToolCandidateCollector 改造

```python
@inject
class ToolCandidateCollector:
    """工具候选收集器：通过 ToolProviderRegistry 遍历所有已注册来源。"""

    def __init__(
        self,
        session=None,
        builtin_tool_service: BuiltinToolService | None = None,
        inventory: ToolInventory | None = None,
        registry: ToolProviderRegistry | None = None,
    ):
        self.session = session or db.session
        self.builtin_tool_service = builtin_tool_service
        self.inventory = inventory or ToolInventory()
        self.registry = registry or self._build_default_registry()

    def _build_default_registry(self) -> ToolProviderRegistry:
        """构建默认注册表，注册所有内置 Provider。"""
        registry = ToolProviderRegistry()
        registry.register(ApiToolProvider(self.inventory))
        registry.register(McpToolProvider(self.inventory))
        registry.register(BuiltinToolProvider(self.builtin_tool_service, self.inventory))
        registry.register(KnowledgeToolProvider(self.inventory))
        registry.register(UserMemoryToolProvider(self.inventory))
        registry.register(ExternalDataToolProvider(self.inventory))
        registry.register(SkillToolProvider(self.inventory))
        registry.register(WorkflowToolProvider(self.inventory))
        return registry

    def collect(self, account_id: UUID) -> list[dict[str, object]]:
        """遍历注册表采集所有候选工具。"""
        return self.registry.collect_all(account_id, self.session)
```

### 4.5 第三方 SDK 型接入示例

当第三方项目只有 SDK（无 MCP/API）时，写一个 Provider 注册即可：

```python
# api/internal/core/tools/providers/openclaw_tool_provider.py

from uuid import UUID
from api.internal.core.tools.tool_provider import ToolProvider
from api.internal.core.tools.tool_provider_registry import ToolProviderRegistry
from api.internal.entity.tool_inventory_entity import ToolSourceType, normalize_tool_metadata


class OpenClawToolProvider:
    """OpenClaw 能力接入：把 OpenClaw SDK 的方法包装为工具候选。"""

    @property
    def source_type(self) -> ToolSourceType:
        return ToolSourceType.EXTERNAL_SDK  # 新增枚举值

    def collect(self, account_id: UUID, session) -> list[dict[str, object]]:
        # 调用 OpenClaw SDK 获取可用能力列表
        from openclaw import list_capabilities  # 假设的 SDK

        candidates = []
        for cap in list_capabilities():
            metadata = normalize_tool_metadata({
                "tool_pool": "general",
                "capabilities": [cap.name],
                "risk_level": "medium",
                "permission_scope": "user",
            })
            candidates.append({
                "id": f"openclaw:{cap.name}",
                "name": cap.name,
                "description": cap.description,
                "source_type": self.source_type.value,
                "inputs": cap.parameters,
                "metadata": metadata,
                "visibility": "private",
                "enabled": True,
                "task_keywords": cap.keywords,
            })
        return candidates
```

注册方式：在 `module.py` 的 DI 绑定中注册，或在 `_build_default_registry()` 中条件注册。

---

## 5. ToolSourceType 枚举补全

现有枚举缺少 `USER_MEMORY` 和 `EXTERNAL_DATA`（这两个来源存在但未在枚举中定义），新增 `EXTERNAL_SDK` 用于第三方 SDK 型接入：

```python
class ToolSourceType(str, Enum):
    API = "api"
    MCP = "mcp"
    BUILTIN = "builtin"
    KNOWLEDGE = "knowledge"
    WORKFLOW = "workflow"
    SKILL = "skill"
    AGENT_BINDING = "agent_binding"
    USER_MEMORY = "user_memory"           # 新增：用户记忆工具
    EXTERNAL_DATA = "external_data"       # 新增：外部数据源工具
    EXTERNAL_SDK = "external_sdk"         # 新增：第三方 SDK 型工具
```

---

## 6. 与现有代码的集成点

| 文件 | 改动 | 风险 | 说明 |
|---|---|---|---|
| `api/internal/entity/tool_inventory_entity.py` | ToolSourceType 新增 3 个枚举值 | 低 | 纯枚举扩展 |
| `api/internal/core/tools/tool_provider.py` | 新增 ToolProvider 协议 | 无 | 新文件 |
| `api/internal/core/tools/tool_provider_registry.py` | 新增 Registry | 无 | 新文件 |
| `api/internal/core/tools/providers/*.py` | 新增 8 个 Provider 类（从现有方法提取） | 中 | 逐个迁移验证 |
| `api/internal/service/tool_inventory_service.py` | `collect()` 改为调 Registry；`__init__` 注入 Registry | 中 | 核心方法改动，需测试 |
| `api/app/http/module.py` | binder 绑定 ToolProviderRegistry 单例 | 低 | DI 注册 |

### 迁移策略（渐进式）

1. **Phase 1**：新增 ToolProvider 协议 + Registry + 1 个 Provider（如 ApiToolProvider），`collect()` 改为 Registry + 剩余硬编码方法并行。验证 ApiToolProvider 输出与原方法一致。
2. **Phase 2**：逐个迁移剩余 7 个方法为 Provider，每迁移一个验证一次。
3. **Phase 3**：`collect()` 完全改为遍历 Registry，移除所有硬编码 `_collect_*` 方法。
4. **Phase 4**：接入第一个第三方 SDK 型 Provider（如 OpenClaw），验证完整链路。

---

## 7. Admin 管理面

复用现有 admin 资源编排板块（详见 [admin-refactor-plan.md](./admin-refactor-plan.md)），新增"已注册扩展"列表页：

| 管理项 | 说明 | 数据来源 |
|---|---|---|
| MCP 工具管理 | 已有（AdminMcpView） | McpProvider 表 |
| API 工具管理 | 已有（ToolsView） | ApiTool 表 |
| 已注册 ToolProvider 列表 | **新增**，只读展示所有已注册 Provider | `ToolProviderRegistry.list_providers()` |
| SDK 型扩展详情 | **新增**，展示 Provider 的 source_type、工具数量、健康状态 | Provider.collect() 结果统计 |

技术栈一致：Vue 3 + Arco Design 前端，Flask + SQLAlchemy 后端。新增一个 admin API 端点暴露 `list_providers()` 即可。

---

## 8. 后续快速集成标准流程

当 GitHub 上出现好用的能力项目时：

```
Step 1: 判断它暴露什么接口？
  ├─ MCP → admin 配 MCP Provider，零代码，完成
  ├─ REST API → admin 配 API Tool，零代码，完成
  └─ SDK → 进入 Step 2

Step 2: 写 XxxToolProvider（实现 ToolProvider 协议）
  ├─ 调用 SDK 获取能力列表
  ├─ 包装为工具 dict（含 metadata 治理字段）
  └注册到 ToolProviderRegistry

Step 3: 配置治理元数据
  ├─ risk_level（safe/low/medium/high/dangerous）
  ├─ permission_scope（system/tenant/project/user/public）
  └─ cost_level（low/medium/high）

Step 4: 绑定到目标 Agent 的工具池

Step 5: Agent 即可在对话框调用
```

**耗时预估**：
- MCP/API 型：配置即用，分钟级
- SDK 型：~100 行 Provider 代码，半天级

---

## 9. 关键决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 是否做 AppHost 完整应用托管 | **不做** | 成本过重；iframe 模式 UI 割裂、付费/账号治理复杂；Agent 无法编排纯前端应用 |
| 是否引入统一插件契约 | **不引入** | 不同颗粒度用不同策略，强行统一会让简单工具变重 |
| 是否把第三方 agent 框架整体拉入 | **不拉入** | 与现有 Agent 引擎竞争，导致双引擎冲突；只取能力作工具 |
| ToolProvider 返回值类型 | `list[dict]`（非强类型） | 与现有 8 个方法兼容，降低改造风险；后续可渐进引入强类型 |
| 现有方法改造方式 | 提取为 Provider 类，逻辑不变 | 渐进式迁移，逐个验证，可随时停 |
| MCP 是否为首选集成通道 | **是** | 零代码、现有工厂支持、2026 年 MCP 普及趋势 |

---

## 10. 与现有架构的关系

```
现有架构（不动）                    本次新增（最小改动）
┌─────────────────────────┐       ┌──────────────────────────┐
│ App 层（Agent 应用载体）  │       │ ToolProvider 协议（新）    │
│ 工作流层（DAG 编排）      │       │ ToolProviderRegistry（新） │
│ Agent 层（BaseAgent）     │       │ 8 个 Provider 类（提取）   │
│                          │       │                          │
│ 工具治理层（复用，不改）   │◄──────│ ToolCandidateCollector    │
│  ├ ToolPolicyFilter      │       │  .collect() 改为遍历Registry│
│  ├ ToolRanker            │       │                          │
│  └ RuntimeToolMountService│      │ ToolSourceType +3 枚举    │
│                          │       │                          │
│ 4 个工厂（builtin/api/    │       │ Admin 已注册扩展列表（新） │
│   mcp/skill）             │       │                          │
└─────────────────────────┘       └──────────────────────────┘
```

**核心原则**：不破坏现有可用的工具治理框架，只改采集入口。现有 4 个工厂的逻辑全部保留，只是被组织为 Provider 类。治理链路（Filter → Ranker → MountService）完全不动。

---

## 11. 实现路线图

| 阶段 | 交付物 | 验收标准 |
|---|---|---|
| P1: 协议与注册表 | ToolProvider 协议 + Registry + ToolSourceType 补全 | 协议可被实现，Registry 可注册/遍历 |
| P2: 单 Provider 试点 | ApiToolProvider 迁移，collect() 改为 Registry + 硬编码并行 | ApiToolProvider 输出与原 `_collect_api_tools` 逐字段一致 |
| P3: 全量迁移 | 剩余 7 个 Provider 迁移，移除硬编码方法 | collect() 完全遍历 Registry，所有工具来源输出不变 |
| P4: 第三方接入验证 | 接入第一个 SDK 型 Provider | 第三方能力可通过 Agent 对话框调用 |
| P5: Admin 管理面 | 已注册扩展列表页 | admin 可查看所有 Provider 及工具数量 |
