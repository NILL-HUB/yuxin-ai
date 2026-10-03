"""编排层元工具：子代理执行中按需申请追加工具。

设计要点：
- 复用主链路唯一的工具选择入口（``OrchestratorService.build_tool_subset``）与
  治理（``RuntimeToolMountService``），不引入第二套选择/治理实现；
- 工具本身不接触工具清单，只把「能力描述」转交给注入的 provider；
- provider 返回新挂载的工具后，由调用方（``AgentTaskExecutor``）写回当前 Agent
  实例的 ``agent_config.tools``——``FunctionCallAgent._llm_node`` 每轮都会重读该
  列表，因此追加的工具在**本次执行的后续轮次**即生效。
"""
import logging
from typing import Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

REQUEST_MORE_TOOLS_NAME = "request_more_tools"

# provider 契约：(query, reason) -> 给模型看的说明文本。
# 工具追加动作由调用方（AgentTaskExecutor）负责写回 Agent 实例。
RequestMoreToolsProvider = Callable[[str, str], str]


class _RequestMoreToolsArgs(BaseModel):
    query: str = Field(description="描述你需要什么能力或工具，例如「查询企业工商信息」")
    reason: str = Field(default="", description="说明现有工具为什么不够用（可选）")


def build_request_more_tools_tool(provider: RequestMoreToolsProvider) -> StructuredTool:
    """构造 ``request_more_tools`` 元工具（闭包绑定注入的 provider）。"""

    def _run(query: str, reason: str = "") -> str:
        try:
            return provider(query, reason)
        except Exception:
            logger.warning("request_more_tools 申请追加工具失败", exc_info=True)
            return "申请追加工具失败，请继续用现有工具尽力完成，或说明缺少的能力。"

    return StructuredTool.from_function(
        func=_run,
        name=REQUEST_MORE_TOOLS_NAME,
        description=(
            "当现有工具不足以完成当前子任务时，用本工具按能力描述申请追加工具。"
            "query 描述你需要的工具能力（如「企业工商信息查询」）；"
            "它会返回新挂载的工具清单，若当前工具池无匹配能力则明确告知缺什么。"
            "不要用它替代对现有工具的正常调用。"
        ),
        args_schema=_RequestMoreToolsArgs,
    )
