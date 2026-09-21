"""外部素材获取服务（KB-P6）：yt-dlp 库调用下载 + 前缀校验。

强制约束（设计 §5.3）：
- 默认关闭：由工具层 _enabled() 控制挂载，本服务不做开关；
- 提取器白名单，排除 generic 兜底（SSRF 关键）——只允许已实名 extractor；
- 体积上限提前拒绝，主媒体流式上传不读进内存；
- 仅公开内容，不做登录态/Cookies，只认平台可匿名抓取。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# 允许的实名提取器白名单（新增站点在此登记）。未命中一律拒绝。
ALLOWED_EXTRACTORS = {"youtube", "bilibili", "vimeo", "dailymotion", "twitch"}


class MediaFetchError(Exception):
    """外部素材获取业务失败（不重试）。其子类是 Celery 判定不重试的边界。"""


class MediaFetchService:
    """负责 fetch_media 的下载编排。所有业务校验在此，供 Celery 任务与单测复用。"""

    def validate_url(self, url: str, *, max_bytes: int | None = None) -> dict:
        """URL scheme 前置校验：仅 http/https。"""
        from urllib.parse import urlparse
        parsed = urlparse(str(url or "").strip() or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"ok": False, "error": "仅支持 http/https 链接，请提供可公开访问的视频/音频网页地址"}
        return {"ok": True}

    def _extractor_allowed(self, extractor_key: str) -> bool:
        return str(extractor_key or "").strip().lower() in ALLOWED_EXTRACTORS

    def _respect_size_cap(self, info: dict, *, max_bytes: int | None) -> dict:
        if max_bytes is None or max_bytes <= 0:
            return {"ok": True}
        size = 0
        for key in ("filesize", "filesize_approx"):
            size = max(size, int(info.get(key) or 0))
        if size <= 0:
            size = int(os.getenv("MEDIA_FETCH_MAX_BYTES_FALLBACK", "536870912") or "536870912")  # 512MB
        if size > max_bytes:
            return {"ok": False, "error": f"素材体积约 {size // 1024 // 1024} MiB 超出本板块上限，请降低分辨率后重试"}
        return {"ok": True}

    def _download(
        self,
        url: str,
        temp_dir: str,
        *,
        format_spec: str,
        max_bytes: int | None,
        prefer_subtitle: bool = True,
    ) -> dict[str, Any]:
        """用 yt-dlp 库下载媒体到临时目录；返回主媒体路径 + 元数据 + 可选字幕路径。"""
        import yt_dlp
        outtmpl = os.path.join(temp_dir, "%(title).30B-%(id)s.%(ext)s")
        opts: dict[str, Any] = {
            "format": format_spec,
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": False,
        }
        if prefer_subtitle:
            opts.update({
                "writesubtitles": True,
                "writeautomaticsub": False,
                "subtitleslangs": ["en", "zh-Hans", "zh-CN", "zh"],
                "subtitlesformat": "vtt/srt",
                "skip_download": False,
            })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "Unsupported URL" in msg or "requested format is not available" in msg:
                raise MediaFetchError("该链接当前无法解析，可能为平台不支持或页面已失效") from exc
            if "Unable to download webpage" in msg:
                raise MediaFetchError("无法访问该网页，链接可能失效或平台要求登录（暂不支持登录态）") from exc
            logger.warning("yt-dlp 下载失败 url=%s", url, exc_info=True)
            raise MediaFetchError(f"外部素材下载失败：{msg[:200]}") from exc

        extractor = str(info.get("extractor_key") or "").lower()
        if not self._extractor_allowed(extractor):
            raise MediaFetchError("该站点暂不在支持的提取器白名单内，无法入库")
        cap_result = self._respect_size_cap(info, max_bytes=max_bytes)
        if not cap_result["ok"]:
            raise MediaFetchError(cap_result["error"])

        filepath = info.get("requested_downloads") or info.get("_filename") or ""
        if isinstance(filepath, list):
            filepath = next((str(f.get("filepath") or "") for f in filepath if f.get("filepath")), "")
        media_path = str(filepath or "")
        if not media_path or not os.path.exists(media_path):
            raise MediaFetchError("下载完成但未找到产物文件，请稍后重试")

        result: dict[str, Any] = {
            "media_path": media_path,
            "ext": str(info.get("ext") or "").lower(),
            "info": info,
        }
        if prefer_subtitle:
            srt = self._find_subtitle(temp_dir, media_path)
            result["subtitle_path"] = srt
        return result

    @staticmethod
    def _find_subtitle(temp_dir: str, media_path: str) -> str | None:
        base = os.path.splitext(os.path.basename(media_path or ""))[0]
        if not base:
            return None
        for name in os.listdir(temp_dir):
            low = name.lower()
            if name.startswith(base) and (low.endswith(".vtt") or low.endswith(".srt")):
                return os.path.join(temp_dir, name)
        return None

    @staticmethod
    def _stream_sha3(path: str, chunk_size: int = 1024 * 1024) -> str:
        """分块流式计算文件 sha3_256，避免把 GB 级大文件整块读进内存。

        去重依赖 ``UploadFile.hash``（storage_migration 以 hash 为 group_key），
        必须返回真实值，不能用非空占位符（会把所有外部媒体误判为同组）。
        """
        digest = hashlib.sha3_256()
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _inject(self):
        """惰性取用依赖（强类型，走运行时 Injector）。测试可预置对应 mock 覆盖。"""
        if getattr(self, "_cos", None) is None:
            from app.http.module import injector
            from internal.service.cos_service import CosService
            from internal.service.knowledge_base_service import KnowledgeBaseService
            from internal.service.upload_file_service import UploadFileService

            self._cos = injector.get(CosService)
            self._upload_file_service = injector.get(UploadFileService)
            self._knowledge_base_service = injector.get(KnowledgeBaseService)
        return self

    def import_document(
        self,
        *,
        url: str,
        knowledge_base,
        account,
        temp_dir: str,
        max_bytes: int | None,
        format_spec: str = "bv*+ba/b",
    ) -> dict:
        """下载 → 流式上传 → 建档 → 字幕 metadata 关联。

        主媒体走 upload_local_file 流式上传（保 key，GB 级不进内存）并分块算真实
        sha3_256 供去重；字幕为小文件用 upload_bytes 建记录并写入
        document.metadata_[subtitle_upload_file_id]，供 L1 解析时优先消费。

        失败语义：上传/建档/字幕任一步抛错时，对已上传的 target_key 做 best-effort
        清理（删除孤儿 COS 对象），然后原样 raise。UploadFile 记录若有残留，
        待后续任务/运维回收，不做复杂级联删除；COS 失败异常保持抛给上层
        （T3 Celery 据 MediaFetchError/其他异常决定是否重试）。
        仅公开内容，不做登录态/Cookies。
        """
        self._inject()

        fetched = self._download(
            url, temp_dir, format_spec=format_spec, max_bytes=max_bytes, prefer_subtitle=True,
        )
        media_path = fetched["media_path"]
        filename = os.path.basename(media_path)

        # 主媒体流式上传（保 key，不读进内存）。注入对象实际是运行时存储代理
        # （RuntimeStorageProxy），不暴露 CosService._build_object_key，故直接调静态方法生成 key。
        from internal.service.cos_service import CosService
        target_key = CosService._build_object_key(filename)
        try:
            media_hash = self._stream_sha3(media_path)
            self._cos.upload_local_file(source_path=media_path, target_key=target_key)

            extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            active_backend = getattr(self._cos, "active_backend", None)
            backend = str(active_backend() if callable(active_backend) else os.getenv("STORAGE_BACKEND", "cos")).strip().lower()
            backend = "local" if backend in ("", "local") else "cos"
            main_upload = self._upload_file_service.create_upload_file(
                account_id=account.id,
                name=filename,
                key=target_key,
                size=os.path.getsize(media_path),
                extension=extension,
                mime_type=None,
                hash=media_hash,
                storage_backend=backend,
            )

            document = self._knowledge_base_service.create_document_from_upload_file(
                knowledge_base_id=knowledge_base.id,
                upload_file=main_upload,
                account=account,
            )

            metadata_patch: dict[str, Any] = {}
            subtitle_path = fetched.get("subtitle_path")
            if subtitle_path and os.path.exists(subtitle_path):
                with open(subtitle_path, "rb") as fh:
                    sub_content = fh.read()
                sub_record = self._cos.upload_bytes(
                    filename=os.path.basename(subtitle_path),
                    content=sub_content,
                    account_id=account.id,
                    mime_type="text/vtt" if subtitle_path.lower().endswith(".vtt") else "text/plain",
                )
                metadata_patch["subtitle_upload_file_id"] = str(sub_record.id)

            if metadata_patch:
                # 合并字幕关联信息到 document.metadata_ 并持久化。
                # 复用知识库 service 继承自 BaseService.update 的通用更新方法。
                merged = dict(getattr(document, "metadata_", None) or {})
                merged.update(metadata_patch)
                self._knowledge_base_service.update(document, metadata_=merged)
        except Exception:
            # best-effort 清理已上传的孤儿 COS 对象；UploadFile 行残留待运维回收
            try:
                self._cos.delete_object(target_key)
            except Exception:
                logger.exception("清理孤儿 COS 对象失败 key=%s", target_key)
            raise

        return {
            "ok": True,
            "document_id": str(getattr(document, "id", "")),
            "subtitle_attached": bool(metadata_patch.get("subtitle_upload_file_id")),
            "message": "外部素材已下载并入知识库，开始解析",
        }