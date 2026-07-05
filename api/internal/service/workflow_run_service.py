"""工作流执行历史服务模块。"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from injector import inject
from sqlalchemy import desc

from internal.entity.workflow_entity import (
    WorkflowNodeExecutionStatus,
    WorkflowRunStatus,
    WorkflowTriggerSource,
)
from internal.model.workflow import WorkflowNodeExecution, WorkflowRun
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


@inject
class WorkflowRunService:
    """工作流执行历史服务，负责执行记录的持久化与查询。"""

    def __init__(self, db: SQLAlchemy) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 执行记录持久化（供 WorkflowAppService 在事件循环中调用）
    # ------------------------------------------------------------------
    def create_run(
        self,
        workflow_id: UUID,
        account_id: UUID,
        trigger_source: str,
        inputs: dict[str, Any],
        total_steps: int,
        app_id: Optional[UUID] = None,
    ) -> WorkflowRun:
        """创建工作流执行记录（workflow_started 事件时调用）。"""
        run = WorkflowRun(
            workflow_id=workflow_id,
            app_id=app_id,
            account_id=account_id,
            trigger_source=trigger_source,
            inputs=inputs,
            outputs={},
            status=WorkflowRunStatus.RUNNING.value,
            error="",
            total_steps=total_steps,
            elapsed_time=0.0,
            total_tokens=0,
        )
        self.db.session.add(run)
        self.db.session.commit()
        return run

    def update_run(
        self,
        run_id: UUID,
        status: str,
        outputs: Optional[dict[str, Any]] = None,
        error: str = "",
        elapsed_time: float = 0.0,
        total_tokens: int = 0,
    ) -> None:
        """更新工作流执行记录（workflow_finished 事件时调用）。"""
        run = self.db.session.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if not run:
            return
        run.status = status
        if outputs is not None:
            run.outputs = outputs
        run.error = error
        run.elapsed_time = elapsed_time
        run.total_tokens = total_tokens
        self.db.session.commit()

    def create_node_execution(
        self,
        run_id: UUID,
        node_id: UUID,
        node_type: str,
        title: str,
        inputs: dict[str, Any],
    ) -> WorkflowNodeExecution:
        """创建节点执行记录（node_started 事件时调用）。"""
        node_exec = WorkflowNodeExecution(
            workflow_run_id=run_id,
            node_id=node_id,
            node_type=node_type,
            title=title,
            inputs=inputs,
            outputs={},
            status=WorkflowNodeExecutionStatus.RUNNING.value,
            error="",
            elapsed_time=0.0,
            execution_metadata={},
        )
        self.db.session.add(node_exec)
        self.db.session.commit()
        return node_exec

    def update_node_execution(
        self,
        node_exec_id: UUID,
        status: str,
        outputs: Optional[dict[str, Any]] = None,
        error: str = "",
        elapsed_time: float = 0.0,
        execution_metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """更新节点执行记录（node_finished/node_failed 事件时调用）。"""
        node_exec = (
            self.db.session.query(WorkflowNodeExecution)
            .filter(WorkflowNodeExecution.id == node_exec_id)
            .first()
        )
        if not node_exec:
            return
        node_exec.status = status
        if outputs is not None:
            node_exec.outputs = outputs
        node_exec.error = error
        node_exec.elapsed_time = elapsed_time
        if execution_metadata is not None:
            node_exec.execution_metadata = execution_metadata
        self.db.session.commit()

    # ------------------------------------------------------------------
    # 查询接口（供 handler 调用）
    # ------------------------------------------------------------------
    def get_runs_with_page(
        self,
        workflow_id: UUID,
        account: Any,
        page: int = 1,
        page_size: int = 10,
        status: Optional[str] = None,
        trigger_source: Optional[str] = None,
    ) -> tuple[list[WorkflowRun], Any]:
        """分页查询工作流的执行历史记录。"""
        query = (
            self.db.session.query(WorkflowRun)
            .filter(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.account_id == account.id,
            )
        )
        if status:
            query = query.filter(WorkflowRun.status == status)
        if trigger_source:
            query = query.filter(WorkflowRun.trigger_source == trigger_source)
        query = query.order_by(desc(WorkflowRun.created_at))
        paginator = query.paginate(page=page, per_page=page_size, error_out=False)
        return paginator.items, paginator

    def get_run(self, run_id: UUID, account: Any) -> Optional[WorkflowRun]:
        """获取单条执行记录详情。"""
        return (
            self.db.session.query(WorkflowRun)
            .filter(
                WorkflowRun.id == run_id,
                WorkflowRun.account_id == account.id,
            )
            .first()
        )

    def get_node_executions(self, run_id: UUID, account: Any) -> list[WorkflowNodeExecution]:
        """获取执行记录的节点级回放数据。"""
        # 先校验 run 归属当前账号
        run = self.get_run(run_id, account)
        if not run:
            return []
        return (
            self.db.session.query(WorkflowNodeExecution)
            .filter(WorkflowNodeExecution.workflow_run_id == run_id)
            .order_by(WorkflowNodeExecution.created_at)
            .all()
        )

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    @staticmethod
    def serialize_run(run: WorkflowRun) -> dict[str, Any]:
        """序列化执行记录为字典。"""
        return {
            "id": str(run.id),
            "workflow_id": str(run.workflow_id),
            "app_id": str(run.app_id) if run.app_id else None,
            "account_id": str(run.account_id),
            "trigger_source": run.trigger_source,
            "inputs": run.inputs or {},
            "outputs": run.outputs or {},
            "status": run.status,
            "error": run.error or "",
            "total_steps": run.total_steps,
            "elapsed_time": run.elapsed_time,
            "total_tokens": run.total_tokens,
            "created_at": run.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if run.created_at else None,
            "updated_at": run.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if run.updated_at else None,
        }

    @staticmethod
    def serialize_node_execution(node_exec: WorkflowNodeExecution) -> dict[str, Any]:
        """序列化节点执行记录为字典。"""
        return {
            "id": str(node_exec.id),
            "workflow_run_id": str(node_exec.workflow_run_id),
            "node_id": str(node_exec.node_id),
            "node_type": node_exec.node_type,
            "title": node_exec.title,
            "inputs": node_exec.inputs or {},
            "outputs": node_exec.outputs or {},
            "status": node_exec.status,
            "error": node_exec.error or "",
            "elapsed_time": node_exec.elapsed_time,
            "execution_metadata": node_exec.execution_metadata or {},
            "created_at": node_exec.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if node_exec.created_at else None,
            "updated_at": node_exec.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if node_exec.updated_at else None,
        }
