import os
import tempfile
from types import SimpleNamespace

from internal.entity.knowledge_entity import ExternalAuthorizationStatus, ExternalSourceType
from internal.service.connectors.base_connector import BaseConnector
from internal.service.connectors.lark_connector import LarkConnector
from internal.service.connectors.local_folder_connector import LocalFolderConnector
from internal.service.external_data_source_connector_factory import ConnectorFactory


class TestConnectorFactory:
    def test_factory_should_return_lark_connector_for_lark_source(self):
        factory = ConnectorFactory()
        connector = factory.get_connector(ExternalSourceType.LARK.value)
        assert isinstance(connector, LarkConnector)

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
        for source_type in [ExternalSourceType.LARK.value, ExternalSourceType.DRIVE.value]:
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
