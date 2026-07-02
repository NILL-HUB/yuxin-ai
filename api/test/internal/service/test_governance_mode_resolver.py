from types import SimpleNamespace

from internal.entity.orchestration_feature_flag_entity import (
    POOL_GOVERNANCE_FLAG_BLOCK_ALL,
    POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE,
    POOL_GOVERNANCE_FLAG_OBSERVE_ONLY,
    POOL_GOVERNANCE_MODE_BLOCK_ALL,
    POOL_GOVERNANCE_MODE_BLOCK_SENSITIVE,
    POOL_GOVERNANCE_MODE_OBSERVE_ONLY,
)
from internal.service.governance_mode_resolver import GovernanceModeResolver


# ------------------------------------------------------------------ #
#  Stub                                                               #
# ------------------------------------------------------------------ #

class _QueryStub:
    """支持 filter(...).all() 链式调用的查询桩。"""

    def __init__(self, all_result=None):
        self._all_result = all_result or []

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._all_result


class _SessionStub:
    """按调用顺序依次返回预设查询结果的会话桩。"""

    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


class _SessionRaisesStub:
    """query() 直接抛异常的会话桩，用于验证降级路径。"""

    def query(self, *_args, **_kwargs):
        raise RuntimeError("table missing")


class _DbStub:
    def __init__(self, session):
        self.session = session


def _flag(code, enabled):
    return SimpleNamespace(code=code, enabled=enabled)


def _resolver(queries=None):
    session = _SessionStub(queries)
    return GovernanceModeResolver(db=_DbStub(session))


# ------------------------------------------------------------------ #
#  resolve_mode 测试                                                  #
# ------------------------------------------------------------------ #

def test_resolve_mode_stage1_observe_only_when_all_disabled():
    # 所有阶段开关都未启用 → 阶段1（observe_only=True）
    resolver = _resolver([
        _QueryStub(all_result=[
            _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, True),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, False),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, False),
        ]),
    ])

    mode = resolver.resolve_mode()

    assert mode["mode"] == POOL_GOVERNANCE_MODE_OBSERVE_ONLY
    assert mode["observe_only"] is True
    assert mode["block_sensitive"] is False
    assert mode["block_all"] is False


def test_resolve_mode_stage1_default_when_no_rows():
    # 表存在但无记录 → 降级阶段1（observe_only 默认 True）
    resolver = _resolver([_QueryStub(all_result=[])])

    mode = resolver.resolve_mode()

    assert mode["mode"] == POOL_GOVERNANCE_MODE_OBSERVE_ONLY
    assert mode["observe_only"] is True
    assert mode["block_sensitive"] is False
    assert mode["block_all"] is False


def test_resolve_mode_stage2_block_sensitive():
    resolver = _resolver([
        _QueryStub(all_result=[
            _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, True),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, True),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, False),
        ]),
    ])

    mode = resolver.resolve_mode()

    assert mode["mode"] == POOL_GOVERNANCE_MODE_BLOCK_SENSITIVE
    assert mode["observe_only"] is False
    assert mode["block_sensitive"] is True
    assert mode["block_all"] is False


def test_resolve_mode_stage3_block_all_overrides_block_sensitive():
    # block_all + block_sensitive 同时启用 → block_all 优先（阶段3）
    resolver = _resolver([
        _QueryStub(all_result=[
            _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, True),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, True),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, True),
        ]),
    ])

    mode = resolver.resolve_mode()

    assert mode["mode"] == POOL_GOVERNANCE_MODE_BLOCK_ALL
    assert mode["observe_only"] is False
    assert mode["block_sensitive"] is False
    assert mode["block_all"] is True


def test_resolve_mode_stage3_block_all_alone():
    resolver = _resolver([
        _QueryStub(all_result=[
            _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, False),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, False),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, True),
        ]),
    ])

    mode = resolver.resolve_mode()

    assert mode["mode"] == POOL_GOVERNANCE_MODE_BLOCK_ALL
    assert mode["observe_only"] is False
    assert mode["block_sensitive"] is False
    assert mode["block_all"] is True


def test_resolve_mode_degrades_to_stage1_on_db_error():
    # 查询异常时降级为阶段1（安全默认）
    resolver = GovernanceModeResolver(db=_DbStub(_SessionRaisesStub()))

    mode = resolver.resolve_mode()

    assert mode["mode"] == POOL_GOVERNANCE_MODE_OBSERVE_ONLY
    assert mode["observe_only"] is True
    assert mode["block_sensitive"] is False
    assert mode["block_all"] is False


# ------------------------------------------------------------------ #
#  build_governance_context 测试                                      #
# ------------------------------------------------------------------ #

def test_build_governance_context_stage1_defaults():
    resolver = _resolver([
        _QueryStub(all_result=[
            _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, True),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, False),
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, False),
        ]),
    ])

    ctx = resolver.build_governance_context()

    assert ctx["observe_only"] is True
    assert ctx["block_sensitive_only"] is False
    assert ctx["mode"] == POOL_GOVERNANCE_MODE_OBSERVE_ONLY


def test_build_governance_context_stage2_passes_block_sensitive_only():
    resolver = _resolver([
        _QueryStub(all_result=[
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_SENSITIVE, True),
        ]),
    ])

    ctx = resolver.build_governance_context()

    assert ctx["observe_only"] is False
    assert ctx["block_sensitive_only"] is True
    assert ctx["mode"] == POOL_GOVERNANCE_MODE_BLOCK_SENSITIVE


def test_build_governance_context_stage3_no_block_sensitive_only():
    resolver = _resolver([
        _QueryStub(all_result=[
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, True),
        ]),
    ])

    ctx = resolver.build_governance_context()

    assert ctx["observe_only"] is False
    assert ctx["block_sensitive_only"] is False
    assert ctx["mode"] == POOL_GOVERNANCE_MODE_BLOCK_ALL


def test_build_governance_context_overrides_transparent_pass_through():
    resolver = _resolver([
        _QueryStub(all_result=[
            _flag(POOL_GOVERNANCE_FLAG_OBSERVE_ONLY, True),
        ]),
    ])

    ctx = resolver.build_governance_context(
        app_id="app-123",
        account_id="account-1",
        agent_pool="primary",
        budget_level="high",
    )

    # 默认字段保留
    assert ctx["observe_only"] is True
    assert ctx["mode"] == POOL_GOVERNANCE_MODE_OBSERVE_ONLY
    # overrides 透传
    assert ctx["app_id"] == "app-123"
    assert ctx["account_id"] == "account-1"
    assert ctx["agent_pool"] == "primary"
    assert ctx["budget_level"] == "high"


def test_build_governance_context_overrides_take_priority_over_defaults():
    # 调用方显式提供 observe_only 时应覆盖默认解析值
    resolver = _resolver([
        _QueryStub(all_result=[
            _flag(POOL_GOVERNANCE_FLAG_BLOCK_ALL, True),
        ]),
    ])

    ctx = resolver.build_governance_context(observe_only=True, block_sensitive_only=False)

    # 调用方意图优先：解析器返回 block_all（observe_only=False），但调用方覆盖为 True
    assert ctx["observe_only"] is True
    assert ctx["block_sensitive_only"] is False
    # mode 仍为解析结果（调用方未覆盖 mode）
    assert ctx["mode"] == POOL_GOVERNANCE_MODE_BLOCK_ALL
