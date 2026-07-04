"""Completion 应用类型服务模块。

与 AppService（chatbot/agent）不同，Completion 应用：
- 单轮文本生成，不维护对话历史
- 用户输入作为变量填充到 prompt 模板
- 直接调用 LLM 生成回复，不使用工具
- 适用于翻译、摘要、改写等场景

Plan D-5：实现 app_type=completion 的应用基础逻辑，第一版直接使用
DeepSeek Chat 构建 LLM，后续任务才通过 LanguageModelService 动态构建。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from injector import inject
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from internal.core.language_model.entities.model_entity import ModelFeature
from internal.core.language_model.providers.deepseek.chat import Chat
from internal.entity.app_entity import AppType
from internal.exception import NotFoundException, ValidateErrorException
from internal.model import App, AppConfigVersion
from internal.service.language_model_service import LanguageModelService
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
@dataclass
class CompletionAppService:
    """Completion 应用类型服务，处理 app_type=completion 的应用逻辑。

    与 chatbot/agent 不同，Completion 应用：
    - 单轮文本生成，不维护对话历史
    - 用户输入作为变量填充到 prompt 模板
    - 直接调用 LLM 生成回复，不使用工具
    - 适用于翻译、摘要、改写等场景

    本服务作为独立组件存在，不修改 AppService / AppRuntimeService，
    后续任务会将其集成到对话调用链路中。
    """

    db: SQLAlchemy
    language_model_service: LanguageModelService

    # ------------------------------------------------------------------
    # 应用类型判断
    # ------------------------------------------------------------------
    @staticmethod
    def is_completion_app(app: App) -> bool:
        """判断应用是否为 Completion 类型。

        Args:
            app: 应用实例

        Returns:
            app_type 为 completion 时返回 True，否则 False
        """
        if app is None:
            return False
        return getattr(app, "app_type", None) == AppType.COMPLETION.value

    # ------------------------------------------------------------------
    # 配置读取：prompt 模板与模型配置
    # ------------------------------------------------------------------
    @staticmethod
    def get_prompt_template(app_config: AppConfigVersion | dict[str, Any] | None) -> str:
        """从应用配置中读取 prompt 模板。

        模板中可使用 ``{input}`` 占位符表示用户输入，其他变量暂不支持
        （后续任务扩展）。空模板返回空字符串。

        Args:
            app_config: 应用配置，可为 AppConfigVersion 模型实例或 dict

        Returns:
            prompt 模板字符串，不存在时返回空字符串
        """
        if app_config is None:
            return ""

        # 兼容 dict 与 AppConfigVersion 模型两种形式
        if isinstance(app_config, dict):
            preset_prompt = app_config.get("preset_prompt", "")
        else:
            preset_prompt = getattr(app_config, "preset_prompt", "") or ""

        if not isinstance(preset_prompt, str):
            return ""
        return preset_prompt

    @staticmethod
    def get_model_config(app_config: AppConfigVersion | dict[str, Any] | None) -> dict[str, Any]:
        """从应用配置中读取模型配置。

        返回 ``{provider, model, parameters}`` 结构，缺失时返回默认配置。

        Args:
            app_config: 应用配置，可为 AppConfigVersion 模型实例或 dict

        Returns:
            模型配置字典
        """
        default_model_config = {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "parameters": {},
        }

        if app_config is None:
            return default_model_config

        # 兼容 dict 与 AppConfigVersion 模型两种形式
        if isinstance(app_config, dict):
            model_config = app_config.get("model_config", {})
        else:
            model_config = getattr(app_config, "model_config", {}) or {}

        if not isinstance(model_config, dict) or not model_config:
            return default_model_config

        # 补全缺失字段，保证返回结构一致
        return {
            "provider": model_config.get("provider") or default_model_config["provider"],
            "model": model_config.get("model") or default_model_config["model"],
            "parameters": model_config.get("parameters") or {},
        }

    # ------------------------------------------------------------------
    # 执行入口
    # ------------------------------------------------------------------
    def generate(
        self,
        app_id: UUID,
        user_input: str,
        account: Any,
    ) -> dict[str, Any]:
        """执行单轮文本生成。

        加载 App + draft_app_config，校验 app_type == completion，
        构建 ChatPromptTemplate（如果模板含 ``{input}``，使用模板；否则直接用
        user_input），调用 LLM 生成回复。

        与 chatbot/agent 不同：
        - 不创建对话记录（Completion 无对话记忆）
        - 不使用工具（Completion 是纯文本生成）

        Args:
            app_id: 应用 ID
            user_input: 用户输入文本
            account: 触发账号（保留参数，便于后续权限/审计）

        Returns:
            生成结果字典，结构为::

                {
                    "text": <生成文本>,
                    "elapsed_time": <耗时（秒）>,
                    "model": <模型名>,
                }

            异常时返回::

                {
                    "text": "",
                    "elapsed_time": <耗时（秒）>,
                    "error": <错误信息>,
                    "model": <模型名>,
                }

        Raises:
            NotFoundException: 应用不存在
            ValidateErrorException: 应用类型非 completion
        """
        # 1.加载应用并校验类型
        app = self.db.session.query(App).filter(App.id == app_id).one_or_none()
        if app is None:
            raise NotFoundException(f"应用不存在: {app_id}")

        if not self.is_completion_app(app):
            raise ValidateErrorException(
                f"当前应用类型不是 completion（实际: {app.app_type}），无法调用 generate"
            )

        # 2.加载 draft_app_config 并提取 prompt 模板与模型配置
        draft_app_config = self._load_app_config(app)
        prompt_template = self.get_prompt_template(draft_app_config)
        model_config = self.get_model_config(draft_app_config)
        model_name = str(model_config.get("model") or "deepseek-chat")

        # 3.构建 LLM 与 prompt 链
        llm = self._build_llm(model_config)
        chain = self._build_chain(prompt_template, llm)

        # 4.调用 LLM 生成回复
        start_time = time.perf_counter()
        try:
            text = chain.invoke({"input": user_input})
            elapsed_time = time.perf_counter() - start_time
            # StrOutputParser 已将输出转为 str，二次保险转换
            if not isinstance(text, str):
                text = str(text) if text is not None else ""
            return {
                "text": text,
                "elapsed_time": elapsed_time,
                "model": model_name,
            }
        except Exception as exc:  # noqa: BLE001 - LLM 调用异常需转化为错误结果
            elapsed_time = time.perf_counter() - start_time
            logger.exception(
                "Completion 应用文本生成异常: app_id=%s, model=%s",
                app_id,
                model_name,
            )
            return {
                "text": "",
                "elapsed_time": elapsed_time,
                "error": str(exc),
                "model": model_name,
            }

    def generate_stream(
        self,
        app_id: UUID,
        user_input: str,
        account: Any,
    ) -> Iterator[str]:
        """流式生成文本。

        第一版为 ``generate`` 的简单包装：调用 ``generate`` 后 yield 整个结果
        文本。后续任务才接入 LLM 真正的 stream 方法，按块 yield。

        Args:
            app_id: 应用 ID
            user_input: 用户输入文本
            account: 触发账号（保留参数，便于后续权限/审计）

        Yields:
            生成文本块（第一版为整段文本，仅 yield 一次）
        """
        result = self.generate(app_id, user_input, account)
        text = result.get("text", "")
        if text:
            yield text

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------
    def _load_app_config(self, app: App) -> dict[str, Any]:
        """加载应用的 draft_app_config 并返回 dict 视图。

        优先使用 ``app.draft_app_config`` 属性返回的 AppConfigVersion 对象，
        提取 ``preset_prompt`` 与 ``model_config`` 字段组装成 dict；测试时
        可通过 monkeypatch 替换该方法避免触发数据库交互。

        Args:
            app: 应用实例

        Returns:
            应用配置字典
        """
        draft = getattr(app, "draft_app_config", None)
        if draft is None:
            return {}

        return {
            "preset_prompt": getattr(draft, "preset_prompt", "") or "",
            "model_config": getattr(draft, "model_config", {}) or {},
        }

    @staticmethod
    def _build_llm(model_config: dict[str, Any]) -> Chat:
        """根据模型配置构建 LLM 实例。

        第一版简化实现：直接使用 DeepSeek Chat 构建固定 provider 的 LLM，
        忽略 provider 字段，仅消费 model 与 parameters.temperature。
        后续任务才通过 LanguageModelService 动态构建。

        Args:
            model_config: 模型配置字典 ``{provider, model, parameters}``

        Returns:
            DeepSeek Chat LLM 实例
        """
        model_name = str(model_config.get("model") or "deepseek-chat")
        parameters = model_config.get("parameters") or {}
        temperature = parameters.get("temperature", 1)
        # 兜底类型转换，避免 parameters 中类型异常
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
            temperature = 1

        return Chat(
            model=model_name,
            temperature=temperature,
            features=[ModelFeature.TOOL_CALL.value, ModelFeature.AGENT_THOUGHT.value],
            metadata={},
        )

    @staticmethod
    def _build_chain(prompt_template: str, llm: Chat):
        """根据 prompt 模板与 LLM 构建调用链。

        - 模板含 ``{input}`` 占位符：使用 ChatPromptTemplate.from_template
        - 模板为空或不含 ``{input}``：使用 user_input 作为完整输入构建
          human 消息（模板作为 system 提示保留，便于后续扩展）

        Args:
            prompt_template: prompt 模板字符串
            llm: LLM 实例

        Returns:
            可调用 ``invoke({"input": ...})`` 的链对象
        """
        # 模板为空时直接以用户输入作为人类消息
        if not prompt_template:
            chain = ChatPromptTemplate.from_messages([
                ("human", "{input}"),
            ]) | llm | StrOutputParser()
            return chain

        # 模板含 {input} 占位符：填充用户输入
        if "{input}" in prompt_template:
            chain = ChatPromptTemplate.from_template(prompt_template) | llm | StrOutputParser()
            return chain

        # 模板不含 {input}：模板作为 system 提示，用户输入作为 human 消息
        chain = ChatPromptTemplate.from_messages([
            ("system", prompt_template),
            ("human", "{input}"),
        ]) | llm | StrOutputParser()
        return chain
