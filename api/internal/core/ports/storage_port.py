from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ObjectStoragePort(Protocol):
    def upload_file(self, file: Any, only_image: bool = False, account: Any = None) -> Any:
        ...

    def upload_bytes(self, filename: str, content: bytes, **kwargs: Any) -> Any:
        ...

    def upload_local_file(
        self, *, source_path: str, target_key: str, mime_type: str | None = None
    ) -> str:
        """把本地磁盘上的文件**流式**上传到目标后端，保持 target_key 不变。

        这是大文件（分片合并产物、跨后端复制）的唯一落盘入口：走 SDK 的流式/
        分片上传，不把整个文件读进内存。返回最终对象 key。
        """
        ...

    def download_file(self, key: str, target_file_path: str) -> None:
        ...

    def copy_object(self, source_key: str, target_key: str) -> int:
        """服务端复制对象（秒传用），返回目标对象字节数。"""
        ...

    def delete_object(self, key: str) -> bool:
        """删除对象（幂等）；对象不存在时返回 False。"""
        ...

    @classmethod
    def upload_bytes_without_record(
        cls, filename: str, content: bytes, mime_type: str = "", folder: str = ""
    ) -> Any:
        ...

    def get_file_url(self, key: str, download_name: str | None = None) -> str:
        ...
