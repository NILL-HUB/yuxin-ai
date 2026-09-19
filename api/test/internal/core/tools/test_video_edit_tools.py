"""视频编辑工具：参数解析、派发、错误可读化。

工具不向 Agent 抛异常，一律返回 {"ok": bool, ...} JSON。
"""
import importlib
import json

import pytest

_PKG = "internal.core.tools.builtin_tools.providers.video_edit_tools"

# 注意：必须按**子模块**导入，不能用
#   `from ...video_edit_tools import video_trim`
# 因为包的 __init__.py 会重导出同名工厂函数（Provider 动态导入依赖该约定），
# 包属性会把子模块遮蔽成函数，导致 `video_trim._load_task` 与 `__file__` 都不可用。
video_trim = importlib.import_module(f"{_PKG}.video_trim")
video_concat = importlib.import_module(f"{_PKG}.video_concat")
video_subtitle = importlib.import_module(f"{_PKG}.video_subtitle")


def _capture_delay(monkeypatch, module):
    captured = {}

    class _Task:
        @staticmethod
        def delay(*args, **kwargs):
            captured["args"] = args
            return __import__("types").SimpleNamespace(id="task-1")

    monkeypatch.setattr(module, "_load_task", lambda: _Task)
    return captured


def test_trim_tool_requires_account():
    tool = video_trim.video_trim()
    payload = json.loads(tool._run(knowledge_base_id="kb", document_id="d", start_sec=0, end_sec=1))
    assert payload["ok"] is False
    assert "账号" in payload["error"]


def test_trim_tool_requires_kb_and_document():
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(tool._run(document_id="d", start_sec=0, end_sec=1))
    assert payload["ok"] is False
    assert "知识库" in payload["error"] or "素材" in payload["error"]


def test_trim_tool_rejects_negative_start():
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", start_sec=-1, end_sec=1)
    )
    assert payload["ok"] is False
    assert "开始时间" in payload["error"]


def test_trim_tool_rejects_end_not_after_start():
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", start_sec=2, end_sec=2)
    )
    assert payload["ok"] is False


def test_trim_tool_dispatches_celery_task(monkeypatch):
    captured = _capture_delay(monkeypatch, video_trim)
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb-1", document_id="doc-1",
                  start_sec=1.0, end_sec=3.0, name="裁剪")
    )
    assert payload["ok"] is True
    assert payload["task_id"] == "task-1"
    assert captured["args"][0] == "kb-1"
    assert captured["args"][1] == "doc-1"
    assert captured["args"][4] == "裁剪"


def test_trim_tool_reports_dispatch_failure_readably(monkeypatch):
    class _Boom:
        @staticmethod
        def delay(*a, **k):
            raise RuntimeError("broker down")

    monkeypatch.setattr(video_trim, "_load_task", lambda: _Boom)
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", start_sec=0, end_sec=1)
    )
    assert payload["ok"] is False
    assert "提交" in payload["error"]


def test_concat_tool_requires_two_documents():
    tool = video_concat.video_concat(account_id="acc")
    payload = json.loads(tool._run(knowledge_base_id="kb", document_ids=["d1"]))
    assert payload["ok"] is False
    assert "两段" in payload["error"]


def test_concat_tool_dispatches_in_order(monkeypatch):
    captured = _capture_delay(monkeypatch, video_concat)
    tool = video_concat.video_concat(account_id="acc")
    json.loads(tool._run(knowledge_base_id="kb", document_ids=["d3", "d1"], name="合片"))
    assert captured["args"][1] == ["d3", "d1"]


def test_subtitle_tool_requires_cues():
    tool = video_subtitle.video_subtitle(account_id="acc")
    payload = json.loads(tool._run(knowledge_base_id="kb", document_id="d", cues=[]))
    assert payload["ok"] is False
    assert "字幕" in payload["error"]


def test_subtitle_tool_rejects_malformed_cue():
    tool = video_subtitle.video_subtitle(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d",
                  cues=[{"start": "abc", "end": 2, "text": "x"}])
    )
    assert payload["ok"] is False
    assert "时间" in payload["error"]


def test_subtitle_tool_dispatches_cues(monkeypatch):
    captured = _capture_delay(monkeypatch, video_subtitle)
    tool = video_subtitle.video_subtitle(account_id="acc")
    cues = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", cues=cues, name="字幕")
    )
    assert captured["args"][2] == cues


def test_tool_yamls_declare_expected_shape():
    from pathlib import Path

    import yaml

    base = Path(video_trim.__file__).parent
    for stem in ("video_trim", "video_concat", "video_subtitle"):
        data = yaml.safe_load((base / f"{stem}.yaml").read_text(encoding="utf-8"))
        assert data["name"] == stem
        assert data["label"]
        assert isinstance(data["params"], list) and data["params"]
        assert isinstance(data["task_keywords"], list) and data["task_keywords"]


def test_positions_yaml_lists_all_three_tools():
    from pathlib import Path

    import yaml

    base = Path(video_trim.__file__).parent
    names = yaml.safe_load((base / "positions.yaml").read_text(encoding="utf-8"))
    assert set(names) == {"video_trim", "video_concat", "video_subtitle"}


# ── Task 6：provider 登记与运行时挂载（接线回归） ──────────────────────────
#
# 本轮实测发现两处计划缺陷，本组用例已按真实约定修正：
#   1) Provider 的导入路径是 entities.provider_entity（不是 providers.provider_entity）；
#   2) `BuiltinProviderManager.get_provider()` 直接返回已初始化的 Provider 实例
#      （不再是 ProviderEntity），故不能再包一层 Provider(...)。


def test_provider_registered_in_providers_yaml():
    from pathlib import Path

    import yaml

    providers_yaml = Path(video_trim.__file__).parents[1] / "providers.yaml"
    data = yaml.safe_load(providers_yaml.read_text(encoding="utf-8"))
    names = [p["name"] for p in data]
    assert "video_edit_tools" in names, "video_edit_tools 未登记进 providers.yaml"
    entry = next(p for p in data if p["name"] == "video_edit_tools")
    # 字段完整性：ProviderEntity 要求这些键存在
    for key in ("label", "description", "icon", "background", "category", "created_at"):
        assert key in entry, f"providers.yaml 缺字段：{key}"


def test_tools_are_mounted_at_runtime_with_account_id():
    """挂载点回归：缺挂载则对话内不可达（历史断链）。"""
    from pathlib import Path

    src = Path(video_trim.__file__).parents[6] / "internal" / "service" / "assistant_agent_service.py"
    text = src.read_text(encoding="utf-8")
    # 用带引号的精确字面量匹配：裸子串匹配会被 `video_edit_tools_DISABLED` 这类
    # 变体误判为通过（反向验证实测踩到过），故必须锚定引号。
    assert '"video_edit_tools"' in text, "assistant_agent_service 未挂载 video_edit_tools"
    for tool_name in ("video_trim", "video_concat", "video_subtitle"):
        assert f'"{tool_name}"' in text, f"未挂载 {tool_name}"
    # 依赖账号的工具必须注入 account_id，否则会返回「缺少账号」
    assert "account_id=str(account_id)" in text


def test_package_init_reexports_factories():
    """包 __init__ 必须重导出工厂函数。

    Provider 用 `getattr(importlib.import_module(pkg), tool_name)` 取工具，
    若包顶层取不到同名可调用对象，工具会整体加载失败（实测 AttributeError）。
    """
    import importlib

    pkg = importlib.import_module(_PKG)
    for name in ("video_trim", "video_concat", "video_subtitle"):
        symbol = getattr(pkg, name)
        assert callable(symbol), f"{_PKG}.{name} 必须是可调用的工厂函数"


def test_provider_loader_discovers_all_tools():
    """Provider 按 positions.yaml 动态导入，工具必须能被真实发现且可调用。"""
    import logging

    from internal.core.tools.builtin_tools.providers.builtin_provider_manager import (
        BuiltinProviderManager,
    )

    logging.disable(logging.CRITICAL)
    try:
        provider = BuiltinProviderManager().get_provider("video_edit_tools")
    finally:
        logging.disable(logging.NOTSET)

    assert provider is not None, "provider 未被管理器发现"
    assert set(provider.tool_func_map) == {"video_trim", "video_concat", "video_subtitle"}
    for name in ("video_trim", "video_concat", "video_subtitle"):
        assert callable(provider.tool_func_map[name]), f"{name} 工厂函数不可调用"