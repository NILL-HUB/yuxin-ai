"""EntityResolver 主体化（ADMIN-P3c-4 缺口十四c + 十五）。

不变量：`_retrieve_candidates` 的归属过滤从硬编码 `user_id` 属性改为
`MemoryOwnerKey` 访问器——用户态 `parse(裸uuid)` 产物 == 历史 `user_id`
字面量（逐字节等价）；admin 态走 `admin_user_id` + `agent_id`。

诚实披露（缺口十五）：本模块当前**无生产调用方**（仅 DI 注册）——本批仅
主体化查询，接线点（写入热路径 or consolidation RESOLVE）待产品决策。
"""

from uuid import uuid4

from internal.service.memory.entity_resolution import EntityResolver


class _StubDb:
    pass


class _RecordingSession:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, parameters=None, **binds):
        params = dict(parameters or {})
        params.update(binds)
        self.calls.append((cypher, params))
        return iter(self._rows)


class _Driver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


def _resolver() -> EntityResolver:
    return EntityResolver(db=_StubDb())


class TestRetrieveCandidatesOwnerScope:
    def test_user_binds_user_id_literal(self):
        """用户态：直接匹配与全文索引均按 user_id 字面量。"""
        session = _RecordingSession([])
        resolver = _resolver()
        uid = str(uuid4())

        resolver._retrieve_candidates(_Driver(session), "Python", "skill", uid)

        assert session.calls, "应有两次查询"
        direct_cypher, direct_params = session.calls[0]
        assert "user_id: $user_id" in direct_cypher
        assert direct_params["user_id"] == uid

    def test_admin_binds_admin_props(self):
        """admin 态：直接匹配与全文索引按 admin 属性（非 user_id）。"""
        session = _RecordingSession([])
        resolver = _resolver()
        admin_id = str(uuid4())

        resolver._retrieve_candidates(
            _Driver(session), "Python", "skill", f"admin:{admin_id}"
        )

        direct_cypher, direct_params = session.calls[0]
        # 直接匹配：type + is_active + admin 归属
        assert "user_id: $user_id" not in direct_cypher
        assert "admin_user_id" in direct_cypher
        assert direct_params["admin_user_id"] == admin_id
        assert direct_params["agent_id"] == "__admin_level__"

        # 全文索引补充：WHERE 按 admin 归属
        fulltext_cypher, fulltext_params = session.calls[1]
        assert "node.admin_user_id = $admin_user_id" in fulltext_cypher
        assert fulltext_params["admin_user_id"] == admin_id
