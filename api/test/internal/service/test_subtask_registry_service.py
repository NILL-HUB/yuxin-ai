import time

from internal.entity.cancel_token_entity import CancelToken
from internal.entity.execution_orchestration_entity import TaskPlanItem
from internal.service.subtask_registry_service import SubtaskRegistryService


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def delete(self, *keys):
        self.ops.append(("delete", keys))
        return self

    def setex(self, key, ttl, value):
        self.ops.append(("setex", key, ttl, value))
        return self

    def execute(self):
        for op in self.ops:
            if op[0] == "delete":
                for key in op[1]:
                    self.redis.data.pop(key, None)
            elif op[0] == "setex":
                self.redis.setex(op[1], op[2], op[3])
        self.ops = []


class _FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def setex(self, key, ttl, value):
        self.data[key] = value

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)

    def mget(self, keys):
        return [self.data.get(key) for key in keys]

    def scan_iter(self, match="", count=100):
        return iter([key for key in self.data if key.startswith(match.rstrip("*"))])

    def pipeline(self):
        return _FakePipeline(self)


class _BrokenRedis(_FakeRedis):
    def setex(self, key, ttl, value):
        raise RuntimeError("redis down")


def _items():
    return [
        TaskPlanItem(
            task_id="t1",
            title="任务一",
            agent_pool="general",
            execution_order=0,
        ),
        TaskPlanItem(
            task_id="t2",
            title="任务二",
            agent_pool="coding",
            depends_on=["t1"],
            execution_order=1,
        ),
    ]


class TestSubtaskRegistryService:
    def test_register_plan_snapshot_pending(self):
        registry = SubtaskRegistryService()

        registry.register_plan(
            request_id="req-1",
            execution_mode="multi_agent_parallel",
            original_query="测试任务",
            items=_items(),
        )

        snapshot = registry.snapshot("req-1")
        assert snapshot is not None
        assert snapshot["request_id"] == "req-1"
        assert snapshot["execution_mode"] == "multi_agent_parallel"
        assert snapshot["original_query"] == "测试任务"
        assert snapshot["task_count"] == 2
        by_id = {item["task_id"]: item for item in snapshot["items"]}
        assert by_id["t1"]["status"] == "pending"
        assert by_id["t2"]["depends_on"] == ["t1"]

    def test_mark_running_and_completed(self):
        registry = SubtaskRegistryService()
        registry.register_plan(
            request_id="req-2",
            execution_mode="single_agent",
            original_query="q",
            items=_items(),
        )

        registry.mark_running("req-2", "t1")
        running = registry.snapshot("req-2")
        assert running["items"][0]["status"] == "running"
        assert running["items"][0]["started_at"] > 0

        registry.mark_completed("req-2", "t1", answer_preview="完成", errors=None)
        completed = registry.snapshot("req-2")
        assert completed["items"][0]["status"] == "completed"
        assert completed["items"][0]["answer_preview"] == "完成"
        assert completed["items"][0]["finished_at"] > 0

    def test_mark_completed_with_errors_marks_failed(self):
        registry = SubtaskRegistryService()
        registry.register_plan(
            request_id="req-3",
            execution_mode="multi_agent_sequential",
            original_query="q",
            items=_items(),
        )

        registry.mark_completed("req-3", "t1", errors=["agent_execution_failed"])

        snapshot = registry.snapshot("req-3")
        assert snapshot["items"][0]["status"] == "failed"
        assert snapshot["items"][0]["errors"] == ["agent_execution_failed"]

    def test_snapshot_unknown_returns_none(self):
        registry = SubtaskRegistryService()

        assert registry.snapshot("missing") is None

    def test_ttl_cleanup_drops_stale_run(self):
        registry = SubtaskRegistryService(_force_memory=True)
        registry.register_plan(
            request_id="req-4",
            execution_mode="single_agent",
            original_query="q",
            items=_items(),
        )

        registry._TTL_SECONDS = -1

        assert registry.snapshot("req-4") is None

    def test_redis_register_snapshot_and_mutations(self):
        redis = _FakeRedis()
        registry = SubtaskRegistryService(redis_client=redis)

        registry.register_plan(
            request_id="req-r1",
            execution_mode="multi_agent_parallel",
            original_query="测试",
            items=_items(),
        )
        registry.mark_running("req-r1", "t1")
        registry.mark_completed("req-r1", "t1", answer_preview="完成")

        snapshot = registry.snapshot("req-r1")
        assert snapshot is not None
        assert snapshot["task_count"] == 2
        by_id = {item["task_id"]: item for item in snapshot["items"]}
        assert by_id["t1"]["status"] == "completed"
        assert by_id["t1"]["answer_preview"] == "完成"
        assert by_id["t2"]["status"] == "pending"
        # Redis 中的独立 item key 也应可被另一个服务实例读取
        other = SubtaskRegistryService(redis_client=redis)
        remote_snapshot = other.snapshot("req-r1")
        assert remote_snapshot is not None
        assert remote_snapshot["items"][0]["status"] == "completed"

    def test_redis_unavailable_falls_back_to_memory(self):
        registry = SubtaskRegistryService(redis_client=_BrokenRedis())

        registry.register_plan(
            request_id="req-r2",
            execution_mode="single_agent",
            original_query="测试",
            items=_items(),
        )
        registry.mark_running("req-r2", "t1")
        registry.mark_completed("req-r2", "t1", errors=["agent_execution_failed"])

        snapshot = registry.snapshot("req-r2")
        assert snapshot is not None
        assert snapshot["items"][0]["status"] == "failed"
        assert snapshot["items"][0]["errors"] == ["agent_execution_failed"]

    def test_carries_timeout_and_activity_metadata(self):
        redis = _FakeRedis()
        registry = SubtaskRegistryService(redis_client=redis)
        items = _items()
        items[0].timeout_seconds = 30

        registry.register_plan(
            request_id="req-t1",
            execution_mode="multi_agent_parallel",
            original_query="测试",
            items=items,
        )
        registry.mark_running("req-t1", "t1")
        registry.mark_activity("req-t1", "t1")

        snapshot = registry.snapshot("req-t1")
        by_id = {item["task_id"]: item for item in snapshot["items"]}
        assert by_id["t1"]["timeout_seconds"] == 30
        assert by_id["t1"]["last_activity_at"] > 0
        assert by_id["t1"]["stall_warning"] is False
        assert by_id["t1"]["timed_out"] is False

    def test_timeout_detection(self):
        registry = SubtaskRegistryService(redis_client=_FakeRedis())
        items = _items()
        items[0].timeout_seconds = 0.05

        registry.register_plan(
            request_id="req-t2",
            execution_mode="multi_agent_parallel",
            original_query="测试",
            items=items,
        )
        registry.mark_running("req-t2", "t1")
        time.sleep(0.06)

        snapshot = registry.snapshot("req-t2")
        by_id = {item["task_id"]: item for item in snapshot["items"]}
        assert by_id["t1"]["timed_out"] is True

    def test_register_and_cancel_token(self):
        registry = SubtaskRegistryService()
        token = CancelToken()

        registry.register_cancel_token("req-c1", token)

        assert registry.cancel("req-c1") is True
        assert token.is_cancelled() is True
        assert registry.cancel("req-c1") is False
