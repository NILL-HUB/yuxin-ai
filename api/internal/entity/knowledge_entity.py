from enum import Enum


class KnowledgeScope(str, Enum):
    SYSTEM = "system"
    TENANT = "tenant"
    PROJECT = "project"
    USER_MEMORY = "user_memory"
    USER_CONTENT = "user_content"


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


class ExternalSourceType(str, Enum):
    LARK = "lark"
    NOTION = "notion"
    DRIVE = "drive"
    GITHUB = "github"
    ENTERPRISE_KNOWLEDGE = "enterprise_knowledge"


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
