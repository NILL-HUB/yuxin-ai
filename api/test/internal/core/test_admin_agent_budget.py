"""管理端 Agent 预算闸门测试（ADMIN-P4 Task 2）。

被测对象：``AdminAgentBudgetGate``——读取 ``admin_agent.budget_config`` 的运行时闸门。
- 未配置 budget_config → 恒放行；
- daily/monthly 执行次数 / token 额度超限 → ``AdminAgentBudgetExceeded``；
- Redis 不可用 → fail-open（放行 + 记日志），不阻断既有行为；
- ``record_usage`` 只累计不校验；``usage`` 返回当前周期用量。
"""
import pytest

from internal.core.admin_agent_budget import (
    AdminAgentBudgetExceeded,
    AdminAgentBudgetGate,
)


class _FakeRedis:
    def __init__(self):
        self._data = {}

    def get(self, key):
        value = self._data.get(key)
        return str(value) if value is not None else None

    def incr(self, key, amount=1):
        self._data[key] = self._data.get(key, 0) + amount
        return self._data[key]

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._cmds = []

    def incr(self, key, amount=1):
        self._cmds.append((key, amount))
        return self

    def execute(self):
        for key, amount in self._cmds:
            self._redis.incr(key, amount)


AGENT_ID = "11111111-1111-1111-1111-111111111111"


class TestNoBudgetConfig:
    def test_empty_config_always_allowed(self):
        gate = AdminAgentBudgetGate(redis_client=_FakeRedis())
        gate.check_and_record(AGENT_ID, {})
        gate.check_and_record(AGENT_ID, None)  # NULL budget_config 同样放行
        gate.check_and_record(AGENT_ID, {"daily_executions": None})

    def test_usage_zero_when_never_recorded(self):
        gate = AdminAgentBudgetGate(redis_client=_FakeRedis())
        usage = gate.usage(AGENT_ID, {})
        assert usage["daily_executions"] == 0
        assert usage["monthly_tokens"] == 0


class TestExecutionLimits:
    def test_daily_executions_limit_enforced(self):
        fake = _FakeRedis()
        gate = AdminAgentBudgetGate(redis_client=fake)
        cfg = {"daily_executions": 2}
        gate.check_and_record(AGENT_ID, cfg)
        gate.check_and_record(AGENT_ID, cfg)
        with pytest.raises(AdminAgentBudgetExceeded):
            gate.check_and_record(AGENT_ID, cfg)

    def test_monthly_executions_limit_enforced(self):
        fake = _FakeRedis()
        gate = AdminAgentBudgetGate(redis_client=fake)
        cfg = {"monthly_executions": 1}
        gate.check_and_record(AGENT_ID, cfg)
        with pytest.raises(AdminAgentBudgetExceeded):
            gate.check_and_record(AGENT_ID, cfg)

    def test_tokens_limit_enforced(self):
        fake = _FakeRedis()
        gate = AdminAgentBudgetGate(redis_client=fake)
        cfg = {"monthly_tokens": 100, "daily_tokens": 50}
        gate.check_and_record(AGENT_ID, cfg, tokens=30)
        gate.check_and_record(AGENT_ID, cfg, tokens=20)  # daily 50 满
        with pytest.raises(AdminAgentBudgetExceeded):
            gate.check_and_record(AGENT_ID, cfg, tokens=1)


class TestFailOpen:
    def test_redis_unavailable_allows(self, monkeypatch):
        gate = AdminAgentBudgetGate(redis_client=None)

        def _no_redis():
            return None

        monkeypatch.setattr(gate, "_redis_client", _no_redis)
        gate.check_and_record(AGENT_ID, {"daily_executions": 1})
        gate.check_and_record(AGENT_ID, {"daily_executions": 1})  # 超限也不拒绝

    def test_record_usage_redis_error_swallowed(self, monkeypatch):
        gate = AdminAgentBudgetGate(redis_client=None)

        def _boom():
            raise RuntimeError("redis down")

        monkeypatch.setattr(gate, "_redis_client", _boom)
        gate.check_and_record(AGENT_ID, {"daily_executions": 1})  # 不抛


class TestUsage:
    def test_record_and_read_back(self):
        fake = _FakeRedis()
        gate = AdminAgentBudgetGate(redis_client=fake)
        gate.check_and_record(AGENT_ID, {"daily_executions": 5, "monthly_tokens": 1000}, tokens=100)
        usage = gate.usage(AGENT_ID, {})
        assert usage["daily_executions"] == 1
        assert usage["monthly_executions"] == 1
        assert usage["daily_tokens"] == 100
        assert usage["monthly_tokens"] == 100
