from internal.service.a2a_client import A2AClient


class TestA2AClient:
    def test_invoke_returns_fixed_jsonrpc_format(self):
        client = A2AClient(endpoint="https://agent.example.com")
        result = client.invoke("你好", agent_id="agent-1")

        assert result["jsonrpc"] == "2.0"
        assert result["id"] == "agent-1"
        assert result["result"]["message"] == "你好"
        assert result["result"]["status"] == "ok"
        assert result["result"]["agent_id"] == "agent-1"
        assert result["result"]["endpoint"] == "https://agent.example.com"
        assert "error" not in result

    def test_invoke_without_agent_id_defaults_to_none(self):
        client = A2AClient()
        result = client.invoke("测试消息")

        assert result["id"] is None
        assert result["result"]["status"] == "ok"
        assert result["result"]["message"] == "测试消息"

    def test_invoke_passes_timeout_from_constructor(self):
        client = A2AClient(endpoint="https://agent.example.com", timeout=45)
        assert client.timeout == 45

        result = client.invoke("消息")
        assert result["result"]["status"] == "ok"

    def test_health_check_returns_true_for_valid_http_endpoint(self):
        client = A2AClient(endpoint="https://agent.example.com")
        assert client.health_check() is True
        assert client.health_check("http://localhost:8080") is True

    def test_health_check_returns_false_for_missing_endpoint(self):
        client = A2AClient()
        assert client.health_check() is False
        assert client.health_check("") is False

    def test_health_check_returns_false_for_invalid_scheme(self):
        client = A2AClient(endpoint="ftp://bad.example.com")
        assert client.health_check() is False
        assert client.health_check("not-a-url") is False

    def test_health_check_explicit_endpoint_overrides_instance_endpoint(self):
        client = A2AClient(endpoint="ftp://bad.example.com")
        assert client.health_check("https://good.example.com") is True
