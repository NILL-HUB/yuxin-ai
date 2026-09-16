"""HyperFrames 渲染执行器测试。

只对「可确定性判定」的部分做单测（命令构造 / 环境变量注入 / 产物校验 /
错误分型）；真实渲染调用通过注入的 runner 替身验证，避免单测依赖 Chromium。
"""
import subprocess
from pathlib import Path

import pytest

from internal.core.video.hyperframes_renderer import (
    RenderEnvironmentError,
    RenderFailedError,
    build_render_command,
    build_render_env,
    render_composition,
    verify_artifact,
)


class _Settings:
    HYPERFRAMES_CLI_VERSION = "0.8.42"
    HYPERFRAMES_BROWSER_PATH = r"C:\chrome\headless_shell.exe"
    HYPERFRAMES_FFMPEG_PATH = r"C:\ff\ffmpeg.exe"
    HYPERFRAMES_FFPROBE_PATH = r"C:\ff\ffprobe.exe"
    RENDER_TIMEOUT_SEC = 1800


def test_build_render_env_injects_three_paths():
    env = build_render_env(_Settings())

    assert env["HYPERFRAMES_BROWSER_PATH"] == r"C:\chrome\headless_shell.exe"
    assert env["HYPERFRAMES_FFMPEG_PATH"] == r"C:\ff\ffmpeg.exe"
    assert env["HYPERFRAMES_FFPROBE_PATH"] == r"C:\ff\ffprobe.exe"


def test_build_render_env_missing_ffprobe_raises():
    class _Missing(_Settings):
        HYPERFRAMES_FFPROBE_PATH = ""

    with pytest.raises(RenderEnvironmentError) as exc:
        build_render_env(_Missing())

    assert "HYPERFRAMES_FFPROBE_PATH" in str(exc.value)


def test_build_render_command_pins_cli_version():
    cmd = build_render_command(
        _Settings(), output_path=Path("out.mp4"), quality="draft", fps=30
    )

    assert cmd[0] == "npx"
    assert "hyperframes@0.8.42" in cmd, "CLI 版本必须钉死以保证结果可复现"
    assert "render" in cmd
    assert "out.mp4" in " ".join(cmd)
    assert "--quality" in cmd and "draft" in cmd


def test_unsupported_quality_rejected():
    with pytest.raises(RenderFailedError):
        build_render_command(
            _Settings(), output_path=Path("o.mp4"), quality="ultra", fps=30
        )


def test_render_composition_raises_when_artifact_missing(tmp_path):
    """CLI 退出码为 0 但没产物 -> 必须报错，不能返回不存在的文件。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    def _runner(cmd, cwd, env, timeout):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(RenderFailedError):
        render_composition(
            project_dir=tmp_path,
            output_path=tmp_path / "missing.mp4",
            settings=_Settings(),
            runner=_runner,
            prober=lambda path: 10.0,
        )


def test_render_composition_requires_index_html(tmp_path):
    """工程目录缺 index.html 必须直接报错，而不是跑到一半才失败。"""
    with pytest.raises(RenderFailedError) as exc:
        render_composition(
            project_dir=tmp_path,
            output_path=tmp_path / "o.mp4",
            settings=_Settings(),
            runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
            prober=lambda path: 10.0,
        )

    assert "index.html" in str(exc.value)


def test_render_composition_succeeds_when_artifact_and_probe_ok(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    output = tmp_path / "ok.mp4"

    def _runner(cmd, cwd, env, timeout):
        output.write_bytes(b"fake-mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    result = render_composition(
        project_dir=tmp_path,
        output_path=output,
        settings=_Settings(),
        runner=_runner,
        prober=lambda path: 10.0,
    )

    assert result == output


def test_render_composition_nonzero_exit_with_valid_artifact_still_fails(tmp_path):
    """本机实测：CLI 可能产物已生成但最后一步探测失败而非 0 退出。

    此时必须报错（让上层重试/报错），不能因为「产物在」就宣称成功——
    否则会把一个渲染流程被判失败的半成品当成品入库。
    """
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    output = tmp_path / "half.mp4"

    def _runner(cmd, cwd, env, timeout):
        output.write_bytes(b"fake-mp4")
        return subprocess.CompletedProcess(cmd, 1, "", "Render artifact duration probe failed")

    with pytest.raises(RenderFailedError):
        render_composition(
            project_dir=tmp_path,
            output_path=output,
            settings=_Settings(),
            runner=_runner,
            prober=lambda path: 10.0,
        )


def test_verify_artifact_rejects_zero_duration(tmp_path):
    output = tmp_path / "bad.mp4"
    output.write_bytes(b"x")

    with pytest.raises(RenderFailedError):
        verify_artifact(output, prober=lambda path: 0.0)


def test_verify_artifact_rejects_empty_file(tmp_path):
    output = tmp_path / "empty.mp4"
    output.write_bytes(b"")

    with pytest.raises(RenderFailedError):
        verify_artifact(output, prober=lambda path: 10.0)
