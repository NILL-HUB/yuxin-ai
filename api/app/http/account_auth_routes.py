"""账号鉴权路由模块（从 asgi_app.py 拆分）：/account/*、/auth/*、/oauth/*、/upload-files/*。"""
from uuid import UUID

from quart import Response, request

from app.http import support as _support
from app.http.support import (
    _err,
    _int_arg,
    _json_resp,
    _ok,
    _ok_msg,
    _resolve_account,
    _to_thread,
)
from internal.service.account_service import AccountService

_registered = False


def _get_service(cls):
    return _support._get_service(cls)


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/account")
    async def async_get_current_user() -> Response:
        """async 获取当前账号信息。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.account_schema import GetCurrentUserResp

        account_service = _get_service(AccountService)
        data = {
            "id": account.id,
            "name": account.name,
            "email": account.email,
            "avatar": account.avatar,
            "last_login_at": account.last_login_at,
            "last_login_ip": account.last_login_ip,
            "last_login_location": await _to_thread(
                account_service.resolve_ip_location, account.last_login_ip
            ),
            "created_at": account.created_at,
            "password_set": account.is_password_set,
            "oauth_bindings": await _to_thread(
                account_service.get_account_oauth_bindings, account
            ),
        }
        return _ok(GetCurrentUserResp().dump(data))

    @quart_app.post("/account/password")
    async def async_update_password() -> Response:
        """async 更新账号密码。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        current_password = str(payload.get("current_password") or "")
        new_password = str(payload.get("new_password") or "")
        if not current_password or not new_password:
            return _err("invalid_param", "当前密码与新密码不能为空", 400)

        await _to_thread(
            _get_service(AccountService).change_password,
            account,
            current_password,
            new_password,
        )
        return _ok_msg("更新账号密码成功")

    @quart_app.post("/account/name")
    async def async_update_name() -> Response:
        """async 更新账号名称。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return _err("invalid_param", "账号名称不能为空", 400)

        await _to_thread(_get_service(AccountService).update_account, account, name=name)
        return _ok_msg("更新账号名称成功")

    @quart_app.post("/account/avatar")
    async def async_update_avatar() -> Response:
        """async 更新账号头像。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        avatar = str(payload.get("avatar") or "")
        if not avatar:
            return _err("invalid_param", "头像地址不能为空", 400)

        await _to_thread(_get_service(AccountService).update_account, account, avatar=avatar)
        return _ok_msg("更新账号头像成功")

    @quart_app.post("/account/email/send-code")
    async def async_send_change_email_code() -> Response:
        """async 发送换绑邮箱验证码。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        email = str(payload.get("email") or "")
        if not email:
            return _err("invalid_param", "邮箱不能为空", 400)

        await _to_thread(
            _get_service(AccountService).send_change_email_code, account, email
        )
        return _ok_msg("验证码已发送到新邮箱,请查收")

    @quart_app.post("/account/email")
    async def async_update_email() -> Response:
        """async 更新绑定邮箱。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True) or {}
        email = str(payload.get("email") or "")
        code = str(payload.get("code") or "")
        current_password = str(payload.get("current_password") or "")
        if not email or not code:
            return _err("invalid_param", "邮箱与验证码不能为空", 400)

        await _to_thread(
            _get_service(AccountService).update_email,
            account,
            email,
            code,
            current_password,
        )
        return _ok_msg("绑定邮箱更新成功")

    @quart_app.get("/account/sessions")
    async def async_get_account_sessions() -> Response:
        """async 获取账号登录会话列表。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.account_schema import GetAccountSessionsResp

        raw_session_id = request.args.get("session_id") or None
        current_session_id = UUID(str(raw_session_id)) if raw_session_id else None
        sessions = await _to_thread(
            _get_service(AccountService).get_account_sessions,
            account,
            current_session_id,
        )
        return _ok(
            GetAccountSessionsResp().dump(
                {
                    "session_capable": current_session_id is not None,
                    "current_session_id": current_session_id,
                    "sessions": sessions,
                }
            )
        )

    @quart_app.get("/account/login-history")
    async def async_get_account_login_history() -> Response:
        """async 获取账号登录历史。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.account_schema import GetAccountLoginHistoryResp

        raw_session_id = request.args.get("session_id") or None
        current_session_id = UUID(str(raw_session_id)) if raw_session_id else None

        history = await _to_thread(
            _get_service(AccountService).get_account_login_history,
            account,
            current_session_id,
            status=request.args.get("status") or None,
            search=request.args.get("search") or None,
            current_page=_int_arg("current_page", 1),
            page_size=_int_arg("page_size", 20),
        )
        return _ok(GetAccountLoginHistoryResp().dump(history))

    @quart_app.post("/account/sessions/revoke-others")
    async def async_revoke_other_account_sessions() -> Response:
        """async 撤销其他登录会话。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        raw_session_id = request.args.get("session_id") or None
        current_session_id = UUID(str(raw_session_id)) if raw_session_id else None
        await _to_thread(
            _get_service(AccountService).revoke_other_account_sessions,
            account,
            current_session_id,
        )
        return _ok_msg("其他登录设备已全部下线")

    @quart_app.post("/account/sessions/<uuid:session_id>/revoke")
    async def async_revoke_account_session(session_id) -> Response:
        """async 撤销指定登录会话。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        raw_session_id = request.args.get("session_id") or None
        current_session_id = UUID(str(raw_session_id)) if raw_session_id else None
        await _to_thread(
            _get_service(AccountService).revoke_account_session,
            account,
            session_id,
            current_session_id=current_session_id,
        )
        return _ok_msg("登录设备已下线")

    @quart_app.post("/account/oauth/<string:provider_name>/unbind")
    async def async_unbind_oauth(provider_name) -> Response:
        """async 解绑第三方登录。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.oauth_service import OAuthService

        await _to_thread(
            _get_service(OAuthService).unbind_oauth, account, provider_name
        )
        return _ok_msg("解绑第三方账号成功")

    @quart_app.post("/account/security/send-bind-phone-code")
    async def async_send_bind_phone_code() -> Response:
        """async 发送绑定手机号验证码。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        phone = str(payload.get("phone") or "").strip()
        if not phone:
            return _json_resp(
                code="validate_error",
                message="手机号不能为空",
                data={"phone": ["手机号不能为空"]},
                status=400,
            )
        phone = _get_service(AccountService).normalize_phone(phone)
        if not _get_service(AccountService).is_valid_phone(phone):
            return _json_resp(
                code="validate_error",
                message="手机号格式不正确",
                data={"phone": ["手机号格式不正确"]},
                status=400,
            )
        await _to_thread(
            _get_service(AccountService).send_bind_phone_code, account, phone=phone
        )
        return _ok_msg("验证码已发送")

    @quart_app.post("/account/security/bind-phone")
    async def async_bind_phone() -> Response:
        """async 绑定手机号。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        phone = str(payload.get("phone") or "").strip()
        code = str(payload.get("code") or "")
        if not phone or not code:
            return _json_resp(
                code="validate_error",
                message="手机号与验证码不能为空",
                data={"phone": ["手机号与验证码不能为空"]},
                status=400,
            )
        phone = _get_service(AccountService).normalize_phone(phone)
        if not _get_service(AccountService).is_valid_phone(phone):
            return _json_resp(
                code="validate_error",
                message="手机号格式不正确",
                data={"phone": ["手机号格式不正确"]},
                status=400,
            )
        await _to_thread(
            _get_service(AccountService).bind_phone, account, phone=phone, code=code
        )
        return _ok_msg("手机号绑定成功")

    @quart_app.post("/account/security/unbind-phone")
    async def async_unbind_phone() -> Response:
        """async 解绑手机号。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        code = str(payload.get("code") or "")
        if not code:
            return _json_resp(
                code="validate_error",
                message="验证码不能为空",
                data={"code": ["验证码不能为空"]},
                status=400,
            )
        await _to_thread(_get_service(AccountService).unbind_phone, account, code=code)
        return _ok_msg("手机号解绑成功")

    @quart_app.post("/account/security/send-verify-email-code")
    async def async_send_verify_email_code() -> Response:
        """async 发送邮箱验证码。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        await _to_thread(_get_service(AccountService).send_verify_email_code, account)
        return _ok_msg("验证码已发送")

    @quart_app.post("/account/security/verify-email")
    async def async_verify_email() -> Response:
        """async 验证邮箱。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        code = str(payload.get("code") or "")
        if not code:
            return _json_resp(
                code="validate_error",
                message="验证码不能为空",
                data={"code": ["验证码不能为空"]},
                status=400,
            )
        await _to_thread(_get_service(AccountService).verify_email, account, code=code)
        return _ok_msg("邮箱验证成功")

    @quart_app.get("/auth/login-methods")
    async def async_login_methods() -> Response:
        """获取当前启用的登录方式开关。"""
        payload = await _to_thread(_get_service(AccountService).login_methods)
        return _ok(payload)

    @quart_app.post("/auth/password-login")
    async def async_password_login() -> Response:
        """async 账号密码登录。"""
        from internal.schema.auth_schema import PasswordLoginResp

        payload = await request.get_json(force=True, silent=True) or {}
        identifier = str(payload.get("identifier") or payload.get("email") or "").strip()
        password = str(payload.get("password") or "")
        if not identifier or not password:
            return _json_resp(
                code="validate_error",
                message="账号与密码不能为空",
                data={"identifier": ["账号与密码不能为空"]},
                status=400,
            )
        credential = await _to_thread(
            _get_service(AccountService).password_login, identifier, password
        )
        return _ok(PasswordLoginResp().dump(credential))

    @quart_app.post("/auth/register/prepare")
    async def async_prepare_register() -> Response:
        """async 发送注册验证码。"""
        payload = await request.get_json(force=True, silent=True) or {}
        email = str(payload.get("email") or "").strip()
        password = str(payload.get("password") or "")
        if not email or not password:
            return _json_resp(
                code="validate_error",
                message="邮箱与密码不能为空",
                data={"email": ["邮箱与密码不能为空"]},
                status=400,
            )
        await _to_thread(
            _get_service(AccountService).prepare_register,
            email,
            password,
            username=str(payload.get("username") or "").strip() or None,
        )
        return _ok_msg("验证码已发送到您的邮箱,请查收")

    @quart_app.post("/auth/register/direct")
    async def async_direct_register() -> Response:
        """async 直接注册（无需邮箱验证码）。"""
        from internal.schema.auth_schema import PasswordLoginResp

        payload = await request.get_json(force=True, silent=True) or {}
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        if not username or not password:
            return _json_resp(
                code="validate_error",
                message="用户名与密码不能为空",
                data={"username": ["用户名与密码不能为空"]},
                status=400,
            )
        credential = await _to_thread(
            _get_service(AccountService).direct_register,
            username,
            password,
            str(payload.get("invite_code") or "").strip(),
        )
        return _ok(PasswordLoginResp().dump(credential))

    @quart_app.post("/auth/register/verify")
    async def async_verify_register() -> Response:
        """async 校验注册验证码并创建账号。"""
        from internal.schema.auth_schema import PasswordLoginResp

        payload = await request.get_json(force=True, silent=True) or {}
        email = str(payload.get("email") or "").strip()
        password = str(payload.get("password") or "")
        code = str(payload.get("code") or "")
        if not email or not password or not code:
            return _json_resp(
                code="validate_error",
                message="邮箱/密码/验证码不能为空",
                data={"email": ["邮箱/密码/验证码不能为空"]},
                status=400,
            )
        credential = await _to_thread(
            _get_service(AccountService).register_by_email_code,
            email,
            password,
            code,
            str(payload.get("username") or "").strip() or None,
            str(payload.get("invite_code") or "").strip(),
        )
        return _ok(PasswordLoginResp().dump(credential))

    @quart_app.get("/auth/register/invite-info")
    async def async_register_invite_info() -> Response:
        """校验邀请码有效性并返回注册必填状态（扫码/分享链接预填用）。"""
        from internal.schema.distribution_schema import InviteInfoResp
        from internal.service.distribution_service import DistributionService

        code = str(request.args.get("code") or "").strip()
        result = await _to_thread(_get_service(DistributionService).invite_info, code)
        return _ok(InviteInfoResp().dump(result))

    @quart_app.post("/auth/logout")
    async def async_auth_logout() -> Response:
        """async 退出登录。"""
        raw_session_id = request.args.get("session_id") or ""
        if raw_session_id:
            account, err = await _resolve_account()
            if err is not None:
                return err
            try:
                session_id = UUID(str(raw_session_id))
            except (ValueError, TypeError):
                return _ok_msg("退出登陆成功")
            await _to_thread(
                _get_service(AccountService).revoke_account_session,
                account,
                session_id,
                current_session_id=session_id,
                allow_current=True,
            )
        return _ok_msg("退出登陆成功")

    @quart_app.post("/auth/send-reset-code")
    async def async_send_reset_code() -> Response:
        """async 发送密码重置验证码。"""
        payload = await request.get_json(force=True, silent=True) or {}
        email = str(payload.get("email") or "").strip()
        if not email:
            return _json_resp(
                code="validate_error",
                message="邮箱不能为空",
                data={"email": ["邮箱不能为空"]},
                status=400,
            )
        await _to_thread(_get_service(AccountService).send_reset_code, email)
        return _ok_msg("如果该邮箱已注册，验证码已发送，请查收")

    @quart_app.post("/auth/reset-password")
    async def async_reset_password() -> Response:
        """async 重置密码。"""
        payload = await request.get_json(force=True, silent=True) or {}
        email = str(payload.get("email") or "").strip()
        code = str(payload.get("code") or "")
        new_password = str(payload.get("new_password") or "")
        if not email or not code or not new_password:
            return _json_resp(
                code="validate_error",
                message="邮箱/验证码/新密码不能为空",
                data={"email": ["邮箱/验证码/新密码不能为空"]},
                status=400,
            )
        await _to_thread(
            _get_service(AccountService).reset_password, email, code, new_password
        )
        return _ok_msg("密码重置成功,请使用新密码登录")

    @quart_app.post("/auth/login-challenge/verify")
    async def async_verify_login_challenge() -> Response:
        """async 完成异常登录的二次验证码校验。"""
        from internal.schema.auth_schema import PasswordLoginResp

        payload = await request.get_json(force=True, silent=True) or {}
        challenge_id = str(payload.get("challenge_id") or "")
        code = str(payload.get("code") or "")
        if not challenge_id or not code:
            return _json_resp(
                code="validate_error",
                message="challenge_id 与验证码不能为空",
                data={"challenge_id": ["challenge_id 与验证码不能为空"]},
                status=400,
            )
        credential = await _to_thread(
            _get_service(AccountService).verify_login_challenge, challenge_id, code
        )
        return _ok(PasswordLoginResp().dump(credential))

    @quart_app.post("/auth/login-challenge/resend")
    async def async_resend_login_challenge() -> Response:
        """async 重发异常登录的二次验证码。"""
        payload = await request.get_json(force=True, silent=True) or {}
        challenge_id = str(payload.get("challenge_id") or "")
        if not challenge_id:
            return _json_resp(
                code="validate_error",
                message="challenge_id 不能为空",
                data={"challenge_id": ["challenge_id 不能为空"]},
                status=400,
            )
        await _to_thread(
            _get_service(AccountService).resend_login_challenge, challenge_id
        )
        return _ok_msg("验证码已发送到您的邮箱,请查收")

    @quart_app.post("/auth/send-code")
    async def async_send_code() -> Response:
        """async 统一验证码发送入口（邮箱/手机号通道）。"""
        from internal.service.email_service import EmailService

        allowed_scenes = {
            "login_challenge",
            "phone_register",
            "phone_login",
            "phone_bind",
            "email_login",
            "email_verify",
            "password_reset",
            "change_email",
            "register",
        }
        payload = await request.get_json(force=True, silent=True) or {}
        scene = str(payload.get("scene") or "").strip()
        if scene not in allowed_scenes:
            return _json_resp(
                code="validate_error",
                message="scene 不合法",
                data={"scene": [f"scene 仅支持 {'/'.join(sorted(allowed_scenes))}"]},
                status=400,
            )
        email = str(payload.get("email") or "").strip()
        phone = str(payload.get("phone") or "").strip()
        if phone:
            phone = _get_service(AccountService).normalize_phone(phone)
            if not _get_service(AccountService).is_valid_phone(phone):
                return _json_resp(
                    code="validate_error",
                    message="手机号格式不正确",
                    data={"phone": ["手机号格式不正确"]},
                    status=400,
                )
        if not email and not phone:
            return _json_resp(
                code="validate_error",
                message="email/phone 至少提供一个",
                data={"email": ["email/phone 至少提供一个"]},
                status=400,
            )
        await _to_thread(
            _get_service(EmailService).send_code,
            scene,
            email=email or None,
            phone=phone or None,
        )
        return _ok_msg("验证码已发送")

    @quart_app.post("/auth/phone-code-login")
    async def async_phone_code_login() -> Response:
        """async 手机号验证码登录。"""
        from internal.schema.auth_schema import PasswordLoginResp

        payload = await request.get_json(force=True, silent=True) or {}
        phone = str(payload.get("phone") or "").strip()
        code = str(payload.get("code") or "")
        if not phone or not code:
            return _json_resp(
                code="validate_error",
                message="手机号与验证码不能为空",
                data={"phone": ["手机号与验证码不能为空"]},
                status=400,
            )
        phone = _get_service(AccountService).normalize_phone(phone)
        if not _get_service(AccountService).is_valid_phone(phone):
            return _json_resp(
                code="validate_error",
                message="手机号格式不正确",
                data={"phone": ["手机号格式不正确"]},
                status=400,
            )
        credential = await _to_thread(
            _get_service(AccountService).phone_code_login, phone, code
        )
        return _ok(PasswordLoginResp().dump(credential))

    @quart_app.post("/auth/email-code-login")
    async def async_email_code_login() -> Response:
        """async 邮箱验证码登录。"""
        from internal.schema.auth_schema import PasswordLoginResp

        payload = await request.get_json(force=True, silent=True) or {}
        email = str(payload.get("email") or "").strip()
        code = str(payload.get("code") or "")
        if not email or not code:
            return _json_resp(
                code="validate_error",
                message="邮箱与验证码不能为空",
                data={"email": ["邮箱与验证码不能为空"]},
                status=400,
            )
        credential = await _to_thread(
            _get_service(AccountService).email_code_login, email, code
        )
        return _ok(PasswordLoginResp().dump(credential))

    @quart_app.post("/auth/register/phone-prepare")
    async def async_phone_register_prepare() -> Response:
        """async 手机号注册：发送注册验证码。"""
        from internal.service.email_service import EmailService

        payload = await request.get_json(force=True, silent=True) or {}
        phone = str(payload.get("phone") or "").strip()
        if not phone:
            return _json_resp(
                code="validate_error",
                message="手机号不能为空",
                data={"phone": ["手机号不能为空"]},
                status=400,
            )
        phone = _get_service(AccountService).normalize_phone(phone)
        if not _get_service(AccountService).is_valid_phone(phone):
            return _json_resp(
                code="validate_error",
                message="手机号格式不正确",
                data={"phone": ["手机号格式不正确"]},
                status=400,
            )
        await _to_thread(
            _get_service(EmailService).send_code,
            EmailService.PHONE_REGISTER_SCENE,
            email=None,
            phone=phone,
        )
        return _ok_msg("验证码已发送")

    @quart_app.post("/auth/register/phone-verify")
    async def async_phone_register_verify() -> Response:
        """async 手机号注册：校验验证码并创建账号。"""
        from internal.schema.auth_schema import PasswordLoginResp

        payload = await request.get_json(force=True, silent=True) or {}
        phone = str(payload.get("phone") or "").strip()
        code = str(payload.get("code") or "")
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        if not phone or not code:
            return _json_resp(
                code="validate_error",
                message="手机号与验证码不能为空",
                data={"phone": ["手机号与验证码不能为空"]},
                status=400,
            )
        phone = _get_service(AccountService).normalize_phone(phone)
        if not _get_service(AccountService).is_valid_phone(phone):
            return _json_resp(
                code="validate_error",
                message="手机号格式不正确",
                data={"phone": ["手机号格式不正确"]},
                status=400,
            )
        credential = await _to_thread(
            _get_service(AccountService).phone_register,
            phone=phone,
            code=code,
            username=username,
            password=password,
        )
        return _ok(PasswordLoginResp().dump(credential))

    @quart_app.get("/oauth/<string:provider_name>")
    async def async_oauth_provider(provider_name) -> Response:
        """async OAuth 授权入口（返回重定向地址）。"""
        from internal.service import OAuthService

        oauth = await _to_thread(
            _get_service(OAuthService).get_oauth_by_provider_name, provider_name
        )
        redirect_url = await _to_thread(oauth.get_authorization_url)
        return _ok({"redirect_url": redirect_url})

    @quart_app.post("/oauth/authorize/<string:provider_name>")
    async def async_oauth_authorize(provider_name) -> Response:
        """async OAuth 授权回调。"""
        from internal.schema.oauth_schema import AuthorizeResp
        from internal.service import OAuthService

        data = await request.get_json(force=True, silent=True) or {}
        code = str(data.get("code") or request.args.get("code") or "")
        if not code:
            return _json_resp(
                code="validate_error",
                message="授权 code 不能为空",
                data={"code": ["授权 code 不能为空"]},
                status=400,
            )
        intent = str(data.get("intent") or "login")
        if intent == "bind":
            account, err = await _resolve_account()
            if err is not None:
                return err
            credential = await _to_thread(
                _get_service(OAuthService).bind_oauth,
                account,
                provider_name,
                code,
                current_session=None,
            )
        else:
            credential = await _to_thread(
                _get_service(OAuthService).oauth_login, provider_name, code
            )
        return _ok(AuthorizeResp().dump(credential))

    @quart_app.post("/upload-files/file")
    async def async_upload_file() -> Response:
        """async 上传文件/文档。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.schema.upload_file_schema import UploadFileResp
        from internal.service import CosService

        files = await request.files
        file = files.get("file")
        if file is None or not file.filename:
            return _json_resp(
                code="validate_error",
                message="请选择要上传的文件",
                data={"file": ["请选择要上传的文件"]},
                status=400,
            )
        upload_file = await _to_thread(
            _get_service(CosService).upload_file, file, False, account
        )
        return _ok(UploadFileResp().dump(upload_file))

    @quart_app.post("/upload-files/image")
    async def async_upload_image() -> Response:
        """async 上传图片。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import CosService

        files = await request.files
        file = files.get("file")
        if file is None or not file.filename:
            return _json_resp(
                code="validate_error",
                message="请选择要上传的图片",
                data={"file": ["请选择要上传的图片"]},
                status=400,
            )
        upload_file = await _to_thread(
            _get_service(CosService).upload_file, file, True, account
        )
        image_url = await _to_thread(
            _get_service(CosService).get_file_url, upload_file.key
        )
        return _ok({"image_url": image_url})
