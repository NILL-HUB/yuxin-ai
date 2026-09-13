from internal.model import KnowledgePartition


def test_partition_table_name():
    assert KnowledgePartition.__tablename__ == "knowledge_partition"


def test_partition_has_two_level_support_columns():
    columns = KnowledgePartition.__table__.columns
    assert "parent_id" in columns
    assert "partition_key" in columns
    assert "visibility_scope" in columns


def test_partition_key_is_unique_per_base():
    constraints = {c.name for c in KnowledgePartition.__table__.constraints if c.name}
    assert "uq_knowledge_partition_base_key" in constraints


def test_partition_foreign_keys_have_cascade():
    fks = {fk.parent.name: fk for fk in KnowledgePartition.__table__.foreign_keys}
    assert "knowledge_base_id" in fks
    assert fks["knowledge_base_id"].ondelete == "CASCADE"
    assert fks["parent_id"].ondelete == "CASCADE"


def test_partition_key_is_not_nullable():
    assert KnowledgePartition.__table__.columns["partition_key"].nullable is False
