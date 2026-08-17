from internal.service.a2a_gateway_service import A2AGatewayService


def test_a2a_gateway_service_can_be_resolved_by_injector():
    """回归：字段曾标注为 Any，injector 报 Injecting Any is not supported。"""
    from injector import Injector

    from internal.service.public_agent_a2a_service import PublicAgentA2AService
    from internal.service.public_agent_registry_service import PublicAgentRegistryService

    injector = Injector()
    injector.binder.bind(PublicAgentA2AService, to=_FakeRouter())
    injector.binder.bind(PublicAgentRegistryService, to=_FakeRegistry())

    gateway = injector.get(A2AGatewayService)

    assert isinstance(gateway, A2AGatewayService)
    assert isinstance(gateway.public_agent_a2a_service, _FakeRouter)
    assert isinstance(gateway.public_agent_registry_service, _FakeRegistry)


class _FakeRegistry:
    def search_public_agents(self, query, limit=50):
        return [{"name": "数据分析"}, {"name": "写作助手"}]


class _FakeRouter:
    def route_public_agents(self, query, caller_account_id, limit=3):
        return {
            "delegated_results": [
                {
                    "agent_name": "数据分析",
                    "answer": "数据分析结果：123",
                }
            ]
        }


class _FakeCancellableRouter(_FakeRouter):
    def __init__(self, cancelled=False):
        self.cancelled = cancelled

    def cancel_task(self, task_id):
        self.last_cancelled_task_id = task_id
        return self.cancelled


def test_agent_card_lists_public_agents():
    gateway = A2AGatewayService(
        public_agent_a2a_service=_FakeRouter(),
        public_agent_registry_service=_FakeRegistry(),
    )
    card = gateway.get_agent_card(base_url="http://localhost")
    assert card["name"] == "Yuxin AI Gateway"
    assert card["supportedInterfaces"][0]["url"].endswith("/a2a")
    assert any(skill["id"] == "agent.数据分析" for skill in card["skills"])


def test_message_send_delegates_and_returns_task():
    gateway = A2AGatewayService(
        public_agent_a2a_service=_FakeRouter(),
        public_agent_registry_service=_FakeRegistry(),
    )
    response = gateway.handle_message_send(
        "req-1",
        {
            "message": {
                "role": "ROLE_USER",
                "parts": [{"text": "分析一下数据", "mediaType": "text/plain"}],
            }
        },
    )
    assert response["id"] == "req-1"
    assert response["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    answer = response["result"]["task"]["messages"][0]["parts"][0]["text"]
    assert "数据分析结果：123" in answer


def test_message_send_empty_text_returns_error():
    gateway = A2AGatewayService(
        public_agent_a2a_service=_FakeRouter(),
        public_agent_registry_service=_FakeRegistry(),
    )
    response = gateway.handle_message_send("req-2", {"message": {"parts": []}})
    assert response["error"]["code"] == -32602


def test_tasks_get_unknown_returns_error():
    gateway = A2AGatewayService(
        public_agent_a2a_service=_FakeRouter(),
        public_agent_registry_service=_FakeRegistry(),
    )
    response = gateway.handle_tasks_get("req-3", {"id": "missing"})
    assert response["error"]["code"] == -32001


def test_tasks_cancel_calls_public_service():
    router = _FakeCancellableRouter(cancelled=True)
    gateway = A2AGatewayService(
        public_agent_a2a_service=router,
        public_agent_registry_service=_FakeRegistry(),
    )
    response = gateway.handle_tasks_cancel("req-4", {"id": "task-1"})

    assert response["id"] == "req-4"
    assert response["result"]["task"]["status"]["state"] == "TASK_STATE_CANCELED"
    assert router.last_cancelled_task_id == "task-1"


def test_tasks_cancel_unknown_returns_error():
    gateway = A2AGatewayService(
        public_agent_a2a_service=_FakeCancellableRouter(cancelled=False),
        public_agent_registry_service=_FakeRegistry(),
    )
    response = gateway.handle_tasks_cancel("req-5", {"id": "missing"})

    assert response["error"]["code"] == -32001


def test_tasks_cancel_empty_id_returns_invalid_params():
    gateway = A2AGatewayService(
        public_agent_a2a_service=_FakeCancellableRouter(cancelled=False),
        public_agent_registry_service=_FakeRegistry(),
    )
    response = gateway.handle_tasks_cancel("req-6", {})

    assert response["error"]["code"] == -32602


def test_format_result_handles_plain_message():
    assert (
        A2AGatewayService._format_result({"message": "简单结果"})
        == "简单结果"
    )
