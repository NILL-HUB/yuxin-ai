"""rename builtin provider codex_os -> host_os

Revision ID: q3d4e5f6a7b8
Revises: q2c3d4e5f6a7
Create Date: 2026-09-15 00:00:00.000000

本机文件操作 provider 的历史命名为 `codex_os`。原 Codex CLI 链路
（`run_os_task` + worker `/run` 端点 + `delete_guard`）已于 2026-09-08
整体移除（原因：Codex 强依赖 OpenAI，ChatGPT 登录/API key + 地区限制，
ToC 不可行），现存三件套（`os_file_task` / `os_recycle_bin` / `os_snapshot`）
为纯 Python 自研。目录与 provider name 现更正为 `host_os`，不再使用已废弃命名。

背景（为什么必须写这条迁移）：
`BuiltinToolSyncService.sync_yaml_to_db()` 是**只增不删**的 upsert——以 provider
`name` 为键。YAML 改名后启动同步会**新建 `host_os` 行，而旧 `codex_os` 行与
其下工具的 `python_module` 一并残留**（实测已出现新旧两套并存）。旧行的
`python_module` 指向已不存在的 `providers.codex_os` 目录，一旦命中即 import 失败。

本迁移：
1. 删除旧 provider `codex_os` 行及其下 `builtin_tool` 行（其 python_module 已失效）。
2. 把 `host_os` 下工具的 python_module 兜底修正为 `...providers.host_os`
   （正常应由启动同步写入，这里显式兜底，避免未重启实例读到空值）。

**明确不处理**（避免后续 Agent 误判为残留缺陷）：
`routing_log` / `tool_confirmation` 中同样含 `codex_os` 与 "Codex 系统自动化" 字样
（实测：routing_log 11 行，时间 2026-08-24~09-07；tool_confirmation 2 行），
它们是**追加型审计快照**，记录"当时系统确实这样路由/执行过"，属于历史事实，
不改写（改写即伪造审计）。仓储先例：`0a1b2c3d4e6f` 删除 `run_os_task` 时
同样只清理 `tool_governance_policy` + `builtin_tool`，未触碰 `routing_log`。
且无消费方按 tool_id 反查这些行（`RoutingQualityMetricsService` 只按
`metadata.tool_pool` 分组），不构成功能影响。第三方技能目录
（`skills/catalog/codex` 等）中的 Codex 字样属外部技能内容，同理不动。

downgrade 反向重建 `codex_os` 行（仅数据行，不含已删除的 run_os_task）。
"""
from alembic import op
from sqlalchemy import text

revision = "q3d4e5f6a7b8"
down_revision = "q2c3d4e5f6a7"
branch_labels = None
depends_on = None

_OLD_PROVIDER = "codex_os"
_NEW_PROVIDER = "host_os"
_MODULE_PREFIX = "internal.core.tools.builtin_tools.providers"


def upgrade():
    conn = op.get_bind()

    # 1) 删除旧 provider 下的工具行，再删 provider 行（FK: builtin_tool.provider_id）
    removed_tools = conn.execute(
        text(
            "DELETE FROM builtin_tool WHERE provider_id IN "
            "(SELECT id FROM builtin_tool_provider WHERE name = :old)"
        ),
        {"old": _OLD_PROVIDER},
    ).rowcount
    removed_providers = conn.execute(
        text("DELETE FROM builtin_tool_provider WHERE name = :old"),
        {"old": _OLD_PROVIDER},
    ).rowcount

    # 2) 兜底修正 host_os 下工具的 python_module（幂等）
    fixed_modules = conn.execute(
        text(
            "UPDATE builtin_tool SET python_module = :prefix || '.host_os' "
            "WHERE provider_id IN (SELECT id FROM builtin_tool_provider WHERE name = :new) "
            "AND python_module <> :prefix || '.host_os'"
        ),
        {"prefix": _MODULE_PREFIX, "new": _NEW_PROVIDER},
    ).rowcount

    print(
        f"[migration] builtin provider 改名 codex_os→host_os："
        f"删除旧 provider {removed_providers} 行、旧工具 {removed_tools} 行，"
        f"修正 python_module {fixed_modules} 行"
    )


def downgrade():
    conn = op.get_bind()

    # 反向：把 host_os 改回 codex_os（python_module 一并回写）
    conn.execute(
        text("UPDATE builtin_tool_provider SET name = :old WHERE name = :new"),
        {"old": _OLD_PROVIDER, "new": _NEW_PROVIDER},
    )
    conn.execute(
        text(
            "UPDATE builtin_tool SET python_module = :prefix || '.codex_os' "
            "WHERE provider_id IN (SELECT id FROM builtin_tool_provider WHERE name = :old) "
            "AND python_module <> :prefix || '.codex_os'"
        ),
        {"prefix": _MODULE_PREFIX, "old": _OLD_PROVIDER},
    )

    print("[migration] 已回滚 builtin provider 命名 host_os→codex_os")
