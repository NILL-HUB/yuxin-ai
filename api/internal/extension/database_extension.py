"""统一数据库底座单例（替代 flask_sqlalchemy 的 db）。

说明：
- 兼容层：保留 ``db.Model`` / ``db.Column`` / ``db.session`` / ``db.auto_commit`` 等
  flask_sqlalchemy 常用 API 名字，底层为纯 SQLAlchemy 异步实现（asyncpg）。
- ``db.session`` 为 async_scoped_session：在 async 上下文中调用 ``db.session()``
  返回当前任务绑定的 AsyncSession；service 层 async 方法中使用。
- Celery 任务 / 迁移脚本使用 ``db.sync_session_factory`` / ``db.sync_engine``。
"""

from pkg.sqlalchemy import SQLAlchemy, Base  # noqa: F401  (Base 供 model 层导入)

db = SQLAlchemy()
