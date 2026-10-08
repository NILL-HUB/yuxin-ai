"""SSE 响应构造回归测试：长流不得被 Quart 响应超时掐断。

背景（2026-10-05 实测定位）：Quart 的 ``RESPONSE_TIMEOUT`` 默认 60s，超时会在写出
chunked 终止符**之前**掐断响应——客户端读到截断流（``http.client`` 抛
``IncompleteRead``），服务端报 "ASGI callable returned without completing
response"。长对话/深度思考单帧可远超 60s（``SSE_MAX_FRAME_SECONDS=1800``），
因此 ``_sse_stream_response`` 必须显式 ``timeout = None``。

隔离复现（uvicorn + 同款 Quart，25s 单帧 ×3）：
- 默认超时：60.0s 掐断，``IncompleteRead(56 bytes read)``；
- ``timeout = None``：75.0s 正常读完，心跳齐全，干净 EOF。
"""
import asyncio
import time

from app.http import support


def _run(coro):
    return asyncio.run(coro)


class TestSseResponseTimeout:
    """所有 SSE 出口构造响应时都必须关闭 Quart 响应超时。"""

    def test_stream_response_disables_quart_timeout(self):
        resp = support._sse_stream_response(iter(["data: x\n\n"]))

        assert resp.timeout is None
        assert resp.mimetype == "text/event-stream"
        assert resp.headers["X-Accel-Buffering"] == "no"
        assert resp.headers["Cache-Control"] == "no-cache"

    def test_stream_response_leaves_connection_to_transport(self):
        """不写死 Connection：显式 keep-alive 会与声明 close 的客户端冲突。"""
        resp = support._sse_stream_response(iter(["data: x\n\n"]))

        assert "Connection" not in resp.headers

    def test_sse_response_disables_quart_timeout(self):
        """主入口 `_sse_response`（Agent/工作流/应用对话约 20 处调用）同样关闭超时。"""
        resp = support._sse_response(iter(["data: x\n\n"]))

        assert resp.timeout is None


class TestSseHeartbeat:
    def test_emits_keepalive_during_slow_frame(self, monkeypatch):
        """单帧静默超过心跳间隔时输出 keep-alive 注释帧，且实质帧不丢失。"""
        monkeypatch.setattr(support, "SSE_HEARTBEAT_INTERVAL", 0.05)

        def _slow():
            time.sleep(0.2)
            yield "data: f1\n\n"
            time.sleep(0.2)
            yield "data: f2\n\n"

        async def _collect():
            resp = support._sse_response(_slow())
            frames = []
            async for frame in resp.response:
                frames.append(frame)
            return frames

        frames = _run(_collect())

        assert "data: f1\n\n" in frames
        assert "data: f2\n\n" in frames
        assert any(": keep-alive" in frame for frame in frames)
