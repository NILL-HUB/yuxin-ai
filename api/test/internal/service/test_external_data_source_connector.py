import os
import tempfile
from types import SimpleNamespace

from internal.entity.knowledge_entity import ExternalAuthorizationStatus, ExternalSourceType
from internal.service.connectors.base_connector import BaseConnector
from internal.service.connectors.github_connector import GithubConnector
from internal.service.connectors.lark_connector import LarkConnector
from internal.service.connectors.local_folder_connector import LocalFolderConnector
from internal.service.connectors.notion_connector import NotionConnector
from internal.service.external_data_source_connector_factory import ConnectorFactory


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

    def test_sync_should_return_documents_from_config(self):
        connector = LarkConnector()
        preset_docs = [
            {"name": "飞书文档1", "content": "内容1"},
            {"name": "飞书文档2", "content": "内容2"},
        ]
        data_source = SimpleNamespace(config={"preset_documents": preset_docs})
        documents = connector.sync(data_source)
        assert len(documents) == 2
        assert documents[0]["name"] == "飞书文档1"

    def test_sync_should_return_empty_without_preset(self):
        connector = LarkConnector()
        data_source = SimpleNamespace(config={})
        documents = connector.sync(data_source)
        assert documents == []


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

    def test_sync_should_return_documents_from_config(self):
        connector = NotionConnector()
        preset_docs = [
            {"name": "Notion文档1", "content": "内容1"},
            {"name": "Notion文档2", "content": "内容2"},
        ]
        data_source = SimpleNamespace(config={"preset_documents": preset_docs})
        documents = connector.sync(data_source)
        assert len(documents) == 2
        assert documents[0]["name"] == "Notion文档1"

    def test_sync_should_return_empty_without_preset(self):
        connector = NotionConnector()
        data_source = SimpleNamespace(config={})
        documents = connector.sync(data_source)
        assert documents == []


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

    def test_sync_should_return_documents_from_config(self):
        connector = GithubConnector()
        preset_docs = [
            {"name": "README.md", "content": "# 项目说明"},
        ]
        data_source = SimpleNamespace(config={"preset_documents": preset_docs})
        documents = connector.sync(data_source)
        assert len(documents) == 1
        assert documents[0]["name"] == "README.md"

    def test_sync_should_return_empty_without_preset(self):
        connector = GithubConnector()
        data_source = SimpleNamespace(config={})
        documents = connector.sync(data_source)
        assert documents == []
