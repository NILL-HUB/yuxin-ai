"""admin 检查更新：解析上游 latest.yml（``_fetch_desktop_update_latest``）。

该函数是「管理员检查是否有更新」的读取路径——读的 latest.yml 与客户端
检查更新时同源，因此解析结果即客户端将看到的版本与更新内容。
"""

import pytest
import requests

from app.http.admin_routes_8 import _fetch_desktop_update_latest


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


SAMPLE_LATEST_YML = """
version: 0.1.1
files:
  - url: setup-0.1.1.exe
    sha512: abc
    size: 123
path: setup-0.1.1.exe
sha512: abc
releaseDate: '2026-09-30T10:00:00.000Z'
releaseNotes: |-
  新增：更新弹窗与更新历程
  修复：设备在线状态
"""


def test_fetch_latest_yml_parses_version_and_notes(monkeypatch):
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse(SAMPLE_LATEST_YML)

    monkeypatch.setattr(requests, "get", fake_get)

    result = _fetch_desktop_update_latest("https://openllm.cloud/desktop-updates/")

    assert captured["url"] == "https://openllm.cloud/desktop-updates/latest.yml"
    assert result["ok"] is True
    assert result["latest_version"] == "0.1.1"
    assert "新增：更新弹窗与更新历程" in result["release_notes"]
    assert result["package_path"] == "setup-0.1.1.exe"
    assert result["release_date"].startswith("2026-09-30")


def test_fetch_latest_yml_propagates_http_error(monkeypatch):
    def fake_get(url, timeout=None):
        return _FakeResponse("", status_code=404)

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(requests.exceptions.HTTPError):
        _fetch_desktop_update_latest("https://openllm.cloud/desktop-updates")
