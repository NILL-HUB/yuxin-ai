import json
import importlib
from types import SimpleNamespace

from internal.core.tools.builtin_tools.providers.vision_tools.vision_analyze import (
    VisionAnalyzeTool,
    _is_safe_image_url,
    _resolve_image_data_uri,
)


def test_is_safe_image_url_rejects_localhost():
    safe, _ = _is_safe_image_url("http://localhost/a.png")
    assert safe is False


def test_resolve_data_uri_passthrough():
    uri = "data:image/png;base64,AA=="
    assert _resolve_image_data_uri(uri) == uri


def test_vision_analyze_returns_analysis(monkeypatch):
    class _FakeLLM:
        def invoke(self, messages):
            content = messages[0].content
            assert content[0]["type"] == "text"
            assert content[1]["type"] == "image_url"
            return SimpleNamespace(content="图片里有一只猫")

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.vision_tools.vision_analyze"
    )
    monkeypatch.setattr(module, "_invoke_vision_model", lambda data_uri, prompt: "图片里有一只猫")

    result = json.loads(
        VisionAnalyzeTool()._run(image="data:image/png;base64,AA==", prompt="描述")
    )

    assert result["ok"] is True
    assert result["analysis"] == "图片里有一只猫"


def test_vision_analyze_returns_error_on_bad_url():
    result = json.loads(VisionAnalyzeTool()._run(image="http://localhost/a.png"))
    assert result["ok"] is False
