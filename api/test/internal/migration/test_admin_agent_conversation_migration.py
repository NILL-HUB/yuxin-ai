"""P2 会话/消息表与 builtin_key 迁移守卫。

设计 §10.1：管理端 Agent 的会话与消息走**独立表**，不与用户端
conversation/message 混表；预置 Agent 需 builtin_key 作幂等键。
"""
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "x1a2b3c4d5e7_add_admin_agent_conversation.py"


def test_migration_declares_correct_down_revision():
    assert MIGRATION.is_file(), "缺少 P2 会话表迁移"
    source = MIGRATION.read_text(encoding="utf-8")
    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
    assert down is not None
    assert down.group(1) == "w1e2f3a4b5c6", "down_revision 必须是当前单 head"


def test_migration_creates_both_tables_and_builtin_key():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "admin_agent_conversation" in source
    assert "admin_agent_message" in source
    assert "builtin_key" in source
    assert "postgresql_where" in source, "builtin_key 幂等键必须是部分唯一索引"


def test_migration_is_reversible():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "def downgrade" in source
    assert "drop_table" in source
    assert "drop_column" in source


def test_models_exported_and_declared():
    from internal.model import AdminAgentConversation, AdminAgentMessage

    assert AdminAgentConversation.__tablename__ == "admin_agent_conversation"
    assert AdminAgentMessage.__tablename__ == "admin_agent_message"
    assert hasattr(AdminAgentConversation, "admin_agent_id")
    assert hasattr(AdminAgentMessage, "tool_calls")
