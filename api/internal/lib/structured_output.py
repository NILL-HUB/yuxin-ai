"""Structured output fallback for LLM providers without native response_format support.

Some providers (e.g. DeepSeek-compatible endpoints) reject ``with_structured_output``
with a 400 ``response_format is unavailable`` error.  Instead of letting the whole
execution chain collapse, this module falls back to a plain-text invocation with an
explicit JSON schema instruction and parses the model response locally.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncIterator, Iterator

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
)
from langchain_core.runnables import Runnable
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_UNSUPPORTED_PATTERNS = (
    "response_format",
    "structured output",
    "json_schema",
    "json schema",
    "json mode",
    "json_mode",
    "not support",
    "unsupported",
    "unavailable",
    "not implemented",
)


def _is_unsupported_structured_error(exc: Exception) -> bool:
    """判断异常是否属于“provider 不支持结构化输出”而非普通业务错误。"""
    message = str(exc).lower()
    for pattern in _UNSUPPORTED_PATTERNS:
        if pattern in message:
            return True
    exception_name = type(exc).__name__.lower()
    return "notimplemented" in exception_name or "notimplementederror" in exception_name


def _extract_text_from_response(response: Any) -> str:
    """从 LangChain 响应（字符串 / AIMessage / 其他对象）中提取文本。"""
    if isinstance(response, str):
        return response
    if isinstance(response, BaseMessage):
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return "\n".join(parts)
        return str(content)
    return str(response)


def parse_json_blob(text: str) -> Any:
    """从模型文本中提取并解析 JSON 对象或数组。

    兼容常见模型输出形态：
    - 纯 JSON
    - ```json ... ``` 代码块
    - JSON 前后带解释性文本
    """
    if not text:
        raise ValueError("empty model response")

    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)

    # 直接从剥离后的文本解析
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 提取第一个 JSON 对象或数组
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(stripped)):
            char = stripped[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : index + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError("no JSON object found in model response")


def _coerce_messages(input_value: Any) -> Any:
    """把 dict / 普通对象输入转换成 LangChain 消息，保持字符串输入原样。"""
    if isinstance(input_value, str):
        return input_value
    if isinstance(input_value, list):
        if all(isinstance(item, BaseMessage) for item in input_value):
            return input_value
        return [HumanMessage(content=str(item)) for item in input_value]
    if isinstance(input_value, dict):
        return [HumanMessage(content=json.dumps(input_value, ensure_ascii=False))]
    return str(input_value)


class StructuredOutputFallbackRunnable(Runnable[Any, BaseModel]):
    """与 LangChain Runnable 兼容的结构化输出包装器。

    优先使用原生 ``with_structured_output``；provider 不支持时退化为
    普通文本调用 + JSON 提示 + 本地解析。
    """

    def __init__(
        self,
        llm: Any,
        response_model: type[BaseModel],
        *,
        include_raw: bool = False,
        name: str | None = None,
    ) -> None:
        self.llm = llm
        self.response_model = response_model
        self.include_raw = include_raw
        self.name = name or f"structured_fallback_{response_model.__name__}"
        self._schema = self._build_schema(response_model)

    @staticmethod
    def _build_schema(response_model: type[BaseModel]) -> dict[str, Any]:
        if isinstance(response_model, type) and issubclass(response_model, BaseModel):
            try:
                return response_model.model_json_schema()
            except Exception:
                pass
        try:
            return response_model.model_json_schema()
        except Exception:
            return {}

    def _build_json_prompt(self, prompt: str) -> str:
        schema_text = json.dumps(self._schema, ensure_ascii=False, indent=2)
        return (
            "你是一个严格的 JSON 输出器。请只输出一个 JSON 对象，不要输出任何解释、"
            "代码块标记或其他文字。JSON 必须严格符合下面的 schema：\n\n"
            f"```json\n{schema_text}\n```\n\n用户请求：\n{prompt}"
        )

    def _parse_response(self, response: Any) -> BaseModel:
        text = _extract_text_from_response(response)
        try:
            parsed = parse_json_blob(text)
        except Exception as exc:
            raise ValueError(f"structured output fallback: failed to parse JSON: {exc}") from exc

        if isinstance(parsed, self.response_model):
            result = parsed
        elif isinstance(parsed, dict):
            result = self.response_model.model_validate(parsed)
        else:
            raise ValueError(
                f"structured output fallback: expected object but got {type(parsed).__name__}"
            )

        if self.include_raw:
            return self.response_model.model_validate(
                {
                    **result.model_dump(),
                    "raw": text,
                }
            )
        return result

    @staticmethod
    def _aggregate_stream(stream: Iterator[Any]) -> str:
        chunks: list[Any] = []
        for chunk in stream:
            chunks.append(chunk)
        return StructuredOutputFallbackRunnable._aggregate_chunks(chunks)

    @staticmethod
    async def _aggregate_async_stream(stream: AsyncIterator[Any]) -> str:
        chunks: list[Any] = []
        async for chunk in stream:
            chunks.append(chunk)
        return StructuredOutputFallbackRunnable._aggregate_chunks(chunks)

    @staticmethod
    def _aggregate_chunks(chunks: list[Any]) -> str:
        if not chunks:
            return ""
        aggregated = chunks[0]
        for chunk in chunks[1:]:
            try:
                aggregated = aggregated + chunk
            except (TypeError, AttributeError):
                aggregated = chunk
        return _extract_text_from_response(aggregated)

    def invoke(self, input_value: Any, config: Any | None = None, **kwargs: Any) -> Any:
        del config, kwargs

        try:
            if self.include_raw:
                structured = self.llm.with_structured_output(
                    self.response_model,
                    include_raw=True,
                )
            else:
                structured = self.llm.with_structured_output(self.response_model)
            return structured.invoke(input_value)
        except Exception as exc:
            if not _is_unsupported_structured_error(exc):
                raise
            logger.warning(
                "结构化输出不被当前模型支持，降级为 JSON 文本解析: model=%s error=%s",
                getattr(self.llm, "model_name", getattr(self.llm, "model", "?")),
                exc,
            )

        messages = _coerce_messages(input_value)
        prompt = messages if isinstance(messages, str) else messages
        if isinstance(prompt, str):
            prompt_text = self._build_json_prompt(prompt)
        else:
            prompt_text = self._build_json_prompt(
                "\n".join(
                    f"{type(msg).__name__}: {msg.content if isinstance(msg.content, str) else str(msg.content)}"
                    for msg in prompt
                )
            )
        response = self.llm.invoke(prompt_text)
        return self._parse_response(response)

    def stream(self, input_value: Any, config: Any | None = None, **kwargs: Any) -> Iterator[Any]:
        del config, kwargs

        try:
            if self.include_raw:
                structured = self.llm.with_structured_output(
                    self.response_model,
                    include_raw=True,
                )
            else:
                structured = self.llm.with_structured_output(self.response_model)
            for chunk in structured.stream(input_value):
                yield chunk
            return
        except Exception as exc:
            if not _is_unsupported_structured_error(exc):
                raise
            logger.warning(
                "结构化流式输出不被当前模型支持，降级为 JSON 文本流解析: model=%s error=%s",
                getattr(self.llm, "model_name", getattr(self.llm, "model", "?")),
                exc,
            )

        messages = _coerce_messages(input_value)
        if isinstance(messages, str):
            prompt_text = self._build_json_prompt(messages)
        else:
            prompt_text = self._build_json_prompt(
                "\n".join(
                    f"{type(msg).__name__}: {msg.content if isinstance(msg.content, str) else str(msg.content)}"
                    for msg in messages
                )
            )
        text = self._aggregate_stream(self.llm.stream(prompt_text))
        yield self._parse_response(text)

    async def ainvoke(self, input_value: Any, config: Any | None = None, **kwargs: Any) -> Any:
        del config, kwargs

        try:
            if self.include_raw:
                structured = self.llm.with_structured_output(
                    self.response_model,
                    include_raw=True,
                )
            else:
                structured = self.llm.with_structured_output(self.response_model)
            return await structured.ainvoke(input_value)
        except Exception as exc:
            if not _is_unsupported_structured_error(exc):
                raise
            logger.warning(
                "结构化输出不被当前模型支持（async），降级为 JSON 文本解析: model=%s error=%s",
                getattr(self.llm, "model_name", getattr(self.llm, "model", "?")),
                exc,
            )

        messages = _coerce_messages(input_value)
        if isinstance(messages, str):
            prompt_text = self._build_json_prompt(messages)
        else:
            prompt_text = self._build_json_prompt(
                "\n".join(
                    f"{type(msg).__name__}: {msg.content if isinstance(msg.content, str) else str(msg.content)}"
                    for msg in messages
                )
            )
        response = await self.llm.ainvoke(prompt_text)
        return self._parse_response(response)

    async def astream(
        self,
        input_value: Any,
        config: Any | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        del config, kwargs

        try:
            if self.include_raw:
                structured = self.llm.with_structured_output(
                    self.response_model,
                    include_raw=True,
                )
            else:
                structured = self.llm.with_structured_output(self.response_model)
            async for chunk in structured.astream(input_value):
                yield chunk
            return
        except Exception as exc:
            if not _is_unsupported_structured_error(exc):
                raise
            logger.warning(
                "结构化流式输出不被当前模型支持（async），降级为 JSON 文本流解析: model=%s error=%s",
                getattr(self.llm, "model_name", getattr(self.llm, "model", "?")),
                exc,
            )

        messages = _coerce_messages(input_value)
        if isinstance(messages, str):
            prompt_text = self._build_json_prompt(messages)
        else:
            prompt_text = self._build_json_prompt(
                "\n".join(
                    f"{type(msg).__name__}: {msg.content if isinstance(msg.content, str) else str(msg.content)}"
                    for msg in messages
                )
            )
        text = await self._aggregate_async_stream(self.llm.astream(prompt_text))
        yield self._parse_response(text)


def with_structured_output_fallback(
    llm: Any,
    response_model: type[BaseModel],
    *,
    include_raw: bool = False,
    name: str | None = None,
) -> StructuredOutputFallbackRunnable:
    """返回带兜底的结构化输出 Runnable，替代 ``llm.with_structured_output(...)``。"""
    return StructuredOutputFallbackRunnable(
        llm,
        response_model,
        include_raw=include_raw,
        name=name,
    )
