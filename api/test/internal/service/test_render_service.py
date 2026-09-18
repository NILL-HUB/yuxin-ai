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


def test_load_settings_works_without_flask_app_context(monkeypatch):
    """回归：渲染任务在 Celery worker 中执行，那里**没有 Flask app context**。

    曾经的实现用 ``flask.current_app.config``，导致任务一执行就抛
    ``Working outside of application context``——而所有编排测试都 monkeypatch 了
    ``_load_settings``，谁也没测到真实实现，bug 直到真机端到端才暴露。

    这里直接测真实实现：只初始化运行时容器（不 push Flask context），必须拿到配置。
    """
    import internal.service.render_service as module
    from internal.context import init_runtime

    class _Container:
        config = {
            "HYPERFRAMES_CLI_BIN": "/opt/hyperframes/node_modules/.bin/hyperframes",
            "HYPERFRAMES_CLI_VERSION": "0.8.42",
            "HYPERFRAMES_BROWSER_PATH": "/usr/bin/chromium",
            "HYPERFRAMES_FFMPEG_PATH": "/usr/bin/ffmpeg",
            "HYPERFRAMES_FFPROBE_PATH": "/usr/bin/ffprobe",
        }

    init_runtime(_Container())

    settings = module._load_settings()

    # 关键：必须支持**属性**访问——渲染器全部用 getattr(settings, "KEY") 读配置，
    # 直接返回 dict 会让 getattr 取不到值而静默落空。
    assert getattr(settings, "HYPERFRAMES_CLI_BIN", "") == (
        "/opt/hyperframes/node_modules/.bin/hyperframes"
    )
    assert getattr(settings, "HYPERFRAMES_FFPROBE_PATH", "") == "/usr/bin/ffprobe"


def test_load_settings_feeds_renderer_env(monkeypatch):
    """接线：真实 _load_settings 的产物必须能让 build_render_env 通过校验。

    这是「配置能读到」与「渲染器能消费」之间的契约，单独测属性访问还不够。
    """
    import internal.service.render_service as module
    from internal.context import init_runtime
    from internal.core.video.hyperframes_renderer import build_render_env

    class _Container:
        config = {
            "HYPERFRAMES_CLI_VERSION": "0.8.42",
            "HYPERFRAMES_BROWSER_PATH": "/usr/bin/chromium",
            "HYPERFRAMES_FFMPEG_PATH": "/usr/bin/ffmpeg",
            "HYPERFRAMES_FFPROBE_PATH": "/usr/bin/ffprobe",
        }

    init_runtime(_Container())

    # 不抛 RenderEnvironmentError 即代表三个必需路径都读到了
    env = build_render_env(module._load_settings())

    assert env["HYPERFRAMES_BROWSER_PATH"] == "/usr/bin/chromium"
    assert env["HYPERFRAMES_FFMPEG_PATH"] == "/usr/bin/ffmpeg"
    assert env["HYPERFRAMES_FFPROBE_PATH"] == "/usr/bin/ffprobe"
