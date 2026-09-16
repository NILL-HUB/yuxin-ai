"""渲染运行时配置项测试。

HyperFrames 硬依赖三个外部二进制（浏览器 / ffmpeg / ffprobe），
且 CLI 版本必须钉死以保证「同一 composition 重复渲染结果一致」。
这些配置项缺失时渲染会在启动阶段直接失败，故用测试锁定默认值与覆盖行为。
"""
import importlib

import pytest


def _load_config(monkeypatch, **env):
    """在干净环境下重新构造 Config，避免被其他测试的 env 污染。"""
    for key in (
        "HYPERFRAMES_CLI_VERSION",
        "HYPERFRAMES_BROWSER_PATH",
        "HYPERFRAMES_FFMPEG_PATH",
        "HYPERFRAMES_FFPROBE_PATH",
        "RENDER_TIMEOUT_SEC",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config.config as module

    importlib.reload(module)
    return module


def test_render_config_has_defaults(monkeypatch):
    module = _load_config(monkeypatch)
    config = module.Config()

    assert config.HYPERFRAMES_CLI_VERSION == "0.8.42"
    assert config.HYPERFRAMES_BROWSER_PATH == ""
    assert config.HYPERFRAMES_FFMPEG_PATH == ""
    assert config.HYPERFRAMES_FFPROBE_PATH == ""
    assert config.RENDER_TIMEOUT_SEC == 1800


def test_render_config_reads_env(monkeypatch):
    module = _load_config(
        monkeypatch,
        HYPERFRAMES_CLI_VERSION="0.9.0",
        HYPERFRAMES_BROWSER_PATH=r"C:\chrome\headless_shell.exe",
        HYPERFRAMES_FFMPEG_PATH=r"C:\ffmpeg\ffmpeg.exe",
        HYPERFRAMES_FFPROBE_PATH=r"C:\ffmpeg\ffprobe.exe",
        RENDER_TIMEOUT_SEC="600",
    )
    config = module.Config()

    assert config.HYPERFRAMES_CLI_VERSION == "0.9.0"
    assert config.HYPERFRAMES_BROWSER_PATH == r"C:\chrome\headless_shell.exe"
    assert config.HYPERFRAMES_FFPROBE_PATH == r"C:\ffmpeg\ffprobe.exe"
    assert config.RENDER_TIMEOUT_SEC == 600
