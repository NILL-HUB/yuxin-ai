from __future__ import annotations

import json

import pytest

from internal.core.skills.scf_handler import main_handler

_TEST_TOKEN = "test-token"


@pytest.fixture(autouse=True)
def _sandbox_token(monkeypatch):
    """函数侧 fail-closed 校验 SANDBOX_TOKEN；测试统一注入。"""
    monkeypatch.setenv("SANDBOX_TOKEN", _TEST_TOKEN)


def _decode(response: dict) -> dict:
    assert response["statusCode"] == 200
    return json.loads(response["body"])


def _body(payload: dict) -> dict:
    return {**payload, "token": _TEST_TOKEN}


def test_scf_handler_should_execute_code_payload():
    response = main_handler(
        {
            "body": _body({
                "action": "execute_skill",
                "code": "def analyze_request(params):\n    return {'summary': params['request']}\n",
                "func_name": "analyze_request",
                "args": [{"request": "hello"}],
                "kwargs": {},
            })
        },
        None,
    )

    assert _decode(response)["result"] == {"summary": "hello"}


def test_scf_handler_should_accept_direct_invoke_payload():
    """SDK 直调（tencent_scf 后端）：event 即 payload，无 body 包裹。"""
    response = main_handler(
        _body({
            "action": "execute_skill",
            "code": "def add(a, b):\n    return a + b\n",
            "func_name": "add",
            "args": [1, 2],
            "kwargs": {},
        }),
        None,
    )

    assert _decode(response)["result"] == 3


def test_scf_handler_should_reject_when_token_missing(monkeypatch):
    """fail-closed：payload 缺 token 一律拒绝。"""
    response = main_handler(
        {
            "body": {
                "action": "execute_skill",
                "code": "def add(a, b):\n    return a + b\n",
                "func_name": "add",
                "args": [1, 2],
            }
        },
        None,
    )

    assert "unauthorized" in _decode(response)["error"]


def test_scf_handler_should_reject_when_env_token_not_configured(monkeypatch):
    """fail-closed：函数未配置 SANDBOX_TOKEN 时拒绝一切请求（不得裸奔）。"""
    monkeypatch.delenv("SANDBOX_TOKEN", raising=False)
    response = main_handler(
        _body({
            "action": "execute_skill",
            "code": "def add(a, b):\n    return a + b\n",
            "func_name": "add",
            "args": [1, 2],
        }),
        None,
    )

    assert "unauthorized" in _decode(response)["error"]


def test_scf_handler_should_allow_imports_for_code_analysis():
    response = main_handler(
        {
            "body": _body({
                "action": "execute_skill",
                "code": (
                    "from pathlib import Path\n\n"
                    "def analyze_request(params):\n"
                    "    path = Path(params['path'])\n"
                    "    return {'suffix': path.suffix, 'name': path.name}\n"
                ),
                "func_name": "analyze_request",
                "args": [{"path": "app/src/views/SkillPage.vue"}],
                "kwargs": {},
            })
        },
        None,
    )

    decoded = _decode(response)
    assert decoded["result"] == {"suffix": ".vue", "name": "SkillPage.vue"}


def test_scf_handler_should_allow_future_import_and_class_definition():
    response = main_handler(
        {
            "body": _body({
                "action": "execute_skill",
                "code": (
                    "from __future__ import annotations\n\n"
                    "class Box:\n"
                    "    def __init__(self, value):\n"
                    "        self.value = value\n\n"
                    "class Child(Box):\n"
                    "    def __init__(self, value):\n"
                    "        super().__init__(value)\n\n"
                    "def analyze_request(params):\n"
                    "    box = Child(params['request'])\n"
                    "    return {'summary': box.value}\n"
                ),
                "func_name": "analyze_request",
                "args": [{"request": "hello"}],
                "kwargs": {},
            })
        },
        None,
    )

    assert _decode(response)["result"] == {"summary": "hello"}


def test_scf_handler_should_reject_third_party_imports():
    """标准运行时无第三方库：白名单外的 import 明确报错（而非静默失败）。"""
    response = main_handler(
        {
            "body": _body({
                "action": "execute_skill",
                "code": "import requests\n\ndef main(params):\n    return {}\n",
                "func_name": "main",
                "args": [{}],
                "kwargs": {},
            })
        },
        None,
    )

    decoded = _decode(response)
    assert "not allowed" in decoded["error"]


def test_scf_handler_should_support_sync_package_without_explicit_code():
    response = main_handler(
        {
            "body": _body({
                "action": "sync_package",
                "skill": {"source_key": "code_workbench"},
                "version": {"version": 1},
            })
        },
        None,
    )

    decoded = _decode(response)
    assert decoded["result"]["synced"] is True
    assert decoded["result"]["source_key"] == "code_workbench"
