from langchain_core.messages import HumanMessage, SystemMessage

from internal.service.language_model_service import RuntimeFallbackLanguageModelProxy


class _FakeModelWithoutTokenCount:
    """模拟 deepseek-v4-flash 等未实现 token 计数的模型。"""

    features = []
    metadata = {}

    def get_num_tokens_from_messages(self, messages):
        raise NotImplementedError(
            "get_num_tokens_from_messages() is not presently implemented for model deepseek-v4-flash"
        )


def _build_proxy() -> RuntimeFallbackLanguageModelProxy:
    model = _FakeModelWithoutTokenCount()
    proxy = RuntimeFallbackLanguageModelProxy(features=[], metadata={})
    object.__setattr__(proxy, "_model", model)
    object.__setattr__(proxy, "_primary_model", model)
    object.__setattr__(
        proxy,
        "_requested_model_ref",
        {"provider": "deepseek", "model": "deepseek-v4-flash"},
    )
    return proxy


def test_token_count_falls_back_when_model_not_implemented():
    proxy = _build_proxy()
    messages = [SystemMessage(content="你好"), HumanMessage(content="今天天气怎么样")]

    count = proxy.get_num_tokens_from_messages(messages)

    assert isinstance(count, int)
    assert count > 0
