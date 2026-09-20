"""管理端 Agent 预算闸门（ADMIN-P4 Task 2，设计 §6.3）。

``admin_agent.budget_config`` 列已存在（ADMIN-P1a 建列），此前**零运行时读取**
（只存不读断链）。本模块提供唯一运行时闸门：

- ``budget_config`` schema：``{"daily_executions": int?, "monthly_executions": int?,
  "daily_tokens": int?, "monthly_tokens": int?}``，缺省 / 空字典 = 不限制；
- 计数存储：Redis 周期键 ``budget:{agent_id}:{metric}:{YYYYMMDD|YYYYMM}``；
- **Redis 不可用 → fail-open**（放行 + 记日志），不阻断既有行为；
- 超限抛 ``AdminAgentBudgetExceeded``（``ValueError`` 子类），由调用方按
  HTTP / SSE 语义转为 400 或 error 帧。

施加点（接线）：``AdminAgentExecutionService`` 的 invoke 路由入口、
``AdminAgentChatService.chat`` 对话入口、``GET /admin/agents/<id>/budget/usage``。
"""
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class AdminAgentBudgetExceeded(ValueError):
    """预算闸门拒绝：当前周期额度已耗尽。"""


class AdminAgentBudgetGate:
    """按 ``admin_agent.budget_config`` 施加周期执行 / token 限额。"""

    # (limit_key, metric, period, 每次的消耗量)
    _CHECKS = (
        ("daily_executions", "executions", "daily", 1),
        ("monthly_executions", "executions", "monthly", 1),
        ("daily_tokens", "tokens", "daily", None),  # delta 由 tokens 参数决定
        ("monthly_tokens", "tokens", "monthly", None),
    )

    def __init__(self, redis_client=None):
        """``redis_client`` 显式注入优先；None 时回退到 Flask 应用扩展。"""
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------

    def _redis_client(self):
        if self._redis is not None:
            return self._redis
        try:
            from internal.context import current_app

            return current_app.extensions.get("redis")
        except Exception:
            logger.warning("预算闸门: 获取 Redis 失败，fail-open", exc_info=True)
            return None

    @staticmethod
    def _period_key(period: str) -> str:
        now = datetime.now(UTC)
        return now.strftime("%Y%m%d") if period == "daily" else now.strftime("%Y%m")

    def _key(self, agent_id, metric: str, period: str) -> str:
        return f"budget:{agent_id}:{metric}:{period}:{self._period_key(period)}"

    @staticmethod
    def _limits(budget_config) -> dict:
        cfg = budget_config or {}
        out = {}
        for limit_key in ("daily_executions", "monthly_executions", "daily_tokens", "monthly_tokens"):
            raw = cfg.get(limit_key)
            try:
                value = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                value = None
            out[limit_key] = value if value is not None and value > 0 else None
        return out

    # ------------------------------------------------------------------
    # 闸门主逻辑
    # ------------------------------------------------------------------

    def assert_allowed(self, agent_id, budget_config, *, tokens: int = 0) -> None:
        """超限抛 ``AdminAgentBudgetExceeded``；Redis 不可用 fail-open。"""
        limits = self._limits(budget_config)
        if not any(limits.values()):
            return
        try:
            redis = self._redis_client()
        except Exception:
            logger.warning("预算闸门: 获取 Redis 异常，fail-open agent=%s", agent_id, exc_info=True)
            return
        if redis is None:
            logger.warning("预算闸门: Redis 不可用，fail-open agent=%s", agent_id)
            return
        for limit_key, metric, period, fixed_delta in self._CHECKS:
            limit = limits.get(limit_key)
            if not limit:
                continue
            delta = tokens if fixed_delta is None else fixed_delta
            key = self._key(agent_id, metric, period)
            try:
                used = int(redis.get(key) or 0)
            except Exception:
                logger.warning("预算闸门: 读取计数失败，按 0 处理 key=%s", key, exc_info=True)
                used = 0
            if used + delta > limit:
                raise AdminAgentBudgetExceeded(
                    f"预算闸门: {limit_key} 周期额度已用完（{used}/{limit}）"
                )

    def record_usage(self, agent_id, budget_config, *, tokens: int = 0) -> None:
        """累计执行次数与 token 消耗（不校验）。Redis 不可用 / 异常吞掉。"""
        try:
            redis = self._redis_client()
            if redis is None:
                return
            pipe = redis.pipeline()
            pipe.incr(self._key(agent_id, "executions", "daily"), 1)
            pipe.incr(self._key(agent_id, "executions", "monthly"), 1)
            if tokens and tokens > 0:
                pipe.incr(self._key(agent_id, "tokens", "daily"), int(tokens))
                pipe.incr(self._key(agent_id, "tokens", "monthly"), int(tokens))
            pipe.execute()
        except Exception:
            logger.warning("预算闸门: 用量累计失败 agent=%s", agent_id, exc_info=True)

    def check_and_record(self, agent_id, budget_config, *, tokens: int = 0) -> None:
        """闸门单入口：先校验（超限抛错），再累计。"""
        self.assert_allowed(agent_id, budget_config, tokens=tokens)
        self.record_usage(agent_id, budget_config, tokens=tokens)

    # ------------------------------------------------------------------
    # 用量查询（admin 端展示）
    # ------------------------------------------------------------------

    def usage(self, agent_id, budget_config) -> dict:
        """返回当前周期各度量用量：``{"daily_executions": N, ...}``。"""
        redis = self._redis_client()
        out = {}
        if redis is None:
            for metric in ("executions", "tokens"):
                for period in ("daily", "monthly"):
                    out[f"{period}_{metric}"] = 0
            return out
        for metric in ("executions", "tokens"):
            for period in ("daily", "monthly"):
                key = self._key(agent_id, metric, period)
                try:
                    out[f"{period}_{metric}"] = int(redis.get(key) or 0)
                except Exception:
                    out[f"{period}_{metric}"] = 0
        return out
