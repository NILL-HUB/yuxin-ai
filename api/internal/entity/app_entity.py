from enum import Enum


class AppStatus(str, Enum):
    """应用状态枚举类"""
    DRAFT = "draft"
    PUBLISHED = "published"


class AppType(str, Enum):
    """应用类型枚举"""
    CHATBOT = "chatbot"        # 对话型（默认，向后兼容）
    AGENT = "agent"            # Agent 型（带工具调用）
    WORKFLOW = "workflow"      # 工作流型（绑定一个 workflow）
    COMPLETION = "completion"  # 补全型（单轮文本生成，无对话记忆）


class AppConfigType(str, Enum):
    """应用配置类型枚举类"""
    DRAFT = "draft"
    PUBLISHED = "published"


# 应用默认配置信息
# 注意：app_type 是 App 级别属性（存储在 App 表），不放在 AppConfigVersion 配置中
# workflow_id 是 AppConfigVersion 级别属性，因为 draft 和 published 可能绑定不同 workflow
# model_config 默认为空字典，运行时由 LanguageModelService 从 admin 数据库统一解析
DEFAULT_APP_CONFIG = {
    "workflow_id": None,  # Workflow 应用类型绑定的 workflow_id（仅 app_type=workflow 时有效）
    "model_config": {},
    "dialog_round": 3,
    "preset_prompt": "",
    "tools": [],
    "mcp_bindings": [],
    "mcp_tool_snapshots": [],
    "skills": [],
    "workflows": [],
    # 知识库 id 列表，App 配置主用字段
    "knowledge_base_ids": [],
    "retrieval_config": {
        "retrieval_strategy": "semantic",
        "k": 10,
        "score": 0.5,
    },
    "long_term_memory": {
        "enable": True,
    },
    "opening_statement": "",
    "opening_questions": [],
    "speech_to_text": {
        "enable": True,
    },
    "text_to_speech": {
        "enable": True,
        "voice": "alex",
        "auto_play": True,
    },
    "suggested_after_answer": {
        "enable": True,
    },
    "review_config": {
        "enable": False,
        "keywords": [],
        "inputs_config": {
            "enable": False,
            "preset_response": "",
        },
        "outputs_config": {
            "enable": False,
        },
    },
}
