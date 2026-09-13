from internal.model import KnowledgeDocument


def test_document_has_media_columns():
    columns = KnowledgeDocument.__table__.columns
    assert "partition_id" in columns
    assert "media_type" in columns
    assert "parse_profile" in columns


def test_media_type_defaults_to_document():
    columns = KnowledgeDocument.__table__.columns
    assert columns["media_type"].server_default.arg.text == "'document'::character varying"


def test_partition_foreign_key_sets_null_on_delete():
    fks = {fk.parent.name: fk for fk in KnowledgeDocument.__table__.foreign_keys}
    assert fks["partition_id"].ondelete == "SET NULL"
