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
    """取渲染所需的运行时配置，返回**支持属性访问**的配置视图。

    独立成模块级函数便于测试替换。

    ⚠️ 两个坑，缺一不可：

    1. 必须用 ``internal.context.current_app``（本仓库替代 flask.current_app 的运行时
       容器代理），**不能**用 ``flask.current_app``：渲染任务在 Celery worker 中执行，
       那里没有 Flask app context 栈（``_ensure_runtime`` 初始化的是运行时容器，不是
       Flask 应用），用 flask.current_app 会直接抛 ``Working outside of application
       context``。
    2. 必须包成对象而非直接用 ``current_app.config``：容器 config 是普通 dict，而
       ``hyperframes_renderer`` 全部用 ``getattr(settings, "HYPERFRAMES_*")`` **属性**
       读取，对 dict 做 getattr 取不到值会静默落空（Flask 的 config 是带
       ``__getattr__`` 的子类，换容器后该语义消失）。故用 SimpleNamespace 还原属性语义。
    """
    from types import SimpleNamespace

    from internal.context import current_app

    return SimpleNamespace(**current_app.config)


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
            kb_service = self._get_service(KnowledgeBaseService)
            document = kb_service.store_render_output(
                account=account, video_path=output_path, name=name or "渲染成品"
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        result = {
            "document_id": str(document.id),
            "knowledge_base_id": str(document.knowledge_base_id),
            "name": document.name,
        }
        # 可播放地址：对话内成片预览的载荷来源。
        # 必须在 rmtree 之后调用——它只依赖 DB 记录（upload_file.key），不碰工作目录。
        artifact = kb_service.build_output_artifact(document)
        if artifact:
            result["artifact"] = artifact
        return result

    def _get_service(self, cls):
        from app.http.module import injector

        return injector.get(cls)
