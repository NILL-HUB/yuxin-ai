"""管理端 Agent 对话链路的枚举（设计 §10.1）。"""
from enum import Enum


class AdminAgentMessageRole(str, Enum):
    """管理端会话消息角色。"""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AdminAgentChatEvent(str, Enum):
    """管理端对话 SSE 事件名。

    与用户端 `QueueEvent` 分开：两条链路的前端契约不同，共用枚举会让
    一侧新增事件意外改变另一侧契约。
    """

    MESSAGE = "message"   # 会话/消息 id 已建立
    TOOL = "tool"         # 一次板块工具调用及其结果
    ANSWER = "answer"     # 最终答复
    ERROR = "error"       # 链路异常（已可读化）
    END = "end"           # 流结束
