"""存储配额与知识库板块枚举。

集中定义配额常量、权益 feature_key、扩展包 plan_type 与板块/分区枚举，
避免这些稳定值散落在 service 中。
"""
from enum import Enum


# 1 GB = 1024^3 字节（与存储计量的二进制口径一致）
BYTES_PER_GB = 1024 ** 3

# 注册用户的默认免费配额（GB）；套餐权益高于此值时取套餐值
DEFAULT_STORAGE_QUOTA_GB = 5

# 套餐权益中承载存储容量的 feature_key（PlanEntitlement.feature_key）
STORAGE_QUOTA_FEATURE_KEY = "storage_quota_gb"


class StorageAddonPlanType(str, Enum):
    """套餐类型：存储扩展包。"""

    STORAGE_ADDON = "storage_addon"


class KnowledgeBaseType(str, Enum):
    """知识库板块类型，决定允许上传的媒体类型（硬约束）。"""

    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    MIXED = "mixed"


class PartitionMode(str, Enum):
    """分区模式，决定分区如何产生。"""

    NONE = "none"
    DATE_MONTH = "date_month"
    DATE_DAY = "date_day"
    CUSTOM = "custom"


class DocumentMediaType(str, Enum):
    """素材媒体类型。"""

    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
