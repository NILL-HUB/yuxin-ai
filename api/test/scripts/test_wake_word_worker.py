import argparse

from scripts.wake_word_worker import _dependency_error, _notify_wake, _resolve_config


def test_resolve_config_uses_defaults(monkeypatch):
    monkeypatch.delenv("WAKE_WORD_KEYWORD", raising=False)
    monkeypatch.delenv("WAKE_WORD_ENDPOINT", raising=False)
    monkeypatch.delenv("WAKE_WORD_TOKEN", raising=False)
    args = argparse.Namespace(keyword="", endpoint="", token="", engine="")

    config = _resolve_config(args)

    assert config["keyword"] == "hey yuxin"
    assert config["endpoint"] == ""
    assert config["engine"] == "openwakeword"


def test_resolve_config_prefers_explicit_args():
    args = argparse.Namespace(
        keyword="hello yuxin",
        endpoint="http://127.0.0.1:9999/wake",
        token="t",
        engine="porcupine",
    )

    config = _resolve_config(args)

    assert config["keyword"] == "hello yuxin"
    assert config["endpoint"] == "http://127.0.0.1:9999/wake"
    assert config["token"] == "t"
    assert config["engine"] == "porcupine"


def test_dependency_error_returns_install_hint():
    error = _dependency_error()
    assert isinstance(error, str)
    assert error  # 环境未安装时返回安装提示


def test_notify_wake_without_endpoint_returns_true():
    assert _notify_wake({"keyword": "hey", "endpoint": "", "token": "", "engine": "openwakeword"}) is True
