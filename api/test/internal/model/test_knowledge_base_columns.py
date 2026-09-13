from internal.model import KnowledgeBase


def test_base_has_base_type_column():
    columns = KnowledgeBase.__table__.columns
    assert "base_type" in columns
    assert columns["base_type"].server_default.arg.text == "'mixed'::character varying"


def test_base_has_partition_mode_column():
    columns = KnowledgeBase.__table__.columns
    assert "partition_mode" in columns
    assert columns["partition_mode"].server_default.arg.text == "'none'::character varying"
