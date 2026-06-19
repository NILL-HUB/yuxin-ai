from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ObjectStoragePort(Protocol):
    def upload_file(self, file: Any, only_image: bool = False, account: Any = None) -> Any:
        ...

    def upload_bytes(self, filename: str, content: bytes, mime_type: str = "", folder: str = "") -> Any:
        ...

    def download_file(self, key: str, target_file_path: str) -> None:
        ...

    @classmethod
    def upload_bytes_without_record(
        cls, filename: str, content: bytes, mime_type: str = "", folder: str = ""
    ) -> Any:
        ...
