from types import SimpleNamespace

from internal.service.mcp_service import McpService


def _build_service() -> McpService:
    return McpService(
        db=SimpleNamespace(),
        mcp_provider_manager=SimpleNamespace(
            get_providers=lambda: [],
            get_provider=lambda _name: None,
        ),
        icon_generator_service=SimpleNamespace(generate_icon=lambda *_args, **_kwargs: "icon"),
    )


def _cli_binding(**overrides):
    binding = {
        "name": "cli_echo",
        "description": "本地 CLI 回声",
        "transport": "cli",
        "command": "python",
        "args": ["-c", "print('{text}')"],
        "env": {},
        "tool_schema": {
            "echo": {
                "description": "回声文本",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        },
        "enabled": True,
    }
    binding.update(overrides)
    return binding


def test_normalize_binding_keeps_tool_schema_and_sets_raw_protocol_for_cli():
    service = _build_service()

    normalized = service._normalize_binding(_cli_binding())

    assert normalized["transport"] == "cli"
    assert normalized["protocol"] == "raw"
    assert normalized["tool_schema"] == _cli_binding()["tool_schema"]


def test_normalize_binding_keeps_existing_protocol_for_non_cli():
    service = _build_service()

    normalized = service._normalize_binding(
        _cli_binding(transport="http", url="https://mcp.example.com", protocol="mcp", tool_schema={})
    )

    assert normalized["transport"] == "http"
    assert normalized["protocol"] == "mcp"
    assert normalized["tool_schema"] == {}


def test_is_binding_enabled_true_for_cli_with_command():
    service = _build_service()

    assert service._is_binding_enabled(_cli_binding()) is True


def test_is_binding_enabled_false_for_cli_without_command():
    service = _build_service()

    assert service._is_binding_enabled(_cli_binding(command="")) is False


def test_binding_reason_empty_for_cli_with_command():
    service = _build_service()

    assert service._binding_reason(_cli_binding()) == ""


def test_binding_reason_requires_command_for_cli():
    service = _build_service()

    assert service._binding_reason(_cli_binding(command="   ")) == "stdio/cli 模式需要 command"
