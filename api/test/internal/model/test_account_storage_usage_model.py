from internal.model import AccountStorageUsage


def test_table_name():
    assert AccountStorageUsage.__tablename__ == "account_storage_usage"


def test_used_bytes_is_bigint():
    from sqlalchemy import BigInteger

    assert isinstance(AccountStorageUsage.__table__.columns["used_bytes"].type, BigInteger)


def test_account_id_is_unique():
    constraints = {c.name for c in AccountStorageUsage.__table__.constraints if c.name}
    assert "uq_account_storage_usage_account_id" in constraints
