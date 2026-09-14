"""存储配额常量与扩展包套餐类型。

只承载「存储配额」域的稳定值：
- 配额常量（默认基线、字节换算）
- 套餐权益 feature_key
- 存储扩展包的 plan_type

知识库板块/分区枚举属「知识库」域，定义在
``internal/entity/knowledge_entity.py``，不要在本文件重复定义。
"""
from enum import Enum


# 1 GB = 1024^3 字节（与存储计量的二进制口径一致）
BYTES_PER_GB = 1024 ** 3

# 注册用户的默认免费配额（GB）；套餐权益高于此值时取套餐值
DEFAULT_STORAGE_QUOTA_GB = 5

# 套餐权益中承载存储容量的 feature_key（PlanEntitlement.feature_key）
STORAGE_QUOTA_FEATURE_KEY = "storage_quota_gb"

# 套餐权益中承载「单文件上传上限（GB）」的 feature_key
MAX_SINGLE_FILE_FEATURE_KEY = "max_single_file_gb"

# 无套餐权益时的单文件上限（字节）：15MB，与分片上传引入前的单文件上传上限一致
DEFAULT_MAX_SINGLE_FILE_BYTES = 15 * 1024 * 1024


class StorageAddonPlanType(str, Enum):
    """套餐类型：存储扩展包（Plan.plan_type 的一种取值）。"""

    STORAGE_ADDON = "storage_addon"
