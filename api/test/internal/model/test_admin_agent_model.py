"""admin_agent 模型结构测试（设计 §10.1）。"""
from internal.model.admin_agent import AdminAgent


class TestAdminAgentModel:
    def test_tablename(self):
        assert AdminAgent.__tablename__ == "admin_agent"

    def test_required_columns_exist(self):
        columns = {c.name for c in AdminAgent.__table__.columns}
        for name in (
            "id", "owner_admin_user_id", "name", "description", "prompt_key",
            "granted_permissions", "automation_policy", "budget_config",
            "enabled", "created_at", "updated_at",
        ):
            assert name in columns, f"缺少列 {name}"

    def test_id_is_primary_key(self):
        pk = {c.name for c in AdminAgent.__table__.primary_key.columns}
        assert pk == {"id"}

    def test_jsonb_columns_have_empty_defaults(self):
        """JSONB 列必须带空默认值，避免 NULL 导致的解析分支。"""
        assert AdminAgent.__table__.columns["granted_permissions"].server_default.arg.text == "'[]'::jsonb"
        assert AdminAgent.__table__.columns["automation_policy"].server_default.arg.text == "'{}'::jsonb"
        assert AdminAgent.__table__.columns["budget_config"].server_default.arg.text == "'{}'::jsonb"

    def test_owner_fk_cascades(self):
        fks = list(AdminAgent.__table__.columns["owner_admin_user_id"].foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "admin_user.id"
        assert fks[0].ondelete == "CASCADE"

    def test_enabled_defaults_true(self):
        assert AdminAgent.__table__.columns["enabled"].server_default.arg.text == "true"
