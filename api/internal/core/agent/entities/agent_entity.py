from typing import Any
from uuid import UUID
from langchain_core.messages import AnyMessage
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langgraph.graph import MessagesState

from internal.entity.app_entity import DEFAULT_APP_CONFIG
from internal.entity.conversation_entity import InvokeFrom
from internal.core.agent.entities.tool_policy_entity import DATASET_RETRIEVAL_TOOL_NAME, ToolPolicy


def get_agent_system_prompt_template(template_key: str = "agent_system_prompt_template") -> str:
    """从系统提示词库读取 Agent 身份模板（可管理版本），未命中回退 YAML 内置默认。

    模板包含 ``{preset_prompt}`` / ``{long_term_memory}`` / ``{user_memory}`` /
    ``{tool_description}`` 等占位符，由调用方负责 ``.format()`` 填充。
    提示词默认文本集中在 ``internal/core/prompts/system_prompts.yaml``，
    代码中不再硬编码系统提示词。
    """
    from internal.service.system_prompt_library_service import SystemPromptLibraryService
    return SystemPromptLibraryService().get_prompt_or_default(template_key)


def get_max_iteration_response() -> str:
    """读取 Agent 迭代次数超限回复文案（系统提示词库可管理，YAML 兜底）。"""
    from internal.service.system_prompt_library_service import SystemPromptLibraryService
    return SystemPromptLibraryService().get_prompt_or_default("max_iteration_response")


class AgentConfig(BaseModel):
    """智能体配置信息，涵盖：LLM大语言模型、预设prompt、关联插件、知识库、工作流、是否开启长期记忆等内容，后期可以随时扩展"""
    # 代表用户的唯一标识及调用来源，默认来源是WEB_APP
    user_id: UUID
    invoke_from: InvokeFrom = InvokeFrom.WEB_APP.value

    # 最大迭代次数
    max_iteration_count: int = 10

    # 智能体预设提示词
    # 注意：系统提示词模板不再硬编码在代码中，统一从系统提示词库读取
    # （get_agent_system_prompt_template），Agent 执行时经模板 .format() 注入。
    # 此字段保留为空串以兼容历史调用方，实际模板由各 Agent 内部从系统提示词库解析。
    system_prompt: str = ""
    preset_prompt: str = ""  # 预设prompt，默认为空，该值由前端用户在编排的时候记录，并填充到system_prompt中

    # 智能体长期记忆是否开启
    enable_long_term_memory: bool = False  # 是否开启会话信息汇总/长期记忆

    # 深度思考模式
    enable_deep_thinking: bool = False  # 是否开启深度思考（DeepAgent）

    # LangGraph checkpoint 持久化（对话状态/断点恢复/time travel 基础设施）
    # 启用后需通过 astream/ainvoke 并携带 thread_id（跨请求恢复对话状态）
    enable_checkpoint: bool = False

    # 运行时 Flask application，用于线程内补充 app context（如附件持久化）
    runtime_flask_app: Any = None

    # 运行时语言模型服务，用于模型请求失败时获取默认兜底模型
    language_model_service: Any = None

    # 智能体使用的工具列表
    tools: list[BaseTool] = Field(default_factory=list)

    # 工具运行时策略
    tool_policy: ToolPolicy = Field(default_factory=ToolPolicy)

    # 审核配置
    review_config: dict = Field(default_factory=lambda: DEFAULT_APP_CONFIG["review_config"])


class AgentState(MessagesState):
    """智能体状态类"""
    task_id: UUID  # 该次状态对应的任务id，每次运行时会使用独立的任务id
    iteration_count: int  # 迭代次数，默认为0
    history: list[AnyMessage]  # 短期记忆(历史记录)
    long_term_memory: str  # 长期记忆
    pending_skill_prompts: list[dict[str, Any]]  # 已按需加载、等待在本轮注入的 prompt-only skill 正文
    user_memory: str  # 用户长期记忆召回内容
    authorized_tools: list[str] = Field(default_factory=list)  # 用户本轮已授权的高风险工具
