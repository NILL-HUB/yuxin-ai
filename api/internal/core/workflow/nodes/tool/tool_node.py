import json
import time
from typing import Optional, Any
from pydantic import PrivateAttr
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from internal.core.tools.api_tools.entities import ToolEntity
from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state
from internal.exception import FailException, NotFoundException
from internal.model import ApiTool
from .tool_entity import ToolNodeData


# 嵌套 workflow / agent_binding 的最大递归深度，防止无限嵌套
MAX_NESTED_DEPTH = 8
# 在 RunnableConfig.configurable 中传递调用栈的键名
CALL_STACK_CONFIG_KEY = "_workflow_tool_call_stack"


class ToolNode(BaseNode):
    """扩展插件节点

    支持按 tool_type 分发到 7 种工具类型：
    - builtin_tool / api_tool: 构造函数中立即初始化 _tool（保持原逻辑，向后兼容）
    - mcp / knowledge / skill / workflow / agent_binding: invoke 时延迟加载底座服务执行

    workflow 与 agent_binding 类型带环检测（通过 RunnableConfig.configurable 传递调用栈），
    防止 workflow 嵌套 workflow 或 agent_binding 互相调用导致无限递归。
    """
    node_data: ToolNodeData
    _tool: BaseTool = PrivateAttr(None)

    def __init__(self, *args: Any, **kwargs: Any):
        """构造函数，完成对内置工具/API工具的初始化

        builtin_tool / api_tool 在构造时立即初始化 _tool（保持向后兼容）；
        mcp / knowledge / skill / workflow / agent_binding 延迟到 invoke 时按需加载，
        避免构造期依赖运行时上下文（account_id / flask_app / call_stack 等）。
        """
        # 1.调用父类构造函数完成数据初始化
        super().__init__(*args, **kwargs)

        # 2.空工具类型直接返回（延迟加载场景由 invoke 处理）
        tool_type = self.node_data.tool_type
        if tool_type in ("", "mcp", "knowledge", "skill", "workflow", "agent_binding"):
            return

        # 3.导入依赖注入及工具提供者
        from app.http.module import injector

        # 4.内置工具：调用内置提供者获取工具实例
        if tool_type == "builtin_tool":
            from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
            builtin_provider_manager = injector.get(BuiltinProviderManager)

            _tool = builtin_provider_manager.get_tool(self.node_data.provider_id, self.node_data.tool_id)
            if not _tool:
                raise NotFoundException("该内置插件扩展不存在，请核实后重试")

            self._tool = _tool(**self.node_data.params)
            return

        # 5.API工具：查询数据库记录并创建API工具
        if tool_type == "api_tool":
            from pkg.sqlalchemy import SQLAlchemy
            db = injector.get(SQLAlchemy)

            api_tool = db.session.query(ApiTool).filter(
                ApiTool.provider_id == self.node_data.provider_id,
                ApiTool.name == self.node_data.tool_id
            ).one_or_none()
            if not api_tool:
                raise NotFoundException("该API扩展插件不存在，请核实重试")

            from internal.core.tools.api_tools.providers import ApiProviderManager
            api_provider_manager = injector.get(ApiProviderManager)

            self._tool = api_provider_manager.get_tool(ToolEntity(
                id=str(api_tool.id),
                name=api_tool.name,
                url=api_tool.url,
                method=api_tool.method,
                description=api_tool.description,
                headers=api_tool.provider.headers,
                parameters=api_tool.parameters,
            ))

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """扩展插件执行节点，根据 tool_type 分发执行

        - builtin_tool / api_tool: 调用构造期初始化的 self._tool（原逻辑）
        - mcp: 延迟加载 McpToolFactory，按 binding 执行
        - knowledge: 延迟加载 RetrievalService，按 knowledge_base_id 检索
        - skill: 延迟加载 SkillService，按 skill_id 执行
        - workflow: 延迟加载 AppConfigService 嵌套 Workflow（带环检测）
        - agent_binding: 延迟加载 AppService 调用子 App（带环检测）
        """
        # 1.提取节点中的输入数据
        start_at = time.perf_counter()
        inputs_dict = extract_variables_from_state(self.node_data.inputs, state)

        # 2.按 tool_type 分发获取执行结果
        # FailException（含环检测/加载失败）直接穿透，保留原始错误信息；
        # 其他异常统一包装为"扩展插件执行失败"
        try:
            result = self._dispatch_invoke(inputs_dict, config)
        except FailException:
            raise
        except Exception:
            raise FailException("扩展插件执行失败，请稍后尝试")

        # 3.检测result是否为字符串，如果不是则转换
        if not isinstance(result, str):
            result = json.dumps(result)

        # 4.提取并构建输出数据结构
        outputs = {}
        if self.node_data.outputs:
            outputs[self.node_data.outputs[0].name] = result
        else:
            outputs["text"] = result

        # 5.构建响应状态并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED.value,
                    inputs=inputs_dict,
                    outputs=outputs,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }

    def _dispatch_invoke(self, inputs_dict: dict[str, Any], config: Optional[RunnableConfig]) -> Any:
        """按 tool_type 分发执行，返回工具调用结果。"""
        tool_type = self.node_data.tool_type

        # builtin_tool / api_tool: 走构造期初始化的 _tool（原逻辑）
        if tool_type in ("", "builtin_tool", "api_tool"):
            return self._tool.invoke(inputs_dict)

        # mcp: 延迟加载 McpToolFactory
        if tool_type == "mcp":
            return self._invoke_mcp_tool(inputs_dict)

        # knowledge: 延迟加载 RetrievalService
        if tool_type == "knowledge":
            return self._invoke_knowledge_tool(inputs_dict, config)

        # skill: 延迟加载 SkillService
        if tool_type == "skill":
            return self._invoke_skill_tool(inputs_dict)

        # workflow: 嵌套 Workflow + 环检测
        if tool_type == "workflow":
            return self._invoke_workflow_tool(inputs_dict, config)

        # agent_binding: 调用子 App + 环检测
        if tool_type == "agent_binding":
            return self._invoke_agent_binding_tool(inputs_dict, config)

        # 未知 tool_type 兜底（不应到达，Literal 已约束）
        raise FailException(f"不支持的工具类型: {tool_type}")

    # ------------------------------------------------------------------ #
    #  mcp / knowledge / skill / workflow / agent_binding 延迟加载实现     #
    # ------------------------------------------------------------------ #

    def _invoke_mcp_tool(self, inputs_dict: dict[str, Any]) -> Any:
        """复用 McpToolFactory 加载 MCP 工具并执行。

        node_data.provider_id 存 provider_key，tool_id 存 tool_name；
        node_data.meta 存 binding 详情（transport/url/headers 等）。
        """
        from app.http.module import injector
        from internal.core.tools.mcp_tools.providers import McpToolFactory

        binding = self._build_mcp_binding()
        mcp_factory = McpToolFactory()
        tools = mcp_factory.get_tools([binding])
        if not tools:
            raise FailException("MCP工具加载失败或无可执行工具，请核实后重试")
        return tools[0].invoke(inputs_dict)

    def _build_mcp_binding(self) -> dict[str, Any]:
        """从 node_data 构造 MCP binding 字典。

        优先使用 meta 中的完整 binding；否则用 provider_id/tool_id 拼装最小 binding。
        """
        meta = self.node_data.meta or {}
        if isinstance(meta, dict) and meta.get("url") or meta.get("command"):
            # meta 已含完整 binding 信息（前端保存的 ToolSelection）
            binding = dict(meta)
            # 补齐 provider_key / tool_names 以便 McpToolFactory 识别
            if self.node_data.provider_id and not binding.get("provider_key"):
                binding["provider_key"] = self.node_data.provider_id
            if self.node_data.tool_id:
                tool_names = binding.get("tool_names") or []
                if self.node_data.tool_id not in tool_names:
                    binding["tool_names"] = [self.node_data.tool_id]
            return binding
        # 最小 binding：仅含 provider_key + tool_name，需调用方在 meta 补全 url/transport
        binding = {"provider_key": self.node_data.provider_id, "name": self.node_data.provider_id}
        if self.node_data.tool_id:
            binding["tool_names"] = [self.node_data.tool_id]
        binding.update(meta)
        return binding

    def _invoke_knowledge_tool(self, inputs_dict: dict[str, Any], config: Optional[RunnableConfig]) -> Any:
        """复用 RetrievalService 构造知识库检索工具并执行。

        node_data.tool_id 存 knowledge_base_id / dataset_id。
        query 从 inputs_dict 提取（取第一个字符串值或 'query' 键）。
        """
        from app.http.module import injector
        from internal.service.retrieval_service import RetrievalService

        knowledge_base_id = self.node_data.tool_id
        if not knowledge_base_id:
            raise FailException("知识库工具节点缺少 knowledge_base_id，请核实后重试")

        query = self._extract_query_from_inputs(inputs_dict)
        retrieval_service = injector.get(RetrievalService)
        flask_app = self._get_flask_app()

        # 复用 RetrievalService.create_knowledge_retrieval_tool 构造工具
        # account_id 从 config 或运行时上下文获取，缺失时用空 UUID 兜底
        account_id = self._extract_account_id_from_config(config)
        tool = retrieval_service.create_knowledge_retrieval_tool(
            flask_app=flask_app,
            knowledge_base_ids=[self._to_uuid(knowledge_base_id)],
            account_id=account_id,
        )
        return tool.invoke({"query": query})

    def _invoke_skill_tool(self, inputs_dict: dict[str, Any]) -> Any:
        """复用 SkillService 加载技能包工具并执行。

        node_data.tool_id 存 skill_id。
        """
        from app.http.module import injector
        from internal.service.skill_service import SkillService

        skill_id = self.node_data.tool_id
        if not skill_id:
            raise FailException("技能工具节点缺少 skill_id，请核实后重试")

        skill_service = injector.get(SkillService)
        tools = skill_service.get_langchain_tools_by_skill_bindings(
            [{"skill_id": skill_id}],
        )
        if not tools:
            raise FailException("技能工具加载失败或无可执行工具，请核实后重试")
        return tools[0].invoke(inputs_dict)

    def _invoke_workflow_tool(self, inputs_dict: dict[str, Any], config: Optional[RunnableConfig]) -> Any:
        """复用 AppConfigService 加载嵌套 Workflow 并执行（带环检测）。

        node_data.tool_id 存 workflow_id。
        环检测：通过 RunnableConfig.configurable 的调用栈，若 workflow_id 已在栈中则拒绝；
        max_depth 限制嵌套层数（MAX_NESTED_DEPTH）。
        """
        from app.http.module import injector
        from internal.service.app_config_service import AppConfigService

        workflow_id = self.node_data.tool_id
        if not workflow_id:
            raise FailException("工作流工具节点缺少 workflow_id，请核实后重试")

        # 环检测 + 深度限制
        call_stack = self._get_call_stack(config)
        workflow_id_str = str(workflow_id)
        if workflow_id_str in call_stack:
            raise FailException(
                f"检测到工作流嵌套循环，workflow {workflow_id_str} 已在调用链中，已停止执行"
            )
        if len(call_stack) >= MAX_NESTED_DEPTH:
            raise FailException(
                f"工作流嵌套深度超过上限 {MAX_NESTED_DEPTH}，已停止执行"
            )

        # 加载嵌套 Workflow 为 langchain 工具
        app_config_service = injector.get(AppConfigService)
        workflow_uuid = self._to_uuid(workflow_id)
        tools = app_config_service.get_langchain_tools_by_workflow_ids([workflow_uuid])
        if not tools:
            raise FailException("嵌套工作流加载失败或未发布，请核实后重试")

        # 将更新后的 call_stack 通过 config 传递给嵌套执行
        nested_config = self._push_call_stack(config, workflow_id_str)
        return tools[0].invoke(inputs_dict, config=nested_config)

    def _invoke_agent_binding_tool(self, inputs_dict: dict[str, Any], config: Optional[RunnableConfig]) -> Any:
        """复用 AppRuntimeService 调用子 App（带环检测）。

        node_data.tool_id 存目标 app_id。
        环检测：通过 RunnableConfig.configurable 的调用栈，若 app_id 已在栈中则拒绝。
        """
        from app.http.module import injector
        from internal.service.app_runtime_service import AppRuntimeService

        target_app_id = self.node_data.tool_id
        if not target_app_id:
            raise FailException("Agent绑定工具节点缺少 app_id，请核实后重试")

        # 环检测 + 深度限制
        call_stack = self._get_call_stack(config)
        target_app_id_str = str(target_app_id)
        if target_app_id_str in call_stack:
            raise FailException(
                f"检测到 Agent 调用循环，子应用 {target_app_id_str} 已在调用链中，已停止执行"
            )
        if len(call_stack) >= MAX_NESTED_DEPTH:
            raise FailException(
                f"Agent 嵌套深度超过上限 {MAX_NESTED_DEPTH}，已停止执行"
            )

        app_runtime_service = injector.get(AppRuntimeService)
        flask_app = self._get_flask_app()
        account = self._extract_account(config)
        # 当前 app_id 从 config 获取（嵌套执行时由调用方传入）
        current_app_id = self._extract_current_app_id(config)

        tools = app_runtime_service.get_langchain_tools_by_agent_bindings(
            [{"app_id": target_app_id_str}],
            account=account,
            app_id=self._to_uuid(current_app_id) if current_app_id else self._to_uuid(target_app_id_str),
            flask_app=flask_app,
        )
        if not tools:
            raise FailException("Agent子应用工具加载失败，请核实后重试")

        nested_config = self._push_call_stack(config, target_app_id_str)
        return tools[0].invoke(inputs_dict, config=nested_config)

    # ------------------------------------------------------------------ #
    #  环检测与运行时上下文辅助                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_flask_app():
        """安全获取当前 Flask 应用，无应用上下文时返回 None。"""
        try:
            from internal.context import has_app_context, current_app
            if has_app_context():
                return current_app._get_current_object()
        except Exception:
            pass
        return None

    @staticmethod
    def _get_call_stack(config: Optional[RunnableConfig]) -> list[str]:
        """从 RunnableConfig.configurable 提取调用栈，缺失时返回空列表。"""
        if not config:
            return []
        configurable = config.get("configurable") if isinstance(config, dict) else None
        if not isinstance(configurable, dict):
            return []
        stack = configurable.get(CALL_STACK_CONFIG_KEY)
        if not isinstance(stack, list):
            return []
        return [str(item) for item in stack if str(item).strip()]

    @staticmethod
    def _push_call_stack(config: Optional[RunnableConfig], app_or_workflow_id: str) -> RunnableConfig:
        """将下一跳 id 压入调用栈，返回新的 config（不修改原 config）。"""
        base_config = dict(config) if isinstance(config, dict) else {}
        configurable = dict(base_config.get("configurable") or {})
        stack = list(configurable.get(CALL_STACK_CONFIG_KEY) or [])
        stack.append(str(app_or_workflow_id))
        configurable[CALL_STACK_CONFIG_KEY] = stack
        base_config["configurable"] = configurable
        return base_config

    @staticmethod
    def _extract_query_from_inputs(inputs_dict: dict[str, Any]) -> str:
        """从输入字典提取查询字符串，优先取 'query' 键，否则取第一个字符串值。"""
        if not isinstance(inputs_dict, dict):
            return ""
        if "query" in inputs_dict:
            return str(inputs_dict["query"])
        for value in inputs_dict.values():
            if isinstance(value, str):
                return value
        return ""

    @staticmethod
    def _extract_account_id_from_config(config: Optional[RunnableConfig]):
        """从 config 提取 account_id（用于 knowledge 检索权限）。"""
        if not config:
            return None
        configurable = config.get("configurable") if isinstance(config, dict) else None
        if not isinstance(configurable, dict):
            return None
        account_id = configurable.get("account_id")
        if account_id:
            from uuid import UUID
            try:
                return UUID(str(account_id))
            except Exception:
                return None
        return None

    @staticmethod
    def _extract_account(config: Optional[RunnableConfig]):
        """从 config 提取 Account 简单对象（用于 agent_binding）。"""
        if not config:
            return None
        configurable = config.get("configurable") if isinstance(config, dict) else None
        if not isinstance(configurable, dict):
            return None
        account_id = configurable.get("account_id")
        if not account_id:
            return None
        from types import SimpleNamespace
        from uuid import UUID
        try:
            return SimpleNamespace(id=UUID(str(account_id)))
        except Exception:
            return SimpleNamespace(id=str(account_id))

    @staticmethod
    def _extract_current_app_id(config: Optional[RunnableConfig]) -> Optional[str]:
        """从 config 提取当前 app_id（用于 agent_binding 的调用方标识）。"""
        if not config:
            return None
        configurable = config.get("configurable") if isinstance(config, dict) else None
        if not isinstance(configurable, dict):
            return None
        app_id = configurable.get("app_id") or configurable.get("root_app_id")
        return str(app_id) if app_id else None

    @staticmethod
    def _to_uuid(value: str):
        """将字符串安全转为 UUID，转换失败时返回原字符串。"""
        from uuid import UUID
        try:
            return UUID(str(value))
        except Exception:
            return value
