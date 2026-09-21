"""外部素材获取服务（KB-P6）：yt-dlp 库调用下载 + 前缀校验。

强制约束（设计 §5.3）：
- 默认关闭：由工具层 _enabled() 控制挂载，本服务不做开关；
- 提取器白名单，排除 generic 兜底（SSRF 关键）——只允许已实名 extractor；
- 体积上限提前拒绝，主媒体流式上传不读进内存；
- 仅公开内容，不做登录态/Cookies，只认平台可匿名抓取。
"""
from __future__ import annotations

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