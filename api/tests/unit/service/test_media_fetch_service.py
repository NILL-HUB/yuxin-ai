"""MediaFetchService 校验与下载编排单测（mock yt_dlp，不联网）。"""
from internal.service.media_fetch_service import MediaFetchService


def test_reject_non_http_scheme():
    svc = MediaFetchService()
    assert svc.validate_url("ftp://x.com/v.mp4", max_bytes=0)["ok"] is False


def test_reject_unknown_extractor():
    svc = MediaFetchService()
    assert svc._extractor_allowed("generic") is False
    assert svc._extractor_allowed("youtube") is True
    assert svc._extractor_allowed("bilibili") is True


def test_size_cap_rejected_proactively():
    svc = MediaFetchService()
    info = {"filesize_approx": 2 * 1024 * 1024 * 1024}
    assert svc._respect_size_cap(info, max_bytes=1024)["ok"] is False


def test_size_cap_message_readable():
    """断言体积超限报错消息里 MiB 换算可读（size // 1024 // 1024 无位运算歧义）。"""
    svc = MediaFetchService()
    info = {"filesize_approx": (2 * 1024 * 1024 * 1024) + (512 * 1024 * 1024)}  # 2.5 GiB
    res = svc._respect_size_cap(info, max_bytes=1024)
    assert res["ok"] is False
    msg = res["error"]
    assert "2560 MiB" in msg  # (2.5 * 1024) MiB，非 "1<<30 溢出"