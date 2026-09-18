"""本机渲染 worker（用户设备侧出片）。

由桌面客户端（Electron 主进程）托管启动，经本地能力桥（desktop/bridge.js）
的 `/render` 路由被服务端调用；也可在服务端容器内独立运行（回退通道）。

与 browser/computer worker 同一范式：ThreadingHTTPServer + Bearer 常量时间鉴权。
差异点：渲染是分钟级长任务，且**不返回产物字节流**——只回传落盘路径与体积，
由调用方（服务端）自行取回入库，避免在 HTTP body 里搬运几十 MB 视频。

安全模型：
- 仅接受 Authorization: Bearer <RENDER_WORKER_TOKEN>；
- 未配置 token 时拒绝启动；
- 仅在调用方指定的工作目录内写文件，不暴露任意路径读能力。

硬依赖（与 hyperframes_renderer 一致，缺一不可）：
HYPERFRAMES_BROWSER_PATH / HYPERFRAMES_FFMPEG_PATH / HYPERFRAMES_FFPROBE_PATH。
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import logging
import os
import re
import shutil
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger("render_worker")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8768

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

_REQUIRED_ENV_KEYS = (
    "HYPERFRAMES_BROWSER_PATH",
    "HYPERFRAMES_FFMPEG_PATH",
    "HYPERFRAMES_FFPROBE_PATH",
)


def _env(key: str, default: str = "") -> str:
    return str(os.environ.get(key, default) or "").strip()


def _authorized(header_value: str) -> bool:
    """常量时间比对 Bearer token；未配置 token 一律拒绝。"""
    expected = _env("RENDER_WORKER_TOKEN")
    if not expected:
        return False
    header = str(header_value or "")
    if not header.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(header[7:].strip(), expected)


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """校验入参，返回错误 dict 或 None。"""
    composition = payload.get("composition")
    if not isinstance(composition, dict):
        return {"ok": False, "error": "composition 必须是对象"}
    segments = composition.get("segments")
    if not isinstance(segments, list) or not segments:
        return {"ok": False, "error": "composition.segments 必须是非空列表"}
    return None


def _load_settings() -> Any:
    """构造渲染器所需配置视图（属性访问语义，与 server 侧一致）。

    本 worker 不依赖 Flask / internal.context，直接读环境变量并包成对象——
    ``hyperframes_renderer`` 全部用 ``getattr(settings, "HYPERFRAMES_*")``
    属性读取，对 dict 做 getattr 会静默落空。
    """
    return SimpleNamespace(
        HYPERFRAMES_BROWSER_PATH=_env("HYPERFRAMES_BROWSER_PATH"),
        HYPERFRAMES_FFMPEG_PATH=_env("HYPERFRAMES_FFMPEG_PATH"),
        HYPERFRAMES_FFPROBE_PATH=_env("HYPERFRAMES_FFPROBE_PATH"),
        HYPERFRAMES_CLI_VERSION=_env("HYPERFRAMES_CLI_VERSION") or "0.8.42",
        HYPERFRAMES_CLI_BIN=_env("HYPERFRAMES_CLI_BIN"),
    )


def _render_composition(
    composition_spec: dict, *, output_path: str, settings: Any
) -> str:
    """默认实现：复用服务端渲染器的 CLI 调用（测试会替换本函数）。"""
    from internal.core.video.composition_builder import build_composition_html
    from internal.core.video.hyperframes_renderer import (
        RenderEnvironmentError,
        render_composition as render_impl,
    )

    missing = [key for key in _REQUIRED_ENV_KEYS if not getattr(settings, key, "")]
    if missing:
        raise RenderEnvironmentError("渲染环境缺少必需配置：" + "、".join(missing))

    work_dir = Path(output_path).parent
    (work_dir / "index.html").write_text(
        build_composition_html(composition_spec), encoding="utf-8"
    )
    render_impl(
        project_dir=work_dir,
        output_path=Path(output_path),
        settings=settings,
        quality="standard",
        fps=int(composition_spec.get("fps") or 30),
    )
    return str(output_path)


def _cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _run_render(payload: dict[str, Any]) -> dict[str, Any]:
    """执行一次渲染，返回 {ok, path, size_bytes, name} 或 {ok: False, error}。"""
    validation_error = _validate_payload(payload)
    if validation_error is not None:
        return validation_error

    settings = _load_settings()
    composition = payload["composition"]
    name = str(payload.get("name") or "渲染成品").strip() or "渲染成品"
    work_dir = tempfile.mkdtemp(prefix="hf-local-render-")
    try:
        output_path = str(Path(work_dir) / "output.mp4")
        produced = _render_composition(
            composition, output_path=output_path, settings=settings
        )
        artifact = Path(produced)
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            _cleanup_dir(work_dir)
            return {"ok": False, "error": "渲染未产出有效文件"}
    except Exception as exc:  # noqa: BLE001 - worker 边界必须转成 JSON 错误
        logger.warning("本机渲染失败: %s", exc, exc_info=True)
        _cleanup_dir(work_dir)
        return {"ok": False, "error": f"本机渲染失败: {exc}"}

    # 成功：**保留 work_dir**——调用方随后经 `/artifact` 取回产物，
    # 取走后由 `_read_artifact` 清理该目录。
    return {
        "ok": True,
        "path": str(artifact),
        "size_bytes": artifact.stat().st_size,
        "name": name,
    }


def _read_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    """读取本机渲染产物（仅限渲染临时目录，防止任意路径读取）。

    安全边界：产物路径必须位于系统临时目录下且前缀为 hf-local-render-，
    否则拒绝——避免该端点被用作任意文件读取。
    """
    raw_path = str(payload.get("path") or "").strip()
    if not raw_path:
        return {"ok": False, "error": "path 不能为空"}
    artifact = Path(raw_path).resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if not str(artifact).startswith(str(tmp_root)) or "hf-local-render-" not in str(artifact):
        return {"ok": False, "error": "产物路径不在允许范围内"}
    if not artifact.is_file():
        return {"ok": False, "error": "产物不存在或已被清理"}
    safe_name = _SAFE_NAME_RE.sub("_", artifact.name) or "render-output.mp4"
    with open(artifact, "rb") as fh:
        content = fh.read()
    # 产物已取走，清理渲染临时目录，避免用户设备上残留
    _cleanup_dir(str(artifact.parent))
    return {
        "ok": True,
        "name": safe_name,
        "size_bytes": len(content),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def do_POST(self):  # noqa: N802
        route = self.path.rstrip("/")
        if route not in {"/render", "/artifact"}:
            self._json_response({"ok": False, "error": "not found"}, status=404)
            return
        if not _authorized(self.headers.get("Authorization", "")):
            self._json_response({"ok": False, "error": "unauthorized"}, status=401)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self._json_response({"ok": False, "error": "invalid json"}, status=400)
            return

        if route == "/artifact":
            self._json_response(_read_artifact(payload))
            return
        self._json_response(_run_render(payload))

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local render worker")
    parser.add_argument("--host", default=_env("RENDER_WORKER_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port", type=int, default=int(_env("RENDER_WORKER_PORT", str(DEFAULT_PORT)))
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if not _env("RENDER_WORKER_TOKEN"):
        logger.error("RENDER_WORKER_TOKEN 未配置，拒绝启动")
        raise SystemExit(1)
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    logger.info("Local render worker listening on %s:%s", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
