"""全局控制配置服务：单行 JSONB 存储（id=1），按 section 分组。

admin「系统配置 → 全局控制配置」页面的数据源，承载系统级全局行为开关：
- ``runtime_fallback``：模型运行时降级（enabled 同档候选轮换 + retry_attempts 重连次数）
- ``media_fetch``：外部素材获取（enabled 开关 + max_bytes_fallback 体积估算上限）
- ``agent_checkpoint``：会话级 Checkpoint 续跑开关
- ``skill_catalog_sync``：启动时同步技能目录开关
- ``image_request_policy``：图片请求策略（strict / auto_upgrade）
- ``vision_fallback``：视觉兜底模型（provider / model）

与 desktop_client_config（桌面客户端连接）同款单行模式；字段白名单校验，
未在默认配置中登记的 key 不入库。
"""
from __future__ import annotations

import logging

from internal.extension.database_extension import db
from internal.model.global_control_config import GlobalControlConfig

logger = logging.getLogger(__name__)

# 各 section 的默认配置：key 集合即允许持久化的字段集合（白名单）。
DEFAULT_CONFIGS: dict[str, dict] = {
    "runtime_fallback": {"enabled": True, "retry_attempts": 5},
    "media_fetch": {"enabled": False, "max_bytes_fallback": 536870912},
    "agent_checkpoint": {"enabled": False},
    "skill_catalog_sync": {"enabled": False},
    "image_request_policy": {"policy": "strict"},
    "vision_fallback": {"provider": "", "model": ""},
}

# 各 section 字段类型约束（admin 更新时校验）
_SECTION_FIELD_TYPES: dict[str, dict[str, type]] = {
    "runtime_fallback": {"enabled": bool, "retry_attempts": int},
    "media_fetch": {"enabled": bool, "max_bytes_fallback": int},
    "agent_checkpoint": {"enabled": bool},
    "skill_catalog_sync": {"enabled": bool},
    "image_request_policy": {"policy": str},
    "vision_fallback": {"provider": str, "model": str},
}

SUPPORTED_SECTIONS = frozenset(DEFAULT_CONFIGS)

# 可选值枚举约束
_POLICY_OPTIONS = {"strict", "auto_upgrade"}


class GlobalControlConfigService:
    """全局控制配置：单行记录（id=1），configs JSONB 按 section 分组持久化。"""

    def __init__(self, session=None):
        self.session = session or db.session

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def _row(self) -> GlobalControlConfig:
        row = self.session.query(GlobalControlConfig).filter(GlobalControlConfig.id == 1).one_or_none()
        if row is None:
            row = GlobalControlConfig(id=1, configs={})
            self.session.add(row)
            self.session.flush()
        return row

    def get_config(self, section: str) -> dict:
        """读取指定 section 的配置，未知 section 或字段缺失时回退默认值。"""
        defaults = DEFAULT_CONFIGS.get(section)
        if defaults is None:
            return {}
        cfg = dict(defaults)
        row = self._row()
        if row.configs and isinstance(row.configs, dict):
            raw = row.configs.get(section)
            if isinstance(raw, dict):
                cfg.update({k: v for k, v in raw.items() if k in defaults})
        return cfg

    def get_all_configs(self) -> dict:
        """读取全部 section 配置，供 admin 页面展示。"""
        return {section: self.get_config(section) for section in SUPPORTED_SECTIONS}

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def update_config(self, section: str, patch: dict) -> dict:
        """更新指定 section 的配置（字段白名单 + 类型/枚举校验）。"""
        defaults = DEFAULT_CONFIGS.get(section)
        if defaults is None:
            raise ValueError(f"不支持的配置分组: {section}")
        if not isinstance(patch, dict):
            raise ValueError(f"{section} 配置必须是对象")
        types = _SECTION_FIELD_TYPES.get(section, {})

        cfg = self.get_config(section)
        for key, value in patch.items():
            if key not in defaults:
                continue
            expected = types.get(key)
            if expected is bool:
                if not isinstance(value, bool):
                    raise ValueError(f"{key} 必须是布尔值")
                cfg[key] = value
            elif expected is int:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{key} 必须是整数")
                if value <= 0:
                    raise ValueError(f"{key} 必须大于 0")
                cfg[key] = value
            elif expected is str:
                if not isinstance(value, str):
                    raise ValueError(f"{key} 必须是字符串")
                cfg[key] = str(value).strip()

        if section == "image_request_policy" and cfg["policy"] not in _POLICY_OPTIONS:
            raise ValueError(f"图像请求策略仅支持: {'/'.join(sorted(_POLICY_OPTIONS))}")

        row = self._row()
        all_configs = dict(row.configs or {})
        all_configs[section] = cfg
        row.configs = all_configs
        self.session.commit()
        logger.info("global control config updated section=%s keys=%s", section, list(cfg.keys()))
        return cfg

    # ------------------------------------------------------------------
    # 启动补齐
    # ------------------------------------------------------------------
    def ensure_default_config(self) -> None:
        """确保单行记录存在（幂等，供启动时调用）。"""
        row = self.session.query(GlobalControlConfig).filter(GlobalControlConfig.id == 1).one_or_none()
        if row is not None:
            return
        self.session.add(GlobalControlConfig(id=1, configs={}))
        self.session.commit()
        logger.info("global_control_config 默认行已补齐")
