"""CompletionAppService 单元测试。

覆盖 Plan D-5 中定义的全部场景：
- is_completion_app：completion/chatbot/workflow 类型判断
- get_prompt_template：模板提取（存在/缺失/非 dict）
- get_model_config：模型配置提取（存在/缺失/默认值）
- generate：成功生成/模板含 {input}/模板不含 {input}/非 completion 应用/应用不存在/LLM 异常
- generate_stream：流式包装生成

mock 风格参考 test_workflow_app_service.py，不依赖真实数据库。
LLM 通过 monkeypatch 替换 ``_build_llm`` 与 ``_build_chain``，避免真实调用。
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from internal.entity.app_entity import AppType
from internal.exception import NotFoundException, ValidateErrorException
from internal.model import App
from internal.service.completion_app_service import CompletionAppService


# ----------------------------------------------------------------------
# 测试用 mock 基础设施
# ----------------------------------------------------------------------

class _ModelQuery:
    """模拟 SQLAlchemy Query，按模型返回预设结果。"""

    def __init__(self, result=None):
        self._result = result

    def filter(self, *_args, **_kwargs):
        # filter 链式调用返回自身，复用预设结果
        return self

    def one_or_none(self):
        return self._result

    def get(self, _pk):
        return self._result


class _DummySession:
    """模拟 SQLAlchemy session，按 model 路由到不同结果。"""

    def __init__(self):
        # key: model class, value: 预设查询结果
        self._results: dict[type, object] = {}

    def set_result(self, model: type, result):
        self._results[model] = result

    def query(self, model):
        return _ModelQuery(self._results.get(model))


class _DummyDB:
    """模拟 SQLAlchemy db，仅暴露 session 属性。"""

    def __init__(self):
        self.session = _DummySession()


def _new_service(db: _DummyDB | None = None) -> CompletionAppService:
    """构造 CompletionAppService 实例，注入 mock db 与 mock language_model_service。"""
    return CompletionAppService(
        db=db or _DummyDB(),
        language_model_service=SimpleNamespace(),  # 第一版未实际使用，占位即可
    )


def _make_app(
    app_type: str = AppType.COMPLETION.value,
    preset_prompt: str = "",
    model_config: dict | None = None,
) -> SimpleNamespace:
    """构造 mock App 对象。

    draft_app_config 上挂载 preset_prompt 与 model_config 属性，
    模拟 _load_app_config 的数据来源。
    """
    draft = SimpleNamespace(
        preset_prompt=preset_prompt,
        model_config=model_config or {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "parameters": {"temperature": 0.5},
        },
    )
    return SimpleNamespace(
        id=uuid4(),
        app_type=app_type,
        draft_app_config=draft,
    )


class _MockLLM(RunnableLambda):
    """模拟 LLM Runnable，invoke 返回 AIMessage。

    继承自 RunnableLambda 以便在 ``ChatPromptTemplate | llm | StrOutputParser``
    链中作为 Runnable 使用；返回 AIMessage 与真实 ChatModel 行为一致，
    StrOutputParser 会从 ``.content`` 取出文本。
    """

    def __init__(self, content: str = "mocked output"):
        self._content = content
        self.invoke_called = 0
        super().__init__(self._invoke_func)

    def _invoke_func(self, _messages):
        self.invoke_called += 1
        return AIMessage(content=self._content)


class _MockChain:
    """模拟 LLM 调用链，invoke 返回固定文本。"""

    def __init__(self, text: str = "mocked output", raise_exc: Exception | None = None):
        self._text = text
        self._raise_exc = raise_exc
        self.invoke_called = 0
        self.last_input = None

    def invoke(self, input_dict):
        self.invoke_called += 1
        self.last_input = input_dict
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._text


# ----------------------------------------------------------------------
# 测试用例
# ----------------------------------------------------------------------

class TestCompletionAppService:
    # --- is_completion_app ---

    def test_is_completion_app_returns_true_for_completion_type(self):
        """app_type=completion 时返回 True。"""
        app = _make_app(app_type=AppType.COMPLETION.value)

        assert CompletionAppService.is_completion_app(app) is True

    def test_is_completion_app_returns_false_for_chatbot_type(self):
        """app_type=chatbot 时返回 False。"""
        app = _make_app(app_type=AppType.CHATBOT.value)

        assert CompletionAppService.is_completion_app(app) is False

    def test_is_completion_app_returns_false_for_workflow_type(self):
        """app_type=workflow 时返回 False。"""
        app = _make_app(app_type=AppType.WORKFLOW.value)

        assert CompletionAppService.is_completion_app(app) is False

    def test_is_completion_app_returns_false_for_none_app(self):
        """app 为 None 时返回 False。"""
        assert CompletionAppService.is_completion_app(None) is False

    # --- get_prompt_template ---

    def test_get_prompt_template_returns_template(self):
        """配置中有 preset_prompt 时返回模板字符串。"""
        config = {"preset_prompt": "请将以下文本翻译为英文: {input}"}

        result = CompletionAppService.get_prompt_template(config)

        assert result == "请将以下文本翻译为英文: {input}"

    def test_get_prompt_template_returns_empty_when_no_template(self):
        """配置中无 preset_prompt 时返回空字符串。"""
        result = CompletionAppService.get_prompt_template({"model_config": {}})

        assert result == ""

    def test_get_prompt_template_returns_empty_when_none_config(self):
        """app_config 为 None 时返回空字符串。"""
        result = CompletionAppService.get_prompt_template(None)

        assert result == ""

    def test_get_prompt_template_from_dict(self):
        """从 dict 获取模板字符串。"""
        config = {"preset_prompt": "摘要: {input}"}

        result = CompletionAppService.get_prompt_template(config)

        assert result == "摘要: {input}"

    def test_get_prompt_template_from_namespace(self):
        """从 AppConfigVersion 模型实例（SimpleNamespace 模拟）获取模板。"""
        config = SimpleNamespace(preset_prompt="改写: {input}")

        result = CompletionAppService.get_prompt_template(config)

        assert result == "改写: {input}"

    def test_get_prompt_template_returns_empty_when_non_string(self):
        """preset_prompt 为非字符串时返回空字符串。"""
        config = {"preset_prompt": 123}

        result = CompletionAppService.get_prompt_template(config)

        assert result == ""

    # --- get_model_config ---

    def test_get_model_config_returns_config(self):
        """配置中有 model_config 时返回完整字典。"""
        config = {
            "model_config": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "parameters": {"temperature": 0.7},
            },
        }

        result = CompletionAppService.get_model_config(config)

        assert result["provider"] == "deepseek"
        assert result["model"] == "deepseek-chat"
        assert result["parameters"] == {"temperature": 0.7}

    def test_get_model_config_returns_default_when_missing(self):
        """配置中无 model_config 时返回默认配置。"""
        result = CompletionAppService.get_model_config({"preset_prompt": ""})

        assert result["provider"] == "deepseek"
        assert result["model"] == "deepseek-chat"
        assert result["parameters"] == {}

    def test_get_model_config_returns_default_when_none_config(self):
        """app_config 为 None 时返回默认配置。"""
        result = CompletionAppService.get_model_config(None)

        assert result["provider"] == "deepseek"
        assert result["model"] == "deepseek-chat"
        assert result["parameters"] == {}

    def test_get_model_config_fills_missing_fields(self):
        """model_config 中部分字段缺失时补全为默认值。"""
        config = {"model_config": {"provider": "deepseek"}}

        result = CompletionAppService.get_model_config(config)

        # 缺失 model 与 parameters 时使用默认值
        assert result["provider"] == "deepseek"
        assert result["model"] == "deepseek-chat"
        assert result["parameters"] == {}

    # --- generate ---

    def test_generate_with_input_placeholder(self, monkeypatch):
        """模板含 {input} 时通过 ChatPromptTemplate.from_template 填充用户输入。"""
        app = _make_app(
            app_type=AppType.COMPLETION.value,
            preset_prompt="请将以下文本翻译为英文: {input}",
        )
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        # mock _build_llm 返回 mock 对象
        mock_llm = _MockLLM(content="Translated text")
        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: mock_llm,
        )
        # mock _build_chain 捕获 prompt_template，验证含 {input} 时调用 from_template
        captured: dict = {}

        def _fake_build_chain(prompt_template, llm):
            captured["prompt_template"] = prompt_template
            captured["llm"] = llm
            return _MockChain(text="Translated text")

        monkeypatch.setattr(CompletionAppService, "_build_chain", staticmethod(_fake_build_chain))

        result = service.generate(uuid4(), "你好世界", SimpleNamespace(id=uuid4()))

        assert captured["prompt_template"] == "请将以下文本翻译为英文: {input}"
        assert captured["llm"] is mock_llm
        assert result["text"] == "Translated text"
        assert result["model"] == "deepseek-chat"

    def test_generate_without_input_placeholder(self, monkeypatch):
        """模板不含 {input} 时模板作为 system 提示，用户输入作为 human 消息。"""
        app = _make_app(
            app_type=AppType.COMPLETION.value,
            preset_prompt="你是一个翻译助手，请翻译用户输入为英文。",
        )
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        mock_llm = _MockLLM(content="Translated")
        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: mock_llm,
        )
        captured: dict = {}

        def _fake_build_chain(prompt_template, llm):
            captured["prompt_template"] = prompt_template
            return _MockChain(text="Translated")

        monkeypatch.setattr(CompletionAppService, "_build_chain", staticmethod(_fake_build_chain))

        result = service.generate(uuid4(), "你好", SimpleNamespace(id=uuid4()))

        # 模板不含 {input}，应作为 system 提示
        assert captured["prompt_template"] == "你是一个翻译助手，请翻译用户输入为英文。"
        assert result["text"] == "Translated"

    def test_generate_without_template(self, monkeypatch):
        """无 prompt 模板时直接以用户输入作为 human 消息。"""
        app = _make_app(
            app_type=AppType.COMPLETION.value,
            preset_prompt="",
        )
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: _MockLLM(),
        )
        captured: dict = {}

        def _fake_build_chain(prompt_template, llm):
            captured["prompt_template"] = prompt_template
            return _MockChain(text="plain output")

        monkeypatch.setattr(CompletionAppService, "_build_chain", staticmethod(_fake_build_chain))

        result = service.generate(uuid4(), "直接输入", SimpleNamespace(id=uuid4()))

        assert captured["prompt_template"] == ""
        assert result["text"] == "plain output"

    def test_generate_returns_dict_with_text(self, monkeypatch):
        """generate 返回 dict 含 text 字段。"""
        app = _make_app(app_type=AppType.COMPLETION.value)
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: _MockLLM(),
        )
        monkeypatch.setattr(
            CompletionAppService,
            "_build_chain",
            staticmethod(lambda pt, llm: _MockChain(text="hello")),
        )

        result = service.generate(uuid4(), "input", SimpleNamespace(id=uuid4()))

        assert isinstance(result, dict)
        assert "text" in result
        assert result["text"] == "hello"

    def test_generate_returns_elapsed_time(self, monkeypatch):
        """generate 返回 dict 含 elapsed_time 字段且为非负数。"""
        app = _make_app(app_type=AppType.COMPLETION.value)
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: _MockLLM(),
        )
        monkeypatch.setattr(
            CompletionAppService,
            "_build_chain",
            staticmethod(lambda pt, llm: _MockChain(text="hi")),
        )

        result = service.generate(uuid4(), "input", SimpleNamespace(id=uuid4()))

        assert "elapsed_time" in result
        assert isinstance(result["elapsed_time"], float)
        assert result["elapsed_time"] >= 0

    def test_generate_returns_model_field(self, monkeypatch):
        """generate 返回 dict 含 model 字段，与配置一致。"""
        app = _make_app(
            app_type=AppType.COMPLETION.value,
            model_config={
                "provider": "deepseek",
                "model": "deepseek-reasoner",
                "parameters": {"temperature": 0.0},
            },
        )
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: _MockLLM(),
        )
        monkeypatch.setattr(
            CompletionAppService,
            "_build_chain",
            staticmethod(lambda pt, llm: _MockChain(text="hi")),
        )

        result = service.generate(uuid4(), "input", SimpleNamespace(id=uuid4()))

        assert result["model"] == "deepseek-reasoner"

    def test_generate_raises_for_non_completion_app(self):
        """非 completion 应用调用 generate 抛 ValidateErrorException。"""
        app = _make_app(app_type=AppType.CHATBOT.value)
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        with pytest.raises(ValidateErrorException):
            service.generate(uuid4(), "input", SimpleNamespace(id=uuid4()))

    def test_generate_raises_when_app_not_found(self):
        """应用不存在时抛 NotFoundException。"""
        db = _DummyDB()
        db.session.set_result(App, None)
        service = _new_service(db)

        with pytest.raises(NotFoundException):
            service.generate(uuid4(), "input", SimpleNamespace(id=uuid4()))

    def test_generate_handles_llm_error(self, monkeypatch):
        """LLM 异常时返回 error 字段，text 为空字符串。"""
        app = _make_app(app_type=AppType.COMPLETION.value)
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: _MockLLM(),
        )
        # mock chain 在 invoke 时抛异常
        monkeypatch.setattr(
            CompletionAppService,
            "_build_chain",
            staticmethod(
                lambda pt, llm: _MockChain(raise_exc=RuntimeError("LLM 调用失败"))
            ),
        )

        result = service.generate(uuid4(), "input", SimpleNamespace(id=uuid4()))

        assert result["text"] == ""
        assert "error" in result
        assert "LLM 调用失败" in result["error"]
        assert result["model"] == "deepseek-chat"
        assert result["elapsed_time"] >= 0

    def test_generate_calls_chain_with_input(self, monkeypatch):
        """generate 调用 chain.invoke 时传入 ``{"input": user_input}``。"""
        app = _make_app(app_type=AppType.COMPLETION.value)
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: _MockLLM(),
        )
        mock_chain = _MockChain(text="output")
        monkeypatch.setattr(
            CompletionAppService,
            "_build_chain",
            staticmethod(lambda pt, llm: mock_chain),
        )

        service.generate(uuid4(), "用户输入文本", SimpleNamespace(id=uuid4()))

        assert mock_chain.invoke_called == 1
        assert mock_chain.last_input == {"input": "用户输入文本"}

    # --- generate_stream ---

    def test_generate_stream_yields_text(self, monkeypatch):
        """generate_stream 调用 generate 后 yield 文本。"""
        app = _make_app(app_type=AppType.COMPLETION.value)
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: _MockLLM(),
        )
        monkeypatch.setattr(
            CompletionAppService,
            "_build_chain",
            staticmethod(lambda pt, llm: _MockChain(text="streamed text")),
        )

        chunks = list(service.generate_stream(uuid4(), "input", SimpleNamespace(id=uuid4())))

        assert chunks == ["streamed text"]

    def test_generate_stream_yields_nothing_on_error(self, monkeypatch):
        """generate_stream 在 generate 异常时不 yield 任何文本。"""
        app = _make_app(app_type=AppType.COMPLETION.value)
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        monkeypatch.setattr(
            CompletionAppService,
            "_build_llm",
            lambda self, model_config: _MockLLM(),
        )
        monkeypatch.setattr(
            CompletionAppService,
            "_build_chain",
            staticmethod(
                lambda pt, llm: _MockChain(raise_exc=RuntimeError("error"))
            ),
        )

        chunks = list(service.generate_stream(uuid4(), "input", SimpleNamespace(id=uuid4())))

        # generate 异常时 text 为空字符串，generate_stream 不 yield
        assert chunks == []

    # --- _build_llm ---

    def test_build_llm_uses_model_name_from_config(self):
        """_build_llm 使用 model_config 中的 model 名构建 LLM。"""
        model_config = {
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "parameters": {"temperature": 0.2},
        }

        llm = CompletionAppService._build_llm(model_config)

        assert llm is not None
        # DeepSeek Chat 模型通过 model_name 或 model 属性暴露模型名
        model_attr = getattr(llm, "model_name", None) or getattr(llm, "model", None)
        assert model_attr == "deepseek-reasoner"

    def test_build_llm_uses_default_when_model_missing(self):
        """model_config 缺失 model 字段时使用默认值 deepseek-chat。"""
        model_config = {"provider": "deepseek", "parameters": {}}

        llm = CompletionAppService._build_llm(model_config)

        assert llm is not None
        model_attr = getattr(llm, "model_name", None) or getattr(llm, "model", None)
        assert model_attr == "deepseek-chat"

    # --- _build_chain ---

    def test_build_chain_with_input_placeholder(self):
        """模板含 {input} 时构建 from_template 链。"""
        llm = _MockLLM()
        # _build_chain 返回 RunnableSequence，invoke 应能正常调用
        chain = CompletionAppService._build_chain("翻译: {input}", llm)

        result = chain.invoke({"input": "你好"})

        # _MockLLM.invoke 返回 SimpleNamespace(content=...)，
        # 但通过 StrOutputParser 解析时取 content 属性
        assert result == "mocked output"

    def test_build_chain_without_template(self):
        """模板为空时直接以用户输入作为 human 消息。"""
        llm = _MockLLM()
        chain = CompletionAppService._build_chain("", llm)

        result = chain.invoke({"input": "你好"})

        assert result == "mocked output"

    def test_build_chain_without_input_placeholder(self):
        """模板不含 {input} 时模板作为 system 提示。"""
        llm = _MockLLM()
        chain = CompletionAppService._build_chain("你是一个翻译助手。", llm)

        result = chain.invoke({"input": "你好"})

        assert result == "mocked output"
