from werkzeug.datastructures import MultiDict

from internal.entity.storage_quota_entity import StorageAddonPlanType
from internal.schema.admin_billing_plan_schema import UpsertAdminPlanReq


def test_schema_accepts_storage_addon_plan_type():
    form = UpsertAdminPlanReq(MultiDict({"plan_type": "storage_addon"}))
    assert form.validate(), form.errors


def test_schema_still_rejects_unknown_plan_type():
    form = UpsertAdminPlanReq(MultiDict({"plan_type": "unknown_type"}))
    assert not form.validate()


def test_addon_plan_type_value_present_in_order_service_source():
    from internal.service import order_service as module

    source = module.__loader__.get_source(module.__name__)
    assert StorageAddonPlanType.STORAGE_ADDON.value in source
