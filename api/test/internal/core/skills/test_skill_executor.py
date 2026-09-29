from __future__ import annotations

import logging
import json as json_module
import os
from contextlib import contextmanager

import pytest

from internal.core.skills.skill_executor import SkillSandboxExecutor, SkillScfClient
from internal.exception import FailException


@contextmanager
def _skill_exec_runtime(enabled=True, backend=None, configs=None):
    """注册一个确定性的 skill_exec 运行时（替代真实 service/DB）。"""
    from internal.core.agent import sandbox_runtime_registry as registry
    from internal.core.agent.entities.sandbox_runtime_entity import (
        BACKEND_DISABLED,
        BACKEND_HTTP_SANDBOX,
        CAPABILITY_SKILL_EXEC,
        SandboxRuntime,
    )

    resolved_backend = backend or (BACKEND_HTTP_SANDBOX if enabled else BACKEND_DISABLED)
    resolved_configs = dict(configs or {})

    def _loader(capability):
        if capability != CAPABILITY_SKILL_EXEC:
            return SandboxRuntime(capability=capability, enabled=False)
        return SandboxRuntime(
            capability=capability,
            backend=resolved_backend,
            configs=dict(resolved_configs),
            enabled=enabled,
        )

    registry.register_sandbox_runtime_loader(_loader)
    registry.invalidate_sandbox_runtime_cache()
    try:
        yield registry
    finally:
        registry._loader = None
        registry.invalidate_sandbox_runtime_cache()


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200
        self.text = "ok"

    def json(self):
        return self._payload


def test_skill_scf_client_should_post_sync_and_execute_payloads(monkeypatch, caplog):
    calls = []

    def _fake_post(url, json=None, timeout=None, **_kwargs):
        calls.append(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
            }
        )
        return _FakeResponse({"statusCode": 200, "body": json_module.dumps({"result": {"status": "ok"}})})

    # HTTP 传输已统一到 HttpSandboxHandle（core/agent/backends/factory.py）
    monkeypatch.setattr("internal.core.agent.backends.factory.requests.post", _fake_post)

    client = SkillScfClient(endpoint="https://scf.example.com/skills", timeout_seconds=12)

    with caplog.at_level(logging.INFO):
        sync_result = client.sync_package({"skill": {"source_key": "code_workbench"}, "version": {"version": 1}})
        exec_result = client.execute_skill(
            {
                "skill_id": "skill-1",
                "source_key": "code_workbench",
                "tool_name": "analyze_request",
                "entrypoint": "analyze_request",
                "input": {"request": "hello"},
                "bundle": {
                    "skill.py": "def analyze_request(params):\n    return {'echo': params.get('request')}\n",
                },
            }
        )

    assert sync_result == {"status": "ok"}
    assert exec_result == {"status": "ok"}
    assert calls[0]["url"] == "https://scf.example.com/skills"
    assert calls[0]["timeout"] == 12
    assert calls[0]["json"]["action"] == "sync_package"
    assert calls[0]["json"]["func_name"] == "sync_package"
    assert calls[0]["json"]["args"][0]["source_key"] == "code_workbench"
    assert "def sync_package" in calls[0]["json"]["code"]
    assert calls[1]["json"]["action"] == "execute_skill"
    assert calls[1]["json"]["skill_id"] == "skill-1"
    assert calls[1]["json"]["func_name"] == "analyze_request"
    assert calls[1]["json"]["args"] == [{"request": "hello"}]
    assert calls[1]["json"]["kwargs"] == {}
    assert "def analyze_request" in calls[1]["json"]["code"]
    assert caplog.text.count("技能工具 SCF success") == 2


def test_skill_sandbox_executor_should_refuse_local_when_unconfigured(monkeypatch):
    """S5：本地裸跑默认关闭，未启用技能沙箱时直接拒绝（不再静默本地执行）。"""
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("E2B_DOMAIN", raising=False)

    executor = SkillSandboxExecutor()
    with _skill_exec_runtime(enabled=False):
        with pytest.raises(FailException, match="技能沙箱不可用"):
            executor.execute_skill(
                {
                    "bundle": {
                        "skill.py": (
                            "from __future__ import annotations\n\n"
                            "def run(params):\n"
                            "    return {'echo': params.get('value')}\n"
                        )
                    },
                    "entrypoint": "run",
                    "input": {"value": "hello"},
                }
            )


def test_skill_sandbox_executor_should_execute_locally_when_explicitly_allowed(
    monkeypatch, caplog
):
    """S5：仅当显式开启 allow_local_exec 时才回退本地执行（在受限子进程中）。"""
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("E2B_DOMAIN", raising=False)

    executor = SkillSandboxExecutor()
    with _skill_exec_runtime(enabled=False, configs={"allow_local_exec": True}):
        with caplog.at_level(logging.INFO):
            result = executor.execute_skill(
                {
                    "bundle": {
                        "skill.py": (
                            "from __future__ import annotations\n\n"
                            "def run(params):\n"
                            "    return {'echo': params.get('value')}\n"
                        )
                    },
                    "entrypoint": "run",
                    "input": {"value": "hello"},
                }
            )

    assert result == {"echo": "hello"}
    assert "技能工具 sandbox local-subprocess success" in caplog.text


def test_skill_sandbox_executor_local_run_does_not_pollute_parent_env(monkeypatch):
    """S5：技能包 env 只注入子进程，父进程 os.environ 不被写入。"""
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("E2B_DOMAIN", raising=False)
    # 技能包 env 解密替身：返回一个只应存在于子进程的变量
    monkeypatch.setattr(
        "internal.core.skills.skill_executor._decrypt_bundle_env",
        lambda _bundle: {"SKILL_TOKEN": "injected-token"},
    )

    executor = SkillSandboxExecutor()
    with _skill_exec_runtime(enabled=False, configs={"allow_local_exec": True}):
        result = executor.execute_skill(
            {
                "bundle": {
                    "skill.py": (
                        "from __future__ import annotations\n\n"
                        "import os\n\n"
                        "def run(params):\n"
                        "    return {'token': os.environ.get('SKILL_TOKEN')}\n"
                    )
                },
                "entrypoint": "run",
                "input": {},
            }
        )

    # 子进程可见技能包注入的 env
    assert result == {"token": "injected-token"}
    # 父进程（API 进程）未被写入该密钥
    assert "SKILL_TOKEN" not in os.environ


def test_skill_sandbox_executor_local_run_does_not_inherit_parent_secrets(monkeypatch):
    """S5：子进程不继承父进程完整 env，API 密钥不会泄漏给第三方技能代码。"""
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("E2B_DOMAIN", raising=False)
    monkeypatch.setenv("API_SENTINEL_SECRET", "should-not-leak")

    executor = SkillSandboxExecutor()
    with _skill_exec_runtime(enabled=False, configs={"allow_local_exec": True}):
        result = executor.execute_skill(
            {
                "bundle": {
                    "skill.py": (
                        "from __future__ import annotations\n\n"
                        "import os\n\n"
                        "def run(params):\n"
                        "    return {'leaked': os.environ.get('API_SENTINEL_SECRET')}\n"
                    )
                },
                "entrypoint": "run",
                "input": {},
            }
        )

    assert result == {"leaked": None}
    # 父进程原本的 env 保持不变
    assert os.environ["API_SENTINEL_SECRET"] == "should-not-leak"


def test_skill_sandbox_executor_local_run_times_out_and_kills_child(monkeypatch):
    """S5：本地执行超时即终止子进程组，并抛出明确错误（不挂起）。"""
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("E2B_DOMAIN", raising=False)

    executor = SkillSandboxExecutor(timeout_seconds=1)
    with _skill_exec_runtime(enabled=False, configs={"allow_local_exec": True}):
        with pytest.raises(FailException, match="超时"):
            executor.execute_skill(
                {
                    "bundle": {
                        "skill.py": (
                            "from __future__ import annotations\n\n"
                            "import time\n\n"
                            "def run(params):\n"
                            "    time.sleep(30)\n"
                            "    return {'ok': True}\n"
                        )
                    },
                    "entrypoint": "run",
                    "input": {},
                }
            )


def test_skill_sandbox_executor_local_run_applies_resource_limits(monkeypatch):
    """S5：子进程内确实设置了资源上限（防 setrlimit 静默失效）。"""
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("E2B_DOMAIN", raising=False)

    executor = SkillSandboxExecutor()
    with _skill_exec_runtime(enabled=False, configs={"allow_local_exec": True}):
        result = executor.execute_skill(
            {
                "bundle": {
                    "skill.py": (
                        "from __future__ import annotations\n\n"
                        "import resource\n\n"
                        "def run(params):\n"
                        "    soft_nofile, _ = resource.getrlimit(resource.RLIMIT_NOFILE)\n"
                        "    soft_fsize, _ = resource.getrlimit(resource.RLIMIT_FSIZE)\n"
                        "    return {'nofile': soft_nofile, 'fsize': soft_fsize}\n"
                    )
                },
                "entrypoint": "run",
                "input": {},
            }
        )

    from internal.core.skills.skill_executor import (
        _LOCAL_EXEC_FILE_SIZE_BYTES,
        _LOCAL_EXEC_MAX_OPEN_FILES,
    )

    assert result["nofile"] == _LOCAL_EXEC_MAX_OPEN_FILES
    assert result["fsize"] == _LOCAL_EXEC_FILE_SIZE_BYTES


def test_skill_sandbox_executor_should_log_remote_success(monkeypatch, caplog):
    monkeypatch.setenv("E2B_API_KEY", "test-key")
    monkeypatch.setenv("E2B_DOMAIN", "test-domain")

    class _FakeUploadResponse:
        def __init__(self, path: str, error: str | None = None):
            self.path = path
            self.error = error

    class _FakeExecuteResponse:
        def __init__(self, output: str):
            self.output = output

    class _FakeBackend:
        def __init__(self, *_, **__):
            self.id = "sandbox-test-1"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, command: str, *, timeout=None):
            if "_skill_runner.py" in command:
                return _FakeExecuteResponse(
                    "__SKILL_RESULT__"
                    + json_module.dumps(
                        {
                            "ok": True,
                            "result": {"echo": "hello"},
                            "stdout": "",
                            "stderr": "",
                        }
                    )
                )
            return _FakeExecuteResponse("")

        def upload_files(self, files):
            return [_FakeUploadResponse(path) for path, _content in files]

    monkeypatch.setattr(
        "internal.core.skills.skill_executor.build_sandbox_backend",
        lambda _runtime: _FakeBackend(),
    )

    from internal.core.agent.entities.sandbox_runtime_entity import BACKEND_BAIDU_CFC

    executor = SkillSandboxExecutor()
    with _skill_exec_runtime(backend=BACKEND_BAIDU_CFC):
        with caplog.at_level(logging.INFO):
            result = executor.execute_skill(
                {
                    "bundle": {
                        "skill.py": (
                            "from __future__ import annotations\n\n"
                            "def run(params):\n"
                            "    return {'echo': params.get('value')}\n"
                        )
                    },
                    "entrypoint": "run",
                    "input": {"value": "hello"},
                }
            )

    assert result == {"echo": "hello"}
    assert "技能工具 sandbox remote success" in caplog.text


class _RecordingExecutor:
    """记录调用的执行器替身（用于验证 SkillExecutor 的分发）。"""

    def __init__(self, *, result=None, error=None):
        self.calls = []
        self._result = result
        self._error = error

    def execute_skill(self, payload):
        self.calls.append(payload)
        if self._error is not None:
            raise self._error
        return self._result


def test_skill_executor_should_dispatch_by_active_backend():
    """单一入口：http_sandbox → SkillScfClient；baidu_cfc → SkillSandboxExecutor。"""
    from internal.core.agent.entities.sandbox_runtime_entity import (
        BACKEND_BAIDU_CFC,
        BACKEND_HTTP_SANDBOX,
    )
    from internal.core.skills.skill_executor import SkillExecutor

    scf = _RecordingExecutor(result={"via": "scf"})
    sandbox = _RecordingExecutor(result={"via": "sandbox"})
    executor = SkillExecutor(scf_client=scf, sandbox_executor=sandbox)

    with _skill_exec_runtime(backend=BACKEND_HTTP_SANDBOX):
        assert executor.execute_skill({"k": 1}) == {"via": "scf"}
    assert scf.calls and not sandbox.calls

    scf.calls.clear()
    with _skill_exec_runtime(backend=BACKEND_BAIDU_CFC):
        assert executor.execute_skill({"k": 2}) == {"via": "sandbox"}
    assert sandbox.calls and not scf.calls


def test_skill_executor_should_delegate_disabled_to_sandbox_executor():
    """disabled 交由沙箱执行器统一走「未开通 / allow_local_exec」分支，如实报错。"""
    from internal.core.skills.skill_executor import SkillExecutor

    scf = _RecordingExecutor(result={"via": "scf"})
    sandbox = _RecordingExecutor(error=FailException("技能沙箱不可用"))
    executor = SkillExecutor(scf_client=scf, sandbox_executor=sandbox)

    with _skill_exec_runtime(enabled=False):
        with pytest.raises(FailException, match="技能沙箱不可用"):
            executor.execute_skill({})

    assert sandbox.calls and not scf.calls


def test_skill_executor_e2b_mode_should_not_probe_scf_first(caplog):
    """回归：E2B 模式不再「先试 SCF 再兜」，故不再每次刷伪警告、也不再调用 SCF。"""
    from internal.core.agent.entities.sandbox_runtime_entity import BACKEND_BAIDU_CFC
    from internal.core.skills.skill_executor import SkillExecutor

    scf = _RecordingExecutor(result={"via": "scf"})
    sandbox = _RecordingExecutor(result={"via": "sandbox"})
    executor = SkillExecutor(scf_client=scf, sandbox_executor=sandbox)

    with caplog.at_level(logging.WARNING):
        with _skill_exec_runtime(backend=BACKEND_BAIDU_CFC):
            assert executor.execute_skill({}) == {"via": "sandbox"}

    assert not scf.calls
    assert "尝试沙箱回退" not in caplog.text

