from internal.lib.mask_utils import mask_email, mask_phone


class TestMaskEmail:
    def test_mask_email_typical(self):
        assert mask_email("zhangsan@qq.com") == "zh***an@qq.com"

    def test_mask_email_short_local(self):
        assert mask_email("ab@qq.com") == "ab***@qq.com"
        assert mask_email("a@qq.com") == "a***@qq.com"

    def test_mask_email_without_at(self):
        assert mask_email("not-an-email") == "not-an-email"

    def test_mask_email_empty_and_whitespace(self):
        assert mask_email("") == ""
        assert mask_email("   ") == ""
        assert mask_email(None) == ""

    def test_mask_email_keeps_domain(self):
        assert mask_email("demo@example.com").endswith("@example.com")


class TestMaskPhone:
    def test_mask_phone_typical(self):
        assert mask_phone("13800138000") == "138****8000"

    def test_mask_phone_too_short(self):
        assert mask_phone("123456") == "123456"
        assert mask_phone("1234567") == "123****4567"

    def test_mask_phone_empty(self):
        assert mask_phone("") == ""
        assert mask_phone(None) == ""
