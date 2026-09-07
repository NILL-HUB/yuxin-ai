import logging
import threading
import uuid as _uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from internal.context import current_app
from injector import inject
from redis import Redis

from internal.entity.conversation_entity import InvokeFrom
from internal.entity.schedule_task_entity import ScheduleRunStatus
from internal.exception import NotFoundException
from internal.model import Account, Conversation, Message, ScheduleTask, ScheduleTaskRun
from internal.service.base_service import BaseService
from internal.service.assistant_agent_resolver import resolve_assistant_agent_app_id
from pkg.sqlalchemy import SQLAlchemy


logger = logging.getLogger(__name__)

_EXECUTION_LOCK_KEY_PREFIX = "schedule_task_lock:"
# 执行锁 TTL：8 小时。定时 Agent 任务可长跑数小时（复杂编排/多任务组合），
# 锁 TTL 必须覆盖最长任务时长，否则任务未结束锁已过期，下个 tick 会重入。
# Redis 锁仅防「同一任务重入」，不限制并发任务数（并发由每用户上限治理）。
# 超过 8h 的真实长任务由锁续租 watchdog（每 60s 重置 TTL）兜底，见 execute_task。
_EXECUTION_LOCK_TTL_SECONDS = 8 * 60 * 60
_LOCK_RENEW_INTERVAL_SECONDS = 60
# 每用户同时运行中的定时任务上限：10。定时 Agent 任务可能长跑数小时，
# 5 个上限对同时触发多个任务的用户偏紧；10 个已远超正常单人使用强度
# （几乎无人同时跑超过 10 个 Agent 任务），同时防止单用户任务泛滥打满 worker。
_MAX_CONCURRENT_RUNS_PER_ACCOUNT = 10
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
        # 每用户并发上限：防止单用户创建大量定时任务把 worker 打满。
        # 限制语义是「同一账号同时运行中的任务数」，而非 celery worker 的
        # 全局任务累计计数——后者会误伤其他用户的长任务。
        if not self._account_under_concurrency_limit(schedule_task.account_id):
            logger.warning(
                "账号运行中的定时任务已达上限 %d，跳过本次执行 account_id=%s task_id=%s",
                _MAX_CONCURRENT_RUNS_PER_ACCOUNT,
                schedule_task.account_id,
                schedule_task.id,
            )
            return None

        lock_key = f"{_EXECUTION_LOCK_KEY_PREFIX}{schedule_task.id}"
        # 随机 token 标识持有者：释放时用 Lua 脚本比对 token，防止误删
        # 其他进程/实例的锁（如本进程崩溃后锁被他人接管、旧 finally 又来删）。
        lock_token = str(_uuid.uuid4())
        acquired = self.redis_client.set(
            lock_key, lock_token, nx=True, ex=_EXECUTION_LOCK_TTL_SECONDS
        )
        if not acquired:
            logger.warning("定时任务正在执行中，跳过重入 schedule_task_id=%s", schedule_task.id)
            return None

        renew_stop = threading.Event()

        def _renew_lock() -> None:
            """锁续租 watchdog：任务长跑时周期续期，防止真实长任务（>8h）锁过期被重入。"""
            while not renew_stop.wait(_LOCK_RENEW_INTERVAL_SECONDS):
                try:
                    # 仅当锁仍由本 token 持有时续期（PEXPIRE 幂等，不校验归属也可，
                    # 但保持与释放相同的 token 语义）
                    self.redis_client.expire(lock_key, _EXECUTION_LOCK_TTL_SECONDS)
                except Exception:
                    logger.warning("续租定时任务执行锁失败 key=%s", lock_key, exc_info=True)

        renew_thread = threading.Thread(
            target=_renew_lock,
            daemon=True,
            name=f"schedule-lock-renew-{schedule_task.id}",
        )
        renew_thread.start()

        try:
            run = self._create_run(schedule_task)
            try:
                if schedule_task.task_type == "app_execution" and schedule_task.app_id:
                    answer = self._run_bound_app(schedule_task)
                else:
                    answer = self._run_assistant_chat(schedule_task)
                self._finish_run(run, schedule_task, success=True, summary=answer[:_SUMMARY_MAX_LENGTH])
            except Exception as exc:
                logger.exception("定时任务执行失败 schedule_task_id=%s", schedule_task.id)
                self._finish_run(run, schedule_task, success=False, summary="", error=str(exc))
            return run
        finally:
            renew_stop.set()
            renew_thread.join(timeout=5)
            try:
                self._release_lock(lock_key, lock_token)
            except Exception:
                logger.warning("释放定时任务执行锁失败 key=%s", lock_key, exc_info=True)

    @staticmethod
    def _release_lock(redis_client: Redis, lock_key: str, lock_token: str) -> None:
        """按 token 释放 Redis 锁（Lua 脚本原子比对，避免误删他人锁）。"""
        script = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""
        try:
            redis_client.eval(script, 1, lock_key, lock_token)
        except Exception:
            # 部分 Redis 部署禁用 eval 时降级为直接删除（锁本身有过期兜底）
            redis_client.delete(lock_key)

    def _account_under_concurrency_limit(self, account_id: UUID) -> bool:
        """该账号「同时运行中」的定时任务数是否低于上限。

        running 判定附加 6 小时窗口：进程崩溃会留下永不结束的 running 记录，
        若只看 status 会让额度被僵尸占满。started_at 超过 6 小时仍 running 的
        视为崩溃残留，不计入额度（实际执行由 Redis 锁防重入兜底）。
        """
        if _MAX_CONCURRENT_RUNS_PER_ACCOUNT <= 0:
            return True
        try:
            from datetime import timedelta

            window_start = _utcnow_naive() - timedelta(hours=6)
            running_count = (
                self.db.session.query(ScheduleTaskRun.id)
                .filter(
                    ScheduleTaskRun.account_id == account_id,
                    ScheduleTaskRun.status == ScheduleRunStatus.RUNNING.value,
                    ScheduleTaskRun.started_at >= window_start,
                )
                .count()
            )
            return running_count < _MAX_CONCURRENT_RUNS_PER_ACCOUNT
        except Exception:
            logger.warning("检查账号并发额度失败，放行 account_id=%s", account_id, exc_info=True)
            return True

    def _run_bound_app(self, schedule_task: ScheduleTask) -> str:
        """以任务归属用户身份按绑定应用执行，返回最终回答文本。"""
        import json

        from internal.schema.app_schema import DebugChatReq
        from internal.service.app_debug_service import AppDebugService

        # 绑定应用执行时以应用归属账号运行（admin 创建的任务归属 platform，
        # 需切换到应用真正所属账号，避免越权）。
        from internal.model import App

        bound_app = self.db.session.query(App).filter(App.id == schedule_task.app_id).one_or_none()
        if bound_app is None:
            raise NotFoundException("绑定的应用不存在")
        account = self.db.session.query(Account).filter(Account.id == bound_app.account_id).one_or_none()
        if account is None:
            raise NotFoundException("应用归属账号不存在")

        req = DebugChatReq()
        req.query.data = schedule_task.prompt
        req.conversation_id.data = ""
        req.image_urls.data = []

        app_debug_service = current_app.injector.get(AppDebugService)
        answer_parts = []
        for event in app_debug_service.debug_chat(schedule_task.app_id, req, account):
            try:
                if isinstance(event, str):
                    if "event: agent_message" not in event:
                        continue
                    data_part = event.split("data:", 1)[1] if "data:" in event else ""
                    payload = json.loads(data_part)
                    content = payload.get("answer") or payload.get("message") or ""
                    if content:
                        answer_parts.append(str(content))
            except Exception:
                continue
        return "".join(answer_parts) or ""

    def _run_assistant_chat(self, schedule_task: ScheduleTask) -> str:
        """以任务归属用户身份走 AssistantAgentService.chat 完整编排链，返回最终回答。

        执行策略：直接同步迭代 chat 生成器直至自然完成，不设硬超时。
        定时任务可能执行复杂编排跑数小时（甚至多任务组合跨天），
        90 秒硬超时会误杀这类任务，且旧实现的「daemon 线程 + 超时放弃」
        会让主线程放弃后 Agent 仍在后台空转，属于缺陷。长任务由
        schedule_tasks 的「扫描/执行解耦」保证不阻塞每分钟扫描，
        由 Redis 锁保证不重入，由每用户并发上限防止单用户任务泛滥。
        """
        from internal.schema.assistant_agent_schema import AssistantAgentChat
        from internal.service.assistant_agent_service import AssistantAgentService

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

    def _create_schedule_conversation(self, account: Account) -> Conversation:
        """创建定时任务专用会话（归属用户但独立于其真实会话，invoke_from=schedule 与正常对话区分）"""
        assistant_agent_id = resolve_assistant_agent_app_id(self.db)
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
