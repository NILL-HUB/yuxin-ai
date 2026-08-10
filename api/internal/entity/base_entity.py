from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class SerializableMixin:
    def to_dict(self) -> dict:
        if not is_dataclass(self):
            raise TypeError(f"{type(self).__name__} 必须是 dataclass 才能使用 SerializableMixin")
        data = {f.name: self._serialize(getattr(self, f.name)) for f in fields(self)}
        data.update(self._to_dict_extras())
        return data

    def _to_dict_extras(self) -> dict:
        return {}

    @classmethod
    def _serialize(cls, value: Any) -> Any:
        if isinstance(value, SerializableMixin):
            return value.to_dict()
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, list):
            return [cls._serialize(item) for item in value]
        if isinstance(value, dict):
            return {key: cls._serialize(val) for key, val in value.items()}
        return value
