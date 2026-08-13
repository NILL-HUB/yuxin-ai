"""桌面端唤醒词 worker。

在桌面端本地监听麦克风，检测到唤醒词后通知本机事件端点（Electron 壳或
Assistant bridge）。Web 端无常驻麦克风，该能力只在桌面端启用。

依赖（可选）：pip install sounddevice numpy openwakeword
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import urllib.request
from typing import Any


logger = logging.getLogger("wake_word_worker")

DEFAULT_KEYWORD = "hey yuxin"
CHUNK_SECONDS = 0.5
SAMPLE_RATE = 16000


def _env(key: str, default: str = "") -> str:
    return str(os.environ.get(key, default) or "").strip()


def _resolve_config(args: argparse.Namespace) -> dict[str, Any]:
    """从命令行参数与环境变量解析唤醒词配置。"""
    keyword = str(args.keyword or _env("WAKE_WORD_KEYWORD", DEFAULT_KEYWORD)).strip()
    endpoint = str(args.endpoint or _env("WAKE_WORD_ENDPOINT", "")).strip()
    token = str(args.token or _env("WAKE_WORD_TOKEN", "")).strip()
    engine = str(args.engine or _env("WAKE_WORD_ENGINE", "openwakeword")).strip().lower()
    return {
        "keyword": keyword,
        "endpoint": endpoint,
        "token": token,
        "engine": engine,
    }


def _dependency_error() -> str:
    """返回缺失依赖的安装提示；全部可用时返回空字符串。"""
    missing: list[str] = []
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        missing.append("sounddevice")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    if missing:
        return "唤醒词 worker 缺少依赖: " + ", ".join(missing) + "。请安装 sounddevice numpy openwakeword"
    try:
        import openwakeword  # noqa: F401
    except ImportError:
        return "唤醒词 worker 缺少 openwakeword，请安装 openwakeword"
    return ""


def _notify_wake(config: dict[str, Any]) -> bool:
    """向本机事件端点通知唤醒事件。"""
    endpoint = config.get("endpoint") or ""
    if not endpoint:
        logger.info("检测到唤醒词：%s（未配置 WAKE_WORD_ENDPOINT，仅记录日志）", config.get("keyword"))
        return True
    payload = json.dumps(
        {"event": "wake", "keyword": config.get("keyword"), "engine": config.get("engine")},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if config.get("token"):
        headers["Authorization"] = f"Bearer {config['token']}"
    request = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10):
            return True
    except Exception as exc:
        logger.warning("唤醒事件通知失败: %s", exc)
        return False


def _listen(config: dict[str, Any]) -> None:
    """监听麦克风并检测唤醒词（阻塞）。"""
    import numpy as np
    import sounddevice as sd
    from openwakeword.model import Model

    model = Model()
    keyword = str(config.get("keyword") or DEFAULT_KEYWORD).lower()
    logger.info("开始监听唤醒词：%s（engine=%s）", keyword, config.get("engine"))

    def callback(indata, frames, time_info, status):
        audio = np.frombuffer(indata, dtype=np.int16).reshape(-1, 1)
        prediction = model.predict(audio)
        for key, score in prediction.items():
            if score > 0.5 and keyword.replace(" ", "") in key.replace("_", "").replace(" ", ""):
                _notify_wake(config)
                break

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=int(SAMPLE_RATE * CHUNK_SECONDS),
        callback=callback,
    ):
        while True:
            try:
                import time

                time.sleep(1)
            except KeyboardInterrupt:
                logger.info("唤醒词监听已停止")
                return


def main() -> None:
    parser = argparse.ArgumentParser(description="Desktop wake word worker")
    parser.add_argument("--keyword", default="")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--engine", default="")
    parser.add_argument("--check", action="store_true", help="检查依赖并退出")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    config = _resolve_config(args)
    error = _dependency_error()
    if error:
        logger.error(error)
        if args.check:
            return
        raise SystemExit(1)
    if args.check:
        logger.info("唤醒词依赖可用：%s", config.get("engine"))
        return
    if not config.get("endpoint"):
        logger.warning("未配置 WAKE_WORD_ENDPOINT，唤醒事件只写日志")
    _listen(config)


if __name__ == "__main__":
    main()
