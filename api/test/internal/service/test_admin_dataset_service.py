from types import SimpleNamespace

from internal.service.admin_dataset_service import AdminDatasetService


class _ExplodingDataset:
    def __init__(self):
        self.id = "00000000-0000-0000-0000-000000000001"
        self.name = "CRM Knowledge Base"
        self.icon = "https://example.com/icon.png"
        self.description = "customer support docs"
        self.updated_at = None
        self.created_at = None
        self.account = SimpleNamespace(name="Alice", avatar="https://example.com/alice.png")

    @property
    def document_count(self):
        raise AssertionError("service should not read dataset.document_count directly")

    @property
    def related_app_count(self):
        raise AssertionError("service should not read dataset.related_app_count directly")

    @property
    def character_count(self):
        raise AssertionError("service should not read dataset.character_count directly")


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def label(self, _name):
        return self

    def join(self, *_args, **_kwargs):
        return self

    def outerjoin(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def group_by(self, *_args, **_kwargs):
        return self

    @property
    def c(self):
        return SimpleNamespace(
            dataset_id=self,
            document_count=self,
            related_app_count=self,
            character_count=self,
        )

    def subquery(self):
        return self

    def count(self):
        return len(self._rows)

    def order_by(self, *_args, **_kwargs):
        return self

    def offset(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._rows)


class TestAdminDatasetService:
    def test_list_datasets_should_use_aggregated_counts_without_touching_dataset_properties(self):
        dataset = _ExplodingDataset()
        session = _FakeSession([(dataset, 3, 2, 128)])
        service = AdminDatasetService(session=session)

        result = service.list_datasets(current_page=1, page_size=20, search_word="")

        assert result["paginator"]["total_record"] == 1
        assert result["list"][0]["name"] == "CRM Knowledge Base"
        assert result["list"][0]["document_count"] == 3
        assert result["list"][0]["related_app_count"] == 2
        assert result["list"][0]["character_count"] == 128
