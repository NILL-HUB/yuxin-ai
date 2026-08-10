#!/usr/bin/env python3
"""图片识别脚本：调用智谱免费视觉模型，三模型依次降级。

用法：
    python vision.py --file /path/to/image.jpg --question "请描述图片内容"
    python vision.py --image "data:image/jpeg;base64,..." --question "图中文字是什么"
    python vision.py --url https://example.com/img.jpg --question "这张图是什么"

降级链：GLM-4.6V-Flash -> GLM-4.1V-Thinking-Flash -> GLM-4V-Flash
API Key：读取同目录 .env 中的 ZHIPU_API_KEY，或环境变量注入。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path

import requests
from openai import OpenAI

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

# 降级链：按优先级排列，依次尝试
DEFAULT_MODEL_CHAIN = [
    "glm-4.6v-flash",
    "glm-4.1v-thinking-flash",
    "glm-4v-flash",
]

# 图片体积上限（超过则压缩），单位字节
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def load_env_file(env_path: Path) -> None:
    """从 .env 文件加载环境变量（不覆盖已存在的环境变量）。"""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# 图片加载与压缩
# ---------------------------------------------------------------------------


def _image_to_data_url(image_bytes: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"


def _compress_image(image_bytes: bytes, mime: str) -> bytes:
    """图片超限时按 JPEG 质量压缩，最多压缩三轮。"""
    try:
        from PIL import Image
    except ImportError:
        return image_bytes  # 未安装 Pillow 则跳过压缩

    quality = 85
    current = image_bytes
    for _ in range(3):
        if len(current) <= MAX_IMAGE_BYTES:
            return current
        img = Image.open(io.BytesIO(current))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        current = buf.getvalue()
        mime = "image/jpeg"
        quality = max(quality - 25, 30)
    return current


def load_image(args: argparse.Namespace) -> str:
    """加载图片为 data URL 字符串。"""
    if args.image:
        return args.image

    if args.file:
        path = Path(args.file)
        if not path.exists():
            raise SystemExit(f"文件不存在: {path}")
        suffix = path.suffix.lower()
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }.get(suffix, "image/jpeg")
        raw = path.read_bytes()
        if args.max_bytes and len(raw) > args.max_bytes:
            raw = _compress_image(raw, mime)
            mime = "image/jpeg"
        return _image_to_data_url(raw, mime)

    if args.url:
        resp = requests.get(args.url, timeout=30)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        return _image_to_data_url(resp.content, content_type)

    raise SystemExit("必须提供 --image / --file / --url 之一")


# ---------------------------------------------------------------------------
# 模型调用
# ---------------------------------------------------------------------------


def call_vision(client: OpenAI, model: str, data_url: str, question: str, timeout: int) -> str:
    """调用单个视觉模型，返回文字描述。"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": question},
                ],
            }
        ],
        timeout=timeout,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError(f"{model} 返回空内容")
    return content.strip()


def recognize(args: argparse.Namespace) -> dict:
    """按降级链依次调用模型，返回首个成功结果。"""
    api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not api_key:
        return {"error": "未配置 ZHIPU_API_KEY，请在 .env 中填写"}

    base_url = args.base_url or DEFAULT_BASE_URL
    chain = args.model_chain or DEFAULT_MODEL_CHAIN
    data_url = load_image(args)

    client = OpenAI(api_key=api_key, base_url=base_url)

    errors: list[dict] = []
    for model in chain:
        try:
            description = call_vision(client, model, data_url, args.question, args.timeout)
            return {"provider": model, "description": description}
        except Exception as exc:
            errors.append({"provider": model, "error": str(exc)})
            print(f"[image-vision] {model} 调用失败，切换下一个: {exc}", file=sys.stderr)

    return {"error": "所有模型均失败", "details": errors}


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="图片识别（智谱视觉模型，三模型降级）")
    parser.add_argument("--file", help="本地图片路径")
    parser.add_argument("--image", help="data URL 格式的图片 base64")
    parser.add_argument("--url", help="图片 URL")
    parser.add_argument("--question", default="请详细描述这张图片的内容", help="对图片的提问")
    parser.add_argument("--max-bytes", type=int, default=MAX_IMAGE_BYTES, help="图片压缩阈值（字节）")
    parser.add_argument("--timeout", type=int, default=60, help="单次请求超时（秒）")
    parser.add_argument("--base-url", default="", help="API 地址（默认智谱官方）")
    parser.add_argument(
        "--model-chain",
        nargs="+",
        default=[],
        help="模型降级链，如 --model-chain glm-4.6v-flash glm-4v-flash",
    )
    return parser.parse_args()


def main() -> int:
    load_env_file(Path(__file__).resolve().parent.parent / ".env")
    args = parse_args()
    result = recognize(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if "provider" in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
