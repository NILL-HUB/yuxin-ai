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
