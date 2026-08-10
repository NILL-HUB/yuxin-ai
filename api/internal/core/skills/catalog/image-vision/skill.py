"""图片识别技能：调用智谱免费视觉模型，三模型依次降级。

注意：此文件运行在平台 SCF 沙箱中，仅允许标准库（含 urllib），
不能使用 requests / openai 等第三方库。

入口函数：recognize_image(input: dict) -> dict
    input:
        image: 图片 data URL（data:image/jpeg;base64,...）或 http(s) 直链
        question: 对图片的提问（可选）
    output:
        {"provider": "...", "description": "..."}
        或 {"error": "..."}

API Key 从环境变量 ZHIPU_API_KEY 读取（由平台侧注入），
也可通过 input["api_key"] 显式传入。
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

# 降级链：按优先级排列
MODEL_CHAIN = [
    "glm-4.6v-flash",
    "glm-4.1v-thinking-flash",
    "glm-4v-flash",
]

BASE_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

TIMEOUT_SECONDS = 60

_HTTP_ERROR_HINTS = {
    401: "API Key 无效或已过期",
    429: "请求过于频繁或额度用尽",
    500: "模型服务端异常",
    503: "模型服务不可用",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _post_chat_completion(api_key: str, model: str, data_url: str, question: str) -> str:
    """调用单个视觉模型，返回文字描述。"""
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": question},
                ],
            }
        ],
    }
    request = urllib.request.Request(
        BASE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        hint = _HTTP_ERROR_HINTS.get(exc.code, f"HTTP {exc.code}")
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = ""
        raise RuntimeError(f"{hint}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络请求失败: {exc.reason}") from exc

    choices = payload.get("choices") or []
    if not choices:
        error_info = payload.get("error") or {}
        raise RuntimeError(f"接口返回异常: {json.dumps(error_info, ensure_ascii=False)}")
    content = choices[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError(f"{model} 返回空内容")
    return str(content).strip()


def recognize_image(input_data: dict[str, Any]) -> dict[str, Any]:
    """图片识别入口函数：按降级链依次调用，返回首个成功结果。"""
    if not isinstance(input_data, dict):
        input_data = {}

    image = _normalize_text(input_data.get("image"))
    question = _normalize_text(input_data.get("question")) or "请详细描述这张图片的内容"
    api_key = _normalize_text(input_data.get("api_key")) or os.environ.get("ZHIPU_API_KEY", "")

    if not image:
        return {"error": "缺少图片参数 image（data URL 或 http(s) 直链）"}
    if not api_key:
        return {"error": "未配置 ZHIPU_API_KEY，请在平台技能配置中注入"}

    errors: list[dict[str, str]] = []
    for model in MODEL_CHAIN:
        try:
            description = _post_chat_completion(api_key, model, image, question)
            return {"provider": model, "description": description}
        except Exception as exc:
            errors.append({"provider": model, "error": str(exc)})

    return {"error": "所有模型均失败", "details": errors}
