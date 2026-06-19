from unittest.mock import MagicMock

from internal.entity.orchestrator_entity import RequestContext
from internal.model.billing import CreditAccount
from internal.service.request_context_builder_service import RequestContextBuilder


def test_build_should_normalize_query_and_map_account_context():
    ctx = RequestContextBuilder().build(
        "  帮我查询天气  ",
        account_id="acc-1",
        conversation_id="conv-1",
        message_id="msg-1",
    )

    assert isinstance(ctx, RequestContext)
    assert ctx.query == "帮我查询天气"
    assert ctx.account_id == "acc-1"
    assert ctx.conversation_id == "conv-1"
    assert ctx.message_id == "msg-1"


def test_build_should_map_enable_deep_thinking_to_deep_thinking_requested():
    ctx = RequestContextBuilder().build("query", enable_deep_thinking=True)

    assert ctx.enable_deep_thinking is True
    assert ctx.deep_thinking_requested is True


def test_build_should_default_deep_thinking_requested_to_false():
    ctx = RequestContextBuilder().build("query")

    assert ctx.enable_deep_thinking is False
    assert ctx.deep_thinking_requested is False


def test_build_should_validate_budget_level_and_default_unknown_values():
    assert RequestContextBuilder().build("q", budget_level="low").budget_level == "low"
    assert RequestContextBuilder().build("q", budget_level="high").budget_level == "high"
    assert RequestContextBuilder().build("q", budget_level="normal").budget_level == "normal"
    assert RequestContextBuilder().build("q", budget_level="bogus").budget_level == "normal"
    assert RequestContextBuilder().build("q").budget_level == "normal"


def test_build_should_coerce_balance_credits_override():
    assert RequestContextBuilder().build("q", balance_credits=5).balance_credits == 5.0
    assert RequestContextBuilder().build("q", balance_credits="2.5").balance_credits == 2.5
    assert RequestContextBuilder().build("q", balance_credits=-3).balance_credits == 0.0


def test_build_should_default_balance_to_zero_without_db():
    assert RequestContextBuilder().build("q").balance_credits == 0.0
    assert RequestContextBuilder().build("q", balance_credits="not-a-number").balance_credits == 0.0


def test_build_should_filter_non_string_image_urls():
    ctx = RequestContextBuilder().build(
        "q", image_urls=["http://a/1.png", 123, "  ", "http://b/2.png"]
    )

    assert ctx.image_urls == ["http://a/1.png", "http://b/2.png"]


def test_to_safe_dict_should_not_leak_raw_image_urls():
    ctx = RequestContextBuilder().build(
        "q", image_urls=["http://a/1.png", "http://b/2.png"], account_id="acc-1"
    )

    safe = ctx.to_safe_dict()

    assert safe["image_url_count"] == 2
    assert "image_urls" not in safe
    assert safe["query"] == "q"
    assert safe["account_id"] == "acc-1"


class TestRequestContextBuilderBalance:
    def test_should_query_credit_account_balance(self):
        db = MagicMock()
        credit_account = MagicMock()
        credit_account.get_balance.return_value = 5000
        db.session.query.return_value.filter_by.return_value.first.return_value = credit_account
        builder = RequestContextBuilder(db=db)
        ctx = builder.build("query", account_id="acc-123")
        assert ctx.balance_credits == 5000.0
        assert ctx.budget_allowed is True

    def test_should_return_zero_when_no_credit_account(self):
        db = MagicMock()
        db.session.query.return_value.filter_by.return_value.first.return_value = None
        builder = RequestContextBuilder(db=db)
        ctx = builder.build("query", account_id="acc-123")
        assert ctx.balance_credits == 0.0
        assert ctx.budget_allowed is False

    def test_should_return_zero_on_db_exception(self):
        db = MagicMock()
        db.session.query.side_effect = RuntimeError("db down")
        builder = RequestContextBuilder(db=db)
        ctx = builder.build("query", account_id="acc-123")
        assert ctx.balance_credits == 0.0
        assert ctx.budget_allowed is False

    def test_budget_allowed_should_be_false_when_balance_below_threshold(self):
        db = MagicMock()
        credit_account = MagicMock()
        credit_account.get_balance.return_value = 0
        db.session.query.return_value.filter_by.return_value.first.return_value = credit_account
        builder = RequestContextBuilder(db=db)
        ctx = builder.build("query", account_id="acc-123")
        assert ctx.budget_allowed is False
