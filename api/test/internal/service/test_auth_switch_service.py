from internal.service.auth_switch_service import (
    AUTH_CODES,
    DEFAULTS,
    _flag_enabled,
    get_auth_switches,
    validate_auth_switch_combination,
)


class _FlagRow:
    def __init__(self, enabled):
        self.enabled = enabled


class _FlagQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self._row


class _FlagSession:
    def __init__(self, rows_by_code):
        self._rows_by_code = rows_by_code

    def query(self, model):
        code = self._current_code
        return _FlagQuery(self._rows_by_code.get(code))

    def _for_code(self, code):
        self._current_code = code
        return self


class TestGetAuthSwitches:
    def test_reads_enabled_from_rows(self, monkeypatch):
        rows = {
            "AUTH_EMAIL_ENABLED": _FlagRow(True),
            "AUTH_PHONE_ENABLED": _FlagRow(False),
            "AUTH_LOGIN_CHALLENGE_ENABLED": _FlagRow(True),
        }

        def _fake_flag_enabled(session, code, default):
            row = rows.get(code)
            return bool(row.enabled) if row is not None else default

        monkeypatch.setattr("internal.service.auth_switch_service._flag_enabled", _fake_flag_enabled)
        assert get_auth_switches(session=object()) == {
            "AUTH_EMAIL_ENABLED": True,
            "AUTH_PHONE_ENABLED": False,
            "AUTH_LOGIN_CHALLENGE_ENABLED": True,
        }

    def test_falls_back_to_defaults_when_row_missing(self, monkeypatch):
        monkeypatch.setattr("internal.service.auth_switch_service._flag_enabled", lambda _s, code, default: default)
        assert get_auth_switches(session=object()) == dict(DEFAULTS)

    def test_defaults_match_expected_policy(self):
        assert DEFAULTS["AUTH_EMAIL_ENABLED"] is True
        assert DEFAULTS["AUTH_PHONE_ENABLED"] is False
        assert DEFAULTS["AUTH_LOGIN_CHALLENGE_ENABLED"] is True

    def test_auth_codes_covers_three_switches(self):
        assert set(AUTH_CODES) == set(DEFAULTS)


class TestFlagEnabled:
    def test_returns_row_enabled(self):
        session = _FlagSession({"AUTH_EMAIL_ENABLED": _FlagRow(True)})
        assert _flag_enabled(session._for_code("AUTH_EMAIL_ENABLED"), "AUTH_EMAIL_ENABLED", False) is True

    def test_returns_default_when_missing(self):
        session = _FlagSession({})
        assert _flag_enabled(session._for_code("AUTH_EMAIL_ENABLED"), "AUTH_EMAIL_ENABLED", False) is False

    def test_returns_default_on_query_error(self):
        class _BoomSession:
            def query(self, model):
                raise RuntimeError("db down")

        assert _flag_enabled(_BoomSession(), "AUTH_EMAIL_ENABLED", True) is True


class TestValidateAuthSwitchCombination:
    def test_challenge_on_with_all_channels_off_rejected(self):
        assert validate_auth_switch_combination(
            {"AUTH_EMAIL_ENABLED": False, "AUTH_PHONE_ENABLED": False, "AUTH_LOGIN_CHALLENGE_ENABLED": True}
        ) == "新IP验证开关需至少启用邮箱或手机号通道之一"

    def test_challenge_on_with_channel_on_passes(self):
        assert validate_auth_switch_combination(
            {"AUTH_EMAIL_ENABLED": True, "AUTH_PHONE_ENABLED": False, "AUTH_LOGIN_CHALLENGE_ENABLED": True}
        ) is None

    def test_challenge_off_passes(self):
        assert validate_auth_switch_combination(
            {"AUTH_EMAIL_ENABLED": False, "AUTH_PHONE_ENABLED": False, "AUTH_LOGIN_CHALLENGE_ENABLED": False}
        ) is None
