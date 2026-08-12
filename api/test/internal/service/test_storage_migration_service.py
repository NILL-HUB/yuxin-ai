from datetime import datetime
from types import SimpleNamespace

from internal.service.storage.storage_migration_service import StorageMigrationService


def test_build_dedupe_meta_groups_by_hash_and_marks_latest():
    service = StorageMigrationService(db=None)
    files = [
        SimpleNamespace(
            id="old",
            hash="same-content",
            key="key-1",
            created_at=datetime(2024, 1, 1),
        ),
        SimpleNamespace(
            id="new",
            hash="same-content",
            key="key-2",
            created_at=datetime(2024, 1, 2),
        ),
        SimpleNamespace(
            id="other",
            hash="",
            key="key-3",
            created_at=datetime(2024, 1, 3),
        ),
    ]

    groups, latest_ids = service.build_dedupe_meta(files)

    assert groups["same-content"]["size"] == 2
    assert groups["same-content"]["latest_id"] == "new"
    assert groups["key-3"]["size"] == 1
    assert latest_ids == {"new": "same-content", "other": "key-3"}
