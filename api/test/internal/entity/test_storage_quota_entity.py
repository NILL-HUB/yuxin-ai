from internal.entity.storage_quota_entity import (
    BYTES_PER_GB,
    DEFAULT_STORAGE_QUOTA_GB,
    STORAGE_QUOTA_FEATURE_KEY,
    StorageAddonPlanType,
)


def test_default_quota_is_5gb():
    assert DEFAULT_STORAGE_QUOTA_GB == 5


def test_bytes_per_gb_uses_1024_base():
    assert BYTES_PER_GB == 1024 ** 3


def test_quota_feature_key_is_stable():
    assert STORAGE_QUOTA_FEATURE_KEY == "storage_quota_gb"


def test_storage_addon_plan_type_value():
    assert StorageAddonPlanType.STORAGE_ADDON.value == "storage_addon"


def test_storage_addon_str_mixin_compares_with_plain_string():
    assert StorageAddonPlanType.STORAGE_ADDON == "storage_addon"


def test_storage_addon_enum_has_single_member():
    assert [member.value for member in StorageAddonPlanType] == ["storage_addon"]
