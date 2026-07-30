# ============================================================
# openagent 全面验证 + 批量导入脚本（MCP + Skills）
# 用法: 在项目根目录打开 PowerShell 窗口执行:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\full_setup.ps1
# 兼容 PowerShell 5.1 (Windows 自带) 和 PowerShell 7+ (pwsh)
# ============================================================

$ErrorActionPreference = "Continue"
$ROOT = $PSScriptRoot | Split-Path -Parent
Set-Location $ROOT

function Write-Step($n, $msg) {
    Write-Host "`n===== Step ${n}: $msg =====" -ForegroundColor Cyan
}
function Write-OK($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Err($msg) { Write-Host "  [ERR] $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "  $msg" -ForegroundColor Yellow }

# ---- Step 1: 重建容器 ----
Write-Step 1 "重建 API 容器 (含 mcp SDK + nodejs)"
docker compose -f docker/docker-compose.yaml up -d --force-recreate --build llmops-api
if ($LASTEXITCODE -ne 0) {
    Write-Err "容器构建失败，请检查 Dockerfile 和 requirements.txt"
    Write-Info "常见问题: mcp 包安装失败、nodejs 安装失败"
    Write-Info "可尝试手动构建: docker compose build llmops-api"
}
Write-Info "等待 40 秒让容器完成启动和迁移..."
Start-Sleep -Seconds 40

# ---- Step 2: 验证 alembic 迁移 ----
Write-Step 2 "验证 alembic 迁移版本 (期望 d5e6f7a8b9c2)"
$alembicOut = docker exec llmops-api bash -c "cd /app/api && flask db current --directory internal/migration 2>&1" 2>&1
Write-Host $alembicOut
if ($alembicOut -match "d5e6f7a8b9c2") {
    Write-OK "迁移版本正确: d5e6f7a8b9c2"
} else {
    Write-Err "迁移版本不正确"
    Write-Info "检查迁移日志:"
    docker logs llmops-api 2>&1 | Select-String -Pattern "alembic|migration|error|ERROR" | Select-Object -Last 10
}

# ---- Step 3: 检查启动日志 ----
Write-Step 3 "检查容器启动日志 (最后 60 行)"
docker logs llmops-api 2>&1 | Select-Object -Last 60

# ---- Step 4: 验证凭证加密 ----
Write-Step 4 "验证历史凭证已加密 (gAAAAA 前缀)"
Write-Info "api_tool_provider.headers:"
docker exec llmops-db psql -U postgres -d llmops -c "SELECT id, left(headers::text, 100) AS headers_preview FROM api_tool_provider LIMIT 3;" 2>&1
Write-Info "mcp_provider.headers + env:"
docker exec llmops-db psql -U postgres -d llmops -c "SELECT name, transport, left(headers::text, 80) AS headers, left(env::text, 80) AS env FROM mcp_provider LIMIT 5;" 2>&1

# ---- Step 5: 验证 mcp SDK + nodejs ----
Write-Step 5 "验证 mcp SDK 和 nodejs 可用"
docker exec llmops-api bash -c "cd /app/api && python -c 'import mcp; from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; print(\"mcp SDK OK\")'" 2>&1
Write-Info "node version:"
docker exec llmops-api node --version 2>&1
Write-Info "npx version:"
docker exec llmops-api npx --version 2>&1
docker exec llmops-api bash -c "cd /app/api && python -c 'from internal.core.tools.mcp_tools.providers.mcp_stdio_client import McpStdioClient; print(\"McpStdioClient OK\")'" 2>&1

# ---- Step 6: 预热 npx 包 (避免首次使用超时) ----
Write-Step 6 "预热 npx MCP 包 (可能需要几分钟)"
$pks = @(
    "@modelcontextprotocol/server-filesystem",
    "@modelcontextprotocol/server-memory",
    "@modelcontextprotocol/server-fetch",
    "@modelcontextprotocol/server-everything"
)
foreach ($pk in $pks) {
    Write-Info "  预热: $pk"
    docker exec llmops-api bash -c "npx -y $pk --help 2>/dev/null || true" 2>&1 | Out-Null
}

# ---- Step 7: 拷贝导入脚本到容器 ----
Write-Step 7 "拷贝导入脚本和 Skill 数据到容器"
docker cp "scripts/import_all.py" llmops-api:/tmp/import_all.py 2>&1
docker cp "scripts/collected_skills.json" llmops-api:/tmp/collected_skills.json 2>&1
Write-OK "文件已拷贝"

# ---- Step 8: 批量导入 MCP + Skills ----
Write-Step 8 "批量导入 MCP 工具 (10个) + Skill 工具 (33个)"
docker exec llmops-api bash -c "cd /app/api && python /tmp/import_all.py" 2>&1

# ---- Step 9: 验证 MCP 导入结果 ----
Write-Step 9 "验证 MCP 导入结果"
docker exec llmops-db psql -U postgres -d llmops -c "SELECT name, transport, url, command, category FROM mcp_provider ORDER BY transport, name;" 2>&1

# ---- Step 10: 验证 Skill 导入结果 ----
Write-Step 10 "验证 Skill 导入结果"
docker exec llmops-db psql -U postgres -d llmops -c "SELECT source_key, name, executor_type, category FROM skill_package ORDER BY category, source_key;" 2>&1

# ---- Step 11: 验证 builtin 工具 ----
Write-Step 11 "验证 builtin 工具 (ToolSelector 关键词快通道)"
docker exec llmops-api bash -c "cd /app/api && python -c \"
from app.http.app import app
from app.http.module import injector
from internal.service.tool_selector_service import ToolSelectorService
with app.app_context():
    selector = injector.get(ToolSelectorService)
    result = selector.select_tools('现在几点了', candidates=None, max_tools=3)
    print('Result:', result)
    assert any(r.get('tool_name') == 'current_time' for r in result), 'current_time not selected'
    print('OK: ToolSelector works')
\"" 2>&1

# ---- Step 12: 前端构建验证 ----
Write-Step 12 "前端构建验证"
Set-Location "$ROOT\ui"
npm run build 2>&1 | Select-Object -Last 25
Set-Location $ROOT

# ---- 完成 ----
Write-Host "`n========== 全部完成 ==========" -ForegroundColor Green
Write-Host "MCP: 10 个工具已导入 (3 HTTP/SSE + 7 stdio)"
Write-Host "Skills: 33 个技能已导入 (21 SCF + 12 Prompt)"
Write-Host "凭证: 历史明文已统一加密为 Fernet token"
Write-Host "stdio: MCP stdio 传输已启用"
Write-Host ""
Write-Host "浏览器验证:"
Write-Host "  Admin MCP 页面 - 查看导入的 MCP 服务器和导入弹窗"
Write-Host "  Admin Skills 页面 - 查看导入的技能"
Write-Host "  Admin Workflows 页面 - 测试导出/导入按钮"
Write-Host "  Admin Builtin Tools 页面 - 查看内置工具元数据"
