"""机密闸门（confidential_gate）与确认帧契约测试。

不变量：
1. 放行策略两条通道在同一放行点汇合：确认句 → 全部放行；卡片授权 → id 白名单；
2. 命中机密未授权时必须带出结构化条目 + 确认 id（否则前端出不了卡片）；
3. 确认记录创建失败（Redis 不可用）时降级为纯文本提示，绝不抛错；
4. 用户端与管理端的卡片 payload 形状同源（``confirmation_payload``）。
"""

from internal.entity.memory_recall_entity import (
    ConfidentialAccess,
    MemoryRecallOutcome,
    WithheldConfidential,
)


class _FakeConfirmations:
    def __init__(self, *, authorized=(), fail_create=False):
        self._authorized = frozenset(authorized)
        self._fail_create = fail_create
        self.created: list[dict] = []

    def authorized_ids(self, owner_key):
        return self._authorized

    def create(self, *, owner_key, items):
        if self._fail_create:
            raise ConnectionError("redis down")
        self.created.append({"owner_key": owner_key, "items": items})
        return "conf-1"


class _FakeRetriever:
    """替身：记录传入的 access，并按预设回填 status["withheld"]。"""

    def __init__(self, withheld=None):
        self.withheld = withheld or []
        self.seen_access: ConfidentialAccess | None = None
        self.seen_status: dict | None = None

    def retrieve_for_chat(self, query, owner_key, *, top_k, max_chars, access=None, status=None):
        self.seen_access = access
        self.seen_status = status
        if status is not None:
            status["withheld"] = list(self.withheld)
        return "召回文本"


def _gate():
    from internal.service.memory import confidential_gate

    return confidential_gate


def _withheld_items():
    return [
        {
            "memory_id": "m1",
            "types": ["phone"],
            "label": "手机号",
            "preview": "我的手机号是 [PHONE_REDACTED]",
        }
    ]


class TestAccessResolution:
    def test_explicit_confirmation_allows_all(self):
        gate = _gate()
        access = gate.resolve_confidential_access(
            query="确认读取",
            owner_key="u-1",
            confirmations=_FakeConfirmations(authorized=["m9"]),
            is_read_confirmation=lambda text: text == "确认读取",
        )
        assert access.allow_all is True
        assert access.allows("anything") is True

    def test_card_authorization_whitelists_ids(self):
        gate = _gate()
        access = gate.resolve_confidential_access(
            query="我的手机号是多少",
            owner_key="u-1",
            confirmations=_FakeConfirmations(authorized=["m1"]),
            is_read_confirmation=lambda text: False,
        )
        assert access.allow_all is False
        assert access.allows("m1") is True
        assert access.allows("m2") is False

    def test_no_authorization_withholds_everything(self):
        gate = _gate()
        access = gate.resolve_confidential_access(
            query="我的手机号",
            owner_key="u-1",
            confirmations=_FakeConfirmations(),
            is_read_confirmation=lambda text: False,
        )
        assert access.ids == frozenset()
        assert access.allows("m1") is False


class TestGatedRecall:
    def test_creates_confirmation_when_withheld(self):
        gate = _gate()
        confirmations = _FakeConfirmations()
        retriever = _FakeRetriever(withheld=_withheld_items())

        outcome = gate.gated_recall(
            retriever=retriever,
            confirmations=confirmations,
            owner_key="u-1",
            query="我的手机号是多少",
            max_chars=200,
            is_read_confirmation=lambda text: False,
        )

        assert outcome.text == "召回文本"
        assert outcome.needs_confirmation is True
        assert outcome.confirmation_id == "conf-1"
        assert confirmations.created[0]["owner_key"] == "u-1"
        assert confirmations.created[0]["items"] == _withheld_items()

    def test_no_confirmation_when_nothing_withheld(self):
        gate = _gate()
        confirmations = _FakeConfirmations()
        retriever = _FakeRetriever(withheld=[])

        outcome = gate.gated_recall(
            retriever=retriever,
            confirmations=confirmations,
            owner_key="u-1",
            query="普通问题",
            max_chars=200,
            is_read_confirmation=lambda text: False,
        )

        assert outcome.needs_confirmation is False
        assert confirmations.created == []

    def test_create_failure_degrades_to_text_hint(self):
        """Redis 不可用：仍返回文本（含模型提示），只是没有卡片可点。"""
        gate = _gate()
        confirmations = _FakeConfirmations(fail_create=True)
        retriever = _FakeRetriever(withheld=_withheld_items())

        outcome = gate.gated_recall(
            retriever=retriever,
            confirmations=confirmations,
            owner_key="u-1",
            query="我的手机号是多少",
            max_chars=200,
            is_read_confirmation=lambda text: False,
        )

        assert outcome.text == "召回文本"
        assert outcome.withheld == _withheld_items()
        assert outcome.confirmation_id == ""
        assert outcome.needs_confirmation is False  # 没有 id 就不发卡片

    def test_access_is_passed_down_to_retriever(self):
        gate = _gate()
        retriever = _FakeRetriever()
        gate.gated_recall(
            retriever=retriever,
            confirmations=_FakeConfirmations(authorized=["m1"]),
            owner_key="u-1",
            query="问题",
            max_chars=200,
            is_read_confirmation=lambda text: False,
        )

        assert retriever.seen_access is not None
        assert retriever.seen_access.allows("m1") is True
        assert retriever.seen_access.allows("m2") is False
        assert retriever.seen_status is not None


class TestServiceResolutionFailOpen:
    """确认服务取不到（DI 未绑定/Redis 未就绪）时：召回必须照常，只是没有卡片。

    历史缺陷（2026-10-05 真机定位）：服务获取异常直接冒泡到召回层被静默吞掉，
    使 outcome 全空——连普通召回的文本提示都丢了。
    """

    def test_resolve_returns_none_when_get_service_raises(self):
        gate = _gate()

        def _boom(_cls):
            raise RuntimeError("no binding")

        assert gate.resolve_confirmation_service(_boom) is None

    def test_resolve_returns_service_when_available(self):
        gate = _gate()
        fake = _FakeConfirmations()
        assert gate.resolve_confirmation_service(lambda _cls: fake) is fake

    def test_gate_with_missing_service_keeps_text(self):
        gate = _gate()
        retriever = _FakeRetriever(withheld=_withheld_items())

        outcome = gate.gated_recall(
            retriever=retriever,
            confirmations=None,
            owner_key="u-1",
            query="我的手机号是多少",
            max_chars=200,
            is_read_confirmation=lambda text: False,
        )

        assert outcome.text == "召回文本"
        assert outcome.withheld == _withheld_items()
        assert outcome.needs_confirmation is False


class TestConfirmationPayloadContract:
    """卡片线协议：两端共用 ``confirmation_payload``，不得各拼一份。"""

    def test_payload_shape(self):
        outcome = MemoryRecallOutcome(
            text="t",
            withheld=_withheld_items(),
            confirmation_id="conf-1",
        )
        payload = outcome.confirmation_payload()

        assert payload["confirmation_id"] == "conf-1"
        assert payload["count"] == 1
        assert payload["memory_items"][0]["memory_id"] == "m1"
        # 键名不得是裸 items：用户端流里 items 已属于子任务契约（避免同名字段两种形状）
        assert set(payload.keys()) == {"confirmation_id", "memory_items", "count"}

    def test_withheld_entity_serialization_is_single_source(self):
        item = WithheldConfidential(
            memory_id="m1",
            types=("phone",),
            label="手机号",
            preview="[PHONE_REDACTED]",
        )
        assert item.to_dict() == {
            "memory_id": "m1",
            "types": ["phone"],
            "label": "手机号",
            "preview": "[PHONE_REDACTED]",
        }


class TestUserSideFrame:
    """用户端发帧：助手链路静态构造器（事件名走 QueueEvent）。"""

    def test_frame_contains_event_and_payload(self):
        from internal.service.assistant_agent_service import AssistantAgentService

        outcome = MemoryRecallOutcome(
            text="t", withheld=_withheld_items(), confirmation_id="conf-1"
        )
        frame = AssistantAgentService._memory_confirmation_frame(outcome)

        assert frame.startswith("event: memory_confirmation_required\n")
        assert '"confirmation_id": "conf-1"' in frame
        assert frame.endswith("\n\n")

    def test_entities_module_has_matching_event_constants(self):
        """缝合点自检：两侧事件枚举都登记了 memory_confirmation_required。"""
        from internal.core.agent.entities.queue_entity import QueueEvent
        from internal.entity.admin_agent_chat_entity import AdminAgentChatEvent

        assert QueueEvent.MEMORY_CONFIRMATION_REQUIRED.value == "memory_confirmation_required"
        assert (
            AdminAgentChatEvent.MEMORY_CONFIRMATION_REQUIRED.value
            == "memory_confirmation_required"
        )
