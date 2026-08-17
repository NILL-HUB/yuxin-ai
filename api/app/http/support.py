"""app.http 公共支撑模块：Quart 路由复用的 helper 集中地（从 asgi_app.py 拆出）。

职责：
- 统一响应出口（_json_resp / _ok / _ok_msg / _err）
- 鉴权（_resolve_account）与账号加载（_load_account / _load_runtime_context）
- 桥接（_to_thread：同步 service 移入线程池 + 运行时容器上下文）
- SSE 流式（_sse_response：同步生成器 → async SSE，含心跳与活性超时）
- 表单校验辅助（_field / _int_arg）
- service 获取（_get_service / _get_services / _get_conversation_service，集中缓存）
"""

import asyncio
import contextvars
import json
import logging
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

from quart import Response, request

from app.http.app import app as flask_app
from app.http.module import injector
from internal.service.account_service import AccountService
from internal.service.app_runtime_service import AppRuntimeService
from internal.service.app_service import AppService
from internal.service.language_model_service import LanguageModelService

logger = logging.getLogger(__name__)

_services = None
_conversation_service = None
_service_cache = {}


def _get_services():
    """惰性获取运行时服务单例。

    延迟到首次请求时再通过 injector 实例化，避免模块导入阶段
    构建整棵依赖树（测试环境可替换本函数以注入替身）。
    """
    global _services
    if _services is None:
        _services = (
            injector.get(AppRuntimeService),
            injector.get(LanguageModelService),
            injector.get(AccountService),
            injector.get(AppService),
        )
    return _services


def _load_runtime_context(app_id, account_id, image_urls):
    """在运行时容器上下文中加载 account / draft_app_config / async llm。

    同步 DB 操作集中在线程中执行（配合 asyncio.to_thread 调用），
    避免阻塞 uvicorn 事件循环。
    """
    _services = _get_services()
    language_model_service, account_service, app_service = _services[1], _services[2], _services[3]
    with flask_app.app_context():
        account = account_service.get_account(account_id)
        draft_app_config = app_service.get_draft_app_config(app_id, account)
        resolution = language_model_service.resolve_runtime_language_model(
            draft_app_config.get("model_config") or {},
            image_urls=image_urls,
            entrypoint=LanguageModelService.ENTRYPOINT_WEB_APP,
            use_async_class=True,
        )
        return account, draft_app_config, resolution.llm


def _load_account(account_id):
    """在线程中加载 account（同步 DB 访问，配合 asyncio.to_thread 调用）。"""
    _services = _get_services()
    account_service = _services[2]
    with flask_app.app_context():
        return account_service.get_account(account_id)


def _get_conversation_service():
    """惰性获取 ConversationService 单例（测试可替换）。"""
    global _conversation_service
    if _conversation_service is None:
        from internal.service.conversation_service import ConversationService

        _conversation_service = injector.get(ConversationService)
    return _conversation_service


def _get_service(cls):
    """按类型惰性获取 injector 服务单例（测试可替换 _service_cache）。"""
    if cls not in _service_cache:
        _service_cache[cls] = injector.get(cls)
    return _service_cache[cls]


def _json_resp(data=None, code="success", message="", status=200):
    """统一 JSON 响应（与 Flask 侧 HttpCode 契约一致：业务码为字符串）。

    成功业务码使用 HttpCode.SUCCESS 的字符串值 "success"（与前端 isApiResponse
    的 typeof code === 'string' 校验匹配）；status 为 HTTP 状态码（数字）。
    """
    return Response(
        json.dumps({"code": code, "message": message, "data": data}, ensure_ascii=False, default=str),
        mimetype="application/json",
        status=status,
    )


def _ok(data=None):
    return _json_resp(data)


def _ok_msg(message):
    return _json_resp(None, message=message)


def _err(code, message, status=400):
    return _json_resp(None, code=code, message=message, status=status)


def _is_sync_iterator(obj):
    """判断返回值是否为同步生成器/迭代器（用于 SSE 流式响应）。"""
    return not isinstance(obj, (dict, list, str, int, float, bool, type(None))) and hasattr(
        obj, "__next__"
    )


SSE_HEARTBEAT_INTERVAL = 15.0  # 单帧静默超过该时长输出心跳注释帧，维持连接活性
SSE_ACTIVITY_TIMEOUT = 60.0    # 连续无帧产出超过该时长判定生成器失活（探针式超时）


def _sse_response(generator):
    """把同步生成器转成 async SSE 响应流。

    生成器在 to_thread 线程 + 运行时容器上下文中逐步迭代，
    保证内部对 current_app / DB session 的访问可用，且不阻塞 uvicorn 事件循环。

    活性保障（复用 LLMActivityProbe 的活性探针思路）：
    - 心跳帧：单帧执行超过 SSE_HEARTBEAT_INTERVAL 时输出 ": keep-alive" 注释帧，
      避免 nginx send_timeout（默认 60s）在 LLM 长静默期切断浏览器连接；
    - 活性探针：连续无帧产出超过 SSE_ACTIVITY_TIMEOUT 判定生成器失活，
      输出错误帧并关闭生成器；
    - 断连协作：客户端断开（CancelledError）时调用 generator.close()，
      触发生成器 finally 落库，避免孤儿线程继续运行。
    """
    from app.http.app import app as _flask_app

    def _next_in_context(gen):
        with _flask_app.app_context():
            try:
                return next(gen)
            except StopIteration:
                return None
            finally:
                from internal.extension.database_extension import db

                remove_session = getattr(db.session, "remove", None)
                if callable(remove_session):
                    remove_session()

    async def _stream():
        last_activity = time.monotonic()
        try:
            while True:
                # 每帧单独一个 task：心跳等待期间不并发 next，保证生成器线程安全
                frame_task = asyncio.create_task(
                    asyncio.to_thread(_next_in_context, generator)
                )
                try:
                    while True:
                        done, _ = await asyncio.wait(
                            {frame_task}, timeout=SSE_HEARTBEAT_INTERVAL
                        )
                        if done:
                            break
                        # 静默期：先输出心跳帧保持连接活性
                        yield ": keep-alive\n\n"
                        if time.monotonic() - last_activity >= SSE_ACTIVITY_TIMEOUT:
                            payload = {
                                "event": "error",
                                "data": {
                                    "code": "stream_idle_timeout",
                                    "message": "生成器长时间无响应，已终止",
                                },
                            }
                            yield f"event: error\ndata:{json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                            try:
                                generator.close()
                            except Exception:
                                pass
                            return
                finally:
                    # 心跳等待期间若被取消（客户端断连），取消未完成的帧任务
                    frame_task.cancel()
                frame = frame_task.result()
                if frame is None:
                    break
                last_activity = time.monotonic()
                yield frame
        except asyncio.CancelledError:
            # 客户端断连：协作关闭生成器（触发 finally 落库），避免孤儿线程
            try:
                generator.close()
            except Exception:
                pass
            raise
        except Exception as error:
            logging.exception("异步流式响应生成失败: %s", error)
            try:
                from internal.core.agent.failure_utils import (
                    build_failure_observation,
                    classify_failure_event,
                )

                failure_event = classify_failure_event(error)
                payload = {
                    "event": failure_event.value,
                    "observation": build_failure_observation(error, "异步流式响应执行失败"),
                }
                yield f"event: {failure_event.value}\ndata:{json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            except Exception:
                pass

    sse_response = Response(_stream(), mimetype="text/event-stream")
    sse_response.headers["Cache-Control"] = "no-cache"
    sse_response.headers["Connection"] = "keep-alive"
    sse_response.headers["X-Accel-Buffering"] = "no"
    return sse_response


async def _resolve_account(account_id_override: str | None = None):
    """从 Authorization Bearer token 解析账号并加载。

    凭证优先级（修复 Flask→Quart 迁移后的鉴权/断流问题）：
    1. 用户 JWT：sub 即 account_id；若请求显式携带 account_id，则必须一致（防冒用）。
    2. 管理员 JWT：放行，account_id 以请求参数为准（管理员调试任意应用的场景）。
    3. 无 token：仅当显式携带 account_id 时回退加载（公开端点兼容），否则 401。

    返回 (account, None) 或 (None, 错误响应)。
    """
    from internal.exception import UnauthorizedException

    raw = (
        account_id_override
        or request.args.get("account_id")
        or request.headers.get("X-Account-Id")
        or ""
    )
    requested_id = None
    if raw:
        try:
            requested_id = str(UUID(str(raw)))
        except (ValueError, TypeError):
            return None, _err("invalid_param", "account_id 参数无效", 400)

    auth_header = request.headers.get("Authorization") or ""
    token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""

    if token:
        # 1) 用户 JWT（优先：sub 即账号 ID；admin token 带 realm=admin，跳过）
        try:
            from internal.service.jwt_service import JwtService

            payload = JwtService.parse_token(token)
            if payload.get("realm") != "admin":
                account_id = str(payload.get("sub") or "")
                if account_id and account_id.lower() != "none":
                    if _is_user_api_blocked(request.path, request.method):
                        return None, _err("forbidden", "该接口仅管理员可用", 403)
                    if requested_id and requested_id != account_id:
                        return None, _err("forbidden", "无权访问该账号", 403)
                    try:
                        await _to_thread(
                            _get_services()[2].validate_access_session,
                            payload,
                        )
                    except UnauthorizedException:
                        return None, _err("unauthorized", "登录会话已失效，请重新登录", 401)
                    account = await asyncio.to_thread(_load_account, UUID(account_id))
                    return account, None
        except UnauthorizedException:
            pass
        except Exception:
            logger.exception("async 端点解析用户凭证失败")
            return None, _err("unauthorized", "登录凭证无效", 401)

        # 2) 管理员 JWT（用户 token 解析失败时尝试）
        try:
            from internal.service.admin_user_service import AdminUserService

            admin = await _to_thread(
                _get_service(AdminUserService).get_current_admin_from_token, token
            )
            if not admin:
                return None, _err("unauthorized", "管理员凭证无效", 401)
            if not requested_id:
                admin_account_id = (
                    admin.get("account_id")
                    if isinstance(admin, dict)
                    else getattr(admin, "account_id", None)
                )
                if not admin_account_id:
                    return None, _err("invalid_param", "缺少 account_id 参数", 400)
                requested_id = str(admin_account_id)
            account = await asyncio.to_thread(_load_account, UUID(requested_id))
            return account, None
        except UnauthorizedException:
            return None, _err("unauthorized", "管理员凭证无效", 401)
        except Exception:
            logger.exception("async 端点解析管理员凭证失败")
            return None, _err("unauthorized", "登录凭证无效", 401)

    # 3) 无 token：仅允许公开只读端点显式携带 account_id 时回退，否则拒绝。
    #    - 写操作一律拒绝：防止匿名攻击者仅凭目标 account_id 冒充任意账号执行
    #      修改/创建/删除（C-1 认证绕过修复）。
    #    - 读操作同样执行 _is_user_api_blocked 封锁检查：用户端已收敛的接口
    #      （/apps、/workflows、/api-tools 等）即使带 account_id 也不放行。
    #    - 真正的公开端点（/public/*、/web-apps/<token> 等）不依赖本回退，
    #      它们显式使用 account=None 或 _resolve_webapp_actor，行为不受影响。
    if not requested_id:
        return None, _err("unauthorized", "未登录或登录已过期", 401)
    if request.method != "GET":
        return None, _err("unauthorized", "未登录或登录已过期", 401)
    if _is_user_api_blocked(request.path, request.method):
        return None, _err("forbidden", "该接口仅管理员可用", 403)
    try:
        account = await asyncio.to_thread(_load_account, UUID(requested_id))
        return account, None
    except Exception:
        logger.exception("async 端点加载 account 失败: account_id=%s", requested_id)
    return None, _err("account_not_found", "账号不存在", 404)


async def _resolve_admin_permission(permission_code: str | None = None):
    """解析管理员 JWT 并校验指定权限点，返回 (admin_dict, None) 或 (None, error)。"""
    from internal.exception import UnauthorizedException

    auth_header = request.headers.get("Authorization") or ""
    token = (
        auth_header[7:].strip()
        if auth_header.lower().startswith("bearer ")
        else ""
    )
    if not token:
        return None, _err("unauthorized", "管理员凭证无效", 401)

    try:
        from internal.service.admin_user_service import AdminUserService

        admin = await _to_thread(
            _get_service(AdminUserService).get_current_admin_from_token,
            token,
        )
    except UnauthorizedException:
        return None, _err("unauthorized", "管理员凭证无效", 401)
    except Exception:
        logger.exception("解析管理员权限失败")
        return None, _err("unauthorized", "管理员凭证无效", 401)

    if not admin:
        return None, _err("unauthorized", "管理员凭证无效", 401)

    permissions = set(admin.get("permissions") or [])
    if permission_code and permission_code not in permissions:
        return None, _err("forbidden", "无权限执行该操作", 403)
    return admin, None


async def _resolve_admin_operator():
    """解析当前管理员并把其 id 包装为操作者对象（供 admin 路由审计使用）。"""
    admin, err = await _resolve_admin_permission(None)
    if err is not None:
        return None, err
    return SimpleNamespace(id=admin.get("id")), None


_ADMIN_PUBLIC_PATHS = frozenset({"/admin/auth/login"})
_ADMIN_AUTH_ONLY_PATHS = frozenset(
    {
        "/admin/auth/me",
        "/admin/auth/logout",
        "/admin/auth/password",
    }
)


def _admin_path_segments(path: str) -> list[str]:
    return [segment for segment in str(path or "").split("/") if segment]


def _admin_match(segments: list[str], prefix: tuple[str, ...]) -> bool:
    return segments[: len(prefix)] == list(prefix)


def _admin_route_permission(method: str, path: str) -> str | None:
    """根据 HTTP 方法与路径返回所需权限 code；未登记的管理路径返回 None（fail closed）。"""
    method = str(method or "GET").upper()
    segments = _admin_path_segments(path)
    if not segments or segments[0] != "admin":
        return None

    # 认证端点由 before_request 单独处理，不进入权限映射。
    if _admin_match(segments, ("admin", "auth")):
        return None

    # 共享工具端点：上传图片等仅要求进入管理后台。
    if _admin_match(segments, ("admin", "upload-files")):
        return "admin:access"

    # 商店只读浏览。
    store_read_map = {
        ("store", "public-apps"): "app:read",
        ("store", "workflows"): "workflow:read",
        ("store", "tools"): "tool:read",
        ("store", "skills"): "skill:read",
        ("store", "mcp"): "mcp:read",
        ("store", "builtin-tools"): "builtin_tool:read",
        ("store", "mcp-providers"): "mcp:read",
    }
    for prefix, permission in store_read_map.items():
        if _admin_match(segments, ("admin", *prefix)):
            return permission

    # RBAC 管理。
    if _admin_match(segments, ("admin", "roles")):
        if method == "GET":
            return "role:read"
        if method == "POST":
            return "role:create"
        if method in {"PATCH", "PUT"}:
            return "role:update"
        if method == "DELETE":
            return "role:delete"
        return None
    if _admin_match(segments, ("admin", "permissions")):
        return "permission:read" if method == "GET" else None
    if _admin_match(segments, ("admin", "admin-users")):
        if method == "GET":
            return "admin_user:read"
        if method == "POST" and len(segments) == 2:
            return "admin_user:create"
        if method in {"PATCH", "PUT"}:
            return "admin_user:update"
        if "disable" in segments:
            return "admin_user:disable"
        if "enable" in segments or "reset-password" in segments or "sessions" in segments:
            return "admin_user:disable"
        return "admin_user:update"

    # 用户管理与应用分配。
    if _admin_match(segments, ("admin", "users")) and "app-assignments" in segments:
        return "app_assignment:read" if method == "GET" else "app_assignment:update"
    if _admin_match(segments, ("admin", "users")):
        if method == "GET":
            return "user:read"
        if "disable" in segments:
            return "user:disable"
        if method in {"PATCH", "PUT", "DELETE"} or "enable" in segments or "sessions" in segments:
            return "user:update"
        return "user:update"

    # 财务域。
    if _admin_match(segments, ("admin", "plans")):
        return "plan:read" if method == "GET" else "plan:update"
    if _admin_match(segments, ("admin", "redeem-code-batches")) or _admin_match(
        segments, ("admin", "redeem-codes")
    ):
        return "redeem_code:read" if method == "GET" else "redeem_code:update"
    if _admin_match(segments, ("admin", "cost-stats")):
        return "cost_stats:read"
    if _admin_match(segments, ("admin", "cost-policies")):
        return "model_pool:read" if method == "GET" else "model_pool:manage"

    # 模型与供应商。
    if _admin_match(segments, ("admin", "model-providers")):
        if method == "GET":
            return "model_provider:read"
        if method == "POST" and len(segments) == 2:
            return "model_provider:create"
        if method in {"PATCH", "PUT"}:
            return "model_provider:update"
        if method == "DELETE":
            return "model_provider:delete"
        return "model_provider:update"
    if _admin_match(segments, ("admin", "models")):
        if method == "GET":
            return "model_pool:read"
        if method == "POST" and len(segments) == 2:
            return "model_pool:create"
        if method in {"PATCH", "PUT"}:
            return "model_pool:update"
        if method == "DELETE":
            return "model_pool:delete"
        return "model_pool:update"
    if _admin_match(segments, ("admin", "model-keys")) or _admin_match(
        segments, ("admin", "model-tiers")
    ) or _admin_match(segments, ("admin", "language-models")):
        return "model_pool:read" if method == "GET" else "model_pool:manage"

    # 调度平台。
    if _admin_match(segments, ("admin", "schedule-tasks")):
        if method == "GET":
            return "schedule_task:read"
        if method == "POST" and len(segments) == 2:
            return "schedule_task:create"
        if method == "POST" and len(segments) == 3 and segments[2] in {
            "parse",
            "confirm",
            "reject-suggestion",
            "humanize",
        }:
            return "schedule_task:create"
        if method in {"PATCH", "PUT"}:
            return "schedule_task:update"
        if method == "DELETE":
            return "schedule_task:delete"
        return "schedule_task:update"

    # 存储。
    if _admin_match(segments, ("admin", "storage")):
        return "storage:read" if method == "GET" else "storage:update"

    # 模型池治理之外的池治理。
    if _admin_match(segments, ("admin", "agent-pool")) or _admin_match(
        segments, ("admin", "sub-pool-definitions")
    ):
        return "agent_pool:read" if method == "GET" else "agent_pool:manage"
    if _admin_match(segments, ("admin", "tool-governance")):
        return "tool_governance:read" if method == "GET" else "tool_governance:manage"

    # 提示词、内置工具、公开 AI 能力。
    if _admin_match(segments, ("admin", "prompt-templates")):
        if method == "GET":
            return "prompt_template:read"
        if method == "DELETE":
            return "prompt_template:delete"
        return "prompt_template:update"
    if _admin_match(segments, ("admin", "builtin-tools")):
        return "builtin_tool:read" if method == "GET" else "builtin_tool:update"
    if _admin_match(segments, ("admin", "public-ai-features")):
        return "public_ai_feature:read" if method == "GET" else "public_ai_feature:update"

    # 路由质量：动作粒度权限。
    if _admin_match(segments, ("admin", "routing-quality")):
        if method == "POST" and _admin_match(segments, ("admin", "routing-quality", "feedback")):
            return "routing_quality:feedback"
        if method == "POST" and len(segments) >= 5:
            action = segments[-1]
            if action == "accept":
                return "routing_quality:accept"
            if action == "dismiss":
                return "routing_quality:dismiss"
            if action == "apply":
                return "routing_quality:apply"
            if action == "rollback":
                return "routing_quality:rollback"
        if method == "POST" and len(segments) >= 4 and "policy-changes" in segments:
            return "routing_quality:rollback"
        return "routing_quality:read"
    if _admin_match(segments, ("admin", "routing-logs")):
        return "routing_log:read" if method == "GET" else "routing_log:update"

    # 回收站。
    if _admin_match(segments, ("admin", "recycle-bin")):
        if method == "GET":
            return "recycle_bin:read"
        if "restore" in segments:
            return "recycle_bin:write"
        return "recycle_bin:write"

    # 可观测性与上线验收。
    if _admin_match(segments, ("admin", "audit-logs")) or _admin_match(
        segments, ("admin", "approval-insights")
    ):
        return "audit_log:read"
    if _admin_match(segments, ("admin", "orchestration-release-check")):
        return "orchestration_release:read"
    if _admin_match(segments, ("admin", "orchestration-flags")):
        return "orchestration_flag:read" if method == "GET" else "orchestration_flag:update"

    # 开放 API 与案例展示。
    if _admin_match(segments, ("admin", "openapi")):
        if method == "GET":
            return "openapi:read"
        if "delete" in segments:
            return "openapi:delete"
        if method == "POST" and len(segments) == 3:
            return "openapi:create"
        return "openapi:update"
    if _admin_match(segments, ("admin", "showcase")):
        if method == "GET":
            return "showcase:read"
        if "approve" in segments:
            return "showcase:approve"
        return "showcase:update"

    # 知识库与内容资源。
    if _admin_match(segments, ("admin", "system-knowledge")) or _admin_match(
        segments, ("admin", "space", "system-knowledge-bases")
    ):
        return "system_knowledge:read" if method == "GET" else "system_knowledge:write"

    # 应用、工作流、技能、MCP、工具等通用资源：GET=read，POST 子路径=update。
    generic_resources = {
        ("apps",): ("app", "app:read", "app:create", "app:update", "app:delete"),
        ("workflows",): ("workflow", "workflow:read", "workflow:create", "workflow:update", "workflow:delete"),
        ("skills",): ("skill", "skill:read", "skill:create", "skill:update", "skill:delete"),
        ("mcp",): ("mcp", "mcp:read", "mcp:create", "mcp:update", "mcp:delete"),
        ("api-tools",): ("tool", "tool:read", "tool:create", "tool:update", "tool:delete"),
        ("tools",): ("tool", "tool:read", "tool:create", "tool:update", "tool:delete"),
    }
    for prefix, (_resource, read_code, create_code, update_code, delete_code) in generic_resources.items():
        if not _admin_match(segments, ("admin", *prefix)):
            continue
        if method == "GET":
            return read_code
        if method == "DELETE":
            return delete_code
        if method in {"PATCH", "PUT"}:
            return update_code
        if method == "POST":
            if prefix == ("skills",) and len(segments) == 3 and segments[2].startswith("import"):
                return "skill:create"
            if prefix == ("mcp",) and len(segments) == 3 and segments[2].startswith("import"):
                return "mcp:create"
            if prefix == ("api-tools",) and len(segments) == 3 and segments[2].startswith("import"):
                return "tool:create"
            if prefix == ("workflows",) and len(segments) == 3 and segments[2] == "import":
                return "workflow:create"
            if len(segments) == len(prefix) + 1:
                return create_code
            if len(segments) > 2 and segments[-1] in {"delete"}:
                return delete_code
            return update_code
        return None

    return None


# 用户端已收敛：这些接口不再被保留的用户界面消费，普通用户 JWT 一律拒绝。
# admin 端有独立路径（/admin/*），不受影响；web-apps/public 走各自 token/公开通道。
_USER_API_BLOCKED_PREFIXES = (
    "/admin",
    "/my/apps",
    "/memory/write",
    "/memory/retrieve",
    "/memory/health",
    "/analysis/",
    "/tags",
    "/language-models",
    "/space/system-knowledge-bases",
    "/openapi/api-keys",
    "/platform/",
    "/routing-logs/summary",
    "/ai/optimize-prompt",
    "/ai/chat",
    "/ai/openapi-schema-chat",
    "/ai/mcp-schema-chat",
    "/api/async/chat/completion",
    "/async/chat/completion",
    "/upload-files/file",
)

# 资源管理接口的用户域版本已无 UI 消费；写操作与只读 GET 一律拒绝普通用户 JWT。
_USER_API_BLOCKED_WRITE_PREFIXES = (
    "/apps",
    "/workflows",
    "/api-tools",
    "/mcp-providers",
    "/skills",
    "/builtin-tools",
    "/public/apps",
)

_USER_API_BLOCKED_READ_PREFIXES = (
    "/apps",
    "/workflows",
    "/api-tools",
    "/mcp-providers",
    "/skills",
    "/builtin-tools",
)


def _is_user_api_blocked(path: str, method: str = "GET") -> bool:
    """判断用户 JWT 是否禁止访问该路径。"""
    normalized = str(path or "").strip()
    if any(
        normalized == prefix or normalized.startswith(prefix)
        for prefix in _USER_API_BLOCKED_PREFIXES
    ):
        return True

    if normalized.startswith("/conversations/") and (
        "/variables" in normalized or normalized.endswith("/is-pinned")
    ):
        return True
    if normalized.startswith("/tool-confirmations") and not (
        normalized.endswith("/confirm")
        or normalized.endswith("/cancel")
        or (
            normalized.startswith("/tool-confirmations/")
            and normalized.count("/") == 2
        )
    ):
        return True

    write_method = str(method or "GET").upper()
    if write_method == "GET":
        return any(
            normalized == prefix or normalized.startswith(prefix + "/")
            for prefix in _USER_API_BLOCKED_READ_PREFIXES
        )
    return any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in _USER_API_BLOCKED_WRITE_PREFIXES
    )


def _field(raw, default=None):
    """构造 duck-type 表单字段（.data 访问）。"""
    return SimpleNamespace(data=raw if raw is not None else default)


def _int_arg(name, default):
    """解析整型 query 参数，非法或缺失时返回默认值。"""
    raw = request.args.get(name)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _to_thread(fn, *args, **kwargs):
    """把同步 service 调用移入线程池，避免阻塞 uvicorn 事件循环。

    统一在运行时容器上下文中执行：同步服务层依赖 current_app.extensions /
    db.session 等容器能力，缺省会并发 500。同时显式复制当前 contextvars，
    保证线程内仍能读取 internal.context.request / has_request_context。
    """
    request_context = contextvars.copy_context()

    def _run_in_context():
        with flask_app.app_context():
            try:
                return request_context.run(fn, *args, **kwargs)
            finally:
                from internal.extension.database_extension import db

                remove_session = getattr(db.session, "remove", None)
                if callable(remove_session):
                    remove_session()

    return asyncio.to_thread(_run_in_context)


def _resolve_webapp_actor():
    """解析 WebApp 会话主体：已登录用户优先，否则用 visitor_id（简化）。"""
    raw_account_id = request.args.get("account_id") or ""
    if raw_account_id:
        return None, None
    raw_visitor_id = request.args.get("visitor_id") or ""
    if raw_visitor_id:
        try:
            return SimpleNamespace(id=UUID(raw_visitor_id), is_authenticated=False), None
        except (ValueError, TypeError):
            pass
    return SimpleNamespace(id=uuid4(), is_authenticated=False), None
