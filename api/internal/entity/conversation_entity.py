from pydantic import BaseModel, Field
from enum import Enum

class ConversationInfo(BaseModel):
    """从用户输入中提取语言类型、语言判断依据和会话主题标题。
    输出需简洁准确，并与用户主语言一致；中英混合场景优先中文。"""
    language_type: str = Field(description="用户输入的语言类型声明，如纯中文、纯英文或中英混合")
    reasoning: str = Field(description="语言判断依据，使用一句简洁描述")
    subject: str = Field(description=(
        "会话主题标题，需准确概括用户核心意图。"
        "输出语言与用户主语言一致，标题可以稍长且信息完整，避免空泛表述。"
    ))

class SuggestedQuestions(BaseModel):
    """基于历史会话生成最可能的三个后续问题，每个问题不超过 50 个字符。"""
    questions: list[str] = Field(description="建议问题列表，类型为字符串数组")

class InvokeFrom(str, Enum):
    """会话调用来源"""
    SERVICE_API = "service_api"  # 开放api服务调用
    WEB_APP = "web_app"  # web应用
    DEBUGGER = "debugger"  # 调试页面
    ASSISTANT_AGENT = "assistant_agent"  # 辅助Agent调用
    SCHEDULE = "schedule"  # 定时任务调用（与正常对话/日志区分）


class MessageStatus(str, Enum):
    """会话状态"""
    NORMAL = "normal"  # 正常
    STOP = "stop"  # 停止
    TIMEOUT = "timeout"  # 超时
    ERROR = "error"  # 出错


