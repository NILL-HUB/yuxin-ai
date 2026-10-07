from __future__ import annotations

import json
import os
import traceback
from typing import Any

# 技能/工作流代码执行器（腾讯云 SCF 函数侧实现）。
#
# 入参形态（两条调用路径，见 `_load_payload`）：
# - SDK 直调（`tencent_scf` 后端）：event 即 payload 本身；
# - HTTP 触发（`http_sandbox` 后端）：event["body"] 为 payload（字符串或对象）。
#
# 安全（纵深防御）：函数侧强制校验 SANDBOX_TOKEN 环境变量与 payload["token"] 一致；
# 未配置该环境变量时拒绝一切请求（fail-closed）。SDK 直调路径本身已由腾讯云
# IAM 签名保护，此校验用于兜住"日后有人给函数挂了公网触发器"的场景。

_REAL_IMPORT = __import__
# 技能包与工作流代码可用的标准库白名单。
# 注意：腾讯云 SCF 标准运行时**不预装任何第三方库**（实测 requests/numpy/PIL
# 均 ModuleNotFoundError），需要第三方依赖的技能/代码请改用 E2B 类后端，
# 或为函数打包层（Layer）/自定义镜像后再扩展此白名单。
_ALLOWED_IMPORTS = {
    "__future__",
    "base64",
    "collections",
    "contextlib",
    "copy",
    "csv",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "functools",
    "hashlib",
    "html",
    "importlib",
    "io",
    "itertools",
    "json",
    "math",
    "os",
    "pathlib",
    "random",
    "re",
    "secrets",
    "shlex",
    "statistics",
    "string",
    "tempfile",
    "textwrap",
    "time",
    "traceback",
    "typing",
    "urllib",
    "uuid",
}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root_name = str(name or "").split(".", 1)[0]
    if root_name not in _ALLOWED_IMPORTS:
        raise ImportError(f"Import {name!r} is not allowed")
    return _REAL_IMPORT(name, globals, locals, fromlist, level)


def _safe_builtins() -> dict[str, Any]:
    return {
        "__build_class__": __build_class__,
        "__import__": _safe_import,
        "abs": abs,
        "all": all,
        "any": any,
        "AttributeError": AttributeError,
        "BaseException": BaseException,
        "callable": callable,
        "classmethod": classmethod,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "Exception": Exception,
        "float": float,
        "getattr": getattr,
        "hasattr": hasattr,
        "int": int,
        "ImportError": ImportError,
        "IndexError": IndexError,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "len": len,
        "list": list,
        "KeyError": KeyError,
        "max": max,
        "min": min,
        "open": open,
        "object": object,
        "NotImplementedError": NotImplementedError,
        "print": print,
        "range": range,
        "property": property,
        "RuntimeError": RuntimeError,
        "setattr": setattr,
        "set": set,
        "sorted": sorted,
        "staticmethod": staticmethod,
        "str": str,
        "sum": sum,
        "super": super,
        "TypeError": TypeError,
        "type": type,
        "tuple": tuple,
        "ValueError": ValueError,
        "vars": vars,
        "zip": zip,
    }


def _load_payload(event: dict[str, Any]) -> dict[str, Any]:
    """统一取入参：兼容 SDK 直调（event 即 payload）与 HTTP 触发（body 包裹）。"""
    if not isinstance(event, dict):
        return {}
    body_raw = event.get("body")
    if body_raw is None:
        # SDK 直调（tencent_scf 后端）：event 就是 payload 本身
        return event
    if isinstance(body_raw, str):
        if not body_raw.strip():
            return {}
        return json.loads(body_raw)
    if isinstance(body_raw, dict):
        return body_raw
    return {}


def _build_default_sync_code(payload: dict[str, Any]) -> str:
    source_key = str(payload.get("source_key") or payload.get("skill", {}).get("source_key") or "").strip()
    version = payload.get("version")
    return (
        "def sync_package(payload):\n"
        "    return {\n"
        f"        'synced': True,\n"
        f"        'source_key': {source_key!r},\n"
        f"        'version': {version!r},\n"
        "    }\n"
    )


def _error_body(message: str, traceback_text: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"error": message}
    if traceback_text:
        payload["traceback"] = traceback_text
    return {
        "statusCode": 200,
        "body": json.dumps(payload, ensure_ascii=False, default=str),
    }


def _check_token(payload: dict[str, Any]) -> dict[str, Any] | None:
    """校验共享 token（fail-closed）：返回 None 表示通过，否则返回错误响应体。"""
    required = os.environ.get("SANDBOX_TOKEN", "").strip()
    if not required:
        return _error_body("unauthorized: SANDBOX_TOKEN not configured")
    if str(payload.get("token") or "").strip() != required:
        return _error_body("unauthorized: bad token")
    return None


def main_handler(event, context):
    try:
        body = _load_payload(event if isinstance(event, dict) else {})

        unauthorized = _check_token(body)
        if unauthorized is not None:
            return unauthorized

        action = str(body.get("action") or "").strip()
        code = str(body.get("code") or "").strip()
        func_name = str(body.get("func_name") or "").strip()
        args = body.get("args", [])
        kwargs = body.get("kwargs", {})

        if not code and action == "sync_package":
            code = _build_default_sync_code(body)
            func_name = func_name or "sync_package"
            if not args:
                args = [body.get("skill") or body]

        if not code:
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "error": "Missing code",
                    },
                    ensure_ascii=False,
                ),
            }

        if not func_name:
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "error": "Missing func_name",
                    },
                    ensure_ascii=False,
                ),
            }

        if not isinstance(args, list):
            args = [args]
        if not isinstance(kwargs, dict):
            kwargs = {}

        # 注入技能包 env（由平台侧解密后随请求传入），供 skill.py 内 os.environ 读取
        request_env = body.get("env")
        if isinstance(request_env, dict):
            for env_key, env_value in request_env.items():
                if isinstance(env_key, str) and env_key:
                    os.environ[env_key] = str(env_value)

        exec_globals: dict[str, Any] = {
            "__builtins__": _safe_builtins(),
            "__name__": "__scf_handler__",
        }
        exec(code, exec_globals, exec_globals)

        if func_name in exec_globals and callable(exec_globals[func_name]):
            result = exec_globals[func_name](*args, **kwargs)
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "result": result,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            }

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "error": "Function not found or not callable",
                },
                ensure_ascii=False,
            ),
        }
    except Exception as exc:
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
                default=str,
            ),
        }
