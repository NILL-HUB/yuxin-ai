"""SandboxConfigService 单测：能力域分组、单 active 互斥、白名单、env 兜底与显式可用性判定。

覆盖接线：`SandboxConfigService.resolve_runtime()`（沙箱配置的**唯一权威入口**）
→ `sandbox_config` 表 + env 兜底；`ensure_default_config()` 挂在 app.py 启动序列。

回归要点：**行为零变化** —— 无 DB 记录时按当前 env 推断，与升级前一致。
"""
import contextlib

import pytest

from internal.core.agent.backends.endpoint_utils import is_placeholder_endpoint
from internal.core.agent.entities.sandbox_runtime_entity import (
    BACKEND_BAIDU_CFC,
    BACKEND_DISABLED,
    BACKEND_E2B_CLOUD,
    BACKEND_HTTP_SANDBOX,
    CAPABILITY_CODE_INTERPRETER,
    CAPABILITY_SKILL_EXEC,
    CAPABILITY_WORKFLOW_CODE,
    SandboxRuntime,
)
from internal.exception import ValidateErrorException
from internal.model.sandbox_config import SandboxConfig
from internal.service.sandbox.sandbox_config_service import (
    _ALLOWED_CONFIG_KEYS,
    SandboxConfigService,
)


def _row(capability, backend, configs=None, is_active=False, credentials=None) -> SandboxConfig:
    return SandboxConfig(
        capability=capability,
        backend=backend,
        label=backend,
        configs=configs or {},
        credentials=credentials or {},
        is_active=is_active,
    )


# --------------------------------------------------------------------------- #
#  极简假 DB：支持 filter/order_by/first/all，并**真实按列过滤**
#  这样「同能力域单 active」这类语义才被测到（而不是被忽略）
# --------------------------------------------------------------------------- #
def _match(row, expr) -> bool:
    key = getattr(getattr(expr, "left", None), "key", None)
    if key is None:
        return True
    if key == "is_active":
        return bool(getattr(row, "is_active", False)) is True
    expected = getattr(getattr(expr, "right", None), "value", None)
    return str(getattr(row, key, None)) == str(expected)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []

    def filter(self, *exprs):
        self._filters.extend(exprs)
        return self

    def order_by(self, *_args):
        return self

    def _result(self):
        return [r for r in self._rows if all(_match(r, e) for e in self._filters)]

    def first(self):
        result = self._result()
        return result[0] if result else None

    def all(self):
        return self._result()


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def query(self, _model):
        return _FakeQuery(self.rows)

    def add(self, row):
        self.rows.append(row)


class _FakeDB:
    def __init__(self, rows=None):
        self.session = _FakeSession(list(rows or []))

    def auto_commit(self):
        return contextlib.nullcontext()


def _service(rows=None) -> SandboxConfigService:
    return SandboxConfigService(db=_FakeDB(rows))


def _set_e2b(monkeypatch, present: bool):
    if present:
        monkeypatch.setenv("E2B_API_KEY", "k")
        monkeypatch.setenv("E2B_DOMAIN", "sandbox.example.com")
    else:
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        monkeypatch.delenv("E2B_DOMAIN", raising=False)


# --------------------------------------------------------------------------- #
#  env 兜底（行为零变化）
# --------------------------------------------------------------------------- #
def test_env_fallback_maps_e2b_presence_to_baidu_cfc(monkeypatch):
    monkeypatch.delenv("SKILL_SCF_URL", raising=False)
    monkeypatch.delenv("SANDBOX_URL", raising=False)
    _set_e2b(monkeypatch, True)
    assert _service().get_active_backend(CAPABILITY_CODE_INTERPRETER) == BACKEND_BAIDU_CFC

    _set_e2b(monkeypatch, False)
    assert _service().get_active_backend(CAPABILITY_CODE_INTERPRETER) == BACKEND_DISABLED


def test_env_fallback_treats_placeholder_endpoint_as_disabled(monkeypatch):
    _set_e2b(monkeypatch, False)
    monkeypatch.setenv("SANDBOX_URL", "https://your-scf-url.tencentscf.com")
    monkeypatch.delenv("SKILL_SCF_URL", raising=False)
    assert _service().get_active_backend(CAPABILITY_SKILL_EXEC) == BACKEND_DISABLED
    assert _service().get_active_backend(CAPABILITY_WORKFLOW_CODE) == BACKEND_DISABLED


def test_env_fallback_uses_real_endpoint(monkeypatch):
    monkeypatch.setenv("SKILL_SCF_URL", "https://scf.real.example.org/skills")
    assert _service().get_active_backend(CAPABILITY_SKILL_EXEC) == BACKEND_HTTP_SANDBOX


# --------------------------------------------------------------------------- #
#  可用性判定：显式、带原因（禁止静默降级）
# --------------------------------------------------------------------------- #
def test_resolve_runtime_disabled_is_explicit_and_not_enabled():
    runtime = _service().resolve_runtime(CAPABILITY_CODE_INTERPRETER)
    assert isinstance(runtime, SandboxRuntime)
    assert runtime.backend == BACKEND_DISABLED
    assert runtime.enabled is False
    assert runtime.reason


def test_resolve_runtime_e2b_without_credentials_is_not_enabled(monkeypatch):
    _set_e2b(monkeypatch, False)
    row = _row(CAPABILITY_CODE_INTERPRETER, BACKEND_BAIDU_CFC, is_active=True)
    service = _service([row])
    runtime = service.resolve_runtime(CAPABILITY_CODE_INTERPRETER)
    assert runtime.backend == BACKEND_BAIDU_CFC
    assert runtime.enabled is False
    assert "E2B_API_KEY" in runtime.reason


def test_resolve_runtime_http_sandbox_with_real_endpoint_is_enabled(monkeypatch):
    row = _row(
        CAPABILITY_SKILL_EXEC,
        BACKEND_HTTP_SANDBOX,
        configs={"endpoint": "https://scf.real.example.org/skills"},
        is_active=True,
    )
    runtime = _service([row]).resolve_runtime(CAPABILITY_SKILL_EXEC)
    assert runtime.enabled is True
    assert runtime.reason == ""
    assert runtime.get("endpoint") == "https://scf.real.example.org/skills"


def test_resolve_runtime_http_sandbox_with_placeholder_is_not_enabled():
    row = _row(
        CAPABILITY_SKILL_EXEC,
        BACKEND_HTTP_SANDBOX,
        configs={"endpoint": "https://your-scf-url.tencentscf.com"},
        is_active=True,
    )
    runtime = _service([row]).resolve_runtime(CAPABILITY_SKILL_EXEC)
    assert runtime.enabled is False
    assert runtime.reason


def test_resolve_runtime_merges_defaults_with_stored_overrides(monkeypatch):
    _set_e2b(monkeypatch, True)
    row = _row(
        CAPABILITY_CODE_INTERPRETER,
        BACKEND_BAIDU_CFC,
        configs={"template_alias": "custom-lite"},
        is_active=True,
    )
    runtime = _service([row]).resolve_runtime(CAPABILITY_CODE_INTERPRETER)
    assert runtime.get("template_alias") == "custom-lite"
    # 默认值仍在（未被整块覆盖）
    assert runtime.get("fallback_template_alias") == "code-interpreter-v1"
    assert runtime.get_int("execute_timeout_seconds", 0) == 3600


# --------------------------------------------------------------------------- #
#  多后端热切换：同能力域单 active
# --------------------------------------------------------------------------- #
def test_set_active_backend_keeps_single_active_per_capability():
    a = _row(CAPABILITY_CODE_INTERPRETER, BACKEND_BAIDU_CFC, is_active=True)
    b = _row(CAPABILITY_CODE_INTERPRETER, BACKEND_E2B_CLOUD, is_active=False)
    service = _service([a, b])

    service.set_active_backend(CAPABILITY_CODE_INTERPRETER, BACKEND_E2B_CLOUD)

    assert a.is_active is False
    assert b.is_active is True
    assert service.get_active_backend(CAPABILITY_CODE_INTERPRETER) == BACKEND_E2B_CLOUD


def test_set_active_backend_does_not_affect_other_capabilities():
    interp = _row(CAPABILITY_CODE_INTERPRETER, BACKEND_BAIDU_CFC, is_active=True)
    skill = _row(CAPABILITY_SKILL_EXEC, BACKEND_HTTP_SANDBOX, is_active=True)
    service = _service([interp, skill])

    service.set_active_backend(CAPABILITY_CODE_INTERPRETER, BACKEND_DISABLED)

    assert skill.is_active is True
    assert service.get_active_backend(CAPABILITY_SKILL_EXEC) == BACKEND_HTTP_SANDBOX


# --------------------------------------------------------------------------- #
#  校验：能力域 × 后端白名单
# --------------------------------------------------------------------------- #
def test_unknown_capability_raises():
    with pytest.raises(ValidateErrorException):
        _service().resolve_runtime("not_a_capability")


def test_backend_not_allowed_for_capability_raises():
    with pytest.raises(ValidateErrorException):
        # 工作流代码节点不承载 E2B 协议后端
        _service().set_active_backend(CAPABILITY_WORKFLOW_CODE, BACKEND_BAIDU_CFC)


# --------------------------------------------------------------------------- #
#  写入白名单：密钥类不入库
# --------------------------------------------------------------------------- #
def test_upsert_config_drops_non_whitelisted_and_secret_keys():
    service = _service()
    config = service.upsert_config(
        CAPABILITY_CODE_INTERPRETER,
        BACKEND_BAIDU_CFC,
        {"template_alias": "t", "api_key": "SECRET", "E2B_API_KEY": "SECRET", "stray": 1},
    )
    assert config.configs == {"template_alias": "t"}
    assert "api_key" not in _ALLOWED_CONFIG_KEYS[BACKEND_BAIDU_CFC]
    assert "E2B_API_KEY" not in _ALLOWED_CONFIG_KEYS[BACKEND_BAIDU_CFC]


def test_allow_local_exec_is_whitelisted_but_not_a_secret():
    """S5：allow_local_exec 是合法配置键（默认关闭），可经 admin 显式开启。"""
    assert "allow_local_exec" in _ALLOWED_CONFIG_KEYS[BACKEND_HTTP_SANDBOX]
    service = _service()
    config = service.upsert_config(
        CAPABILITY_SKILL_EXEC,
        BACKEND_HTTP_SANDBOX,
        {"endpoint": "https://scf.real.example.org/skills", "allow_local_exec": True},
    )
    assert config.configs == {
        "endpoint": "https://scf.real.example.org/skills",
        "allow_local_exec": True,
    }


# --------------------------------------------------------------------------- #
#  凭证加密入库（2026-09-29：沙箱密钥收编 admin，DB 优先 → env 兜底）
# --------------------------------------------------------------------------- #
def _activate(service, capability=CAPABILITY_CODE_INTERPRETER, backend=BACKEND_BAIDU_CFC):
    service.set_active_backend(capability, backend)
    return service


def test_upsert_config_encrypts_credentials_and_never_stores_plaintext():
    service = _service()
    config = service.upsert_config(
        CAPABILITY_CODE_INTERPRETER,
        BACKEND_BAIDU_CFC,
        {"template_alias": "t"},
        {"E2B_API_KEY": "k-secret", "E2B_DOMAIN": "sandbox.example.com"},
    )
    stored = config.credentials
    assert stored["E2B_API_KEY"].startswith("gAAAAA")  # Fernet 密文
    assert "k-secret" not in str(stored)


def test_upsert_config_rejects_unknown_credential_key():
    service = _service()
    with pytest.raises(ValidateErrorException):
        service.upsert_config(
            CAPABILITY_CODE_INTERPRETER,
            BACKEND_BAIDU_CFC,
            {},
            {"NOT_ALLOWED_KEY": "x"},
        )


def test_resolve_runtime_uses_db_credentials_even_without_env(monkeypatch):
    _set_e2b(monkeypatch, False)  # env 无凭证
    service = _service()
    service.upsert_config(
        CAPABILITY_CODE_INTERPRETER,
        BACKEND_BAIDU_CFC,
        {"template_alias": "t"},
        {"E2B_API_KEY": "db-key", "E2B_DOMAIN": "db.example.com"},
    )
    _activate(service)
    runtime = service.resolve_runtime(CAPABILITY_CODE_INTERPRETER)
    assert runtime.enabled is True  # 后台配置即可用，无需 env
    assert runtime.credentials == {"E2B_API_KEY": "db-key", "E2B_DOMAIN": "db.example.com"}


def test_db_credentials_take_precedence_over_env(monkeypatch):
    _set_e2b(monkeypatch, True)  # env 也有值（不同值）
    service = _service()
    service.upsert_config(
        CAPABILITY_CODE_INTERPRETER,
        BACKEND_BAIDU_CFC,
        {},
        {"E2B_API_KEY": "db-key", "E2B_DOMAIN": "db.example.com"},
    )
    _activate(service)
    runtime = service.resolve_runtime(CAPABILITY_CODE_INTERPRETER)
    assert runtime.credentials["E2B_DOMAIN"] == "db.example.com"


def test_placeholder_env_credentials_are_treated_as_missing(monkeypatch):
    monkeypatch.setenv("E2B_API_KEY", "your-e2b-key-here")
    monkeypatch.setenv("E2B_DOMAIN", "your-domain-here")
    service = _service()
    _activate(service)
    runtime = service.resolve_runtime(CAPABILITY_CODE_INTERPRETER)
    assert runtime.enabled is False
    assert runtime.credentials == {}


def test_serialize_config_masks_credentials_and_declares_keys():
    service = _service()
    service.upsert_config(
        CAPABILITY_CODE_INTERPRETER,
        BACKEND_BAIDU_CFC,
        {},
        {"E2B_API_KEY": "k-secret-value-1234"},
    )
    row = service.get_config(CAPABILITY_CODE_INTERPRETER, BACKEND_BAIDU_CFC)
    view = service.serialize_config(row)
    assert "k-secret-value-1234" not in str(view)  # 绝不回明文
    assert view["credentials"]["E2B_API_KEY"].startswith("k-se")  # 掩码保留首尾
    assert "E2B_API_KEY" in view["credential_keys"]


def test_skill_exec_local_exec_defaults_off():
    row = _row(CAPABILITY_SKILL_EXEC, BACKEND_HTTP_SANDBOX, is_active=True)
    runtime = _service([row]).resolve_runtime(CAPABILITY_SKILL_EXEC)
    assert runtime.get_bool("allow_local_exec", True) is False


def test_resolve_runtime_clamps_code_interpreter_timeouts_to_floors(monkeypatch):
    """深思考沙箱超时应被抬升到历史下限（行为零变化）。"""
    _set_e2b(monkeypatch, True)
    row = _row(
        CAPABILITY_CODE_INTERPRETER,
        BACKEND_BAIDU_CFC,
        configs={"execute_timeout_seconds": 45, "sandbox_timeout_seconds": 123},
        is_active=True,
    )
    runtime = _service([row]).resolve_runtime(CAPABILITY_CODE_INTERPRETER)
    assert runtime.get_int("execute_timeout_seconds", 0) == 3600
    assert runtime.get_int("sandbox_timeout_seconds", 0) == 86400


def test_resolve_runtime_skill_exec_baidu_cfc_defaults():
    row = _row(CAPABILITY_SKILL_EXEC, BACKEND_BAIDU_CFC, is_active=True)
    runtime = _service([row]).resolve_runtime(CAPABILITY_SKILL_EXEC)
    assert runtime.backend == BACKEND_BAIDU_CFC
    assert runtime.get_int("execute_timeout_seconds", 0) == 60
    assert runtime.get_int("sandbox_timeout_seconds", 0) == 300


# --------------------------------------------------------------------------- #
#  ensure_default_config：幂等 + 依 env 推断
# --------------------------------------------------------------------------- #
def test_ensure_default_config_is_idempotent(monkeypatch):
    _set_e2b(monkeypatch, False)
    monkeypatch.delenv("SKILL_SCF_URL", raising=False)
    monkeypatch.setenv("SANDBOX_URL", "https://your-scf-url.tencentscf.com")
    service = _service()

    service.ensure_default_config()
    first_count = len(service.db.session.rows)
    service.ensure_default_config()

    assert len(service.db.session.rows) == first_count
    # 每个能力域恰有一个激活项
    for capability in (CAPABILITY_CODE_INTERPRETER, CAPABILITY_SKILL_EXEC, CAPABILITY_WORKFLOW_CODE):
        actives = [r for r in service.db.session.rows if r.capability == capability and r.is_active]
        assert len(actives) == 1


def test_ensure_default_config_activates_env_inferred_backend(monkeypatch):
    _set_e2b(monkeypatch, True)
    service = _service()
    service.ensure_default_config()
    assert service.get_active_backend(CAPABILITY_CODE_INTERPRETER) == BACKEND_BAIDU_CFC


# --------------------------------------------------------------------------- #
#  占位符判定：与历史实现逐字节一致（S4 收编的回归基线）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", True),
        ("   ", True),
        ("https://your-scf-url.tencentscf.com", True),
        ("http://EXAMPLE-here.local", True),
        ("https://placeholder-x.dev", True),
        ("https://scf.real.example.org/skills", False),
        ("http://10.0.0.8:9000", False),
    ],
)
def test_is_placeholder_endpoint(raw, expected):
    assert is_placeholder_endpoint(raw) is expected
