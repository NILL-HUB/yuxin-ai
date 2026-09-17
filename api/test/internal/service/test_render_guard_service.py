"""渲染闸门服务测试：并发上限、防重锁、队列积压三者的准入与归还。

用 fake Redis 隔离真实连接，但保持 set(nx/ex) / incr / decr / delete / get
的语义一致——闸门的正确性完全依赖这些原子语义。
"""

from internal.service.render_guard_service import (
    MAX_CONCURRENT_RENDERS_PER_ACCOUNT,
    MAX_QUEUED_RENDERS,
    RenderGuardService,
)


class _FakeRedis:
    """最小可用的 Redis 替身：覆盖闸门用到的原子操作。"""

    def __init__(self):
        self.store = {}
        self.expires = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    def incr(self, key):
        current = int(self.store.get(key) or 0) + 1
        self.store[key] = current
        return current

    def decr(self, key):
        current = int(self.store.get(key) or 0) - 1
        self.store[key] = current
        return current

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed

    def expire(self, key, ttl):
        self.expires[key] = ttl
        return True


def _guard():
    return RenderGuardService(redis_client=_FakeRedis())


def test_admit_allows_first_render():
    guard = _guard()

    result = guard.admit(account_id="acc-1", fingerprint="fp-1")

    assert result.allowed is True


def test_admit_rejects_second_concurrent_render_for_same_account():
    """每账号并发=1：第二次进入必须被拒，这是 4C4G 上的核心护城河。"""
    guard = _guard()
    guard.admit(account_id="acc-1", fingerprint="fp-1")

    result = guard.admit(account_id="acc-1", fingerprint="fp-2")

    assert result.allowed is False
    assert "正在进行" in result.reason


def test_admit_allows_other_account_while_one_is_rendering():
    """并发上限是按账号隔离的，不应误伤其他用户。"""
    guard = _guard()
    guard.admit(account_id="acc-1", fingerprint="fp-1")

    result = guard.admit(account_id="acc-2", fingerprint="fp-2")

    assert result.allowed is True


def test_admit_rejects_duplicate_fingerprint():
    """防重锁：同一脚本重复提交（即使槽位已释放）也必须被识别为重复。"""
    guard = _guard()
    guard.admit(account_id="acc-1", fingerprint="same-fp")
    # 释放槽位但保留防重锁，模拟「槽位已归还、锁仍在 TTL 内」
    guard._safe_decr(guard._slot_key("acc-1"))

    result = guard.admit(account_id="acc-1", fingerprint="same-fp")

    assert result.allowed is False
    assert "重复" in result.reason


def test_release_frees_slot_for_next_render():
    """释放后必须能再次渲染，否则用户会被永久锁死。"""
    guard = _guard()
    guard.admit(account_id="acc-1", fingerprint="fp-1")

    guard.release(account_id="acc-1", fingerprint="fp-1")
    result = guard.admit(account_id="acc-1", fingerprint="fp-2")

    assert result.allowed is True


def test_release_removes_dedupe_lock():
    """释放必须清掉防重锁，否则同脚本重试会被误判为重复。"""
    guard = _guard()
    guard.admit(account_id="acc-1", fingerprint="fp-1")

    guard.release(account_id="acc-1", fingerprint="fp-1")
    result = guard.admit(account_id="acc-1", fingerprint="fp-1")

    assert result.allowed is True, "释放后同脚本重试应被允许"


def test_admit_rejects_when_queue_backlog_exceeds_threshold():
    """闸门 6：队列积压超阈值时拒绝新请求，避免任务无限堆积。"""
    guard = _guard()
    for _ in range(MAX_QUEUED_RENDERS):
        guard.mark_enqueued()

    result = guard.admit(account_id="acc-queued", fingerprint="fp")

    assert result.allowed is False
    assert "稍后" in result.reason


def test_mark_dequeued_frees_queue_capacity():
    """任务开始执行即释放积压额度，否则队列计数只增不减。"""
    guard = _guard()
    for _ in range(MAX_QUEUED_RENDERS):
        guard.mark_enqueued()

    guard.mark_dequeued()

    result = guard.admit(account_id="acc-queued2", fingerprint="fp")

    assert result.allowed is True


def test_admit_rejects_blank_account():
    guard = _guard()

    result = guard.admit(account_id="", fingerprint="fp")

    assert result.allowed is False
    assert "账号" in result.reason


def test_slot_counter_does_not_go_negative_on_double_release():
    """重复释放不得把计数减成负数，否则会出现「幽灵额度」。"""
    guard = _guard()
    guard.admit(account_id="acc-1", fingerprint="fp-1")

    guard.release(account_id="acc-1", fingerprint="fp-1")
    guard.release(account_id="acc-1", fingerprint="fp-1")

    assert "render:slot:acc-1" not in guard.redis_client.store


def test_concurrency_threshold_is_one_on_single_node():
    """4C4G 上并发=1 是硬约束（V8 堆 + 内存双重限制），锁定该常量防漂移。"""
    assert MAX_CONCURRENT_RENDERS_PER_ACCOUNT == 1
