from internal.model import KnowledgeBaseTag, KnowledgeDocumentTag


def test_knowledge_base_tag_table_name():
    assert KnowledgeBaseTag.__tablename__ == "knowledge_base_tag"


def test_knowledge_document_tag_table_name():
    assert KnowledgeDocumentTag.__tablename__ == "knowledge_document_tag"


def test_base_tag_has_required_columns():
    columns = KnowledgeBaseTag.__table__.columns
    assert "knowledge_base_id" in columns
    assert "tag_id" in columns
    assert "account_id" in columns


def test_document_tag_has_unique_pair():
    constraints = {c.name for c in KnowledgeDocumentTag.__table__.constraints if c.name}
    assert "uq_knowledge_document_tag_pair" in constraints


def test_knowledge_base_tag_foreign_keys_cascade():
    fks = {fk.parent.name: fk for fk in KnowledgeBaseTag.__table__.foreign_keys}
    assert fks["knowledge_base_id"].ondelete == "CASCADE"
    assert fks["tag_id"].ondelete == "CASCADE"


def test_knowledge_document_tag_foreign_keys_cascade():
    fks = {fk.parent.name: fk for fk in KnowledgeDocumentTag.__table__.foreign_keys}
    assert fks["knowledge_document_id"].ondelete == "CASCADE"
    assert fks["tag_id"].ondelete == "CASCADE"
