"""多模态素材解析服务（L1 基础解析）。

把图片 / 音频 / 视频素材转为可入库的文本片段：
- 图片：视觉模型 OCR + 摘要
- 音频：ASR 全文转写
- 视频：音轨 ASR 转写 + 关键帧视觉描述，关键帧留存为 UploadFile

产物 MediaSegment 直接映射 KnowledgeSegment 的 content 与 metadata，
由 KnowledgeIndexingService 写入并向量化，从而让多媒体素材可被语义检索。
"""
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from injector import inject

from internal.core.ports.storage_port import ObjectStoragePort
from internal.core.vision.timeline_planning import (
    TimelineAnchor,
    anchor_representative_frame,
    build_timeline_plan,
    chunk_anchors,
    parse_timeline_descriptions,
)
from internal.core.vision.vision_invoke import (
    ExtractedFrame,
    extract_video_audio,
    extract_video_frames_in_range,
    extract_video_frames_with_offsets,
    invoke_vision_model,
    invoke_vision_model_multi,
    path_to_data_uri,
)
from internal.entity.knowledge_entity import DocumentMediaType
from internal.model import KnowledgeDocument, UploadFile
from pkg.sqlalchemy import SQLAlchemy
from .audio_service import AudioService
from .base_service import BaseService
from .upload_file_service import UploadFileService

logger = logging.getLogger(__name__)

_IMAGE_PROMPT = (
    "请详细描述这张图片的内容，包括画面主体、场景、风格、配色，"
    "并完整识别其中的文字（OCR）。用简洁的中文段落输出。"
)

_VIDEO_FRAME_PROMPT = (
    "这是视频的一个关键帧。请描述画面主体、场景、动作与镜头类型，"
    "并识别画面中的字幕或文字（OCR）。用简洁的中文段落输出。"
)

_TIMELINE_PROMPT = (
    "这是视频内容时间线描述任务。下面给出若干锚点（台词句或时间片）及对应画面帧。\n"
    "请按锚点顺序，为每个锚点描述其代表画面：画面主体、场景、动作与镜头类型。\n"
    "输出要求：\n"
    "1. 只输出一个 JSON 数组，形如 [{\"anchor_index\": 0, \"description\": \"...\"}]\n"
    "2. 数组元素与锚点一一对应，anchor_index 必须等于锚点序号\n"
    "3. 禁止输出时间码（时间由系统换算）\n"
    "4. 禁止识别画面内字幕文字（字幕由语音转写提供）\n"
    "5. 用简洁的中文段落描述"
)


@dataclass
class MediaSegment:
    """多模态解析产物，映射为一个 KnowledgeSegment。"""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _subtitle_timestamp(text: str) -> float | None:
    """把 srt/vtt 时间（HH:MM:SS.mmm，时/分可缺省）解析为秒。"""
    m = re.match(
        r"^\s*(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>\d{2})[.,](?P<ms>\d{1,3})",
        text,
    )
    if not m:
        return None
    hours = int(m.group("h") or 0)
    minutes = int(m.group("m"))
    seconds = int(m.group("s"))
    ms = int(m.group("ms").ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + ms / 1000.0


def parse_subtitle_cues_from_text(content: str) -> list[dict]:
    """从 vtt/srt 字幕文本解析 cues。

    cues 字段与 ASR 时间码对齐（text/start/end，单位秒），可无损喂给
    build_timeline_plan 与 Segment metadata。
    - 按空行分块，定位含 `-->` 的时间行，其后文本行拼接为该 cue 的 text；
    - 跳过头部（WEBVTT/NOTE/语言标签）与 STYLE/REGION 块；
    - 剥内嵌标签（<i> 等）；缺 end 时回退为 start。
    """
    cues: list[dict] = []
    for block in re.split(r"\r?\n[ \t]*\r?\n", content):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        time_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if time_idx is None:
            continue  # 头部或样式/区域块，不含时间轴
        parts = lines[time_idx].split("-->")
        if len(parts) < 2:
            continue
        start = _subtitle_timestamp(parts[0])
        if start is None:
            continue
        end = _subtitle_timestamp(parts[1].strip().split(" ", 1)[0])
        text = " ".join(lines[time_idx + 1 :])
        text = re.sub(r"<[^>]+>", "", text)  # 剥 VTT/SRT 内嵌标签
        text = " ".join(text.split()).strip()
        if not text:
            continue
        cues.append({"text": text, "start": start, "end": end if end is not None else start})
    return cues


@inject
@dataclass
class KnowledgeMediaExtractorService(BaseService):
    """图片/音频/视频 → 文本片段。

    依赖字段必须用具体类型标注：injector 依据类型注解做依赖解析，
    写 Any 会导致无法注入。
    """

    db: SQLAlchemy
    cos_service: ObjectStoragePort
    audio_service: AudioService
    # 关键帧留存依赖：帧需作为 UploadFile 落库，才能后补视觉向量
    upload_file_service: UploadFileService = None

    def extract(
        self,
        document: KnowledgeDocument,
        upload_file: UploadFile,
        account_id=None,
        document_id=None,
    ) -> list[MediaSegment]:
        """按 media_type 分派解析；文档类型返回空（由既有文本链路处理）。

        account_id / document_id 仅视频分支需要（关键帧留存的归属与来源），
        缺省时视频照常解析但不留存帧，保证既有调用方向后兼容。
        """
        media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
        if media_type == DocumentMediaType.IMAGE.value:
            return self._extract_image(upload_file)
        if media_type == DocumentMediaType.AUDIO.value:
            return self._extract_audio(upload_file)
        if media_type == DocumentMediaType.VIDEO.value:
            return self._extract_video(
                upload_file, account_id=account_id, document_id=document_id, document=document
            )
        return []

    def _download_to(self, upload_file: UploadFile, temp_dir: str) -> str:
        """从对象存储下载素材到临时目录，返回本地路径。"""
        file_path = os.path.join(temp_dir, os.path.basename(upload_file.key) or "material.bin")
        self.cos_service.download_file(upload_file.key, file_path)
        return file_path

    def _invoke_vision(self, data_uri: str, prompt: str) -> str:
        """视觉模型调用（独立方法便于测试替换）。"""
        return invoke_vision_model(data_uri, prompt)

    def _invoke_vision_batch(self, image_data_uris: list[str], prompt: str) -> str:
        """多图批喂视觉模型（独立方法便于测试替换）。"""
        return invoke_vision_model_multi(image_data_uris, prompt)

    def _build_batch_prompt(self, scenario: str, batch: list[TimelineAnchor]) -> str:
        """构造一批锚点的提示词正文（锚点列表 + 帧序号对应关系）。"""
        parts = [_TIMELINE_PROMPT, ""]
        cursor = 0
        for index, anchor in enumerate(batch):
            count = len(anchor.frames)
            frame_range = f"帧号 {cursor}~{cursor + count - 1}" if count else "无对应画面帧"
            if scenario == "B":
                if count:
                    parts.append(
                        f"锚点 {index}：台词「{anchor.anchor_text}」"
                        f"（时间 {anchor.start_sec:.2f}-{anchor.end_sec:.2f}s），对应{frame_range}"
                    )
                else:
                    parts.append(
                        f"锚点 {index}：台词「{anchor.anchor_text}」"
                        f"（时间 {anchor.start_sec:.2f}-{anchor.end_sec:.2f}s），无对应画面帧，仅按台词上下文描述"
                    )
            else:
                parts.append(
                    f"锚点 {index}：时间片 {anchor.start_sec:.2f}-{anchor.end_sec:.2f}s，对应{frame_range}"
                )
            cursor += count
        return "\n".join(parts)

    def _extract_image(self, upload_file: UploadFile) -> list[MediaSegment]:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            data_uri = path_to_data_uri(file_path)
            summary = str(self._invoke_vision(data_uri, _IMAGE_PROMPT) or "").strip()
        if not summary:
            return []
        return [
            MediaSegment(
                content=summary,
                metadata={"media_type": DocumentMediaType.IMAGE.value, "vision_summary": summary},
            )
        ]

    def _extract_audio(self, upload_file: UploadFile) -> list[MediaSegment]:
        """音频：下载后经 ASR 转写为文本片段；转写为空则不产出片段。

        metadata 一并保留 ASR 时间轴（`transcript_segments`）——它是「给素材
        自动加字幕」的唯一时间码来源，不留存则事后只能重新跑一遍 ASR。
        """
        from io import BytesIO

        from werkzeug.datastructures import FileStorage

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            with open(file_path, "rb") as fh:
                content = fh.read()

        filename = (
            getattr(upload_file, "name", None)
            or os.path.basename(getattr(upload_file, "key", "") or "")
            or "material.audio"
        )
        file_storage = FileStorage(
            stream=BytesIO(content),
            filename=filename,
            content_type=getattr(upload_file, "mime_type", None) or "audio/mpeg",
        )
        transcript, cues = self._call_asr_with_segments(file_storage)
        if not transcript:
            return []
        metadata: dict[str, Any] = {"media_type": DocumentMediaType.AUDIO.value}
        if cues:
            metadata["transcript_segments"] = cues
        return [MediaSegment(content=transcript, metadata=metadata)]

    def _extract_frames_with_offsets(self, video_path: str, out_dir: str) -> list[ExtractedFrame]:
        """视频抽帧（独立方法便于测试替换），返回帧与其时间偏移。

        L1 按视频时长动态决定帧数并全片均匀取帧——固定帧数会让长视频只覆盖
        开头（历史缺陷），导致「改细节」无法定位到中后段片段。
        """
        return extract_video_frames_with_offsets(video_path, out_dir)

    def _extract_frames_in_range(
        self, video_path: str, out_dir: str, *, start_sec: float, duration_sec: float
    ) -> list[ExtractedFrame]:
        """在指定时间区间内密抽帧（独立方法便于测试替换，供 L2 扩窗使用）。

        与 `_extract_frames_with_offsets`（全片均匀）相对：本方法只解出窗口内的
        画面，这是 L2「按需放大」而非重扫全片的实现基础。
        """
        return extract_video_frames_in_range(
            video_path, out_dir, start_sec=start_sec, duration_sec=duration_sec
        )

    def _extract_audio_track(self, video_path: str) -> str:
        """抽取视频音轨为单声道 16k WAV（独立方法便于测试替换）。

        目标文件落在视频所在目录（即调用方的临时目录），便于统一清理。
        """
        target_path = os.path.join(os.path.dirname(video_path), f"{uuid4().hex}.wav")
        return extract_video_audio(video_path, target_path)

    def _transcribe_audio_file(self, audio_path: str) -> tuple[str, list[dict]]:
        """把音轨文件转写为（文本, 时间轴分段）（独立方法便于测试替换）。"""
        from io import BytesIO

        from werkzeug.datastructures import FileStorage

        with open(audio_path, "rb") as fh:
            content = fh.read()
        file_storage = FileStorage(
            stream=BytesIO(content),
            filename=os.path.basename(audio_path),
            content_type="audio/wav",
        )
        return self._call_asr_with_segments(file_storage)

    def _call_asr_with_segments(self, file_storage) -> tuple[str, list[dict]]:
        """调用带时间轴的 ASR；ASR 不支持时间戳时降级为纯文本。

        降级路径是必要的：`verbose_json` 是 OpenAI Whisper 兼容参数，
        换用不兼容的 ASR 模型时可能报错，此时仍应产出文本片段
        （字幕能力降级，而非素材解析整体失败）。
        """
        try:
            text, cues = self.audio_service.audio_to_text_with_segments(file_storage)
        except Exception:
            logger.warning(
                "带时间轴的语音转写失败，降级为纯文本转写 filename=%s（期间无机器可读原因）",
                getattr(file_storage, "filename", None), exc_info=True,
            )
            # 时间戳接口不可用：回退到既有纯文本接口（老模型/老 SDK 兼容路径）。
            # 只有「调用失败」才回退——调用成功但结果为空说明音频本身无人声，
            # 此时再调一次纯文本接口只会白白多花一次 ASR。
            try:
                file_storage.stream.seek(0)
            except Exception:
                logger.debug("音轨流不可回绕，直接复用当前读取位置")
            return str(self.audio_service.audio_to_text(file_storage) or "").strip(), []
        return str(text or "").strip(), list(cues or [])

    def _persist_frame(self, frame_path: str, *, account_id, document_id) -> UploadFile:
        """把关键帧留存为 UploadFile，返回落库记录。

        关键帧必须留存：视觉向量属于可后补能力，留存后无需重跑整个视频解析
        （设计稿 §3.4）。extension/mime_type 固定为 jpg，与抽帧产物一致。

        **记录由存储层创建**：`upload_bytes` 内部已调 `create_upload_file` 并返回该
        记录，此处不得再建一条——同一对象 key 出现两条记录会让 purge 时同一份
        字节被 `release_usage` 两次（配额被多还）。
        """
        with open(frame_path, "rb") as fh:
            content = fh.read()
        return self.cos_service.upload_bytes(
            filename=os.path.basename(frame_path),
            content=content,
            account_id=account_id,
            mime_type="image/jpeg",
        )

    def _process_timeline_batch(
        self, batch: list[TimelineAnchor], scenario: str, *, account_id, document_id
    ) -> list[MediaSegment]:
        """处理一批锚点：留存代表帧 → 批喂视觉 → 解析 → 投影落库。

        失败链：批喂/解析失败 → 重试 1 次 → 仍失败 → 降级为该批内逐帧独立调用
        （等价改造前逐帧路径，保证最坏情况仍产出片段）。
        """
        batch_frames: list[ExtractedFrame] = []
        for anchor in batch:
            batch_frames.extend(anchor.frames)

        label = getattr(next((f for a in batch for f in a.frames), None), "path", "?")

        frame_urls: dict[int, str] = {}
        for index, frame in enumerate(batch_frames):
            frame_url = ""
            if account_id is not None and document_id is not None:
                try:
                    frame_url = self._persist_frame(
                        frame.path, account_id=account_id, document_id=document_id
                    ).key or ""
                except Exception:
                    logger.warning(
                        "关键帧留存失败 file=%s frame_index=%s，降级为空 frame_url",
                        label, index, exc_info=True,
                    )
                    frame_url = ""
            frame_urls[index] = frame_url

        data_uris = [path_to_data_uri(frame.path) for frame in batch_frames]
        prompt = self._build_batch_prompt(scenario, batch)

        descriptions: list[tuple[int, str]] = []
        try:
            descriptions = parse_timeline_descriptions(
                self._invoke_vision_batch(data_uris, prompt), len(batch)
            )
        except Exception:
            logger.warning("时间线批喂失败，重试一次 file=%s", label, exc_info=True)
            try:
                descriptions = parse_timeline_descriptions(
                    self._invoke_vision_batch(data_uris, prompt), len(batch)
                )
            except Exception:
                logger.warning("时间线批喂重试仍失败，降级逐帧 file=%s", label, exc_info=True)
                return self._fallback_frame_segments(
                    batch, frame_urls, account_id=account_id, document_id=document_id
                )

        description_map = dict(descriptions)
        segments: list[MediaSegment] = []
        cursor = 0
        for anchor_index, anchor in enumerate(batch):
            rep = anchor_representative_frame(anchor)
            rep_url = ""
            if rep is not None:
                rep_url = frame_urls.get(cursor + anchor.frames.index(rep), "")
            cursor += len(anchor.frames)

            description = description_map.get(anchor_index)
            if scenario == "B" and not description and anchor.speech_text:
                # 场景 B：模型未给描述也保留仅台词段落（可检索）
                description = anchor.speech_text
            if not description:
                # 场景 A 空描述跳过；场景 B 无台词又无描述则跳过
                continue

            metadata: dict[str, Any] = {
                "media_type": DocumentMediaType.VIDEO.value,
                "source": "vision_timeline",
                "anchor_type": anchor.anchor_type,
                "anchor_text": anchor.anchor_text,
                "start_sec": float(anchor.start_sec),
                "end_sec": float(anchor.end_sec),
                "frame_url": rep_url,
            }
            if anchor.speech_text:
                metadata["speech_text"] = anchor.speech_text
            segments.append(MediaSegment(content=description, metadata=metadata))
        return segments

    def _fallback_frame_segments(
        self, batch: list[TimelineAnchor], frame_urls: dict[int, str], *, account_id, document_id
    ) -> list[MediaSegment]:
        """降级：对该批内帧逐帧独立调用，产出与改造前一致的逐帧片段。"""
        segments: list[MediaSegment] = []
        cursor = 0
        for anchor in batch:
            for rel, frame in enumerate(anchor.frames):
                frame_url = frame_urls.get(cursor + rel, "")
                try:
                    description = self._invoke_vision(
                        path_to_data_uri(frame.path), _VIDEO_FRAME_PROMPT
                    )
                except Exception:
                    logger.warning(
                        "降级逐帧视觉分析失败 frame_index=%s", cursor + rel, exc_info=True
                    )
                    continue
                if not str(description or "").strip():
                    continue
                segments.append(
                    MediaSegment(
                        content=description,
                        metadata={
                            "media_type": DocumentMediaType.VIDEO.value,
                            "scene_index": cursor + rel + 1,
                            "frame_url": frame_url,
                            "time_offset": float(frame.time_offset or 0.0),
                        },
                    )
                )
            cursor += len(anchor.frames)
        return segments

    def _extract_video(
        self,
        upload_file: UploadFile,
        account_id=None,
        document_id=None,
        document: KnowledgeDocument | None = None,
    ) -> list[MediaSegment]:
        """视频：平台字幕优先（无则音轨 ASR）+ 批次化时间线叙述（段落代表帧留存）。

        抽帧到临时目录后：
        - 字幕/音轨转写失败只记 warning 不中断（帧描述本身已是有效产物）；
        - 有字幕或 ASR cues 走场景 B（台词句锚点），无 cues 走场景 A（时间片锚点）；
        - 锚点分批（每批 ≈10）批喂视觉模型，每锚点只留存代表帧为 UploadFile；
        - 批喂失败重试 1 次 → 仍失败降级为该批内逐帧独立调用；
        - account_id / document_id 缺失时跳过留存（frame_url 为空字符串）。
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            frames_dir = os.path.join(temp_dir, "frames")
            frames = self._extract_frames_with_offsets(file_path, frames_dir)

            if not frames:
                raise RuntimeError("视频抽帧结果为空，无法解析")

            transcript, cues, is_subtitle = self._consume_subtitle_first(
                file_path,
                upload_file,
                document=document,
                document_id=document_id,
                temp_dir=temp_dir,
            )

            segments: list[MediaSegment] = []
            if transcript:
                metadata: dict[str, Any] = {
                    "media_type": DocumentMediaType.VIDEO.value,
                    # 来源可区分：字幕消费为 platform_subtitle，回退 ASR 为 audio_transcript
                    "source": "platform_subtitle" if is_subtitle else "audio_transcript",
                }
                # 与音频同理：时间轴是「自动加字幕」的来源，需随片段一起落库
                if cues:
                    metadata["transcript_segments"] = cues
                segments.append(MediaSegment(content=transcript, metadata=metadata))

            scenario, anchors = build_timeline_plan(cues, frames)
            if not anchors:
                raise RuntimeError("视频解析未产出任何可用内容")

            for batch in chunk_anchors(anchors):
                segments.extend(
                    self._process_timeline_batch(
                        batch, scenario, account_id=account_id, document_id=document_id
                    )
                )

        if not segments:
            raise RuntimeError("视频解析未产出任何可用内容")
        return segments

    def _consume_subtitle_first(
        self,
        video_path: str,
        upload_file: UploadFile,
        document: KnowledgeDocument | None = None,
        document_id: str | None = None,
        temp_dir: str | None = None,
    ) -> tuple[str, list[dict], bool]:
        """平台字幕优先，无字幕或解析失败则回退音轨 ASR。

        T2 在外部素材入库时把平台字幕 UploadFile id 写入 document.metadata_ 的
        `subtitle_upload_file_id`。本方法读取该 id、下载字幕文件并解析出与 ASR
        同构的 cues（text/start/end，秒），让时间线叙述直接消费平台字幕（含原生
        标点/断句）而非重型 ASR。任何取记录/下载/解析环节失败都只记 warning 并
        回退 ASR，保证既有解析链路的健壮性不变。

        **返回 (text, cues, is_subtitle)**：is_subtitle 标记这段转写是否确实来
        自平台字幕（True）还是回退 ASR（False），供上游区分 transcript 来源
        （metadata.source = platform_subtitle / audio_transcript）。返回结构改动
        属内部通路，不影响 externally 暴露的片段契约；既有调用方均随本改动同步。
        """
        doc = document
        if doc is None and document_id:
            try:
                doc = self.db.session.get(KnowledgeDocument, document_id)
            except Exception:
                doc = None
        sub_id = None
        if doc is not None:
            try:
                sub_id = (getattr(doc, "metadata_", None) or {}).get("subtitle_upload_file_id")
            except Exception:
                sub_id = None
        if not sub_id:
            text, cues = self._transcribe_video_track(video_path, upload_file)
            return text, cues, False

        try:
            subtitle = self.db.session.get(UploadFile, sub_id)
            if subtitle is None:
                raise RuntimeError(f"字幕 UploadFile 不存在 id={sub_id}")
            sub_path = self._download_to(subtitle, temp_dir or tempfile.gettempdir())
            cues = self._parse_subtitle_cues(subtitle, sub_path)
            if not cues:
                raise RuntimeError("平台字幕解析结果为空")
            text = " ".join(str(c.get("text") or "").strip() for c in cues).strip()
            return text, cues, True
        except Exception:
            logger.warning(
                "平台字幕解析失败，回退音轨 ASR upload_file=%s",
                getattr(upload_file, "name", None), exc_info=True,
            )
            text, cues = self._transcribe_video_track(video_path, upload_file)
            return text, cues, False

    def _parse_subtitle_cues(self, record: UploadFile, path: str) -> list[dict]:
        """读取字幕文件并解析 vtt/srt 为 cues（独立方法便于测试替换）。"""
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
        return parse_subtitle_cues_from_text(content)

    def _transcribe_video_track(
        self, video_path: str, upload_file: UploadFile
    ) -> tuple[str, list[dict]]:
        """抽取并转写视频音轨；任一环节失败都降级为无转写（返回空串 + 空时间轴）。

        音轨是增强能力：视频可能没有音轨、ASR 可能不可用，都不应让帧描述失败。
        音轨临时文件无论成功与否都必须删除（抽取失败时路径未知，交由临时目录回收）。
        """
        audio_path = ""
        try:
            audio_path = self._extract_audio_track(video_path)
            text, cues = self._transcribe_audio_file(audio_path)
            return str(text or "").strip(), list(cues or [])
        except Exception:
            logger.warning(
                "视频音轨转写失败，降级为仅帧描述 file=%s",
                getattr(upload_file, "name", None), exc_info=True,
            )
            return "", []
        finally:
            if audio_path:
                try:
                    os.remove(audio_path)
                except OSError:
                    logger.debug("音轨临时文件清理失败 path=%s", audio_path)
