"""渲染编排服务：编（compile）→ 渲（render）→ 库（store）。

把三个纯/半纯部件串起来，并负责工作目录生命周期与账号解析。
渲染产物落成品库后返回 KnowledgeDocument，供上层回链给用户。
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from injector import inject

from internal.core.video.composition_builder import build_composition_html
from internal.core.video.hyperframes_renderer import render_composition as _render
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

logger = logging.getLogger(__name__)


def _load_settings():
    """取渲染所需的运行时配置（Flask config）。

    独立成模块级函数便于测试替换——渲染服务本身不需要 app context 的其他部分。
    """
    from flask import current_app

    return current_app.config


@inject
@dataclass
class RenderService(BaseService):
    """视频渲染编排。

    依赖注入遵循本仓库既有约定：`@inject` + `@dataclass`，`db` 为注入字段
    （参见 `StorageQuotaService`）。不要改成手写 `__init__`——injector 依赖该形态构造。
    """
    db: SQLAlchemy

    # ---- 可替换点：测试 monkeypatch 这两处，隔离真实编译/渲染 ----
    def _build_composition(self, spec: dict) -> str:
        return build_composition_html(spec)

    def _render(self, *, project_dir, output_path, settings, quality, fps):
        return _render(
            project_dir=Path(project_dir),
            output_path=Path(output_path),
            settings=settings,
            quality=quality,
            fps=fps,
        )

    def render_composition(
        self,
        *,
        composition_spec: dict,
        work_dir=None,
        quality: str = "standard",
        fps: int = 30,
    ) -> str:
        """编译并渲染，返回产物 MP4 的绝对路径字符串。

        work_dir 缺省时用临时目录，调用方负责清理（见 _cleanup）。
        """
        owns_dir = work_dir is None
        directory = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="hf-render-"))
        directory.mkdir(parents=True, exist_ok=True)

        (directory / "index.html").write_text(
            self._build_composition(composition_spec), encoding="utf-8"
        )
        output_path = directory / "output.mp4"
        try:
            self._render(
                project_dir=directory,
                output_path=output_path,
                settings=_load_settings(),
                quality=quality,
                fps=fps,
            )
        except Exception:
            if owns_dir:
                shutil.rmtree(directory, ignore_errors=True)
            raise
        return str(output_path)

    def render_to_render_output_base(
        self, *, composition_spec: dict, account_id, name: str = "", quality: str = "standard"
    ) -> dict:
        """渲染并写入成品库，返回可回给用户的结果。"""
        from internal.service.account_service import AccountService
        from internal.service.knowledge_base_service import KnowledgeBaseService

        account = self._get_service(AccountService).get_account(UUID(str(account_id)))
        if account is None:
            raise ValueError(f"账号不存在：{account_id}")

        work_dir = Path(tempfile.mkdtemp(prefix="hf-job-"))
        try:
            output_path = self.render_composition(
                composition_spec=composition_spec,
                work_dir=work_dir,
                quality=quality,
            )
            document = self._get_service(KnowledgeBaseService).store_render_output(
                account=account, video_path=output_path, name=name or "渲染成品"
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        return {
            "document_id": str(document.id),
            "knowledge_base_id": str(document.knowledge_base_id),
            "name": document.name,
        }

    def _get_service(self, cls):
        from app.http.module import injector

        return injector.get(cls)
