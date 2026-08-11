import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from internal.context import current_app
from injector import inject
from redis import Redis

from internal.entity.conversation_entity import InvokeFrom
from internal.entity.schedule_task_entity import ScheduleRunStatus
from internal.exception import NotFoundException
from internal.model import Account, Conversation, Message, ScheduleTask, ScheduleTaskRun
from internal.service.base_service import BaseService
from pkg.sqlalchemy import SQLAlchemy


logger = logging.getLogger(__name__)

_EXECUTION_LOCK_KEY_PREFIX = "schedule_task_lock:"
_EXECUTION_LOCK_TTL_SECONDS = 300
_MAX_CONSECUTIVE_FAILURES = 5
_SUMMARY_MAX_LENGTH = 2000


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@inject
@dataclass
class ScheduleExecutionService(BaseService):
    """定时任务执行：以用户身份走完整编排链（与用户直接对话同构）"""

    db: SQLAlchemy
    redis_client: Redis

    def execute_task(self, schedule_task: ScheduleTask) -> ScheduleTaskRun | None:
        """同步执行一次定时任务，返回运行记录。若任务已被其他进程执行中则跳过并返回 None。"""
        lock_key = f"{_EXECUTION_LOCK_KEY_PREFIX}{schedule_task.id}"
        acquired = self.redis_client.set(lock_key, "1", nx=True, ex=_EXECUTION_LOCK_TTL_SECONDS)
        if not acquired:
            logger.warning("定时任务正在执行中，跳过重入 schedule_task_id=%s", schedule_task.id)
            return None

        try:
            run = self._create_run(schedule_task)
            try:
                answer = self._run_assistant_chat(schedule_task)
                self._finish_run(run, schedule_task, success=True, summary=answer[:_SUMMARY_MAX_LENGTH])
            except Exception as exc:
                logger.exception("定时任务执行失败 schedule_task_id=%s", schedule_task.id)
                self._finish_run(run, schedule_task, success=False, summary="", error=str(exc))
            return run
        finally:
            try:
                self.redis_client.delete(lock_key)
            except Exception:
                logger.warning("释放定时任务执行锁失败 key=%s", lock_key, exc_info=True)

    def _run_assistant_chat(self, schedule_task: ScheduleTask) -> str:
        """以任务归属用户身份走 AssistantAgentService.chat 完整编排链，返回最终回答。"""
        from internal.schema.assistant_agent_schema import AssistantAgentChat
        from internal.service.assistant_agent_service import AssistantAgentService

        def _execute() -> str:
            account = self.db.session.query(Account).filter(Account.id == schedule_task.account_id).one_or_none()
            if account is None:
                raise NotFoundException("任务归属用户不存在")

            # 定时任务使用独立会话执行，避免污染用户真实会话
            conversation = self._create_schedule_conversation(account)
            original_conversation_id = account.assistant_agent_conversation_id
            try:
                assistant_service = current_app.injector.get(AssistantAgentService)

                # 构造请求对象（非流式场景：直接填充 form 字段）
                req = AssistantAgentChat()
                req.query.data = schedule_task.prompt
                req.conversation_id.data = str(conversation.id)
                req.image_urls.data = []
                req.confirm_deep_thinking.data = False

                for _event in assistant_service.chat(
                    req,
                    account,
                    invoke_from=InvokeFrom.SCHEDULE.value,
                ):
                    pass

                # 从独立会话最新 Message 读取最终答案
                message = (
                    self.db.session.query(Message)
                    .filter(Message.conversation_id == conversation.id)
                    .order_by(Message.created_at.desc())
                    .first()
                )
                return (message.answer if message else "") or ""
            finally:
                # chat 内部 sync_active 会把账号助手会话指针切到定时会话，执行后恢复原指针，避免污染
                try:
                    if original_conversation_id is not None:
                        self.update(account, assistant_agent_conversation_id=original_conversation_id)
                except Exception:
                    logger.warning("恢复账号助手会话指针失败 account_id=%s", account.id, exc_info=True)

        result_holder: dict[str, object] = {}
        error_holder: dict[str, BaseException] = {}

        def _run_with_result() -> None:
            try:
                result_holder["value"] = _execute()
            except BaseException as exc:
                error_holder["error"] = exc

        logger.warning("定时任务 chat 开始执行 schedule_task_id=%s", schedule_task.id)
        worker = threading.Thread(target=_run_with_result, daemon=True)
        worker.start()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if "value" in result_holder:
                logger.warning("定时任务 chat 执行完成 schedule_task_id=%s", schedule_task.id)
                return str(result_holder["value"])
            if "error" in error_holder:
                raise error_holder["error"]
            time.sleep(0.5)

        logger.warning("定时任务 chat 执行超时，强制结束 schedule_task_id=%s", schedule_task.id)
        raise TimeoutError("定时任务执行超时")

    def _create_schedule_conversation(self, account: Account) -> Conversation:
        """创建定时任务专用会话（归属用户但独立于其真实会话，invoke_from=schedule 与正常对话区分）"""
        assistant_agent_id = current_app.config.get("ASSISTANT_AGENT_ID")
        return self.create(
            Conversation,
            app_id=assistant_agent_id,
            name="定时任务",
            invoke_from=InvokeFrom.SCHEDULE.value,
            created_by=account.id,
        )

    def _create_run(self, schedule_task: ScheduleTask) -> ScheduleTaskRun:
        return self.create(
            ScheduleTaskRun,
            schedule_task_id=schedule_task.id,
            account_id=schedule_task.account_id,
            owner_type=schedule_task.owner_type or "user",
            trigger_source="schedule",
            status=ScheduleRunStatus.RUNNING.value,
        )

    def _finish_run(
        self,
        run: ScheduleTaskRun,
        task: ScheduleTask,
        *,
        success: bool,
        summary: str,
        error: str = "",
    ) -> None:
        now = _utcnow_naive()
        self.update(
            run,
            status=ScheduleRunStatus.SUCCESS.value if success else ScheduleRunStatus.FAILED.value,
            finished_at=now,
            result_summary=summary or None,
            error_message=error or None,
        )
        self.update(
            task,
            run_count=task.run_count + 1,
            last_run_at=now,
            last_run_status=ScheduleRunStatus.SUCCESS.value if success else ScheduleRunStatus.FAILED.value,
            last_result=summary or error or "",
        )
        self._push_notification(task, run)
        if not success:
            self._maybe_disable_after_consecutive_failures(task)

    def _maybe_disable_after_consecutive_failures(self, task: ScheduleTask) -> None:
        """连续失败 5 次自动停用"""
        recent_runs = (
            self.db.session.query(ScheduleTaskRun)
            .filter(ScheduleTaskRun.schedule_task_id == task.id)
            .order_by(ScheduleTaskRun.started_at.desc())
            .limit(_MAX_CONSECUTIVE_FAILURES)
            .all()
        )
        if len(recent_runs) >= _MAX_CONSECUTIVE_FAILURES and all(
            run.status == ScheduleRunStatus.FAILED.value for run in recent_runs
        ):
            self.update(task, enabled=False, status="paused")

    def _push_notification(self, task: ScheduleTask, run: ScheduleTaskRun) -> None:
        try:
            from internal.lib.websocket_manager import ws_manager

            payload = {
                "type": "schedule_task",
                "title": f"定时任务「{task.name}」{'执行成功' if run.status == ScheduleRunStatus.SUCCESS.value else '执行失败'}",
                "summary": run.result_summary or run.error_message or "",
                "task_id": str(task.id),
                "run_id": str(run.id),
                "status": run.status,
            }
            ws_manager.emit_notification_to_user(str(task.account_id), payload, event="schedule_task_result")
        except Exception as exc:
            logger.warning("定时任务结果推送失败: %s", exc)
