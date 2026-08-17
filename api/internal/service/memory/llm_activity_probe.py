"""LLM 活性探针：检测模型是否仍在正常产出 token，死机时终止调用。

核心原则：宁可不写，也不写垃圾。

探针每 60s 检测一次双信号：
1. LLM token 活性：检测 stream() 是否仍在产出 chunk
   - 有新 chunk → 模型正常思考中，不干扰，继续等待
   - 无新 chunk 超过 60s → 判定死机，终止调用
2. Celery 任务状态：检测当前是否在 Celery 任务上下文中
   - 任务状态为 STARTED/PROGRESS → 任务正常执行中
   - 任务状态异常（FAILED/REVOKED）→ 判定死机，终止调用

设计参考：
- DegradationManager 的后台线程模式（threading.Event + daemon Thread）
- _probe_embedding_dimension 的探针模式

使用方式：
    # 非结构化调用
    result = LLMActivityProbe.invoke_with_probe(
        llm, prompt, feature_key="memory_consolidation"
    )

    # 结构化调用
    result = LLMActivityProbe.invoke_structured_with_probe(
        llm, _ExtractionResult, prompt, feature_key="memory_entity_extraction"
    )

    # 调用方捕获超时异常后必须跳过写入
    try:
        result = LLMActivityProbe.invoke_with_probe(...)
    except LLMActivityTimeoutError:
        logger.warning("记忆写入被探针终止，不写入任何东西")
        return None  # 或空列表/默认值，但不写入
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


# =========================================================
# 异常定义
# =========================================================

class LLMActivityTimeoutError(Exception):
    """探针检测到 LLM 死机/卡死时抛出。

    调用方捕获此异常后**必须跳过写入**，不能写垃圾记忆。
    """

    def __init__(self, feature_key: str, reason: str = "") -> None:
        self.feature_key = feature_key
        self.reason = reason
        super().__init__(
            f"LLM 活性探针终止调用: feature_key={feature_key} reason={reason}"
        )


# =========================================================
# 探针核心类
# =========================================================

class LLMActivityProbe:
    """LLM 活性探针：双信号检测模型是否正常工作。

    使用 stream() 替代 invoke() 以获取 token 活性。
    后台线程每 probe_interval 秒检测一次，死机时抛出 LLMActivityTimeoutError。
    """

    # 探针检测间隔（秒），与 token 停滞阈值一致
    DEFAULT_PROBE_INTERVAL_SECONDS = 60

    @classmethod
    def invoke_with_probe(
        cls,
        llm: Any,
        prompt: str,
        feature_key: str,
        probe_interval: int = DEFAULT_PROBE_INTERVAL_SECONDS,
    ) -> Any:
        """带探针的 LLM invoke 调用（非结构化输出）。

        内部用 stream() 替代 invoke() 以获取 token 活性。
        探针检测到死机时抛出 LLMActivityTimeoutError。

        Args:
            llm: LanguageModelService.get_feature_model() 返回的 LLM 实例
            prompt: 调用 prompt
            feature_key: 功能键，用于日志和追踪
            probe_interval: 探针检测间隔（秒），默认 60s

        Returns:
            LLM 响应结果（AIMessage 或类似对象）

        Raises:
            LLMActivityTimeoutError: 探针检测到 LLM 死机
        """
        return cls._invoke_with_probe_internal(
            llm, prompt, feature_key, probe_interval, structured=False
        )

    @classmethod
    def invoke_structured_with_probe(
        cls,
        llm: Any,
        response_model: type,
        prompt: str,
        feature_key: str,
        probe_interval: int = DEFAULT_PROBE_INTERVAL_SECONDS,
    ) -> Any:
        """带探针的结构化 LLM 调用。

        内部用 with_structured_output().stream() 替代 invoke() 以获取 token 活性。
        探针检测到死机时抛出 LLMActivityTimeoutError。

        Args:
            llm: LanguageModelService.get_feature_model() 返回的 LLM 实例
            response_model: Pydantic 模型类（结构化输出的目标类型）
            prompt: 调用 prompt
            feature_key: 功能键，用于日志和追踪
            probe_interval: 探针检测间隔（秒），默认 60s

        Returns:
            结构化输出结果（response_model 实例）

        Raises:
            LLMActivityTimeoutError: 探针检测到 LLM 死机
        """
        return cls._invoke_with_probe_internal(
            llm, prompt, feature_key, probe_interval,
            structured=True, response_model=response_model,
        )

    @classmethod
    def invoke_messages_with_probe(
        cls,
        llm: Any,
        messages: list,
        feature_key: str,
        probe_interval: int = DEFAULT_PROBE_INTERVAL_SECONDS,
    ) -> Any:
        """带探针的 LLM invoke 调用（接受 messages 列表）。

        内部用 stream() 替代 invoke() 以获取 token 活性。
        探针检测到死机时抛出 LLMActivityTimeoutError。

        适用于公共 AI 功能（direct_answer、assistant_agent_intro 等），
        这些场景传入的是 LangChain Message 列表而非纯文本 prompt。

        Args:
            llm: LanguageModelService.get_feature_model() 返回的 LLM 实例
            messages: LangChain Message 列表（SystemMessage/HumanMessage 等）
            feature_key: 功能键，用于日志和追踪
            probe_interval: 探针检测间隔（秒），默认 60s

        Returns:
            LLM 响应结果（AIMessage 或类似对象）

        Raises:
            LLMActivityTimeoutError: 探针检测到 LLM 死机
        """
        return cls._invoke_messages_with_probe_internal(
            llm, messages, feature_key, probe_interval,
        )

    @classmethod
    def stream_messages_with_probe(
        cls,
        llm: Any,
        messages: list,
        feature_key: str,
        probe_interval: int = DEFAULT_PROBE_INTERVAL_SECONDS,
    ) -> Generator[Any, None, None]:
        """带探针的流式 LLM 调用（接受 messages 列表），返回生成器。

        与 invoke_messages_with_probe 的区别：逐 chunk yield，
        适用于 SSE 流式响应场景（如 DirectAnswerExecutor.stream）。

        Args:
            llm: LanguageModelService.get_feature_model() 返回的 LLM 实例
            messages: LangChain Message 列表
            feature_key: 功能键，用于日志和追踪
            probe_interval: 探针检测间隔（秒），默认 60s

        Yields:
            LLM stream chunk

        Raises:
            LLMActivityTimeoutError: 探针检测到 LLM 死机
        """
        # 复用 monitor_stream 的实现，传入 llm.stream(messages) 作为迭代器
        yield from cls.monitor_stream(
            lambda: llm.stream(messages),
            feature_key=feature_key,
            probe_interval=probe_interval,
        )

    @classmethod
    def monitor_stream(
        cls,
        stream_factory: "Any",
        feature_key: str,
        probe_interval: int = DEFAULT_PROBE_INTERVAL_SECONDS,
    ) -> Generator[Any, None, None]:
        """带探针的通用流式迭代器包装器。

        可包装任意迭代器（包括 LCEL 链的 chain.stream() 输出），
        在迭代过程中启动后台探针线程监测双信号：
        1. LLM token 活性：每个 chunk 更新 last_chunk_time，
           超过 probe_interval 无 chunk → 判定死机
        2. Celery 任务状态：异常状态 → 判定死机

        适用于无法直接被探针包装的调用形态（如 LCEL 链、with_structured_output 链），
        调用方只需把流式迭代器工厂传入即可。

        Args:
            stream_factory: 返回迭代器的可调用对象（每次调用返回新迭代器），
                例如 lambda: chain.stream(stream_input)
            feature_key: 功能键，用于日志和追踪
            probe_interval: 探针检测间隔（秒），默认 60s

        Yields:
            原始迭代器产出的每个 chunk

        Raises:
            LLMActivityTimeoutError: 探针检测到 LLM 死机
        """
        last_chunk_time = [time.time()]
        abort_event = threading.Event()
        start_time = time.time()

        def _probe_worker() -> None:
            while not abort_event.wait(probe_interval):
                now = time.time()
                stall_duration = now - last_chunk_time[0]
                if stall_duration >= probe_interval:
                    logger.warning(
                        "LLMActivityProbe[%s]: 信号1-LLM 无 chunk 产出超过 %.0fs，判定死机，终止调用",
                        feature_key, stall_duration,
                    )
                    abort_event.set()
                    return
                celery_state = cls._check_celery_task_state()
                if celery_state is not None and celery_state not in ("STARTED", "PROGRESS", "PENDING"):
                    logger.warning(
                        "LLMActivityProbe[%s]: 信号2-Celery 任务状态异常: %s，终止调用",
                        feature_key, celery_state,
                    )
                    abort_event.set()
                    return

        probe_thread = threading.Thread(
            target=_probe_worker,
            daemon=True,
            name=f"llm-probe-{feature_key}",
        )
        probe_thread.start()

        try:
            for chunk in stream_factory():
                if abort_event.is_set():
                    raise LLMActivityTimeoutError(
                        feature_key, reason="abort event set during stream"
                    )
                last_chunk_time[0] = time.time()
                yield chunk
        except LLMActivityTimeoutError:
            raise
        except Exception as exc:
            if abort_event.is_set():
                raise LLMActivityTimeoutError(
                    feature_key, reason=f"stream interrupted by probe: {exc}"
                )
            raise
        finally:
            abort_event.set()
            probe_thread.join(timeout=5)
            elapsed = time.time() - start_time
            logger.debug(
                "LLMActivityProbe[%s]: 流式调用结束，耗时 %.1fs",
                feature_key, elapsed,
            )

    # ----------------------------------------------------------
    # 内部实现
    # ----------------------------------------------------------

    @classmethod
    def _invoke_messages_with_probe_internal(
        cls,
        llm: Any,
        messages: list,
        feature_key: str,
        probe_interval: int,
    ) -> Any:
        """探针调用的内部实现（messages 列表版本）。

        核心流程与 _invoke_with_probe_internal 一致：
        1. 启动后台探针线程，每 probe_interval 秒检测一次双信号
        2. 主线程用 stream() 迭代 LLM 响应，每个 chunk 更新 last_chunk_time
        3. 探针检测到死机时设置 abort_event
        4. 主线程检测 abort_event，提前退出抛出 LLMActivityTimeoutError
        5. finally 块中清理探针线程
        """
        last_chunk_time = [time.time()]
        abort_event = threading.Event()
        start_time = time.time()

        def _probe_worker() -> None:
            while not abort_event.wait(probe_interval):
                now = time.time()
                stall_duration = now - last_chunk_time[0]
                if stall_duration >= probe_interval:
                    logger.warning(
                        "LLMActivityProbe[%s]: 信号1-LLM 无 chunk 产出超过 %.0fs，判定死机，终止调用",
                        feature_key, stall_duration,
                    )
                    abort_event.set()
                    return
                celery_state = cls._check_celery_task_state()
                if celery_state is not None and celery_state not in ("STARTED", "PROGRESS", "PENDING"):
                    logger.warning(
                        "LLMActivityProbe[%s]: 信号2-Celery 任务状态异常: %s，终止调用",
                        feature_key, celery_state,
                    )
                    abort_event.set()
                    return

        probe_thread = threading.Thread(
            target=_probe_worker,
            daemon=True,
            name=f"llm-probe-{feature_key}",
        )
        probe_thread.start()

        try:
            chunks = []
            for chunk in llm.stream(messages):
                if abort_event.is_set():
                    raise LLMActivityTimeoutError(
                        feature_key, reason="abort event set during stream"
                    )
                last_chunk_time[0] = time.time()
                chunks.append(chunk)

            if not chunks:
                raise LLMActivityTimeoutError(
                    feature_key, reason="LLM 未产出任何 chunk"
                )

            result = chunks[0]
            for chunk in chunks[1:]:
                try:
                    result = result + chunk
                except (TypeError, AttributeError):
                    result = chunk
            return result
        except LLMActivityTimeoutError:
            raise
        except Exception as exc:
            if abort_event.is_set():
                raise LLMActivityTimeoutError(
                    feature_key, reason=f"stream interrupted by probe: {exc}"
                )
            raise
        finally:
            abort_event.set()
            probe_thread.join(timeout=5)
            elapsed = time.time() - start_time
            logger.debug(
                "LLMActivityProbe[%s]: 调用结束，耗时 %.1fs",
                feature_key, elapsed,
            )

    @classmethod
    def _invoke_with_probe_internal(
        cls,
        llm: Any,
        prompt: str,
        feature_key: str,
        probe_interval: int,
        structured: bool = False,
        response_model: Optional[type] = None,
    ) -> Any:
        """探针调用的内部实现。

        核心流程：
        1. 启动后台探针线程，每 probe_interval 秒检测一次双信号
        2. 主线程用 stream() 迭代 LLM 响应，每个 chunk 更新 last_chunk_time
        3. 探针检测到死机时设置 abort_event
        4. 主线程检测 abort_event，提前退出抛出 LLMActivityTimeoutError
        5. finally 块中清理探针线程
        """
        # 共享状态（用 list 包装以便闭包修改）
        last_chunk_time = [time.time()]
        abort_event = threading.Event()
        start_time = time.time()

        # ----------------------------------------------------------
        # 探针线程：双信号检测
        # ----------------------------------------------------------
        def _probe_worker() -> None:
            """后台探针：每 probe_interval 秒检测一次双信号。"""
            while not abort_event.wait(probe_interval):
                # 信号1: LLM token 活性
                now = time.time()
                stall_duration = now - last_chunk_time[0]
                if stall_duration >= probe_interval:
                    logger.warning(
                        "LLMActivityProbe[%s]: 信号1-LLM 无 chunk 产出超过 %.0fs，判定死机，终止调用",
                        feature_key, stall_duration,
                    )
                    abort_event.set()
                    return

                # 信号2: Celery 任务状态（仅在 Celery 上下文中检测）
                celery_state = cls._check_celery_task_state()
                if celery_state is not None and celery_state not in ("STARTED", "PROGRESS", "PENDING"):
                    logger.warning(
                        "LLMActivityProbe[%s]: 信号2-Celery 任务状态异常: %s，终止调用",
                        feature_key, celery_state,
                    )
                    abort_event.set()
                    return

        probe_thread = threading.Thread(
            target=_probe_worker,
            daemon=True,
            name=f"llm-probe-{feature_key}",
        )
        probe_thread.start()

        # ----------------------------------------------------------
        # 主线程：stream 迭代 + abort 检测
        # ----------------------------------------------------------
        try:
            if structured:
                return cls._stream_structured(
                    llm, response_model, prompt, feature_key,
                    abort_event, last_chunk_time,
                )
            else:
                return cls._stream_plain(
                    llm, prompt, feature_key,
                    abort_event, last_chunk_time,
                )
        except LLMActivityTimeoutError:
            # 重新抛出，让调用方处理
            raise
        except Exception as exc:
            # 如果是 abort 导致的 stream 中断，转换为超时异常
            if abort_event.is_set():
                raise LLMActivityTimeoutError(
                    feature_key, reason=f"stream interrupted by probe: {exc}"
                )
            raise
        finally:
            abort_event.set()
            probe_thread.join(timeout=5)
            elapsed = time.time() - start_time
            logger.debug(
                "LLMActivityProbe[%s]: 调用结束，耗时 %.1fs",
                feature_key, elapsed,
            )

    @staticmethod
    def _stream_plain(
        llm: Any,
        prompt: str,
        feature_key: str,
        abort_event: threading.Event,
        last_chunk_time: list,
    ) -> Any:
        """非结构化 stream 调用：迭代 chunk 并聚合为 AIMessage。"""
        chunks = []
        for chunk in llm.stream(prompt):
            if abort_event.is_set():
                raise LLMActivityTimeoutError(
                    feature_key, reason="abort event set during stream"
                )
            last_chunk_time[0] = time.time()
            chunks.append(chunk)

        if not chunks:
            raise LLMActivityTimeoutError(
                feature_key, reason="LLM 未产出任何 chunk"
            )

        # 聚合 chunks：LangChain AIMessageChunk 支持 + 运算符
        result = chunks[0]
        for chunk in chunks[1:]:
            try:
                result = result + chunk
            except (TypeError, AttributeError):
                # 某些 LLM 返回的 chunk 不支持 + 运算符，保留最后一个
                result = chunk

        return result

    @staticmethod
    def _stream_structured(
        llm: Any,
        response_model: type,
        prompt: str,
        feature_key: str,
        abort_event: threading.Event,
        last_chunk_time: list,
    ) -> Any:
        """结构化 stream 调用：迭代 chunk，最后一个完整 chunk 为结果。

        LangChain with_structured_output().stream() 返回的是部分 pydantic 对象，
        最后一个 chunk 通常是完整对象。
        """
        from internal.lib.structured_output import with_structured_output_fallback

        structured = with_structured_output_fallback(llm, response_model)
        final_result = None

        for chunk in structured.stream(prompt):
            if abort_event.is_set():
                raise LLMActivityTimeoutError(
                    feature_key, reason="abort event set during structured stream"
                )
            last_chunk_time[0] = time.time()
            # 结构化输出的每个 chunk 是部分填充的 pydantic 对象
            # 保留最后一个非 None 的 chunk 作为结果
            if chunk is not None:
                final_result = chunk

        if final_result is None:
            raise LLMActivityTimeoutError(
                feature_key, reason="LLM 结构化输出未产出任何 chunk"
            )

        return final_result

    @staticmethod
    def _check_celery_task_state() -> Optional[str]:
        """检测当前是否在 Celery 任务上下文中，返回任务状态。

        Returns:
            Celery 任务状态字符串（STARTED/PROGRESS/FAILED/REVOKED 等），
            不在 Celery 上下文中时返回 None
        """
        try:
            from celery import current_task
            if current_task and current_task.state:
                return current_task.state
        except Exception:
            # 不在 Celery 上下文中或导入失败，跳过此检测
            pass
        return None
