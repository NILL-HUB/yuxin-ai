"""百炼（通义万相）AI 视频生成服务：经 `bl video` CLI 出片并存入成品库。

执行链：Celery 任务 → 本服务 → subprocess(`bl video generate --download`) → 成品库。

设计要点：
- **复用百炼 CLI 而非直连 HTTP**：CLI 已封装鉴权、异步任务轮询与文件下载；
  系统侧只需注入 `DASHSCOPE_API_KEY`（统一凭证入口，DB 加密凭证优先、env 兜底）。
- **产物入库走既有的 `store_render_output`**：与渲染/剪辑链路同一条成品库路径，
  对话内成片预览（artifact 回填）因此天然可用。
- **分钟级任务**：`bl` 自身的轮询超时 `--timeout` 与 subprocess 硬超时都留足余量；
  失败不重试（重试会重复提交、重复计费），错误消息面向用户可直接展示。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from injector import inject

logger = logging.getLogger(__name__)

# `bl` 内部轮询总超时（秒）与 subprocess 硬超时：后者须大于前者，留出上传/下载时间。
# 实测（2026-10-06，wan2.7-t2v / 3s / 720P）：峰值排队下生成耗时约 25 分钟，
# 故超时按「小时级」留足余量，避免长排队被误判为失败。
_CLI_TIMEOUT_SEC = 3000
_SUBPROCESS_TIMEOUT_SEC = 3300
# 产物体积下限：小于 1KB 基本可判定为「空壳产物」（与剪辑链路同一判定口径）
_MIN_OUTPUT_BYTES = 1024

# 默认模型：万相 2.7 文生视频（720P 约 0.6 元/秒，性价比档）
_DEFAULT_MODEL = "wan2.7-t2v"


class BailianVideoError(RuntimeError):
    """百炼视频生成失败。消息面向用户可直接展示，不进重试。"""


@inject
@dataclass
class BailianVideoService:
    """百炼视频生成服务（对话内工具/Celery 任务共用）。"""

    def _resolve_api_key(self) -> str:
        """解析百炼 API key（统一凭证入口：DB 加密凭证优先，env 兜底）。"""
        from internal.service.tool_credential_resolver import get_tool_credential

        return get_tool_credential("DASHSCOPE_API_KEY", "BAILIAN_API_KEY")

    @staticmethod
    def _extract_task_id(stdout: str) -> str:
        """从 `bl` 的输出中提取 task_id（用于错误提示与日志定位）；缺失返回空串。"""
        for match in re.finditer(r"\{.*?\}", stdout or "", flags=re.DOTALL):
            try:
                payload = json.loads(match.group(0))
            except (ValueError, TypeError):
                continue
            task_id = str(payload.get("task_id") or "").strip()
            if task_id:
                return task_id
        return ""

    def generate_video(
        self,
        *,
        account,
        prompt: str,
        name: str = "",
        model: str = "",
        duration: int = 0,
        resolution: str = "",
        ratio: str = "",
        image_url: str = "",
    ) -> dict:
        """生成视频并写入成品库，返回 {document_id, knowledge_base_id, name, artifact}。

        参数校验失败抛 `BailianVideoError`（业务失败，调用方不应重试）。
        """
        prompt = str(prompt or "").strip()
        if not prompt:
            raise BailianVideoError("视频描述（prompt）不能为空")

        api_key = self._resolve_api_key()
        if not api_key:
            raise BailianVideoError(
                "未配置百炼凭证（DASHSCOPE_API_KEY），请在管理后台「内置工具-凭证」中配置"
            )

        work_dir = Path(tempfile.mkdtemp(prefix="bailian-video-"))
        output_path = work_dir / "output.mp4"
        cmd = [
            "bl", "video", "generate",
            "--prompt", prompt,
            "--download", str(output_path),
            "--output", "json",
            "--timeout", str(_CLI_TIMEOUT_SEC),
        ]
        if str(model or "").strip():
            cmd += ["--model", str(model).strip()]
        if int(duration or 0) > 0:
            cmd += ["--duration", str(int(duration))]
        if str(resolution or "").strip():
            cmd += ["--resolution", str(resolution).strip().upper()]
        if str(ratio or "").strip():
            cmd += ["--ratio", str(ratio).strip()]
        if str(image_url or "").strip():
            cmd += ["--image", str(image_url).strip()]

        env = {**os.environ, "DASHSCOPE_API_KEY": api_key, "NO_COLOR": "1"}
        logger.info(
            "百炼视频生成开始 model=%s duration=%s resolution=%s",
            model or _DEFAULT_MODEL, duration or "默认", resolution or "默认",
        )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=_SUBPROCESS_TIMEOUT_SEC,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise BailianVideoError(
                "百炼 CLI（bl）不可用：当前环境未安装 bailian-cli，请检查镜像构建"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise BailianVideoError(
                f"视频生成超时（>{_SUBPROCESS_TIMEOUT_SEC // 60} 分钟），请缩短时长或稍后重试"
            ) from exc

        try:
            # bl 退出码 0 不等于产物有效（渲染链路同样教训）：两处都校验。
            if proc.returncode != 0 or not output_path.exists():
                detail = (proc.stderr or proc.stdout or "").strip().splitlines()
                tail = " ".join(detail[-3:])[:300] if detail else ""
                task_id = self._extract_task_id(proc.stdout or "")
                suffix = f"（任务 {task_id} 可稍后重试查询）" if task_id else ""
                raise BailianVideoError(f"视频生成失败：{tail or 'CLI 未产出文件'}{suffix}")
            if output_path.stat().st_size < _MIN_OUTPUT_BYTES:
                raise BailianVideoError("视频生成失败：产物为空文件")

            from app.http.module import injector
            from internal.service.knowledge_base_service import KnowledgeBaseService

            kb_service = injector.get(KnowledgeBaseService)
            document = kb_service.store_render_output(
                account=account,
                video_path=str(output_path),
                name=str(name or "").strip() or "百炼生成视频",
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        result = {
            "document_id": str(document.id),
            "knowledge_base_id": str(document.knowledge_base_id),
            "name": document.name,
        }
        artifact = kb_service.build_output_artifact(document)
        if artifact:
            result["artifact"] = artifact
        return result
