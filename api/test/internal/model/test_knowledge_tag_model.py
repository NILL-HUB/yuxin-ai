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
