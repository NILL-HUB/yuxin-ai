from sqlalchemy import BigInteger

from internal.model import UploadFile


def test_size_column_is_bigint():
    assert isinstance(UploadFile.__table__.columns["size"].type, BigInteger)
