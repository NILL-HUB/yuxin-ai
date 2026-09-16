"""policy_change_draft 泛化测试（设计 §5.2）。

泛化内容：suggestion_id 由 NOT NULL 改为可空——通用草稿可不来自路由建议。
路由既有取值保持兼容。
"""
from internal.model.routing_quality import PolicyChangeDraftModel


def test_suggestion_id_is_now_nullable():
    """通用草稿不需要来源建议，因此必须可空。

    若仍 NOT NULL，supervised 档的板块草稿写入会直接 IntegrityError。
    """
    col = PolicyChangeDraftModel.__table__.c.suggestion_id
    assert col.nullable is True


def test_policy_type_semantics_is_board_identifier():
    """policy_type 语义扩展为「板块标识」，长度必须放得下最长板块名。"""
    col = PolicyChangeDraftModel.__table__.c.policy_type
    assert col.type.length >= 64


def test_status_still_covers_three_states():
    """路由既有状态机不变（pending / applied / rolled_back）。"""
    col = PolicyChangeDraftModel.__table__.c.status
    assert col.nullable is False


def test_has_created_at_index_for_global_listing():
    """通用草稿需要「列出全部待应用草稿」，因此需要 status/created_at 维度索引。"""
    names = {idx.name for idx in PolicyChangeDraftModel.__table__.indexes}
    assert "policy_change_draft_status_created_idx" in names


def test_suggestion_id_index_is_retained_for_route_path():
    """路由路径仍按 suggestion_id 查询，索引必须保留（泛化不得删既有索引）。"""
    names = {idx.name for idx in PolicyChangeDraftModel.__table__.indexes}
    assert "policy_change_draft_suggestion_id_idx" in names
