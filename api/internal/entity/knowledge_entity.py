from enum import Enum


class KnowledgeScope(str, Enum):
    SYSTEM = "system"
    TENANT = "tenant"
    PROJECT = "project"
    USER_MEMORY = "user_memory"
    USER_CONTENT = "user_content"


class KnowledgeBaseType(str, Enum):
    """知识库板块类型，决定允许的媒体类型（服务端硬约束）。

    注意与 DocumentMediaType 的区别：本枚举是「板块」的组织类型
    （MIXED 板块可容纳任意 media_type），后者是「单个素材」的媒体类型。
    """

    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    MIXED = "mixed"


class PartitionMode(str, Enum):
    """分区模式：决定分区由系统按日期产生还是用户手动创建。"""

    NONE = "none"
    DATE_MONTH = "date_month"
    DATE_DAY = "date_day"
    CUSTOM = "custom"


class DocumentMediaType(str, Enum):
    """单个素材的媒体类型（knowledge_document.media_type）。"""

    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class OperationContext(str, Enum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM_JOB = "system_job"


class VisibilityScope(str, Enum):
    PRIVATE = "private"
    TEAM = "team"
    TENANT = "tenant"
    PUBLIC = "public"
    INTERNAL = "internal"


class KnowledgeCreatedFrom(str, Enum):
    MANUAL_UPLOAD = "manual_upload"
    CONVERSATION_MEMORY = "conversation_memory"
    ADMIN_CONFIG = "admin_config"
    EXTERNAL_SYNC = "external_sync"
    WORKFLOW_IMPORT = "workflow_import"  # 工作流导入
    RENDER_OUTPUT = "render_output"  # 渲染成品（系统托管成品库）


class ExternalSourceType(str, Enum):
    LARK = "lark"
    NOTION = "notion"
    DRIVE = "drive"
    GITHUB = "github"


class ExternalAuthorizationStatus(str, Enum):
    PENDING = "pending"
    GRANTED = "granted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ExternalSyncStatus(str, Enum):
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"
