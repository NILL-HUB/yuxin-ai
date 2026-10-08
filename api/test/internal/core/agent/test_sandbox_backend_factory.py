"""沙箱后端工厂/注册表单测。

覆盖接线：`SandboxConfigService.resolve_runtime()` → `build_sandbox_backend(runtime)`
（core 层唯一构造入口）；并锁定「接入新沙箱只需延伸分支」这一扩展点。
"""
import json
from types import SimpleNamespace

import pytest
import requests

from internal.core.agent.backends import (
    HttpSandboxHandle,
    available_backends,
    build_sandbox_backend,
)
from internal.core.agent.backends.e2b_protocol_sandbox_backend import E2bProtocolSandboxBackend
from internal.core.agent.entities.sandbox_runtime_entity import (
    BACKEND_ALIYUN_SANDBOX,
    BACKEND_BAIDU_CFC,
    BACKEND_DISABLED,
    BACKEND_E2B_CLOUD,
    BACKEND_HTTP_SANDBOX,
    BACKEND_TENCENT_SCF,
    CAPABILITY_CODE_INTERPRETER,
    CAPABILITY_SKILL_EXEC,
    SandboxRuntime,
)
from internal.exception import FailException


def _runtime(capability, backend, *, enabled, configs=None, credentials=None, reason=""):
    return SandboxRuntime(
        capability=capability,
        backend=backend,
        configs=configs or {},
        credentials=credentials or {},
        enabled=enabled,
        reason=reason,
    )


def test_disabled_backend_builds_nothing_and_reports_reason():
    runtime = _runtime(
        CAPABILITY_CODE_INTERPRETER,
        BACKEND_DISABLED,
        enabled=False,
        reason="该能力域已显式关闭（未开通）",
    )
    assert build_sandbox_backend(runtime) is None
    assert runtime.reason  # 调用方据此如实提示，不再静默降级


def test_all_declared_backends_are_registered():
    # 声明（entity）与实现（factory）不允许漂移：新增后端必须同时注册
    assert set(available_backends()) >= {
        BACKEND_BAIDU_CFC,
        BACKEND_E2B_CLOUD,
        BACKEND_ALIYUN_SANDBOX,
        BACKEND_HTTP_SANDBOX,
        BACKEND_TENCENT_SCF,
        BACKEND_DISABLED,
    }


def test_http_sandbox_returns_handle_with_per_capability_endpoint():
    runtime = _runtime(
        CAPABILITY_SKILL_EXEC,
        BACKEND_HTTP_SANDBOX,
        enabled=True,
        configs={"endpoint": "https://scf.real.example.org/skills", "timeout_seconds": 42},
    )
    handle = build_sandbox_backend(runtime)
    assert isinstance(handle, HttpSandboxHandle)
    assert handle.endpoint == "https://scf.real.example.org/skills"
    assert handle.timeout_seconds == 42


def test_http_sandbox_not_enabled_returns_none():
    runtime = _runtime(
        CAPABILITY_SKILL_EXEC,
        BACKEND_HTTP_SANDBOX,
        enabled=False,
        configs={"endpoint": "https://scf.real.example.org/skills"},
        reason="远端 endpoint 未配置或为占位符",
    )
    assert build_sandbox_backend(runtime) is None


def test_e2b_backend_not_enabled_is_not_constructed(monkeypatch):
    monkeypatch.setenv("E2B_API_KEY", "k")
    monkeypatch.setenv("E2B_DOMAIN", "sandbox.example.com")
    runtime = _runtime(CAPABILITY_CODE_INTERPRETER, BACKEND_BAIDU_CFC, enabled=False)
    assert build_sandbox_backend(runtime) is None


def test_e2b_backend_constructed_from_runtime_configs(monkeypatch):
    # 凭证由 service 层解析后注入 runtime（core 不读 env）。
    # 故意把 env 设成不同值，断言 env **不再被消费**，锁定"后台配置优先"。
    monkeypatch.setenv("E2B_API_KEY", "env-should-be-ignored")
    monkeypatch.setenv("E2B_DOMAIN", "env.example.com")
    runtime = _runtime(
        CAPABILITY_CODE_INTERPRETER,
        BACKEND_BAIDU_CFC,
        enabled=True,
        configs={
            "template_alias": "llmops-code-interpreter-lite",
            "fallback_template_alias": "code-interpreter-v1",
            "execute_timeout_seconds": 120,
            "sandbox_timeout_seconds": 300,
        },
        credentials={"E2B_API_KEY": "k", "E2B_DOMAIN": "sandbox.example.com"},
    )
    backend = build_sandbox_backend(runtime)
    assert isinstance(backend, E2bProtocolSandboxBackend)
    # 后端不再自行读 env 决定模板/凭证，而是消费 runtime
    assert backend._template_alias == "llmops-code-interpreter-lite"
    assert backend._fallback_template_alias == "code-interpreter-v1"
    assert backend._api_key == "k"
    assert backend._domain == "sandbox.example.com"


def test_unknown_backend_raises():
    runtime = _runtime(CAPABILITY_CODE_INTERPRETER, "not_registered", enabled=True)
    with pytest.raises(ValueError):
        build_sandbox_backend(runtime)


def test_extension_point_registering_new_backend():
    """接入新沙箱只需延伸分支：注册一个构造器即可被工厂识别。"""
    from internal.core.agent.backends import factory as factory_module

    sentinel = object()
    factory_module.register_sandbox_backend("custom_sandbox", lambda _runtime: sentinel)
    try:
        runtime = _runtime(CAPABILITY_CODE_INTERPRETER, "custom_sandbox", enabled=True)
        assert build_sandbox_backend(runtime) is sentinel
        assert "custom_sandbox" in available_backends()
    finally:
        factory_module._REGISTRY.pop("custom_sandbox", None)


# --------------------------------------------------------------------------- #
#  HttpSandboxHandle：HTTP 后端的唯一传输入口（execute = 发一次请求、拿回结果）
# --------------------------------------------------------------------------- #


def test_http_handle_normalizes_endpoint_and_timeout():
    handle = HttpSandboxHandle(endpoint="  https://sandbox.example.com/code/  ", timeout_seconds=0)
    assert handle.endpoint == "https://sandbox.example.com/code"
    assert handle.timeout_seconds == 60  # 非法/非正回退默认
    assert HttpSandboxHandle(endpoint="x", timeout_seconds=-5).timeout_seconds == 60
    assert HttpSandboxHandle(endpoint="x", timeout_seconds=7).timeout_seconds == 7


def test_http_handle_execute_posts_json_and_unwraps_scf_body(monkeypatch):
    calls = []

    def _fake_post(url, **kwargs):
        # 注意：不要用 json= 作为形参名，否则会遮蔽模块名 json
        calls.append({"url": url, "json": kwargs["json"], "timeout": kwargs["timeout"]})
        return SimpleNamespace(
            status_code=200,
            text="ok",
            json=lambda: {
                "statusCode": 200,
                "body": json.dumps({"result": {"x": 1}}),
            },
        )

    monkeypatch.setattr("internal.core.agent.backends.factory.requests.post", _fake_post)

    handle = HttpSandboxHandle(endpoint="https://sandbox.example.com/code/", timeout_seconds=30)
    result = handle.execute({"action": "execute_skill"})

    assert result == {"result": {"x": 1}}  # 已解开云函数网关的 body 包裹
    assert calls[0]["url"] == "https://sandbox.example.com/code"  # 尾部 / 已归一
    assert calls[0]["json"] == {"action": "execute_skill"}
    assert calls[0]["timeout"] == 30


def test_http_handle_execute_timeout_override(monkeypatch):
    captured = {}

    def _fake_post(url, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return SimpleNamespace(status_code=200, text="ok", json=lambda: {"result": 1})

    monkeypatch.setattr("internal.core.agent.backends.factory.requests.post", _fake_post)

    HttpSandboxHandle(endpoint="https://sandbox.example.com", timeout_seconds=30).execute({}, timeout=7)

    assert captured["timeout"] == 7


def test_http_handle_execute_passthrough_when_response_is_not_dict(monkeypatch):
    monkeypatch.setattr(
        "internal.core.agent.backends.factory.requests.post",
        lambda *_a, **_k: SimpleNamespace(status_code=200, text="ok", json=lambda: [1, 2, 3]),
    )
    assert HttpSandboxHandle(endpoint="https://sandbox.example.com").execute({}) == [1, 2, 3]


def test_http_handle_execute_requires_endpoint():
    with pytest.raises(FailException, match="endpoint 为空"):
        HttpSandboxHandle(endpoint="").execute({})


def test_http_handle_execute_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "internal.core.agent.backends.factory.requests.post",
        lambda *_a, **_k: SimpleNamespace(
            status_code=500, text="boom", json=lambda: {"msg": "boom"}
        ),
    )
    with pytest.raises(FailException, match="云函数执行失败"):
        HttpSandboxHandle(endpoint="https://sandbox.example.com").execute({})


def test_http_handle_execute_falls_back_to_raw_text_on_non_json_error_body(monkeypatch):
    monkeypatch.setattr(
        "internal.core.agent.backends.factory.requests.post",
        lambda *_a, **_k: SimpleNamespace(
            status_code=502,
            text="gateway error",
            json=lambda: (_ for _ in ()).throw(ValueError("bad json")),
        ),
    )
    with pytest.raises(FailException, match="gateway error"):
        HttpSandboxHandle(endpoint="https://sandbox.example.com").execute({})


def test_http_handle_execute_raises_when_response_not_json(monkeypatch):
    monkeypatch.setattr(
        "internal.core.agent.backends.factory.requests.post",
        lambda *_a, **_k: SimpleNamespace(
            status_code=200,
            text="<html>oops</html>",
            json=lambda: (_ for _ in ()).throw(ValueError("not json")),
        ),
    )
    with pytest.raises(FailException, match="云函数返回非JSON内容"):
        HttpSandboxHandle(endpoint="https://sandbox.example.com").execute({})


@pytest.mark.parametrize(
    "error, message",
    [
        (requests.exceptions.Timeout(), "云函数执行超时"),
        (requests.exceptions.RequestException("net boom"), "网络请求失败"),
    ],
)
def test_http_handle_execute_maps_requests_errors(monkeypatch, error, message):
    monkeypatch.setattr(
        "internal.core.agent.backends.factory.requests.post",
        lambda *_a, **_k: (_ for _ in ()).throw(error),
    )
    with pytest.raises(FailException, match=message):
        HttpSandboxHandle(endpoint="https://sandbox.example.com").execute({})


def test_http_backend_consumers_do_not_bypass_the_handle():
    """锁定「HTTP 后端唯一传输入口」：消费方不得再各自 requests.post（否则又会分裂）。

    回归背景：`SkillScfClient` / `CodeNode` 曾各自 import requests 并发请求，
    导致 endpoint/超时/错误处理三处各写一份，且工厂产出的句柄无人消费。
    """
    import internal.core.skills.skill_executor as skill_executor_module
    import internal.core.workflow.nodes.code.code_node as code_node_module

    assert callable(getattr(HttpSandboxHandle, "execute", None))
    assert not hasattr(skill_executor_module, "requests"), "SkillScfClient 应经 HttpSandboxHandle 发请求"
    assert not hasattr(code_node_module, "requests"), "CodeNode 应经 HttpSandboxHandle 发请求"

