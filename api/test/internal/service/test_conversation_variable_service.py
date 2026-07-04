from datetime import UTC, datetime
from uuid import uuid4

from internal.service.conversation_variable_service import ConversationVariableService


# ------------------------------------------------------------------ #
#  Mock Session / Query                                               #
# ------------------------------------------------------------------ #

class _DummyQuery:
    """模拟 SQLAlchemy Query，支持 filter 链式调用和 all/one_or_none。

    通过解析 BinaryExpression 的 left.key 和 right.value 来提取过滤条件，
    然后对内存中的模型实例列表进行过滤。
    """

    def __init__(self, data, model):
        self._data = data  # 共享引用的模型实例列表
        self._model = model
        self._filters = []  # [(column_name, value), ...]

    def filter(self, *args):
        for arg in args:
            column_name = self._extract_column_name(arg)
            value = self._extract_value(arg)
            self._filters.append((column_name, value))
        return self

    @staticmethod
    def _extract_column_name(arg):
        """从 BinaryExpression 提取列名（Python 属性名）。"""
        left = arg.left
        return getattr(left, "key", None) or getattr(left, "name", None)

    @staticmethod
    def _extract_value(arg):
        """从 BinaryExpression 提取比较值。

        right 可能是 BindParameter（需取 .value），也可能是原始值。
        """
        right = arg.right
        if hasattr(right, "value"):
            return right.value
        return right

    def _apply_filters(self):
        result = list(self._data)
        for col, val in self._filters:
            result = [item for item in result if getattr(item, col, None) == val]
        return result

    def all(self):
        return self._apply_filters()

    def one_or_none(self):
        result = self._apply_filters()
        if len(result) == 0:
            return None
        return result[0]

    def order_by(self, *args):
        return self


class _DummySession:
    """模拟 SQLAlchemy Session，维护内存中的模型实例列表。"""

    def __init__(self):
        self._data = []
        self.commit_count = 0

    def query(self, model):
        return _DummyQuery(self._data, model)

    def add(self, obj):
        """添加模型实例，模拟 DB 设置 id/timestamps。"""
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        now = datetime.now(UTC).replace(tzinfo=None)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        self._data.append(obj)

    def delete(self, obj):
        if obj in self._data:
            self._data.remove(obj)

    def commit(self):
        self.commit_count += 1


def _make_service():
    """创建使用 mock session 的 ConversationVariableService 实例。"""
    session = _DummySession()
    return ConversationVariableService(session=session), session


# ------------------------------------------------------------------ #
#  测试用例                                                           #
# ------------------------------------------------------------------ #

class TestConversationVariableService:
    # --- set_variable ---

    def test_set_variable_should_create_new_variable(self):
        service, session = _make_service()
        conv_id = uuid4()

        result = service.set_variable(conv_id, "counter", 42, value_type="int")

        assert result["name"] == "counter"
        assert result["value_type"] == "int"
        assert result["value"] == 42
        assert result["conversation_id"] == str(conv_id)
        assert result["id"] is not None
        assert result["created_at"] is not None
        assert result["updated_at"] is not None
        assert len(session._data) == 1
        assert session.commit_count == 1

    def test_set_variable_should_update_existing_variable(self):
        service, session = _make_service()
        conv_id = uuid4()

        first = service.set_variable(conv_id, "status", "pending", value_type="string")
        second = service.set_variable(conv_id, "status", "done", value_type="string")

        assert len(session._data) == 1
        assert second["value"] == "done"
        assert second["id"] == first["id"]
        assert session.commit_count == 2

    def test_set_variable_should_auto_infer_type(self):
        service, _ = _make_service()
        conv_id = uuid4()

        # int（value_type="auto" 触发自动推断）
        r1 = service.set_variable(conv_id, "v_int", 42, value_type="auto")
        assert r1["value_type"] == "int"
        assert r1["value"] == 42

        # float
        r2 = service.set_variable(conv_id, "v_float", 3.14, value_type="auto")
        assert r2["value_type"] == "float"
        assert r2["value"] == 3.14

        # bool
        r3 = service.set_variable(conv_id, "v_bool", True, value_type="auto")
        assert r3["value_type"] == "boolean"
        assert r3["value"] is True

        # str
        r4 = service.set_variable(conv_id, "v_str", "hello", value_type="auto")
        assert r4["value_type"] == "string"
        assert r4["value"] == "hello"

        # dict → json
        r5 = service.set_variable(conv_id, "v_json", {"key": "value"}, value_type="auto")
        assert r5["value_type"] == "json"
        assert r5["value"] == {"key": "value"}

        # 空字符串也触发自动推断
        r6 = service.set_variable(conv_id, "v_empty_str", "text", value_type="")
        assert r6["value_type"] == "string"
        assert r6["value"] == "text"

    def test_set_variable_with_explicit_type_should_not_infer(self):
        service, _ = _make_service()
        conv_id = uuid4()

        # 显式指定 string，值为 int 42 → 应规范化为 "42"
        result = service.set_variable(conv_id, "v", 42, value_type="string")

        assert result["value_type"] == "string"
        assert result["value"] == "42"

    # --- get_variable ---

    def test_get_variable_should_return_none_when_not_exists(self):
        service, _ = _make_service()
        conv_id = uuid4()

        result = service.get_variable(conv_id, "missing")

        assert result is None

    def test_get_variable_should_return_dict_when_exists(self):
        service, _ = _make_service()
        conv_id = uuid4()
        service.set_variable(conv_id, "name", "test", value_type="string")

        result = service.get_variable(conv_id, "name")

        assert result is not None
        assert result["name"] == "name"
        assert result["value"] == "test"
        assert result["value_type"] == "string"

    # --- get_variable_value ---

    def test_get_variable_value_should_return_default_when_not_exists(self):
        service, _ = _make_service()
        conv_id = uuid4()

        result = service.get_variable_value(conv_id, "missing", default="fallback")

        assert result == "fallback"

    def test_get_variable_value_should_return_value_when_exists(self):
        service, _ = _make_service()
        conv_id = uuid4()
        service.set_variable(conv_id, "count", 10, value_type="int")

        result = service.get_variable_value(conv_id, "count")

        assert result == 10

    # --- get_variables ---

    def test_get_variables_should_return_all_for_conversation(self):
        service, _ = _make_service()
        conv_id = uuid4()
        other_conv = uuid4()
        service.set_variable(conv_id, "v1", 1, value_type="int")
        service.set_variable(conv_id, "v2", "hello", value_type="string")
        service.set_variable(other_conv, "v3", True, value_type="boolean")

        result = service.get_variables(conv_id)

        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"v1", "v2"}

    # --- delete_variable ---

    def test_delete_variable_should_return_true_when_exists(self):
        service, session = _make_service()
        conv_id = uuid4()
        service.set_variable(conv_id, "temp", "x", value_type="string")

        result = service.delete_variable(conv_id, "temp")

        assert result is True
        assert len(session._data) == 0
        assert session.commit_count == 2  # set_variable(1) + delete_variable(1)

    def test_delete_variable_should_return_false_when_not_exists(self):
        service, session = _make_service()
        conv_id = uuid4()

        result = service.delete_variable(conv_id, "missing")

        assert result is False
        assert session.commit_count == 0  # 不存在时不 commit

    # --- delete_variables_by_conversation ---

    def test_delete_variables_by_conversation_should_delete_all(self):
        service, session = _make_service()
        conv_id = uuid4()
        other_conv = uuid4()
        service.set_variable(conv_id, "v1", 1, value_type="int")
        service.set_variable(conv_id, "v2", 2, value_type="int")
        service.set_variable(conv_id, "v3", 3, value_type="int")
        service.set_variable(other_conv, "v_other", 99, value_type="int")

        count = service.delete_variables_by_conversation(conv_id)

        assert count == 3
        remaining = service.get_variables(conv_id)
        assert len(remaining) == 0
        # 其他会话的变量不受影响
        other_remaining = service.get_variables(other_conv)
        assert len(other_remaining) == 1

    # --- batch_set_variables ---

    def test_batch_set_variables_should_create_all(self):
        service, _ = _make_service()
        conv_id = uuid4()

        results = service.batch_set_variables(conv_id, {
            "v1": 1,
            "v2": "hello",
            "v3": True,
        })

        assert len(results) == 3
        names = {r["name"] for r in results}
        assert names == {"v1", "v2", "v3"}
        all_vars = service.get_variables(conv_id)
        assert len(all_vars) == 3

    def test_batch_set_variables_should_update_existing(self):
        service, _ = _make_service()
        conv_id = uuid4()
        service.set_variable(conv_id, "existing", "old", value_type="string")

        results = service.batch_set_variables(conv_id, {
            "existing": "new",
            "fresh": 42,
        })

        assert len(results) == 2
        existing_result = next(r for r in results if r["name"] == "existing")
        assert existing_result["value"] == "new"
        fresh_result = next(r for r in results if r["name"] == "fresh")
        assert fresh_result["value"] == 42
        all_vars = service.get_variables(conv_id)
        assert len(all_vars) == 2

    # --- to_pool_dict ---

    def test_to_pool_dict_should_return_name_value_mapping(self):
        service, _ = _make_service()
        conv_id = uuid4()
        service.set_variable(conv_id, "v1", 1, value_type="int")
        service.set_variable(conv_id, "v2", "hello", value_type="string")
        service.set_variable(conv_id, "v3", {"key": "val"})

        pool = service.to_pool_dict(conv_id)

        assert pool == {"v1": 1, "v2": "hello", "v3": {"key": "val"}}

    # --- _infer_value_type ---

    def test_infer_value_type_should_handle_bool_before_int(self):
        # bool 是 int 的子类，必须先检查 bool
        assert ConversationVariableService._infer_value_type(True) == "boolean"
        assert ConversationVariableService._infer_value_type(False) == "boolean"
        assert ConversationVariableService._infer_value_type(1) == "int"
        assert ConversationVariableService._infer_value_type(0) == "int"

    # --- _normalize_value ---

    def test_normalize_value_should_handle_none(self):
        assert ConversationVariableService._normalize_value(None, "string") is None
        assert ConversationVariableService._normalize_value(None, "int") is None
        assert ConversationVariableService._normalize_value(None, "json") is None
        assert ConversationVariableService._normalize_value(None, "boolean") is None
        assert ConversationVariableService._normalize_value(None, "float") is None
