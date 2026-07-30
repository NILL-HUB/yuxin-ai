# api/internal/handler/admin_public_ai_feature_handler.py
"""公共 AI 功能配置管理后台 API handler。

功能键（feature_key）由系统预置，管理员只能编辑绑定模型/开关/降级档位，
不能新建或删除功能配置。
"""
from dataclasses import dataclass

from flask import request
from injector import inject

from internal.exception import FailException
from internal.middleware import admin_login_required
from internal.model import PublicAIFeatureConfig
from internal.model.model_pool_entity import ModelPoolConfig
from internal.schema.admin_public_ai_feature_schema import (
    GetPublicAIFeaturesReq,
    PublicAIFeatureItemSchema,
    PublicAIFeatureListSchema,
    UpdatePublicAIFeatureReq,
)
from internal.service.public_ai_feature_service import PublicAIFeatureService
from pkg.response import success_json, validate_error_json
from pkg.sqlalchemy import SQLAlchemy


@inject
@dataclass
class AdminPublicAIFeatureHandler:
    """公共 AI 功能配置 handler（只读列表 + 编辑绑定模型）。"""

    db: SQLAlchemy
    public_ai_feature_service: PublicAIFeatureService

    @admin_login_required
    def list_features(self):
        """GET /admin/public-ai-features 列出所有配置。"""
        form = GetPublicAIFeaturesReq(request.args)
        if not form.validate():
            return validate_error_json(form.errors)

        query = self.db.session.query(PublicAIFeatureConfig)
        category = (form.category.data or "").strip()
        if category:
            query = query.filter_by(feature_category=category)
        enabled_str = (form.enabled.data or "").strip()
        if enabled_str == "true":
            query = query.filter_by(enabled=True)
        elif enabled_str == "false":
            query = query.filter_by(enabled=False)

        model_type = (form.model_type.data or "").strip()
        if model_type:
            query = query.filter_by(model_type=model_type)

        billable = (form.billable.data or "").strip().lower()
        if billable in ("true", "false"):
            query = query.filter_by(billable=(billable == "true"))

        deprecated = (form.deprecated.data or "").strip().lower()
        if deprecated in ("true", "false"):
            query = query.filter_by(deprecated=(deprecated == "true"))

        items = query.order_by(
            PublicAIFeatureConfig.feature_category.asc(),
            PublicAIFeatureConfig.feature_key.asc(),
        ).all()

        return success_json(
            PublicAIFeatureListSchema().dump({"items": items, "total": len(items)})
        )

    @admin_login_required
    def get_feature(self, feature_key: str):
        """GET /admin/public-ai-features/<feature_key> 获取单个配置。"""
        record = self.db.session.query(PublicAIFeatureConfig).filter_by(feature_key=feature_key).first()
        if record is None:
            raise FailException(f"功能配置不存在: {feature_key}")
        return success_json(PublicAIFeatureItemSchema().dump(record))

    @admin_login_required
    def update_feature(self, feature_key: str):
        """PATCH /admin/public-ai-features/<feature_key> 更新配置。

        只允许更新 model_config_id / enabled / fallback_tier 三个字段。
        feature_key / feature_name / feature_category / feature_description 由系统预置，不可修改。
        """
        record = self.db.session.query(PublicAIFeatureConfig).filter_by(feature_key=feature_key).first()
        if record is None:
            raise FailException(f"功能配置不存在: {feature_key}")

        json_data = request.get_json(silent=True) or {}
        form = UpdatePublicAIFeatureReq(data=json_data)
        if not form.validate():
            return validate_error_json(form.errors)

        # 校验 model_config_id 存在性
        model_config_id = (form.model_config_id.data or "").strip()
        if model_config_id:
            model = self.db.session.query(ModelPoolConfig).filter_by(id=model_config_id).first()
            if model is None:
                raise FailException(f"模型配置不存在: {model_config_id}")
            record.model_config_id = model_config_id
        else:
            record.model_config_id = None

        if form.enabled.data is not None:
            record.enabled = form.enabled.data
        if form.fallback_tier.data:
            record.fallback_tier = form.fallback_tier.data

        self.db.session.commit()
        return success_json(PublicAIFeatureItemSchema().dump(record))

    @admin_login_required
    def list_available_models(self):
        """GET /admin/public-ai-features/models?model_type=chat 列出可选模型。

        支持 model_type 查询参数过滤（chat/image/embedding 等），
        不传则返回所有 active 模型。
        """
        model_type = (request.args.get("model_type") or "").strip()
        query = self.db.session.query(ModelPoolConfig).filter_by(status="active")
        if model_type:
            query = query.filter_by(model_type=model_type)
        models = query.order_by(
            ModelPoolConfig.provider.asc(),
            ModelPoolConfig.model_name.asc(),
        ).all()
        return success_json(
            {
                "items": [
                    {
                        "id": str(m.id),
                        "label": f"{m.provider} / {m.model_name} ({m.model_type}, {m.tier})",
                        "provider": m.provider,
                        "model_name": m.model_name,
                        "model_type": m.model_type,
                        "tier": m.tier,
                    }
                    for m in models
                ]
            }
        )
