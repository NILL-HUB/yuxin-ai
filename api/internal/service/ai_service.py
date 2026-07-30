import json
from dataclasses import dataclass
from typing import Generator
from uuid import UUID
from injector import inject
from langchain_core.output_parsers import StrOutputParser
from langchain_core.output_parsers.transform import BaseCumulativeTransformOutputParser
from langchain_core.prompts import ChatPromptTemplate
from internal.core.agent.usage_utils import (
    charge_for_feature,
    get_openai_callback,
    _UsageTrackingHandler,
)
from internal.entity.ai_entity import (
    OPTIMIZE_PROMPT_TEMPLATE,
    MCP_SCHEMA_ASSISTANT_PROMPT,
    OPENAPI_SCHEMA_ASSISTANT_PROMPT,
    PYTHON_CODE_ASSISTANT_PROMPT,
)
from internal.exception import ForbiddenException
from internal.model import Account, Message
from internal.service.memory.llm_activity_probe import LLMActivityProbe
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .conversation_service import ConversationService
from .credit_service import CreditService
from .language_model_service import LanguageModelService


class PythonMarkdownOutputParser(BaseCumulativeTransformOutputParser[str]):
    """Python 代码输出解析器（流式增量模式，保留模型原始输出）。"""

    diff: bool = True

    @property
    def _type(self) -> str:
        return "python_markdown_output"

    def _diff(self, prev: str | None, next: str) -> str:
        previous = prev or ""
        if next.startswith(previous):
            return next[len(previous):]
        return next

    def parse(self, text: str) -> str:
        return text


@inject
@dataclass
class AIService(BaseService):
    """AI服务"""
    db: SQLAlchemy
    conversation_service: ConversationService
    credit_service: CreditService | None = None

    @classmethod
    def _get_credit_service(cls):
        """从依赖注入器获取 CreditService 实例，获取失败返回 None。

        由于 optimize_prompt / code_assistant_chat 等方法为 classmethod，
        无法通过 self 访问注入的 credit_service，故在此从 injector 获取。
        """
        try:
            from app.http.module import injector
            return injector.get(CreditService)
        except Exception:
            return None

    @classmethod
    def _get_account_id(cls) -> UUID | None:
        """从当前登录用户获取 account_id，不在请求上下文时返回 None。"""
        try:
            from flask_login import current_user
            if current_user.is_authenticated:
                return current_user.id
        except Exception:
            pass
        return None

    def generate_suggested_questions_from_message_id(self, message_id: UUID, account: Account) -> list[str]:
        """根据传递的消息id+账号生成建议问题列表"""
        # 1.查询消息并校验权限信息
        message = self.get(Message, message_id)
        if not message or message.created_by != account.id:
            raise ForbiddenException("该条消息不存在或无权限")

        # 2.如果消息已有建议问题，直接返回
        if message.suggested_questions and len(message.suggested_questions) > 0:
            return message.suggested_questions

        # 3.构建对话历史列表
        histories = f"Human: {message.query}\nAI: {message.answer}"

        # 4.调用服务生成建议问题
        suggested_questions = self.conversation_service.generate_suggested_questions(histories)

        # 5.存储建议问题到数据库
        self.update(message, suggested_questions=suggested_questions)

        return suggested_questions

    @classmethod
    def optimize_prompt(cls, prompt: str) -> Generator[str, None, None]:
        """根据传递的prompt进行优化生成"""
        # 1.构建优化prompt的提示词模板
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", OPTIMIZE_PROMPT_TEMPLATE),
            ("human", "{prompt}")
        ])

        # 2.构建LLM（走数据库配置 + compatible_api 分发）
        llm = LanguageModelService.get_feature_model("prompt_optimization")

        # 3.组装优化链
        optimize_chain = prompt_template | llm | StrOutputParser()

        # 4.调用链并流式事件返回，同时捕获 token 用量用于计费
        # 用活跃探针替代固定超时：模型持续产出 token 时不干扰，
        # 仅在 60s 无 chunk 产出（死机）时终止
        account_id = cls._get_account_id()
        stream_input = {"prompt": prompt}
        if get_openai_callback is not None:
            with get_openai_callback() as cb:
                for optimize_prompt in LLMActivityProbe.monitor_stream(
                    lambda: optimize_chain.stream(stream_input),
                    feature_key="prompt_optimization",
                ):
                    data = {"optimize_prompt": optimize_prompt}
                    yield f"event: optimize_prompt\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            token_count = cb.total_tokens
        else:
            handler = _UsageTrackingHandler()
            for optimize_prompt in LLMActivityProbe.monitor_stream(
                lambda: optimize_chain.stream(stream_input, config={"callbacks": [handler]}),
                feature_key="prompt_optimization",
            ):
                data = {"optimize_prompt": optimize_prompt}
                yield f"event: optimize_prompt\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            token_count = handler.total_tokens

        # 5.计费（失败不影响主流程）
        if account_id is not None:
            charge_for_feature(cls._get_credit_service(), account_id, "prompt_optimization", token_count)

    @classmethod
    def code_assistant_chat(cls, question: str) -> Generator[str, None, None]:
        """代码助手聊天 - 流式输出"""
        # 1.构建提示词模板
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", PYTHON_CODE_ASSISTANT_PROMPT),
            ("human", "{question}")
        ])

        # 2.构建 LLM（走数据库配置 + compatible_api 分发）
        llm = LanguageModelService.get_feature_model("code_assistant")

        # 3.组装链（使用 Python 代码输出解析器）
        chain = prompt_template | llm | PythonMarkdownOutputParser()

        # 4.流式调用并返回，同时捕获 token 用量用于计费
        # 用活跃探针替代固定超时：模型持续产出 token 时不干扰，
        # 仅在 60s 无 chunk 产出（死机）时终止
        account_id = cls._get_account_id()
        stream_input = {"question": question}
        if get_openai_callback is not None:
            with get_openai_callback() as cb:
                for chunk in LLMActivityProbe.monitor_stream(
                    lambda: chain.stream(stream_input),
                    feature_key="code_assistant",
                ):
                    if not chunk:
                        continue
                    data = {"content": chunk}
                    yield f"event: message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            token_count = cb.total_tokens
        else:
            handler = _UsageTrackingHandler()
            for chunk in LLMActivityProbe.monitor_stream(
                lambda: chain.stream(stream_input, config={"callbacks": [handler]}),
                feature_key="code_assistant",
            ):
                if not chunk:
                    continue
                data = {"content": chunk}
                yield f"event: message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            token_count = handler.total_tokens

        # 5.计费（失败不影响主流程）
        if account_id is not None:
            charge_for_feature(cls._get_credit_service(), account_id, "code_assistant", token_count)

    @classmethod
    def openapi_schema_assistant_chat(cls, question: str) -> Generator[str, None, None]:
        """OpenAPI Schema 助手聊天 - 流式输出"""
        system_prompt = OPENAPI_SCHEMA_ASSISTANT_PROMPT.replace("{", "{{").replace("}", "}}")

        # 1.构建提示词模板
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{question}")
        ])

        # 2.构建 LLM（走数据库配置 + compatible_api 分发）
        llm = LanguageModelService.get_feature_model("schema_assistant")

        # 3.组装链
        chain = prompt_template | llm | StrOutputParser()

        # 4.流式调用并返回，同时捕获 token 用量用于计费
        # 用活跃探针替代固定超时：模型持续产出 token 时不干扰，
        # 仅在 60s 无 chunk 产出（死机）时终止
        account_id = cls._get_account_id()
        stream_input = {"question": question}
        if get_openai_callback is not None:
            with get_openai_callback() as cb:
                for chunk in LLMActivityProbe.monitor_stream(
                    lambda: chain.stream(stream_input),
                    feature_key="schema_assistant",
                ):
                    if not chunk:
                        continue
                    data = {"content": chunk}
                    yield f"event: message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            token_count = cb.total_tokens
        else:
            handler = _UsageTrackingHandler()
            for chunk in LLMActivityProbe.monitor_stream(
                lambda: chain.stream(stream_input, config={"callbacks": [handler]}),
                feature_key="schema_assistant",
            ):
                if not chunk:
                    continue
                data = {"content": chunk}
                yield f"event: message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            token_count = handler.total_tokens

        # 5.计费（失败不影响主流程）
        if account_id is not None:
            charge_for_feature(cls._get_credit_service(), account_id, "schema_assistant", token_count)

    @classmethod
    def mcp_schema_assistant_chat(cls, question: str) -> Generator[str, None, None]:
        """MCP Schema 助手聊天 - 流式输出"""
        system_prompt = MCP_SCHEMA_ASSISTANT_PROMPT.replace("{", "{{").replace("}", "}}")

        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{question}")
        ])

        llm = LanguageModelService.get_feature_model("schema_assistant")

        chain = prompt_template | llm | StrOutputParser()

        # 流式调用并返回，同时捕获 token 用量用于计费
        # 用活跃探针替代固定超时：模型持续产出 token 时不干扰，
        # 仅在 60s 无 chunk 产出（死机）时终止
        account_id = cls._get_account_id()
        stream_input = {"question": question}
        if get_openai_callback is not None:
            with get_openai_callback() as cb:
                for chunk in LLMActivityProbe.monitor_stream(
                    lambda: chain.stream(stream_input),
                    feature_key="schema_assistant",
                ):
                    if not chunk:
                        continue
                    data = {"content": chunk}
                    yield f"event: message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            token_count = cb.total_tokens
        else:
            handler = _UsageTrackingHandler()
            for chunk in LLMActivityProbe.monitor_stream(
                lambda: chain.stream(stream_input, config={"callbacks": [handler]}),
                feature_key="schema_assistant",
            ):
                if not chunk:
                    continue
                data = {"content": chunk}
                yield f"event: message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            token_count = handler.total_tokens

        # 计费（失败不影响主流程）
        if account_id is not None:
            charge_for_feature(cls._get_credit_service(), account_id, "schema_assistant", token_count)
