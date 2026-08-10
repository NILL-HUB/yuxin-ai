from marshmallow import Schema, fields

from internal.lib.helper import datetime_to_timestamp
from internal.model import ScheduleTask, ScheduleTaskRun


class CreateScheduleTaskReq:
    """定时任务创建请求（FlaskForm 由 handler 用 werkzeug MultiDict 构造）"""


class ScheduleTaskResp(Schema):
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    prompt = fields.String(dump_default="")
    trigger_type = fields.String(dump_default="cron")
    cron_expression = fields.String(dump_default="")
    cron_humanized = fields.String(dump_default="")
    interval_config = fields.Raw(dump_default={})
    enabled = fields.Boolean(dump_default=True)
    status = fields.String(dump_default="")
    description = fields.String(dump_default="")
    run_count = fields.Integer(dump_default=0)
    last_run_at = fields.Integer(allow_none=True)
    last_run_status = fields.String(allow_none=True)
    last_result = fields.String(allow_none=True)
    next_run_at = fields.Integer(allow_none=True)
    created_at = fields.Integer(dump_default=0)
    updated_at = fields.Integer(dump_default=0)

    @staticmethod
    def pre_dump_process(data: ScheduleTask):
        return {
            "id": data.id,
            "name": data.name,
            "prompt": data.prompt,
            "trigger_type": data.trigger_type or "cron",
            "cron_expression": data.cron_expression,
            "cron_humanized": data.cron_humanized,
            "interval_config": data.interval_config or {},
            "enabled": data.enabled,
            "status": data.status,
            "description": data.description,
            "run_count": data.run_count,
            "last_run_at": datetime_to_timestamp(data.last_run_at) if data.last_run_at else None,
            "last_run_status": data.last_run_status,
            "last_result": data.last_result,
            "next_run_at": datetime_to_timestamp(data.next_run_at) if data.next_run_at else None,
            "created_at": datetime_to_timestamp(data.created_at),
            "updated_at": datetime_to_timestamp(data.updated_at),
        }

    @staticmethod
    def dump_many(items):
        return [ScheduleTaskResp.pre_dump_process(item) for item in items]


class ScheduleTaskRunResp(Schema):
    id = fields.UUID(dump_default="")
    schedule_task_id = fields.UUID(dump_default="")
    status = fields.String(dump_default="")
    trigger_source = fields.String(dump_default="schedule")
    started_at = fields.Integer(dump_default=0)
    finished_at = fields.Integer(allow_none=True)
    duration_seconds = fields.Integer(dump_default=0)
    result_summary = fields.String(allow_none=True)
    result_data = fields.Raw(dump_default={})
    error_message = fields.String(allow_none=True)

    @staticmethod
    def pre_dump_process(data: ScheduleTaskRun):
        duration_seconds = 0
        if data.finished_at and data.started_at:
            duration_seconds = max(0, int((data.finished_at - data.started_at).total_seconds()))
        return {
            "id": data.id,
            "schedule_task_id": data.schedule_task_id,
            "status": data.status,
            "trigger_source": data.trigger_source or "schedule",
            "started_at": datetime_to_timestamp(data.started_at),
            "finished_at": datetime_to_timestamp(data.finished_at) if data.finished_at else None,
            "duration_seconds": duration_seconds,
            "result_summary": data.result_summary,
            "result_data": data.result_data or {},
            "error_message": data.error_message,
        }

    @staticmethod
    def dump_many(items):
        return [ScheduleTaskRunResp.pre_dump_process(item) for item in items]
