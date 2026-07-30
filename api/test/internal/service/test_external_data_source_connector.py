import base64
import os
import tempfile
from types import SimpleNamespace

import pytest

from internal.entity.knowledge_entity import ExternalAuthorizationStatus, ExternalSourceType
from internal.service.connectors.base_connector import BaseConnector, ExternalConnectorError
from internal.service.connectors import github_connector, lark_connector, notion_connector
from internal.service.connectors.github_connector import GithubConnector
from internal.service.connectors.lark_connector import LarkConnector
from internal.service.connectors.local_folder_connector import LocalFolderConnector
from internal.service.connectors.notion_connector import NotionConnector
from internal.service.external_data_source_connector_factory import ConnectorFactory


class _FakeResponse:
    """模拟 requests.Response 的轻量对象，供连接器单测使用"""

    def __init__(self, json_data=None, status_code=200, text="", raw_bytes=None):
        self._json = json_data
        self.status_code = status_code
        self.text = text
        self._raw_bytes = raw_bytes

    def json(self):
        if self._json is None:
            raise ValueError("未设置 json 数据")
        return self._json

    @property
    def content(self):
        return self._raw_bytes or b""


class TestConnectorFactory:
    def test_factory_should_return_lark_connector_for_lark_source(self):
        factory = ConnectorFactory()
        connector = factory.get_connector(ExternalSourceType.LARK.value)
        assert isinstance(connector, LarkConnector)

    def test_factory_should_return_notion_connector_for_notion_source(self):
        factory = ConnectorFactory()
        connector = factory.get_connector(ExternalSourceType.NOTION.value)
        assert isinstance(connector, NotionConnector)

    def test_factory_should_return_github_connector_for_github_source(self):
        factory = ConnectorFactory()
        connector = factory.get_connector(ExternalSourceType.GITHUB.value)
        assert isinstance(connector, GithubConnector)

    def test_factory_should_return_local_folder_connector_for_drive_source(self):
        factory = ConnectorFactory()
        connector = factory.get_connector(ExternalSourceType.DRIVE.value)
        assert isinstance(connector, LocalFolderConnector)

    def test_factory_should_raise_for_unsupported_source(self):
        factory = ConnectorFactory()
        try:
            factory.get_connector("unknown_type")
            assert False, "应抛出 ValueError"
        except ValueError as e:
            assert "不支持的数据源类型" in str(e)

    def test_factory_should_return_base_connector_subclass(self):
        factory = ConnectorFactory()
        for source_type in [
            ExternalSourceType.LARK.value,
            ExternalSourceType.NOTION.value,
            ExternalSourceType.DRIVE.value,
            ExternalSourceType.GITHUB.value,
        ]:
            connector = factory.get_connector(source_type)
            assert isinstance(connector, BaseConnector)


class TestLocalFolderConnector:
    def test_authorize_should_grant_for_valid_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            connector = LocalFolderConnector()
            data_source = SimpleNamespace(config={"folder_path": tmpdir})
            result = connector.authorize(data_source, {"folder_path": tmpdir})
            assert result == ExternalAuthorizationStatus.GRANTED.value

    def test_authorize_should_raise_for_invalid_folder(self):
        connector = LocalFolderConnector()
        data_source = SimpleNamespace(config={"folder_path": ""})
        try:
            connector.authorize(data_source, {"folder_path": ""})
            assert False, "应抛出 ValueError"
        except ValueError:
            pass

    def test_sync_should_read_markdown_and_text_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "doc1.md"), "w", encoding="utf-8") as f:
                f.write("# 标题\n内容1")
            with open(os.path.join(tmpdir, "doc2.txt"), "w", encoding="utf-8") as f:
                f.write("内容2")
            with open(os.path.join(tmpdir, "ignore.bin"), "w", encoding="utf-8") as f:
                f.write("binary")

            connector = LocalFolderConnector()
            data_source = SimpleNamespace(config={"folder_path": tmpdir})
            documents = connector.sync(data_source)

            assert len(documents) == 2
            names = [d["name"] for d in documents]
            assert "doc1.md" in names
            assert "doc2.txt" in names

    def test_sync_should_return_empty_for_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            connector = LocalFolderConnector()
            data_source = SimpleNamespace(config={"folder_path": tmpdir})
            documents = connector.sync(data_source)
            assert documents == []

    def test_authorize_should_reject_folder_outside_allowed_roots(self, monkeypatch):
        outside_root = os.path.dirname(tempfile.gettempdir())
        if os.path.realpath(outside_root) == os.path.realpath(tempfile.gettempdir()):
            outside_root = os.path.dirname(os.path.abspath(__file__))
        monkeypatch.setenv("LOCAL_FOLDER_CONNECTOR_ALLOWED_ROOTS", tempfile.gettempdir())
        connector = LocalFolderConnector()
        data_source = SimpleNamespace(config={"folder_path": outside_root})
        try:
            connector.authorize(data_source, {"folder_path": outside_root})
            assert False, "越界目录应被拒绝"
        except ValueError:
            pass

    def test_authorize_should_accept_folder_under_custom_allowed_root(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("LOCAL_FOLDER_CONNECTOR_ALLOWED_ROOTS", tmpdir)
            subfolder = os.path.join(tmpdir, "nested")
            os.makedirs(subfolder)
            connector = LocalFolderConnector()
            data_source = SimpleNamespace(config={"folder_path": subfolder})
            result = connector.authorize(data_source, {"folder_path": subfolder})
            assert result == ExternalAuthorizationStatus.GRANTED.value


class TestLarkConnector:
    @pytest.fixture(autouse=True)
    def _clear_token_cache(self):
        # 每个测试前后清理 tenant_access_token 缓存，避免测试间相互污染
        lark_connector._tenant_token_cache.clear()
        yield
        lark_connector._tenant_token_cache.clear()

    def test_authorize_should_grant_with_app_credentials(self):
        connector = LarkConnector()
        data_source = SimpleNamespace(config={})
        auth_config = {
            "app_id": "cli_test",
            "app_secret": "secret_test",
        }
        result = connector.authorize(data_source, auth_config)
        assert result == ExternalAuthorizationStatus.GRANTED.value

    def test_authorize_should_raise_without_app_id(self):
        connector = LarkConnector()
        data_source = SimpleNamespace(config={})
        try:
            connector.authorize(data_source, {"app_id": "", "app_secret": ""})
            assert False, "应抛出 ValueError"
        except ValueError:
            pass

    def test_sync_should_return_empty_without_credentials(self):
        # 凭证缺失时降级返回空列表，不抛异常
        connector = LarkConnector()
        data_source = SimpleNamespace(config={})
        documents = connector.sync(data_source)
        assert documents == []

    def test_sync_should_fetch_docx_documents_from_lark_api(self, monkeypatch):
        # 模拟飞书 OpenAPI 返回：1 个 docx + 1 个 sheet（应被跳过）
        connector = LarkConnector()
        data_source = SimpleNamespace(config={
            "app_id": "cli_test",
            "app_secret": "secret_test",
            "folder_token": "fld_token",
        })

        def fake_post(url, json=None, timeout=None):
            assert "tenant_access_token/internal" in url
            return _FakeResponse({"code": 0, "tenant_access_token": "t-fake", "expire": 7200})

        def fake_get(url, headers=None, params=None, timeout=None):
            if url.endswith("/drive/v1/files"):
                return _FakeResponse({
                    "code": 0,
                    "data": {
                        "files": [
                            {"token": "doc1", "name": "飞书文档1", "type": "docx", "url": "https://feishu.cn/doc1"},
                            {"token": "sh1", "name": "表格", "type": "sheet", "url": "https://feishu.cn/sh1"},
                        ],
                        "has_more": False,
                    },
                })
            if "/docx/v1/documents/doc1/raw_content" in url:
                return _FakeResponse({"code": 0, "data": {"content": "飞书文档正文"}})
            return _FakeResponse({"code": 0, "data": {}})

        monkeypatch.setattr(lark_connector.requests, "post", fake_post)
        monkeypatch.setattr(lark_connector.requests, "get", fake_get)

        documents = connector.sync(data_source)
        # sheet 被跳过，仅返回 1 个 docx
        assert len(documents) == 1
        assert documents[0]["name"] == "飞书文档1"
        assert documents[0]["content"] == "飞书文档正文"
        assert documents[0]["source_url"] == "https://feishu.cn/doc1"

    def test_sync_should_raise_external_connector_error_on_token_failure(self, monkeypatch):
        # token 接口返回错误码时抛 ExternalConnectorError
        connector = LarkConnector()
        data_source = SimpleNamespace(config={
            "app_id": "cli_test",
            "app_secret": "wrong_secret",
        })

        def fake_post(url, json=None, timeout=None):
            return _FakeResponse({"code": 99991663, "msg": "invalid app_secret"})

        monkeypatch.setattr(lark_connector.requests, "post", fake_post)

        with pytest.raises(ExternalConnectorError):
            connector.sync(data_source)


class TestNotionConnector:
    def test_authorize_should_grant_with_integration_token(self):
        connector = NotionConnector()
        data_source = SimpleNamespace(config={})
        result = connector.authorize(
            data_source, {"integration_token": "secret_test"}
        )
        assert result == ExternalAuthorizationStatus.GRANTED.value

    def test_authorize_should_raise_without_integration_token(self):
        connector = NotionConnector()
        data_source = SimpleNamespace(config={})
        try:
            connector.authorize(data_source, {"integration_token": ""})
            assert False, "应抛出 ValueError"
        except ValueError:
            pass

    def test_sync_should_return_empty_without_credentials(self):
        # 凭证缺失时降级返回空列表，不抛异常
        connector = NotionConnector()
        data_source = SimpleNamespace(config={})
        documents = connector.sync(data_source)
        assert documents == []

    def test_sync_should_return_empty_without_database_or_page(self):
        # 有 token 但未配置 database_id/page_id 时降级返回空列表
        connector = NotionConnector()
        data_source = SimpleNamespace(config={"integration_token": "secret_test"})
        documents = connector.sync(data_source)
        assert documents == []

    def test_sync_should_query_database_and_extract_page_text(self, monkeypatch):
        # 模拟 Notion 数据库查询 + 块内容返回
        connector = NotionConnector()
        data_source = SimpleNamespace(config={
            "integration_token": "secret_test",
            "database_id": "db_1",
        })

        def fake_post(url, headers=None, json=None, timeout=None):
            assert url.endswith("/databases/db_1/query")
            # 断言 Notion-Version 头存在
            assert headers.get("Notion-Version") == "2022-06-28"
            return _FakeResponse({
                "results": [
                    {
                        "id": "page_1",
                        "url": "https://notion.so/page_1",
                        "properties": {
                            "title": {"type": "title", "title": [{"plain_text": "Notion文档1"}]},
                        },
                    },
                ],
                "has_more": False,
            })

        def fake_get(url, headers=None, params=None, timeout=None):
            if "/blocks/page_1/children" in url:
                return _FakeResponse({
                    "results": [
                        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "段落文本"}]}},
                        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "标题"}]}},
                    ],
                    "has_more": False,
                })
            return _FakeResponse({"results": [], "has_more": False})

        monkeypatch.setattr(notion_connector.requests, "post", fake_post)
        monkeypatch.setattr(notion_connector.requests, "get", fake_get)

        documents = connector.sync(data_source)
        assert len(documents) == 1
        assert documents[0]["name"] == "Notion文档1"
        assert "段落文本" in documents[0]["content"]
        assert "标题" in documents[0]["content"]
        assert documents[0]["source_url"] == "https://notion.so/page_1"

    def test_sync_should_raise_external_connector_error_on_api_failure(self, monkeypatch):
        # 数据库查询返回非 200 时抛 ExternalConnectorError
        connector = NotionConnector()
        data_source = SimpleNamespace(config={
            "integration_token": "secret_test",
            "database_id": "db_1",
        })

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(status_code=401)

        monkeypatch.setattr(notion_connector.requests, "post", fake_post)

        with pytest.raises(ExternalConnectorError):
            connector.sync(data_source)


class TestGithubConnector:
    def test_authorize_should_grant_with_token_and_repo(self):
        connector = GithubConnector()
        data_source = SimpleNamespace(config={})
        result = connector.authorize(
            data_source, {"token": "ghp_test", "repo": "owner/repo"}
        )
        assert result == ExternalAuthorizationStatus.GRANTED.value

    def test_authorize_should_raise_without_token(self):
        connector = GithubConnector()
        data_source = SimpleNamespace(config={})
        try:
            connector.authorize(data_source, {"token": "", "repo": "owner/repo"})
            assert False, "应抛出 ValueError"
        except ValueError:
            pass

    def test_authorize_should_raise_for_invalid_repo_format(self):
        connector = GithubConnector()
        data_source = SimpleNamespace(config={})
        try:
            connector.authorize(data_source, {"token": "ghp_test", "repo": "invalid_repo"})
            assert False, "应抛出 ValueError"
        except ValueError:
            pass

    def test_sync_should_return_empty_without_credentials(self):
        # 凭证缺失时降级返回空列表，不抛异常
        connector = GithubConnector()
        data_source = SimpleNamespace(config={})
        documents = connector.sync(data_source)
        assert documents == []

    def test_sync_should_fetch_readme_and_docs_markdown(self, monkeypatch):
        # 模拟 GitHub API：README + docs 目录下 1 个 md 文件 + 1 个非 md 文件（应跳过）
        connector = GithubConnector()
        data_source = SimpleNamespace(config={
            "token": "ghp_test",
            "repo": "owner/repo",
        })

        readme_content = base64.b64encode("# 项目说明".encode("utf-8")).decode("utf-8")
        docs_md_content = base64.b64encode("## 文档内容".encode("utf-8")).decode("utf-8")

        def fake_get(url, headers=None, params=None, timeout=None):
            if url.endswith("/repos/owner/repo/readme"):
                return _FakeResponse({
                    "name": "README.md",
                    "encoding": "base64",
                    "content": readme_content,
                    "html_url": "https://github.com/owner/repo/blob/main/README.md",
                })
            if "/repos/owner/repo/contents/docs" in url:
                return _FakeResponse([
                    {"name": "guide.md", "type": "file", "encoding": "base64",
                     "content": docs_md_content, "html_url": "https://github.com/owner/repo/blob/main/docs/guide.md",
                     "download_url": ""},
                    {"name": "image.png", "type": "file", "encoding": "base64",
                     "content": "", "html_url": "", "download_url": ""},
                ])
            return _FakeResponse(status_code=404)

        monkeypatch.setattr(github_connector.requests, "get", fake_get)

        documents = connector.sync(data_source)
        # README + 1 个 md 文件，image.png 被跳过
        names = sorted(d["name"] for d in documents)
        assert names == ["README.md", "guide.md"]
        readme = next(d for d in documents if d["name"] == "README.md")
        assert readme["content"] == "# 项目说明"
        guide = next(d for d in documents if d["name"] == "guide.md")
        assert guide["content"] == "## 文档内容"

    def test_sync_should_raise_external_connector_error_on_api_failure(self, monkeypatch):
        # README 接口返回 500 时抛 ExternalConnectorError
        connector = GithubConnector()
        data_source = SimpleNamespace(config={
            "token": "ghp_test",
            "repo": "owner/repo",
        })

        def fake_get(url, headers=None, params=None, timeout=None):
            return _FakeResponse(status_code=500)

        monkeypatch.setattr(github_connector.requests, "get", fake_get)

        with pytest.raises(ExternalConnectorError):
            connector.sync(data_source)
