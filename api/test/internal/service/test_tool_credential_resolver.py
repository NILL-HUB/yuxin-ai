"""tool_credential_resolver 行为测试。

验证候选名顺序取值、空白归一、缺失返回空串（缺失语义由调用方决定）。
"""
import pytest

from internal.service import tool_credential_resolver as resolver


def test_returns_first_non_empty_candidate(monkeypatch):
    monkeypatch.setenv("RESOLVER_PRIMARY", "")
    monkeypatch.setenv("RESOLVER_SECONDARY", "secondary-value")

    assert resolver.get_tool_credential("RESOLVER_PRIMARY", "RESOLVER_SECONDARY") == "secondary-value"


def test_skips_whitespace_only_candidates(monkeypatch):
    monkeypatch.setenv("RESOLVER_PRIMARY", "   ")
    monkeypatch.setenv("RESOLVER_SECONDARY", "ok")

    assert resolver.get_tool_credential("RESOLVER_PRIMARY", "RESOLVER_SECONDARY") == "ok"


def test_strips_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv("RESOLVER_ONLY", "  token-key  ")

    assert resolver.get_tool_credential("RESOLVER_ONLY") == "token-key"


def test_returns_empty_string_when_all_missing(monkeypatch):
    monkeypatch.delenv("RESOLVER_ABSENT", raising=False)

    assert resolver.get_tool_credential("RESOLVER_ABSENT") == ""


def test_setting_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("RESOLVER_SETTING", raising=False)

    assert resolver.get_tool_setting("RESOLVER_SETTING", default="180") == "180"


def test_setting_prefers_env_over_default(monkeypatch):
    monkeypatch.setenv("RESOLVER_SETTING", "300")

    assert resolver.get_tool_setting("RESOLVER_SETTING", default="180") == "300"


def test_accepts_multiple_candidate_names_for_aliases(monkeypatch):
    monkeypatch.delenv("RESOLVER_ALIAS_A", raising=False)
    monkeypatch.setenv("RESOLVER_ALIAS_B", "b")

    assert resolver.get_tool_credential("RESOLVER_ALIAS_A", "RESOLVER_ALIAS_B") == "b"
