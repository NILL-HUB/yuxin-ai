"""渲染服务编排测试：编 -> 渲 必须串起来。

用替身隔离真实 subprocess、DB 与 Flask app context，只验证编排契约：
spec 交给编译器、编译产物写盘为 index.html、渲染器拿到工程目录与产物路径。
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from internal.service.render_service import RenderService


def _spec():
    return {
        "composition_id": "main",
        "duration": 5.0,
        "segments": [{"start": 0, "duration": 5, "text": "x"}],
    }


def _wire(monkeypatch, calls):
    """把编译/渲染/配置三处替换为替身（monkeypatch 模块级符号与类方法）。"""
    import internal.service.render_service as module

    def _build(self, spec):
        calls["spec"] = spec
        return "<html>compiled</html>"

    def _render(self, *, project_dir, output_path, settings, quality, fps):
        calls["project_dir"] = Path(project_dir)
        calls["output_path"] = Path(output_path)
        calls["quality"] = quality
        calls["fps"] = fps
        if calls.get("fail"):
            raise calls["fail"]
        Path(output_path).write_bytes(b"mp4")

    monkeypatch.setattr(RenderService, "_build_composition", _build)
    monkeypatch.setattr(RenderService, "_render", _render)
    monkeypatch.setattr(module, "_load_settings", lambda: SimpleNamespace())


def test_render_writes_composition_and_invokes_renderer(tmp_path, monkeypatch):
    calls = {}
    _wire(monkeypatch, calls)
    service = RenderService.__new__(RenderService)

    result = service.render_composition(
        composition_spec=_spec(), work_dir=tmp_path / "job1", quality="draft", fps=30
    )

    assert calls["spec"] == _spec()
    assert (calls["project_dir"] / "index.html").read_text(encoding="utf-8") == "<html>compiled</html>"
    assert calls["output_path"] == calls["project_dir"] / "output.mp4"
    assert calls["quality"] == "draft" and calls["fps"] == 30
    assert result.endswith(".mp4")


def test_render_propagates_failure(tmp_path, monkeypatch):
    from internal.core.video.hyperframes_renderer import RenderFailedError

    calls = {"fail": RenderFailedError("boom")}
    _wire(monkeypatch, calls)
    service = RenderService.__new__(RenderService)

    with pytest.raises(RenderFailedError):
        service.render_composition(
            composition_spec=_spec(), work_dir=tmp_path / "job2", quality="draft", fps=30
        )
