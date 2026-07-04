from enum import Enum


class WorkflowStatus(str, Enum):
    """工作流状态类型枚举"""
    DRAFT = "draft"
    PUBLISHED = "published"


class WorkflowResultStatus(str, Enum):
    """工作流运行结果状态"""
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WorkflowRunStatus(str, Enum):
    """工作流执行状态枚举"""
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


class WorkflowNodeExecutionStatus(str, Enum):
    """工作流节点执行状态枚举"""
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowTriggerSource(str, Enum):
    """工作流触发源枚举"""
    DEBUG = "debug"
    APP = "app"
    SCHEDULE = "schedule"
    API = "api"


# 工作流默认配置信息，默认添加一个空的工作流
DEFAULT_WORKFLOW_CONFIG = {
    "graph": {},
    "draft_graph": {
        "nodes": [],
        "edges": []
    },
}
