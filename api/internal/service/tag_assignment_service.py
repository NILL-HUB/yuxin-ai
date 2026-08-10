"""标签分配服务 - 处理应用/工作流的自动标签分配"""
import logging
from typing import List

from pydantic import BaseModel, Field

from internal.core.agent.usage_utils import charge_for_feature, extract_token_usage
from internal.entity.tag_entity import (
    TAG_KEYWORDS_MAPPING,
    sort_tags_by_priority,
)
from internal.service.language_model_service import LanguageModelService


class TagAssignmentInput(BaseModel):
    """标签分配输入结构"""
    tags: List[str] = Field(
        description="选择的标签列表，最多选择3个最相关的标签。如果无法确定，选择'other'",
        min_length=1,
        max_length=3
    )


class TagAssignmentService:
    """标签分配服务"""

    @staticmethod
    def match_tags_by_keywords(name: str, description: str) -> List[str]:
        """
        基于关键词匹配分配标签（第一层）

        Args:
            name: 应用/工作流名称
            description: 应用/工作流描述

        Returns:
            匹配到的标签列表，按优先级排序
        """
        text = f"{name} {description}".lower()
        matched_tags = {}

        for tag_id, tag_info in TAG_KEYWORDS_MAPPING.items():
            if tag_id == "other":  # 跳过"其他"标签
                continue

            # 计算匹配分数
            match_score = 0
            for keyword in tag_info["keywords"]:
                if keyword.lower() in text:
                    # 名称中的匹配权重更高
                    if keyword.lower() in name.lower():
                        match_score += 2
                    else:
                        match_score += 1

            if match_score > 0:
                matched_tags[tag_id] = {
                    "priority": tag_info["priority"],
                    "score": match_score
                }

        # 按优先级排序，返回标签ID列表
        if matched_tags:
            sorted_tags = sorted(
                matched_tags.items(),
                key=lambda x: x[1]["priority"]
            )
            return [tag_id for tag_id, _ in sorted_tags]

        return []

    @staticmethod
    def assign_tags_by_deepseek(
        name: str,
        description: str,
        credit_service=None,
        account_id=None,
    ) -> List[str]:
        """
        通过 FunctionCall 分配标签（第二层）

        LLM 通过 LanguageModelService.get_cheap_chat_model() 获取，
        走数据库配置 + compatible_api 分发链路。

        Args:
            name: 应用/工作流名称
            description: 应用/工作流描述
            credit_service: 额度计费服务实例（可选，传入时按 token 扣费）
            account_id: 账户 ID（可选，与 credit_service 配合用于计费）

        Returns:
            分配的标签列表
        """
        try:
            # 走数据库配置 + compatible_api 分发
            llm = LanguageModelService.get_feature_model("tag_assignment")

            # 定义FunctionCall工具
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "assign_tags",
                        "description": "根据应用/工作流的名称和描述，从预定义的13个标签中选择最相关的1个或多个标签",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "tags": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "enum": [
                                            "general", "writing", "coding", "business",
                                            "education", "entertainment", "productivity",
                                            "customer_service", "data_analysis", "translation",
                                            "marketing", "research", "other"
                                        ]
                                    },
                                    "description": "选择的标签列表，最多选择3个最相关的标签。如果无法确定，选择'other'",
                                    "minItems": 1,
                                    "maxItems": 3
                                }
                            },
                            "required": ["tags"]
                        }
                    }
                }
            ]

            # 构建提示词
            from internal.service.system_prompt_library_service import SystemPromptLibraryService
            template = SystemPromptLibraryService().get_prompt_or_default(
                "app_tag_assignment_prompt"
            )
            prompt = template.format(name=name, description=description)

            # 调用LLM
            response = llm.invoke(prompt)

            # 公共 AI 功能计费（非消息上下文）
            token_usage = extract_token_usage(response)
            if token_usage and account_id is not None:
                charge_for_feature(
                    credit_service,
                    account_id,
                    "tag_assignment",
                    token_usage["total_tokens"],
                )

            # 解析响应中的标签
            # 这里需要根据实际的LLM响应格式进行解析
            # 假设LLM返回的是JSON格式的FunctionCall结果
            if hasattr(response, 'tool_calls') and response.tool_calls:
                for tool_call in response.tool_calls:
                    if tool_call.get('name') == 'assign_tags':
                        tags = tool_call.get('args', {}).get('tags', [])
                        if tags:
                            return sort_tags_by_priority(tags)

            # 如果解析失败，返回空列表
            return []

        except Exception as e:
            logging.exception(f"使用DeepSeek分配标签失败: {str(e)}")
            return []

    @staticmethod
    def auto_assign_tags(
        name: str,
        description: str,
        credit_service=None,
        account_id=None,
    ) -> List[str]:
        """
        自动分配标签 - 先用关键词匹配，失败则调用DeepSeek

        Args:
            name: 应用/工作流名称
            description: 应用/工作流描述
            credit_service: 额度计费服务实例（可选，传入时按 token 扣费）
            account_id: 账户 ID（可选，与 credit_service 配合用于计费）

        Returns:
            分配的标签列表
        """
        # 第一层：关键词匹配
        tags = TagAssignmentService.match_tags_by_keywords(name, description)

        if tags:
            return tags

        # 第二层：调用DeepSeek
        tags = TagAssignmentService.assign_tags_by_deepseek(
            name, description, credit_service=credit_service, account_id=account_id
        )

        if tags:
            return tags

        # 如果都失败，返回"其他"标签
        return ["other"]

    @staticmethod
    def assign_tags_for_assistant_agent(
        name: str,
        description: str,
        credit_service=None,
        account_id=None,
    ) -> List[str]:
        """
        为辅助Agent创建的应用分配标签 - 直接使用DeepSeek FunctionCall

        Args:
            name: 应用/工作流名称
            description: 应用/工作流描述
            credit_service: 额度计费服务实例（可选，传入时按 token 扣费）
            account_id: 账户 ID（可选，与 credit_service 配合用于计费）

        Returns:
            分配的标签列表
        """
        tags = TagAssignmentService.assign_tags_by_deepseek(
            name, description, credit_service=credit_service, account_id=account_id
        )

        if tags:
            return tags

        # 如果失败，尝试关键词匹配
        tags = TagAssignmentService.match_tags_by_keywords(name, description)

        if tags:
            return tags

        # 如果都失败，返回"其他"标签
        return ["other"]
