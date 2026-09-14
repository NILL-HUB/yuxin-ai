"""分片上传路由。

提供 init / chunk / status / complete / abort 五个接口，
由前端在大文件上传时按分片调用，支持断点续传与秒传。

沿用 app.http.support 的统一 helper，与 knowledge_mcp_routes.py 写法一致。
"""
import logging

from quart import Response, request

from app.http import support as _support
from app.http.support import _json_resp, _ok, _ok_msg, _resolve_account, _to_thread

logger = logging.getLogger(__name__)

_registered = False


def _get_service(cls):
    return _support._get_service(cls)


def _to_int(value) -> int | None:
    """安全地把入参转为整数；非法返回 None（调用方据此返回 400）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def register_routes(quart_app) -> None:
    """注册分片上传路由（幂等）。"""
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.post("/space/chunked-uploads/init")
    async def chunked_upload_init() -> Response:
        """初始化分片会话（含秒传判定）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(silent=True) or {}
        missing = [
            key for key in ("filename", "total_size", "chunk_size", "total_chunks")
            if payload.get(key) in (None, "", 0)
        ]
        if missing:
            return _json_resp(
                code="validate_error",
                message="参数不完整",
                data={key: ["该字段必填"] for key in missing},
                status=400,
            )

        total_size = _to_int(payload.get("total_size"))
        chunk_size = _to_int(payload.get("chunk_size"))
        total_chunks = _to_int(payload.get("total_chunks"))
        if total_size is None or chunk_size is None or total_chunks is None:
            return _json_resp(
                code="validate_error",
                message="分片参数必须为整数",
                data={"params": ["total_size/chunk_size/total_chunks 必须为整数"]},
                status=400,
            )

        from internal.service.chunked_upload_service import ChunkedUploadService

        result = await _to_thread(
            _get_service(ChunkedUploadService).init,
            account=account,
            filename=payload["filename"],
            total_size=total_size,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
            fingerprint=payload.get("fingerprint", ""),
        )
        return _ok(result)

    @quart_app.post("/space/chunked-uploads/chunk")
    async def chunked_upload_chunk() -> Response:
        """上传单个分片。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        form = await request.form
        session_id = form.get("session_id") or ""
        index_raw = form.get("index")
        if not session_id or index_raw is None:
            return _json_resp(
                code="validate_error",
                message="会话与分片下标必填",
                data={"session_id": ["会话与分片下标必填"]},
                status=400,
            )

        files = await request.files
        chunk = files.get("chunk")
        if chunk is None:
            return _json_resp(
                code="validate_error",
                message="分片内容不能为空",
                data={"chunk": ["分片内容不能为空"]},
                status=400,
            )
        content = chunk.stream.read()

        index = _to_int(index_raw)
        if index is None:
            return _json_resp(
                code="validate_error",
                message="分片下标必须为整数",
                data={"index": ["分片下标必须为整数"]},
                status=400,
            )

        from internal.service.chunked_upload_service import ChunkedUploadService

        result = await _to_thread(
            _get_service(ChunkedUploadService).save_chunk,
            session_id=session_id,
            index=index,
            content=content,
        )
        return _ok(result)

    @quart_app.get("/space/chunked-uploads/<session_id>/status")
    async def chunked_upload_status(session_id: str) -> Response:
        """查询会话进度（断点续传）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.chunked_upload_service import ChunkedUploadService

        result = await _to_thread(
            _get_service(ChunkedUploadService).status,
            session_id=session_id,
            account=account,
        )
        return _ok(result)

    @quart_app.post("/space/chunked-uploads/complete")
    async def chunked_upload_complete() -> Response:
        """合并分片并（可选）创建知识库文档。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(silent=True) or {}
        session_id = payload.get("session_id") or ""
        if not session_id:
            return _json_resp(
                code="validate_error",
                message="会话必填",
                data={"session_id": ["会话必填"]},
                status=400,
            )

        from internal.service.chunked_upload_service import ChunkedUploadService

        result = await _to_thread(
            _get_service(ChunkedUploadService).complete,
            session_id=session_id,
            account=account,
        )
        return _ok(result)

    @quart_app.post("/space/chunked-uploads/abort")
    async def chunked_upload_abort() -> Response:
        """放弃上传并清理暂存。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(silent=True) or {}
        session_id = payload.get("session_id") or ""
        if not session_id:
            return _json_resp(
                code="validate_error",
                message="会话必填",
                data={"session_id": ["会话必填"]},
                status=400,
            )

        from internal.service.chunked_upload_service import ChunkedUploadService

        await _to_thread(
            _get_service(ChunkedUploadService).abort,
            session_id=session_id,
            account=account,
        )
        return _ok_msg("已取消上传")
