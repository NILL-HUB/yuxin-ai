import pytest
from pydantic import BaseModel

from internal.lib.structured_output import (
    StructuredOutputFallbackRunnable,
    parse_json_blob,
    with_structured_output_fallback,
)


class _FakeResponse:
    def __init__(self):
        self.request = None
        self.status_code = 400
        self.headers = {}


class _FakeUnsupportedStructuredLLM:
    """模拟 provider 不支持 response_format：结构化输出直接抛 400。"""

    def with_structured_output(self, *_args, **_kwargs):
        from openai import BadRequestError

        raise BadRequestError(
            "This response_format type is unavailable now",
            response=_FakeResponse(),
            body=None,
        )

    def invoke(self, prompt):
        return '好的，结果如下：{"name": "测试会话", "summary": "用户想了解执行流程"}'

    async def ainvoke(self, prompt):
        return self.invoke(prompt)

    def stream(self, prompt):
        yield "好的，结果如下："
        yield '{"name": "测试会话", "summary": "用户想了解执行流程"}'

    async def astream(self, prompt):
        yield "好的，结果如下："
        yield '{"name": "测试会话", "summary": "用户想了解执行流程"}'


class _ConversationInfo(BaseModel):
    name: str
    summary: str = ""


def test_parse_json_blob_extracts_json_from_code_fence():
    text = "好的，结果是 ```json\n{\"a\": 1}\n``` 结束"

    assert parse_json_blob(text) == {"a": 1}


def test_structured_output_fallback_invoke_parses_json():
    llm = _FakeUnsupportedStructuredLLM()
    runnable = with_structured_output_fallback(llm, _ConversationInfo)

    result = runnable.invoke("请生成会话名")

    assert isinstance(result, _ConversationInfo)
    assert result.name == "测试会话"


def test_structured_output_fallback_stream_returns_model_chunk():
    llm = _FakeUnsupportedStructuredLLM()
    runnable = with_structured_output_fallback(llm, _ConversationInfo)

    chunks = list(runnable.stream("请生成会话名"))

    assert chunks
    assert isinstance(chunks[-1], _ConversationInfo)


@pytest.mark.asyncio
async def test_structured_output_fallback_async_methods():
    llm = _FakeUnsupportedStructuredLLM()
    runnable = with_structured_output_fallback(llm, _ConversationInfo)

    result = await runnable.ainvoke("请生成会话名")
    assert isinstance(result, _ConversationInfo)
    assert result.name == "测试会话"

    chunks = []
    async for chunk in runnable.astream("请生成会话名"):
        chunks.append(chunk)
    assert isinstance(chunks[-1], _ConversationInfo)


class _FakeSupportedStructuredLLM:
    """模拟原生结构化输出可用：with_structured_output 返回可调用对象。"""

    def with_structured_output(self, *_args, **_kwargs):
        return _FakeStructuredRunnable()


class _FakeStructuredRunnable:
    def invoke(self, input_value):
        assert input_value == {"query": "hello"}
        return _ConversationInfo(name="原生结果")


def test_structured_output_fallback_prefers_native_structured_output():
    llm = _FakeSupportedStructuredLLM()
    runnable = with_structured_output_fallback(llm, _ConversationInfo)

    result = runnable.invoke({"query": "hello"})

    assert isinstance(result, _ConversationInfo)
    assert result.name == "原生结果"


def test_fallback_runnable_can_be_composed_in_lcel_chain():
    from langchain_core.prompts import ChatPromptTemplate

    runnable = with_structured_output_fallback(
        _FakeUnsupportedStructuredLLM(), _ConversationInfo
    )

    chain = ChatPromptTemplate.from_messages([("human", "{q}")]) | runnable

    assert callable(chain.invoke)
    assert isinstance(runnable, StructuredOutputFallbackRunnable)
