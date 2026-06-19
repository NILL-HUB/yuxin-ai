from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from internal.entity.base_entity import SerializableMixin


class _Color(Enum):
    RED = "red"
    BLUE = "blue"


@dataclass
class _Inner(SerializableMixin):
    name: str = ""
    count: int = 0


@dataclass
class _Sample(SerializableMixin):
    query: str = ""
    tags: list[str] = field(default_factory=list)
    inner: _Inner = field(default_factory=_Inner)
    created_at: datetime | None = None
    ref_id: UUID | None = None
    color: _Color = _Color.RED
    metadata: dict = field(default_factory=dict)

    def _to_dict_extras(self) -> dict:
        return {"tag_count": len(self.tags)}


class TestSerializableMixin:
    def test_to_dict_should_serialize_basic_fields(self):
        obj = _Sample(query="hello", tags=["a", "b"])
        data = obj.to_dict()
        assert data["query"] == "hello"
        assert data["tags"] == ["a", "b"]

    def test_to_dict_should_serialize_datetime_to_isoformat(self):
        dt = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
        obj = _Sample(created_at=dt)
        assert obj.to_dict()["created_at"] == dt.isoformat()

    def test_to_dict_should_serialize_uuid_to_string(self):
        uid = UUID("12345678-1234-5678-1234-567812345678")
        obj = _Sample(ref_id=uid)
        assert obj.to_dict()["ref_id"] == str(uid)

    def test_to_dict_should_serialize_enum_to_value(self):
        obj = _Sample(color=_Color.BLUE)
        assert obj.to_dict()["color"] == "blue"

    def test_to_dict_should_recursively_serialize_nested_mixin(self):
        obj = _Sample(inner=_Inner(name="inner-name", count=3))
        inner = obj.to_dict()["inner"]
        assert inner == {"name": "inner-name", "count": 3}

    def test_to_dict_should_include_extras_from_hook(self):
        obj = _Sample(tags=["x", "y", "z"])
        assert obj.to_dict()["tag_count"] == 3

    def test_to_dict_should_serialize_dict_values(self):
        obj = _Sample(metadata={"key": _Color.RED})
        assert obj.to_dict()["metadata"]["key"] == "red"

    def test_to_dict_should_raise_for_non_dataclass(self):
        class NotADataclass(SerializableMixin):
            pass

        try:
            NotADataclass().to_dict()
            assert False, "应抛出 TypeError"
        except TypeError:
            pass
