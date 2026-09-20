"""视频轻量剪辑服务（trim / concat / subtitle）。

职责边界：
- 本模块负责「下载素材 → 构造命令 → 执行 ffmpeg → 校验产物」；
- 命令构造是纯函数，见 `internal.core.video.ffmpeg_edit`；
- 分钟级/大批量场景由调用方（Celery 任务）承载，本模块自身是同步的。

为什么不做复杂重试/闸门：trim（-c copy）与 concat（-c copy）本质是封装操作（秒级），
subtitle 的重编码也仅对短视频耗时明显；故由 Celery 的 max_retries 兜底即可，
无需复制渲染链路的并发闸门（那是分钟级任务的成本，此处属过度设计）。
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from injector import inject

from internal.core.video.ffmpeg_edit import (
    build_concat_command,
    build_subtitle_command,
    build_trim_command,
    render_srt,
)

logger = logging.getLogger(__name__)

# 单条 ffmpeg 命令超时：剪辑是 IO 密集，但重编码可能较慢，留足余量
_EDIT_TIMEOUT_SEC = 600
# 产物体积下限：小于 1KB 基本可判定为「空壳产物」
_MIN_OUTPUT_BYTES = 1024


class VideoEditError(RuntimeError):
    """视频编辑失败。消息面向用户可直接展示，不进重试。"""


@inject
@dataclass
class VideoEditService:
    """视频剪辑服务。依赖注入保持与既有 service 一致的写型注解。"""

    def _resolve_exe(self) -> str:
        """ffmpeg 可执行文件路径（系统优先，imageio 兜底）。"""
        from internal.core.vision.vision_invoke import _resolve_ffmpeg_exe

        return _resolve_ffmpeg_exe()

    def _probe_duration(self, path: str | Path) -> float:
        """探测时长（秒）；失败返回 0.0（调用方据此跳过边界校验）。"""
        from internal.core.vision.vision_invoke import probe_duration_sec

        return probe_duration_sec(str(path))

    def _run_ffmpeg(self, cmd: list[str], timeout: int = _EDIT_TIMEOUT_SEC) -> None:
        """执行 ffmpeg；失败抛 CalledProcessError（由调用方包装为可读错误）。"""
        subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)

    def _ensure_source(self, path: str | Path) -> Path:
        source = Path(path)
        if not source.is_file():
            raise VideoEditError(f"源视频不存在：{source}")
        return source

    def _ensure_output(self, output: str | Path) -> Path:
        out = Path(output)
        if not out.is_file() or out.stat().st_size < _MIN_OUTPUT_BYTES:
            # ffmpeg 退出码 0 不等于产物有效（既有渲染链路同样教训）
            raise VideoEditError("剪辑未产出有效文件")
        return out

    def _materialize_output(self, output: str | Path) -> Path:
        """产物后处理钩子（默认恒等）。

        单独抽成方法便于测试替换；执行 ffmpeg 的路径本身不在此处，
        故默认实现只回传路径，产物有效性统一由 `_ensure_output` 校验。
        """
        return Path(output)

    def trim(
        self,
        *,
        source_path: str | Path,
        output_path: str | Path,
        start_sec: float,
        end_sec: float | None,
        reencode: bool = False,
    ) -> Path:
        """按时间区间裁剪。默认流拷贝（无损、秒级）。"""
        source = self._ensure_source(source_path)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # 边界校验：仅在能探到时长时启用（探测失败不阻断，交由 ffmpeg 自身报错）
        duration = self._probe_duration(source)
        if duration > 0:
            if float(start_sec) >= duration:
                raise VideoEditError(
                    f"开始时间 {float(start_sec):.2f}s 超出视频时长 {duration:.2f}s"
                )
            if end_sec is not None and float(end_sec) > duration + 0.5:
                raise VideoEditError(
                    f"结束时间 {float(end_sec):.2f}s 超出视频时长 {duration:.2f}s"
                )

        try:
            cmd = build_trim_command(
                self._resolve_exe(),
                source=str(source), output=str(out),
                start_sec=start_sec, end_sec=end_sec, reencode=reencode,
            )
            self._run_ffmpeg(cmd, _EDIT_TIMEOUT_SEC)
        except subprocess.CalledProcessError as exc:
            logger.warning("裁剪失败 source=%s", source, exc_info=True)
            detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
            raise VideoEditError(f"裁剪失败：{detail or exc}") from exc
        except ValueError as exc:
            raise VideoEditError(str(exc)) from exc
        return self._ensure_output(self._materialize_output(out))

    def concat(self, *, source_paths: list[str | Path], output_path: str | Path) -> Path:
        """按传入顺序拼接多段视频（concat demuxer + 流拷贝）。"""
        # 先校验段数（纯参数错误，无需触碰文件系统），再逐个校验素材存在
        if len(list(source_paths or [])) < 2:
            raise VideoEditError("拼接至少需要两段视频")
        paths = [self._ensure_source(p) for p in (source_paths or [])]

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="video-concat-") as work:
            list_file = Path(work) / "list.txt"
            # concat demuxer 清单：绝对路径 + 单引号（-safe 0 允许绝对路径）
            list_file.write_text(
                "".join(f"file '{p.resolve().as_posix()}'\n" for p in paths),
                encoding="utf-8",
            )
            try:
                cmd = build_concat_command(
                    self._resolve_exe(), list_file=str(list_file), output=str(out)
                )
                self._run_ffmpeg(cmd, _EDIT_TIMEOUT_SEC)
            except subprocess.CalledProcessError as exc:
                logger.warning("拼接失败 sources=%s", paths, exc_info=True)
                detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
                raise VideoEditError(f"拼接失败：{detail or exc}") from exc
        return self._ensure_output(out)

    def _assert_fonts_available(self) -> None:
        """校验容器内有可用字体（字幕烧录的**前置硬条件**）。

        为什么必须显式校验：libass 找不到字体时**不会报错退出**，
        而是静默跳过字幕渲染——实测产物与源帧逐像素完全相同、退出码仍是 0。
        这种「假成功」比失败更危险（用户以为加了字幕，实际没有）。
        故在烧录前用 fc-list 探一次，缺失时给可读错误。
        """
        import shutil

        fc_list = shutil.which("fc-list")
        if not fc_list:
            raise VideoEditError(
                "容器缺少 fontconfig（fc-list 不可用），无法烧录字幕。"
                "请在镜像中安装 fontconfig + 字体（见 api/Dockerfile 的说明）。"
            )
        try:
            result = subprocess.run(
                [fc_list], capture_output=True, timeout=30, check=False
            )
        except Exception as exc:  # noqa: BLE001
            raise VideoEditError(f"字体探测失败：{exc}") from exc
        if not (result.stdout or b"").strip():
            raise VideoEditError(
                "容器内没有任何可用字体，字幕无法烧录（libass 会静默跳过）。"
                "请安装字体包（如 fonts-dejavu-core）后重试。"
            )

    def burn_subtitles(
        self,
        *,
        source_path: str | Path,
        output_path: str | Path,
        cues: list[dict[str, Any]],
    ) -> Path:
        """把字幕烧录进画面（subtitles 滤镜，需重编码）。"""
        source = self._ensure_source(source_path)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            srt_text = render_srt(cues)
        except ValueError as exc:
            # 统一成 VideoEditError，工具层只需处理一种异常
            raise VideoEditError(str(exc)) from exc

        # 前置校验：缺字体时 libass 会静默不渲染（退出码仍为 0），必须先拦下
        self._assert_fonts_available()

        with tempfile.TemporaryDirectory(prefix="video-subtitle-") as work:
            srt_path = Path(work) / "subtitle.srt"
            # 必须 UTF-8 无 BOM：带 BOM 时 libass 会把首行时间码读坏
            srt_path.write_text(srt_text, encoding="utf-8")
            try:
                cmd = build_subtitle_command(
                    self._resolve_exe(),
                    source=str(source), output=str(out), srt_path=str(srt_path),
                )
                self._run_ffmpeg(cmd, _EDIT_TIMEOUT_SEC)
            except subprocess.CalledProcessError as exc:
                logger.warning("字幕烧录失败 source=%s", source, exc_info=True)
                detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
                raise VideoEditError(f"字幕烧录失败：{detail or exc}") from exc
        return self._ensure_output(out)

    # ── 编排层：document → 下载 → 剪辑 → 成品库 ───────────────────────────

    def _download_source(self, key: str, dest: str) -> None:
        """从对象存储下载素材到本地（独立方法便于测试替换）。"""
        from app.http.module import injector
        from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

        injector.get(RuntimeStorageProxy).download_file(key, dest)

    def _load_source_documents(
        self, *, account: Any, knowledge_base_id: str, document_ids: list[str]
    ) -> list[Any]:
        """按 id 批量取素材文档（含 upload_file），保持传入顺序。

        归属校验复用 `get_document_detail`（内含知识库归属 + 文档归属双重校验），
        避免手写查询绕过权限。
        """
        from app.http.module import injector
        from internal.service.knowledge_base_service import KnowledgeBaseService

        service = injector.get(KnowledgeBaseService)
        docs = []
        for doc_id in document_ids:
            doc = service.get_document_detail(knowledge_base_id, doc_id, account)
            # get_document_detail 返回的 document 不带 upload_file 关系，按需补取
            upload_file = getattr(doc, "upload_file", None)
            if upload_file is None and getattr(doc, "upload_file_id", None):
                from internal.model.upload_file import UploadFile

                upload_file = service.db.session.query(UploadFile).filter(
                    UploadFile.id == doc.upload_file_id
                ).one_or_none()
                setattr(doc, "upload_file", upload_file)
            docs.append(doc)
        return docs

    def _store_output(self, *, account: Any, video_path: Path, name: str) -> dict:
        """把剪辑产物写入成品库（复用 KB-P3.7 的 store_render_output）。

        返回 `document_id` 与可播放的 `artifact`——后者是「对话内成片预览」
        的载荷来源（缺它则前端只能显示一条无链接的提示）。
        """
        from app.http.module import injector
        from internal.service.knowledge_base_service import KnowledgeBaseService

        service = injector.get(KnowledgeBaseService)
        document = service.store_render_output(
            account=account, video_path=video_path, name=name
        )
        result = {"document_id": str(document.id)}
        artifact = service.build_output_artifact(document)
        if artifact:
            result["artifact"] = artifact
        return result

    def _prepare_source_file(self, doc: Any, work_dir: Path) -> Path:
        """把文档对应素材下载到工作目录，返回本地路径。"""
        upload_file = getattr(doc, "upload_file", None)
        key = getattr(upload_file, "key", "") if upload_file else ""
        if not key:
            raise VideoEditError(f"素材不存在或缺少存储对象：document_id={doc.id}")
        dest = work_dir / f"{doc.id}_{Path(key).name or 'source.mp4'}"
        try:
            self._download_source(key, str(dest))
        except Exception as exc:  # noqa: BLE001 - 统一成可读错误
            logger.warning("下载素材失败 key=%s", key, exc_info=True)
            raise VideoEditError(f"下载素材失败：{exc}") from exc
        return dest

    def trim_document(
        self, *, account: Any, knowledge_base_id: str, document_id: str,
        start_sec: float, end_sec: float | None, name: str, reencode: bool = False,
        segment_index: int | None = None,
    ) -> dict:
        """裁剪单个库内视频并存入成品库。

        `segment_index`（1-based）可选：指定时按该素材的 L1 时间线段落
        （`source=vision_timeline`）取第 N 段区间裁剪，忽略手填秒数——这是
        KB-P4.5 衔接点（段落即剪辑挂载点）；缺省则用 `start_sec/end_sec`。
        """
        docs = self._load_source_documents(
            account=account, knowledge_base_id=knowledge_base_id, document_ids=[document_id]
        )
        if not docs:
            raise VideoEditError(f"素材不存在：document_id={document_id}")
        doc = docs[0]

        start, end = self._resolve_trim_range(
            document=doc, segment_index=segment_index,
            start_sec=start_sec, end_sec=end_sec,
        )

        with tempfile.TemporaryDirectory(prefix="video-edit-") as work:
            work_dir = Path(work)
            source = self._prepare_source_file(doc, work_dir)
            output = work_dir / "output.mp4"
            self.trim(
                source_path=source, output_path=output,
                start_sec=start, end_sec=end, reencode=reencode,
            )
            return self._store_output(account=account, video_path=output, name=name)

    def concat_documents(
        self, *, account: Any, knowledge_base_id: str, document_ids: list[str],
        name: str,
    ) -> dict:
        """按给定顺序拼接多段库内视频并存入成品库。"""
        docs = self._load_source_documents(
            account=account, knowledge_base_id=knowledge_base_id, document_ids=document_ids
        )
        if len(docs) != len(document_ids):
            missing = set(document_ids) - {str(d.id) for d in docs}
            raise VideoEditError(f"素材不存在：document_id={sorted(missing)}")

        with tempfile.TemporaryDirectory(prefix="video-edit-") as work:
            work_dir = Path(work)
            sources = [self._prepare_source_file(doc, work_dir) for doc in docs]
            output = work_dir / "output.mp4"
            self.concat(source_paths=sources, output_path=output)
            return self._store_output(account=account, video_path=output, name=name)

    def reassemble_document(
        self, *, account: Any, knowledge_base_id: str, document_id: str,
        clips: list[dict[str, Any]], name: str,
    ) -> dict:
        """按时间线编排重建视频并存入成品库（成片编辑器后端）。

        `clips` 是有序编排片段，每项 `{"document_id": str, "segment_index": int}`：
        - `segment_index` > 0：取该素材第 N 个时间线段落（1-based，越界抛错，
          复用 `_resolve_trim_range` 的既有校验与日志）；
        - `segment_index` 为 0 / 缺省：取该素材完整视频（首尾全量）。
        同一文档可多次引用（重排/复用段落）；替换段落则引用其他素材——
        归属校验统一走 `_load_source_documents`（复用 get_document_detail 双重校验）。

        执行：下载涉及的素材 → 逐项本地 trim（流拷贝秒级）→ concat（仅 1 项
        跳过）→ 单次 `_store_output`。中间产物只存在于工作目录，不污染成品库。
        """
        if not clips:
            raise VideoEditError("编排至少需要一个片段")

        normalized: list[dict[str, Any]] = []
        for clip in clips:
            clip_doc_id = str((clip or {}).get("document_id") or "").strip()
            if not clip_doc_id:
                raise VideoEditError("编排片段缺少 document_id")
            try:
                raw_index = (clip or {}).get("segment_index") or 0
                if isinstance(raw_index, float) and not raw_index.is_integer():
                    raise VideoEditError("编排片段的段落序号必须是整数（0 表示整段）")
                seg_index = int(raw_index)
            except (TypeError, ValueError):
                raise VideoEditError("编排片段的段落序号必须是整数（0 表示整段）")
            if seg_index < 0:
                raise VideoEditError("编排片段的段落序号不能为负")
            normalized.append({"document_id": clip_doc_id, "segment_index": seg_index})

        # 去重加载涉及的素材（保持首见顺序），并确认主文档确实存在
        unique_ids: list[str] = []
        for clip in normalized:
            if clip["document_id"] not in unique_ids:
                unique_ids.append(clip["document_id"])
        docs = self._load_source_documents(
            account=account, knowledge_base_id=knowledge_base_id,
            document_ids=unique_ids,
        )
        docs_by_id = {str(doc.id): doc for doc in docs}
        if str(document_id) not in docs_by_id:
            raise VideoEditError(f"素材不存在：document_id={document_id}")

        with tempfile.TemporaryDirectory(prefix="video-reassemble-") as work:
            work_dir = Path(work)
            pieces: list[Path] = []
            for index, clip in enumerate(normalized, start=1):
                doc = docs_by_id.get(clip["document_id"])
                if doc is None:
                    raise VideoEditError(f"素材不存在：document_id={clip['document_id']}")
                start, end = self._resolve_trim_range(
                    document=doc, segment_index=clip["segment_index"] or None,
                    start_sec=0.0, end_sec=None,
                )
                source = self._prepare_source_file(doc, work_dir)
                piece = work_dir / f"piece_{index}.mp4"
                self.trim(
                    source_path=source, output_path=piece,
                    start_sec=start, end_sec=end,
                )
                pieces.append(piece)

            if len(pieces) == 1:
                output = pieces[0]
            else:
                output = work_dir / "output.mp4"
                self.concat(source_paths=pieces, output_path=output)
            return self._store_output(account=account, video_path=output, name=name)

    def subtitle_document(
        self, *, account: Any, knowledge_base_id: str, document_id: str,
        cues: list[dict[str, Any]] | None, name: str,
    ) -> dict:
        """给库内视频烧录字幕并存入成品库。

        `cues` 缺省（None/空）时**自动生成时间轴**：优先复用素材入库时留存的
        ASR 时间轴，缺失才重跑一次 ASR（见 `_resolve_cues`）。
        """
        docs = self._load_source_documents(
            account=account, knowledge_base_id=knowledge_base_id, document_ids=[document_id]
        )
        if not docs:
            raise VideoEditError(f"素材不存在：document_id={document_id}")

        with tempfile.TemporaryDirectory(prefix="video-edit-") as work:
            work_dir = Path(work)
            source = self._prepare_source_file(docs[0], work_dir)
            output = work_dir / "output.mp4"
            resolved = self._resolve_cues(
                document=docs[0], source_path=source, cues=cues,
            )
            self.burn_subtitles(source_path=source, output_path=output, cues=resolved)
            return self._store_output(account=account, video_path=output, name=name)

    # ── 自动字幕：时间轴解析 ─────────────────────────────────────────────

    def _load_document_segments(self, document_id: Any) -> list[Any]:
        """取出该素材的全部片段（独立方法便于测试替换）。"""
        from app.http.module import injector
        from internal.model import KnowledgeSegment
        from internal.service.knowledge_base_service import KnowledgeBaseService

        session = injector.get(KnowledgeBaseService).db.session
        return session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document_id,
        ).all()

    def _load_stored_cues(self, document: Any) -> list[dict[str, Any]]:
        """读取 L1 解析时留存的 ASR 时间轴（`metadata.transcript_segments`）。

        优先复用已落库的时间轴：素材入库时已跑过一次 ASR，重跑既慢、又可能
        得到不一致的分段，还会多消耗一次 ASR 配额。
        """
        document_id = getattr(document, "id", None)
        if document_id is None:
            return []

        cues: list[dict[str, Any]] = []
        for row in self._load_document_segments(document_id):
            metadata = getattr(row, "metadata_", None) or {}
            raw = metadata.get("transcript_segments")
            if not isinstance(raw, list):
                continue
            cues.extend(cue for cue in raw if isinstance(cue, dict))
        # 多片段合并后必须按时间排序：SRT 时间码乱序会让部分播放器错位
        return sorted(cues, key=lambda cue: float(cue.get("start") or 0.0))

    def _transcribe_source(self, source_path: str | Path) -> list[dict[str, Any]]:
        """对本地视频重跑 ASR 得到时间轴（独立方法便于测试替换）。

        这是「素材入库时未留存时间轴」时的兜底路径：抽取音轨 → 带时间轴 ASR。
        音轨落在临时目录内，随上下文退出整体回收。
        """
        from io import BytesIO

        from werkzeug.datastructures import FileStorage

        from app.http.module import injector
        from internal.core.vision.vision_invoke import extract_video_audio
        from internal.service.audio_service import AudioService

        with tempfile.TemporaryDirectory(prefix="video-subtitle-asr-") as work:
            audio_path = os.path.join(work, f"{uuid4().hex}.wav")
            extract_video_audio(str(source_path), audio_path)
            with open(audio_path, "rb") as fh:
                content = fh.read()

        file_storage = FileStorage(
            stream=BytesIO(content),
            filename=os.path.basename(audio_path),
            content_type="audio/wav",
        )
        _, cues = injector.get(AudioService).audio_to_text_with_segments(file_storage)
        return [cue for cue in (cues or []) if isinstance(cue, dict)]

    def _load_timeline_segments(self, document: Any) -> list[dict[str, Any]]:
        """收集该素材的 L1 时间线段落（`metadata.source=vision_timeline`）。

        KB-P4.5 起 L1 视频解析把「批次化时间线叙述」段落写入
        `KnowledgeSegment.metadata`，字段含 `start_sec / end_sec /
        anchor_type / anchor_text / speech_text`。这些段落即 KB-P4 剪辑
        的定位挂载点——返回按 `start_sec` 升序的时间线段落清单，供选段。
        """
        document_id = getattr(document, "id", None)
        if document_id is None:
            return []

        timeline: list[dict[str, Any]] = []
        for row in self._load_document_segments(document_id):
            metadata = getattr(row, "metadata_", None) or {}
            if metadata.get("source") != "vision_timeline":
                continue
            start = metadata.get("start_sec")
            end = metadata.get("end_sec")
            if start is None or end is None:
                continue
            timeline.append({
                "start_sec": float(start),
                "end_sec": float(end),
                "anchor_type": metadata.get("anchor_type", ""),
                "anchor_text": metadata.get("anchor_text", ""),
                "speech_text": metadata.get("speech_text", ""),
            })
        # 段落必须按时间升序；剪第 N 段依此序号稳定定位
        return sorted(timeline, key=lambda seg: float(seg["start_sec"] or 0.0))

    def _resolve_trim_range(
        self, *, document: Any, segment_index: int | None,
        start_sec: float | None, end_sec: float | None,
    ) -> tuple[float, float | None]:
        """确定裁剪区间：按时间线段落选段优先，否则用调用方手填秒数。

        `segment_index` 为 1-based（用户说「裁第 2 段」对应 2）。越界/无段落
        时报可读错误，不静默截错段；未提供 `segment_index` 时维持既有
        手填秒数语义（`_load_document_segments` 零成本不触碰）。
        """
        if segment_index is None:
            return float(start_sec or 0.0), None if end_sec is None else float(end_sec)

        timeline = self._load_timeline_segments(document)
        if segment_index < 1 or segment_index > len(timeline):
            raise VideoEditError(
                f"时间线段落序号 {segment_index} 越界：该素材共有 {len(timeline)} 段。"
                "请提供有效序号，或用 start_sec/end_sec 直接指定秒数。"
            )
        target = timeline[segment_index - 1]
        logger.info(
            "按时间线段落选段 document_id=%s segment_index=%s (%.2f~%.2f, %s)",
            getattr(document, "id", None), segment_index,
            target["start_sec"], target["end_sec"], target.get("anchor_text", ""),
        )
        return float(target["start_sec"]), float(target["end_sec"])

    def _resolve_cues(
        self, *, document: Any, source_path: str | Path,
        cues: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """确定最终字幕条目：显式传入优先，否则自动生成。

        自动生成的两级来源（先便宜后昂贵）：
        1. 复用 L1 落库的 ASR 时间轴（零额外 ASR 成本）；
        2. 兜底重跑 ASR（素材入库时未留存时间轴，或素材并非视频）。
        """
        if cues:
            return list(cues)

        stored = self._load_stored_cues(document)
        if stored:
            logger.info(
                "复用已留存 ASR 时间轴 document_id=%s cue_count=%s",
                getattr(document, "id", None), len(stored),
            )
            return stored

        generated = self._transcribe_source(source_path)
        if not generated:
            raise VideoEditError(
                "未能生成字幕时间轴：素材未留存语音时间戳，重新识别也未返回带时间轴的结果。"
                "请确认素材含清晰人声，或在调用时显式提供 cues。"
            )
        logger.info(
            "重跑 ASR 生成字幕时间轴 document_id=%s cue_count=%s",
            getattr(document, "id", None), len(generated),
        )
        return generated
