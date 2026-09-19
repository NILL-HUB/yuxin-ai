import logging
import os
import re
import tempfile
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from langchain_core.documents import Document as LCDocument
from sqlalchemy import func

from internal.core.file_extractor import FileExtractor
from internal.core.ports.storage_port import ObjectStoragePort
from internal.core.vision.frame_sampling import plan_l2_windows
from internal.core.vision.vision_invoke import path_to_data_uri, probe_duration_sec
from internal.entity.dataset_entity import DocumentStatus, SegmentStatus
from internal.entity.knowledge_entity import DocumentMediaType
from internal.exception import NotFoundException
from internal.model import KnowledgeDocument, KnowledgeSegment, UploadFile
from internal.service.embeddings_service import EmbeddingsService
from internal.service.jieba_service import JiebaService
from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService
from internal.service.knowledge_vector_service import KnowledgeVectorService
from internal.service.visual_embedding_service import VisualEmbeddingService
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

_L2_FRAME_PROMPT = (
    "这是视频的一个关键帧。请做更详尽的画面分析：画面主体与动作、场景环境、"
    "镜头类型与构图、配色与光线、画面中出现的所有文字（OCR），"
    "以及该画面可能对应的剧情/叙事作用。用结构化中文段落输出。"
)

logger = logging.getLogger(__name__)

# L2 密抽窗口的临时子目录名
_L2_WINDOW_DIR = "l2_windows"

# 默认的处理规则（文档分割与预处理配置）
_DEFAULT_PROCESS_RULE = {
    "mode": "custom",
    "rule": {
        "pre_process_rules": [
            {"id": "remove_extra_space", "enabled": True},
            {"id": "remove_url_and_email", "enabled": True},
        ],
        "segment": {
            "separators": [
                "\n\n",
                "\n",
                "。|！|？",
                r"\.\s|\!\s|\?\s",
                r"；|;\s",
                r"，|,\s",
                " ",
                ""
            ],
            "chunk_size": 500,
            "chunk_overlap": 50,
        }
    }
}


@inject
@dataclass
class KnowledgeIndexingService(BaseService):
    db: SQLAlchemy
    file_extractor: FileExtractor
    embeddings_service: EmbeddingsService
    jieba_service: JiebaService
    knowledge_vector_service: KnowledgeVectorService
    media_extractor: KnowledgeMediaExtractorService
    # 关键帧视觉向量与帧文件下载；缺省为 None 时跳过视觉索引（向后兼容）。
    # 与 rerank_service 同范式：具体类型标注 + None 默认值，injector 仍会注入。
    visual_embedding_service: VisualEmbeddingService = None
    cos_service: ObjectStoragePort = None

    def build_document(self, document_id: UUID, account) -> None:
        document = self.get(KnowledgeDocument, document_id)
        if document is None:
            raise NotFoundException("知识库文档不存在")

        try:
            self.update(
                document,
                status=DocumentStatus.PARSING.value,
            )

            media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
            if media_type != DocumentMediaType.DOCUMENT.value:
                logger.info("开始解析多模态素材 document_id=%s media_type=%s", document_id, media_type)
                self._build_media_document(document)
            else:
                logger.info("开始解析知识库文档 document_id=%s", document_id)
                lc_documents = self._parsing(document)

                logger.info("开始分割知识库文档 document_id=%s", document_id)
                lc_segments = self._splitting(document, lc_documents)

                logger.info("开始构建知识库索引 document_id=%s", document_id)
                self._indexing(document, lc_segments)

                logger.info("开始完成知识库文档索引 document_id=%s", document_id)
                self._completed(document, lc_segments)
            logger.info("知识库文档处理完成 document_id=%s", document_id)

        except Exception as e:
            logger.exception("构建知识库文档发生错误 document_id=%s 错误信息:%s", document_id, str(e))
            self.update(
                document,
                status=DocumentStatus.ERROR.value,
                error=str(e),
            )

    def build_documents(self, document_ids: list[UUID], account) -> None:
        for document_id in document_ids:
            try:
                self.build_document(document_id, account)
            except Exception as e:
                logger.exception("批量构建知识库文档单条失败 document_id=%s 错误信息:%s", document_id, str(e))

    def build_document_l2(
        self,
        document_id: UUID,
        start_sec: float | None = None,
        end_sec: float | None = None,
    ) -> dict:
        """对已完成的素材执行 L2 深度解析（按需触发）。

        L2 让素材「能被精细修改」：由 L1 命中帧定位窗口，只在窗口内按 0.5 秒/帧
        密抽并逐帧详述，**不重扫全片**（规格 §5.4）。窗口内新帧新建 Segment，
        与 L1 片段区分（`metadata.tier2_window=True`）。
        状态写入 parse_profile.tier2，失败只标记 error 不回滚 L1 产物——
        L1 的「能被找到」能力必须保留。

        `start_sec` / `end_sec` 均给出时按显式区间密抽（规格 §2「A+B」）；
        缺省时由 L1 命中帧自动推导窗口。

        Returns:
            {"document_id": ..., "tier2": {...}}，供任务侧记录。
        """
        document = self.get(KnowledgeDocument, document_id)
        if document is None:
            raise NotFoundException("知识库文档不存在")

        parse_profile = dict(getattr(document, "parse_profile", None) or {})
        parse_profile["tier2"] = {"status": "running"}
        self.update(document, parse_profile=parse_profile)

        explicit_range = (
            (float(start_sec), float(end_sec))
            if start_sec is not None and end_sec is not None
            else None
        )

        try:
            result = self._enhance_l2(document, explicit_range=explicit_range)
        except Exception as exc:
            logger.exception("L2 深度解析失败 document_id=%s", document_id)
            parse_profile["tier2"] = {"status": "error", "error": str(exc)}
            self.update(document, parse_profile=parse_profile)
            raise

        parse_profile["tier2"] = {"status": "completed", **result}
        self.update(document, parse_profile=parse_profile)
        return {"document_id": str(document_id), "tier2": parse_profile["tier2"]}

    def _enhance_l2(
        self, document: KnowledgeDocument, explicit_range: tuple[float, float] | None = None
    ) -> dict:
        """L2 增强主体：由 L1 命中帧定位窗口，只在窗口内密抽并详述。

        规格 §5.4：L2 是「放大镜」不是「重扫」。L1 帧的 `time_offset` 给出
        目标时刻，扩窗后仅在窗口内按 0.5 秒/帧抽取——这是成本从「整片逐帧」
        降到「按需区间」的关键。

        其余媒体类型（图片/音频）的 L2 增强仍是后续增量，此处直接返回。
        """
        media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
        if media_type != DocumentMediaType.VIDEO.value:
            return {"media_type": media_type, "window_frames": 0}

        segments = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).all()

        # 窗口只能由 **L1 片段**推导：L2 自己产生的窗口帧若参与推导，会形成
        # 「上一轮窗口 → 下一轮更大窗口」的自我放大（帧数逐轮膨胀）。
        l1_segments = [
            s for s in segments if not (getattr(s, "metadata_", None) or {}).get("tier2_window")
        ]
        hit_offsets = [
            frame["time_offset"]
            for frame in (self._segment_frame(s) for s in l1_segments)
            if frame is not None
        ]

        # 重新触发 L2 前先清掉上一轮的窗口片段与帧：否则会累积重复片段，
        # 且旧帧对象永不释放（帧已计配额，等于配额泄漏）。
        self._clear_previous_l2_windows(document, segments)

        windows = plan_l2_windows(
            hit_offsets,
            duration_sec=self._resolve_document_duration(document),
            explicit_range=explicit_range,
        )
        if not windows:
            logger.info("L2 无可用窗口（无 L1 命中帧），跳过 document_id=%s", document.id)
            return {"media_type": media_type, "window_frames": 0, "windows": 0}

        created = 0
        for index, (window_start, window_end) in enumerate(windows, start=1):
            created += self._extract_and_persist_window(
                document, window_start, window_end - window_start, window_index=index
            )
        return {
            "media_type": media_type,
            "window_frames": created,
            "windows": len(windows),
        }

    def _clear_previous_l2_windows(self, document: KnowledgeDocument, segments) -> None:
        """删除上一轮 L2 窗口片段及其帧对象、记录与配额。

        L2 的窗口帧是**新建**的持久化产物（与 L1 帧不同，L1 每轮由
        `_release_stale_frames` 统一清理）。若不清理旧窗口，重复触发会：
        1. 累积重复片段（同一时间段出现多份详述）；
        2. 旧帧对象与配额永不释放（泄漏）。
        """
        stale = [
            s for s in segments if (getattr(s, "metadata_", None) or {}).get("tier2_window")
        ]
        if not stale:
            return

        keys: list[str] = []
        for segment in stale:
            metadata = getattr(segment, "metadata_", None) or {}
            frame_url = str(metadata.get("frame_url") or "").strip()
            if frame_url and frame_url not in keys:
                keys.append(frame_url)

        rows = (
            self.db.session.query(UploadFile)
            .filter(UploadFile.key.in_(keys))
            .all()
            if keys
            else []
        )
        seen: set[str] = set()
        for row in rows:
            key = getattr(row, "key", None)
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                self._delete_frame_object(key, getattr(row, "storage_backend", None))
            except Exception:
                logger.warning(
                    "清理旧 L2 帧对象失败 document_id=%s key=%s", document.id, key, exc_info=True,
                )
            try:
                account_id = getattr(row, "account_id", None)
                size = int(getattr(row, "size", 0) or 0)
                if account_id is not None and size > 0:
                    self._release_frame_quota(account_id, size)
            except Exception:
                logger.warning(
                    "释放旧 L2 帧配额失败 document_id=%s key=%s", document.id, key, exc_info=True,
                )
            try:
                self.delete(row)
            except Exception:
                logger.warning(
                    "删除旧 L2 帧记录失败 document_id=%s key=%s", document.id, key, exc_info=True,
                )

        for segment in stale:
            try:
                self.knowledge_vector_service.remove_segment(segment)
            except Exception:
                logger.warning(
                    "清理旧 L2 片段向量失败 segment_id=%s", segment.id, exc_info=True,
                )
            try:
                self.delete(segment)
            except Exception:
                logger.warning(
                    "删除旧 L2 片段失败 segment_id=%s", segment.id, exc_info=True,
                )

    def _resolve_document_duration(self, document: KnowledgeDocument) -> float:
        """解析视频时长（独立方法便于测试替换）；探测失败返回 0.0（不裁剪上界）。

        注意：`probe_duration_sec` 需要**本地文件路径**，而 `upload_file.key`
        是对象存储 key——必须先下载到临时文件再探测，否则恒为 0.0（窗口上界失效）。
        本方法在 `_download_document_video` 之外单独下载，是为了保证「时长探测」
        与「实际抽帧」互不复用同一临时文件的生命周期。
        """
        try:
            upload_file = self._get_upload_file(document)
            with tempfile.TemporaryDirectory() as temp_dir:
                local_path = os.path.join(
                    temp_dir, os.path.basename(upload_file.key) or "material.mp4"
                )
                self.cos_service.download_file(upload_file.key, local_path)
                duration = probe_duration_sec(local_path)
        except Exception:
            logger.warning("L2 时长解析失败 document_id=%s", document.id, exc_info=True)
            duration = 0.0
        return float(duration or 0.0)

    def _extract_and_persist_window(
        self, document: KnowledgeDocument, start_sec: float, duration_sec: float, *, window_index: int
    ) -> int:
        """对单个窗口密抽并逐帧建 Segment；返回成功入库的帧数。

        单帧失败只跳过该帧——L2 是增强能力，不应因个别帧失败丢弃整个窗口。

        **必须同时写文本向量与视觉向量**：L2 的价值就是让窗口内的细节「能被搜到」。
        只建 Segment 不索引，用户永远检索不到这些片段，等于白跑。
        """
        knowledge_base = document.knowledge_base
        if knowledge_base is None:
            return 0

        video_path = self._download_document_video(document)
        if not video_path:
            return 0

        created = 0
        next_position = self._next_segment_position(document)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                out_dir = os.path.join(temp_dir, _L2_WINDOW_DIR, str(window_index))
                frames = self.media_extractor._extract_frames_in_range(
                    video_path, out_dir, start_sec=start_sec, duration_sec=duration_sec
                )
                for frame in frames:
                    try:
                        frame_url = self._persist_window_frame(frame, document)
                    except Exception:
                        logger.warning(
                            "L2 窗口帧留存失败 document_id=%s offset=%s",
                            document.id, frame.time_offset, exc_info=True,
                        )
                        frame_url = ""
                    if not frame_url:
                        continue
                    try:
                        data_uri = self._load_frame_data_uri(frame_url)
                        detailed = self._invoke_l2_vision(data_uri)
                    except Exception:
                        logger.warning(
                            "L2 窗口帧视觉详述失败 document_id=%s frame_url=%s",
                            document.id, frame_url, exc_info=True,
                        )
                        continue
                    if not str(detailed or "").strip():
                        continue
                    segment = self.create(
                        KnowledgeSegment,
                        knowledge_base_id=document.knowledge_base_id,
                        knowledge_document_id=document.id,
                        owner_account_id=document.owner_account_id,
                        position=next_position,
                        content=detailed,
                        keywords=self.jieba_service.extract_keywords(detailed, 10),
                        metadata_={
                            "media_type": DocumentMediaType.VIDEO.value,
                            "scene_index": created + 1,
                            "frame_url": frame_url,
                            "time_offset": float(frame.time_offset or 0.0),
                            # 标记为 L2 窗口帧，区别于 L1 全片粗抽帧
                            "tier2_window": True,
                            "tier2_window_start": float(start_sec),
                            "tier2_window_duration": float(duration_sec),
                            "tier2_status": "completed",
                        },
                        character_count=len(detailed),
                        token_count=self.embeddings_service.calculate_token_count(detailed),
                        status=SegmentStatus.INDEXING.value,
                        enabled=False,
                    )
                    # 文本向量：让窗口细节可被文本检索命中
                    self.knowledge_vector_service.index_segment(segment, knowledge_base)
                    # 视觉向量：让窗口细节可被画面检索命中（与 L1 帧共用同一通道）
                    self._index_visual_vectors(document, [segment])
                    # 置为完成并启用（与 L1 收尾语义一致）
                    self.update(
                        segment,
                        status=SegmentStatus.COMPLETED.value,
                        enabled=True,
                    )
                    next_position += 1
                    created += 1
        except Exception:
            logger.warning(
                "L2 窗口抽帧失败 document_id=%s window=%s", document.id, start_sec, exc_info=True
            )
        return created

    def _next_segment_position(self, document: KnowledgeDocument) -> int:
        """返回该文档下一个可用的片段序号（L2 新片段接在既有片段之后）。"""
        existing = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).all()
        return max((int(getattr(s, "position", 0) or 0) for s in existing), default=0) + 1

    def _download_document_video(self, document: KnowledgeDocument) -> str:
        """把素材视频下载到临时文件；失败返回空串（单窗口失败不中断整轮 L2）。"""
        try:
            upload_file = self._get_upload_file(document)
            directory = tempfile.mkdtemp()
            target = os.path.join(directory, os.path.basename(upload_file.key) or "material.mp4")
            self.cos_service.download_file(upload_file.key, target)
            return target
        except Exception:
            logger.warning("L2 素材下载失败 document_id=%s", document.id, exc_info=True)
            return ""

    def _load_frame_data_uri(self, frame_url: str) -> str:
        """把留存帧下载并转为 data URI（独立方法便于测试替换）。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, os.path.basename(frame_url))
            self.cos_service.download_file(frame_url, local_path)
            return path_to_data_uri(local_path)

    def _persist_window_frame(self, frame, document: KnowledgeDocument) -> str:
        """把窗口帧留存为 UploadFile，返回对象 key（失败抛错由调用方降级）。"""
        return str(
            self.media_extractor._persist_frame(
                frame.path,
                account_id=getattr(document, "owner_account_id", None),
                document_id=document.id,
            ).key
            or ""
        )

    def _invoke_l2_vision(self, data_uri: str) -> str:
        """L2 视觉详述调用（独立方法便于测试替换）。"""
        from internal.core.vision.vision_invoke import invoke_vision_model

        return invoke_vision_model(data_uri, _L2_FRAME_PROMPT)

    def _get_upload_file(self, document: KnowledgeDocument) -> UploadFile:
        """取文档关联的上传文件，缺失时抛错。"""
        if not document.upload_file_id:
            raise NotFoundException("当前文档未关联上传文件，无法解析")
        upload_file = self.db.session.query(UploadFile).filter(
            UploadFile.id == document.upload_file_id,
        ).one_or_none()
        if upload_file is None:
            raise NotFoundException("上传文件不存在")
        return upload_file

    def _build_media_document(self, document: KnowledgeDocument) -> None:
        """多模态素材：解析产物即片段，跳过文本切分。"""
        upload_file = self._get_upload_file(document)
        # 必须把归属信息传下去：视频关键帧要作为 UploadFile 落库（视觉向量的前置），
        # 不传则帧不留存、frame_url 恒空，视觉索引链路会静默失效。
        media_segments = self.media_extractor.extract(
            document,
            upload_file,
            account_id=getattr(document, "owner_account_id", None),
            document_id=document.id,
        )
        if not media_segments:
            raise NotFoundException("素材解析未产出可用内容")

        knowledge_base = document.knowledge_base
        if knowledge_base is None:
            raise NotFoundException("知识库不存在")

        existing_segments = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).all()
        # 旧帧必须先释放：帧已计入存储配额，若只删片段不删帧文件，
        # 每轮重解析（编辑文档重建索引 / Celery 重试）都会多留一批永不释放的
        # 帧对象与记录，等于持续配额泄漏。
        self._release_stale_frames(document, existing_segments)
        for existing in existing_segments:
            self.knowledge_vector_service.remove_segment(existing)
            self.delete(existing)

        segment_ids = []
        created_segments = []
        for index, item in enumerate(media_segments, start=1):
            segment = self.create(
                KnowledgeSegment,
                knowledge_base_id=document.knowledge_base_id,
                knowledge_document_id=document.id,
                owner_account_id=document.owner_account_id,
                position=index,
                content=item.content,
                keywords=self.jieba_service.extract_keywords(item.content, 10),
                metadata_=item.metadata,
                character_count=len(item.content),
                token_count=self.embeddings_service.calculate_token_count(item.content),
                status=SegmentStatus.INDEXING.value,
                enabled=False,
            )
            self.knowledge_vector_service.index_segment(segment, knowledge_base)
            segment_ids.append(segment.id)
            created_segments.append(segment)

        # 关键帧视觉向量：与文本片段向量并行的一条召回通道（文本与画面共享语义空间）
        self._index_visual_vectors(document, created_segments)

        self.update(document, status=DocumentStatus.INDEXING.value)
        self._finalize_segments(
            document,
            segment_ids,
            parse_profile={
                "tier1": {
                    "status": "completed",
                    "media_type": getattr(document, "media_type", None),
                    "segment_count": len(segment_ids),
                    "video_frame_count": self._count_frames(created_segments),
                },
                "frames": self._collect_frames(created_segments),
            },
        )

    @staticmethod
    def _segment_frame(segment) -> dict | None:
        """取出片段的帧信息；非视频帧片段返回 None。"""
        metadata = getattr(segment, "metadata_", None) or {}
        if metadata.get("media_type") != DocumentMediaType.VIDEO.value:
            return None
        frame_url = str(metadata.get("frame_url") or "")
        if not frame_url:
            return None
        # 时间偏移是帧的定位坐标：缺它则帧清单只能排序、无法换算时间轴位置，
        # 「改细节」与 L2 区间密抽都无从定位到具体片段。
        # 时间线叙述段不落 time_offset，但带 start_sec/end_sec 窗口，回退到窗口中点。
        time_offset = metadata.get("time_offset")
        if time_offset is None:
            start = metadata.get("start_sec")
            end = metadata.get("end_sec")
            time_offset = (
                (float(start) + float(end)) / 2.0
                if start is not None and end is not None
                else 0.0
            )
        return {
            "segment_id": str(getattr(segment, "id", "")),
            "frame_url": frame_url,
            "scene_index": int(metadata.get("scene_index") or 0),
            "time_offset": float(time_offset or 0.0),
        }

    @classmethod
    def _collect_frames(cls, segments) -> list[dict]:
        """收集帧清单，写入 parse_profile.frames，供「改细节」定位与视觉向量后补。"""
        return [frame for frame in (cls._segment_frame(s) for s in segments) if frame]

    @classmethod
    def _count_frames(cls, segments) -> int:
        return len(cls._collect_frames(segments))

    def _release_stale_frames(self, document, segments) -> None:
        """删除上一轮解析留下的帧对象与 UploadFile 记录，并释放其配额。

        帧是持久化产物且计入存储配额。重解析（编辑文档重建索引、Celery 重试）
        若只清片段不清帧，会持续留下孤儿帧对象——既占对象存储，又因用户永不
        删除它们而永久占用配额。

        失败只记 warning 不中断：清理是补偿动作，不应让整轮解析失败。
        """
        keys: list[str] = []
        for segment in segments or []:
            metadata = getattr(segment, "metadata_", None) or {}
            frame_url = str(metadata.get("frame_url") or "").strip()
            if frame_url and frame_url not in keys:
                keys.append(frame_url)
        if not keys:
            return

        rows = (
            self.db.session.query(UploadFile)
            .filter(UploadFile.key.in_(keys))
            .all()
        )
        seen: set[str] = set()
        for row in rows:
            key = getattr(row, "key", None)
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                self._delete_frame_object(key, getattr(row, "storage_backend", None))
            except Exception:
                logger.warning(
                    "清理旧帧对象失败 document_id=%s key=%s", document.id, key, exc_info=True,
                )
            try:
                account_id = getattr(row, "account_id", None)
                size = int(getattr(row, "size", 0) or 0)
                if account_id is not None and size > 0:
                    self._release_frame_quota(account_id, size)
            except Exception:
                logger.warning(
                    "释放旧帧配额失败 document_id=%s key=%s", document.id, key, exc_info=True,
                )
            try:
                self.delete(row)
            except Exception:
                logger.warning(
                    "删除旧帧记录失败 document_id=%s key=%s", document.id, key, exc_info=True,
                )

    @staticmethod
    def _delete_frame_object(key: str, storage_backend) -> None:
        """删除帧的底层存储对象（独立方法便于测试替换）。

        注意：`ObjectStoragePort` 协议没有删除操作，必须走既有的
        `_delete_object(backend, key)` 分发到 local/cos/oss 实现。
        """
        from internal.service.storage.storage_migration_service import _delete_object

        backend = (storage_backend or "local").strip() or "local"
        _delete_object(backend, key)

    def _release_frame_quota(self, account_id, size: int) -> None:
        """释放旧帧占用的存储配额（独立方法便于测试替换）。"""
        from app.http.module import injector
        from internal.service.storage_quota_service import StorageQuotaService

        injector.get(StorageQuotaService).release_usage(account_id, size)

    def _index_visual_vectors(self, document, segments) -> None:
        """为带 frame_url 的视频帧片段建立视觉向量索引。

        先清空该素材旧视觉向量再重建——素材是「每次完整重新生成」的产物，
        与文本片段保持同一幂等语义。
        """
        service = getattr(self, "visual_embedding_service", None)
        storage = getattr(self, "cos_service", None)
        if service is None or storage is None:
            return

        try:
            service.delete_by_document(document.id)
        except Exception:
            logger.warning("清理旧视觉向量失败 document_id=%s", document.id, exc_info=True)

        for segment in segments:
            frame = self._segment_frame(segment)
            if frame is None:
                continue
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    local_path = os.path.join(temp_dir, os.path.basename(frame["frame_url"]))
                    storage.download_file(frame["frame_url"], local_path)
                    data_uri = path_to_data_uri(local_path)
                embedding = service.embed_image(data_uri)
                if not embedding:
                    logger.warning("帧视觉编码失败，跳过 segment_id=%s", segment.id)
                    continue
                service.index_frame(
                    knowledge_base_id=document.knowledge_base_id,
                    knowledge_document_id=document.id,
                    segment_id=segment.id,
                    account_id=document.owner_account_id,
                    frame_url=frame["frame_url"],
                    scene_index=frame["scene_index"],
                    embedding=embedding,
                )
            except Exception:
                logger.warning(
                    "帧视觉向量写入失败 segment_id=%s frame_url=%s",
                    segment.id, frame["frame_url"], exc_info=True,
                )

    def _finalize_segments(self, document, segment_ids, parse_profile=None) -> None:
        """统一收尾：片段置为完成并启用，文档置为完成。"""
        if segment_ids:
            with self.db.auto_commit():
                self.db.session.query(KnowledgeSegment).filter(
                    KnowledgeSegment.id.in_(segment_ids),
                ).update({
                    "status": SegmentStatus.COMPLETED.value,
                    "enabled": True,
                })

        update_fields = {"status": DocumentStatus.COMPLETED.value}
        if parse_profile is not None:
            update_fields["parse_profile"] = parse_profile
        self.update(document, **update_fields)

    def _parsing(self, document: KnowledgeDocument) -> list[LCDocument]:
        upload_file = self._get_upload_file(document)

        lc_documents = self.file_extractor.load(upload_file, False, True)

        for lc_document in lc_documents:
            lc_document.page_content = self._clean_extra_text(lc_document.page_content)

        self.update(
            document,
            character_count=sum([len(lc_document.page_content) for lc_document in lc_documents]),
            status=DocumentStatus.SPLITTING.value,
        )

        return lc_documents

    def _splitting(self, document: KnowledgeDocument, lc_documents: list[LCDocument]) -> list[LCDocument]:
        rule = _DEFAULT_PROCESS_RULE["rule"]

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=rule["segment"]["chunk_size"],
            chunk_overlap=rule["segment"]["chunk_overlap"],
            separators=rule["segment"]["separators"],
            is_separator_regex=True,
            length_function=self.embeddings_service.calculate_token_count,
        )

        for lc_document in lc_documents:
            lc_document.page_content = self._clean_text_by_process_rule(
                lc_document.page_content, rule,
            )

        lc_segments = text_splitter.split_documents(lc_documents)

        position = self.db.session.query(func.coalesce(func.max(KnowledgeSegment.position), 0)).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).scalar()

        for lc_segment in lc_segments:
            position += 1
            content = lc_segment.page_content
            segment = self.create(
                KnowledgeSegment,
                knowledge_base_id=document.knowledge_base_id,
                knowledge_document_id=document.id,
                owner_account_id=document.owner_account_id,
                position=position,
                content=content,
                keywords=[],
                metadata_={},
                character_count=len(content),
                token_count=self.embeddings_service.calculate_token_count(content),
                status=SegmentStatus.WAITING.value,
                enabled=False,
            )
            lc_segment.metadata = {
                "segment_id": str(segment.id),
                "knowledge_base_id": str(document.knowledge_base_id),
                "knowledge_document_id": str(document.id),
                "node_id": str(segment.id),
            }

        self.update(
            document,
            token_count=sum([self.embeddings_service.calculate_token_count(seg.page_content) for seg in lc_segments]),
            status=DocumentStatus.INDEXING.value,
        )
        return lc_segments

    def _indexing(self, document: KnowledgeDocument, lc_segments: list[LCDocument]) -> None:
        knowledge_base = document.knowledge_base
        if knowledge_base is None:
            raise NotFoundException("知识库不存在")

        for lc_segment in lc_segments:
            keywords = self.jieba_service.extract_keywords(lc_segment.page_content, 10)

            segment = self.db.session.query(KnowledgeSegment).filter(
                KnowledgeSegment.id == lc_segment.metadata["segment_id"],
            ).one_or_none()
            if segment is None:
                continue

            self.update(
                segment,
                keywords=keywords,
                status=SegmentStatus.INDEXING.value,
            )
            segment.keywords = keywords

            self.knowledge_vector_service.index_segment(segment, knowledge_base)

        self.update(
            document,
            status=DocumentStatus.INDEXING.value,
        )

    def _completed(self, document: KnowledgeDocument, lc_segments: list[LCDocument]) -> None:
        segment_ids = [lc_segment.metadata["segment_id"] for lc_segment in lc_segments]

        self.update(
            document,
            character_count=sum([len(seg.page_content) for seg in lc_segments]),
        )
        self._finalize_segments(document, segment_ids)

    @staticmethod
    def _clean_text_by_process_rule(text: str, rule: dict) -> str:
        """根据处理规则清除多余的字符串"""
        # 循环遍历所有预处理规则
        for pre_process_rule in rule["pre_process_rules"]:
            # 删除多余空格
            if pre_process_rule["id"] == "remove_extra_space" and pre_process_rule["enabled"] is True:
                pattern = r'\n{3,}'
                text = re.sub(pattern, '\n\n', text)
                pattern = r'[\t\f\r\x20\u00a0\u1680\u180e\u2000-\u200a\u202f\u205f\u3000]{2,}'
                text = re.sub(pattern, ' ', text)
            # 删除多余的URL链接及邮箱
            if pre_process_rule["id"] == "remove_url_and_email" and pre_process_rule["enabled"] is True:
                pattern = r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)'
                text = re.sub(pattern, '', text)
                pattern = r'https?://[^\s]+'
                text = re.sub(pattern, '', text)

        return text

    @staticmethod
    def _clean_extra_text(text: str) -> str:
        text = re.sub(r'<\|', '<', text)
        text = re.sub(r'\|>', '>', text)
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\xEF\xBF\xBE]', '', text)
        text = re.sub('\uFFFE', '', text)
        return text
