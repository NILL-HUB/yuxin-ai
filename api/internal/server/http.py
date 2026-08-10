"""应用容器（替代 Flask Http 服务引擎，彻底移除 Flask 依赖）。

职责：
- 承载全局配置（conf）与扩展单例（db / mail / redis / neo4j / logging）
- 提供 ``app_context()`` 兼容上下文（内部为 no-op，服务层不再依赖 app context）
- 提供 ``_register_error_handler`` 供测试/兼容调用（业务码契约与旧 Flask 一致）
"""
import json
import logging
import os
import sys
from contextlib import contextmanager

from config import Config
from internal.exception import CustomException
from internal.extension import logging_extension, redis_extension, neo4j_extension
from pkg.response import HttpCode
from pkg.sqlalchemy import SQLAlchemy
from internal.extension.database_extension import db
from internal.extension.mail_extension import mail


class Http:
    """应用容器：配置 + 扩展单例引导（无 Web 框架依赖）。"""

    def __init__(
            self,
            *args,
            conf: Config,
            db: SQLAlchemy = db,
            mail=mail,
            **kwargs,
    ):
        # 1.保存配置（对象形式 + dict 视图，兼容 config.get 两种调用）
        self._conf = conf
        self.config = {
            key: getattr(conf, key)
            for key in dir(conf)
            if not key.startswith("_") and not callable(getattr(conf, key))
        }
        self.debug = getattr(conf, "DEBUG", False)

        # 兼容 current_app.root_path：定位应用模块所在目录（app/http），
        # 供 builtin_tool_service 等通过 dirname(dirname(root_path)) 推导项目根目录。
        self._name = args[0] if args else "app.http.app"
        self.root_path = self._resolve_root_path(self._name)

        # 2.扩展单例挂载点（service 层 current_app.extensions 兼容来源）
        self.extensions: dict = {}

        # 3.初始化扩展
        db.init_app(conf)
        self.extensions["sqlalchemy"] = db
        mail.init_app(conf)
        self.extensions["mail"] = mail
        logging_extension.init_app(self)
        redis_extension.init_app(self)
        neo4j_extension.init_app(self)
        self.extensions["neo4j"] = neo4j_extension.get_driver()

        # 4.注册绑定异常处理（契约兼容）
        self._error_handler_registered = True

    @staticmethod
    def _resolve_root_path(app_name: str) -> str:
        """根据应用模块名解析 root_path（与 Flask 语义一致：模块所在目录）。"""
        module = sys.modules.get(app_name)
        module_file = getattr(module, "__file__", None) if module is not None else None
        if module_file:
            return os.path.dirname(os.path.abspath(module_file))
        # 兜底：以当前文件位置（api/internal/server）推导到 api/app/http
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))) + os.sep + "app" + os.sep + "http"

    @contextmanager
    def app_context(self):
        """兼容 app context 上下文（no-op：service 层不再依赖 Flask app context）。"""
        yield self

    @contextmanager
    def test_request_context(self, *args, **kwargs):
        """兼容测试 request context（no-op）。"""
        yield self

    def _register_error_handler(self, error: Exception):
        """统一异常处理：返回 (Response, status)，兼容旧 Flask 业务码契约。

        不依赖 Quart app context：直接构造 Quart Response，JSON 序列化显式处理
        （str 枚举 / dataclass 均通过 default=str 归一化）。
        """
        from quart import Response

        # 1.异常信息是不是我们的自定义异常，如果是可以提取message和code等信息
        if isinstance(error, CustomException):
            warning_codes = {HttpCode.FAIL, HttpCode.NOT_FOUND, HttpCode.FORBIDDEN}
            if error.code in warning_codes:
                logging.warning("业务异常: code=%s, message=%s", error.code, error.message)
            else:
                logging.info("业务异常: code=%s, message=%s", error.code, error.message)
            body = json.dumps(
                {
                    "code": error.code.value if hasattr(error.code, "value") else str(error.code),
                    "message": error.message,
                    "data": error.data if error.data is not None else {},
                },
                ensure_ascii=False,
                default=str,
            )
            return Response(body, mimetype="application/json", status=200), 200
        # 2.非业务异常按错误级别并携带堆栈记录
        logging.error("系统异常: %s", error, exc_info=error)
        # 3.如果不是我们的自定义异常，则有可能是程序、数据库抛出的异常，也可以提取信息，设置为FAIL状态码
        if self.debug:
            raise error
        body = json.dumps(
            {
                "code": HttpCode.FAIL.value,
                "message": "服务器内部错误",
                "data": {},
            },
            ensure_ascii=False,
            default=str,
        )
        return Response(body, mimetype="application/json", status=200), 200
