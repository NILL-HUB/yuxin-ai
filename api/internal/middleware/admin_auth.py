from functools import wraps

from flask import g, request

from internal.exception import ForbiddenException, UnauthorizedException
from internal.service.admin_user_service import AdminUserService


def extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if " " not in auth_header:
        raise UnauthorizedException("管理员接口需要授权才能访问")
    token_type, token = auth_header.split(None, 1)
    if token_type.lower() != "bearer" or not token:
        raise UnauthorizedException("管理员接口需要授权才能访问")
    return token


def admin_login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        token = extract_bearer_token()
        current_admin = AdminUserService().get_current_admin_from_token(token)
        g.current_admin_user = current_admin
        g.current_admin_roles = current_admin.get("roles", [])
        g.current_admin_permissions = current_admin.get("permissions", [])
        return view_func(*args, **kwargs)

    return wrapper


def permission_required(permission_code: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            permissions = set(getattr(g, "current_admin_permissions", []))
            if permission_code not in permissions:
                raise ForbiddenException("没有权限访问该管理功能")
            return view_func(*args, **kwargs)

        return wrapper

    return decorator
