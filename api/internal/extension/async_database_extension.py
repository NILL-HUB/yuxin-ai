"""异步数据库会话基建（薄转发兼容层）。

历史说明：本模块曾独立承载 AsyncDatabase（asyncpg 引擎 / async_sessionmaker）。
阶段 3.4 将异步 DB 底座合并进 ``internal.extension.database_extension.db``，
此处保留 ``async_db`` 名称以便已迁移代码与既有导入继续工作。
"""

from internal.extension.database_extension import db as async_db

__all__ = ["async_db"]
