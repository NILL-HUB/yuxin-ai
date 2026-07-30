# MCP stdio + 凭证迁移 + 批量导入 验证脚本
# 用法: 在项目根目录执行 pwsh -NoProfile -File scripts/verify_and_import.ps1

$ErrorActionPreference = "Continue"
$ROOT = $PSScriptRoot | Split-Path -Parent

Write-Host "`n===== Step 1: 重建并重启 API 容器 =====" -ForegroundColor Cyan
Set-Location $ROOT
docker compose -f docker/docker-compose.yaml up -d --force-recreate --build llmops-api
Write-Host "等待容器启动 (30s)..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

Write-Host "`n===== Step 2: 验证 alembic 迁移版本 =====" -ForegroundColor Cyan
docker exec llmops-api bash -c "cd /app/api && flask db current --directory internal/migration 2>&1 | tail -5"

Write-Host "`n===== Step 3: 检查启动日志 =====" -ForegroundColor Cyan
docker logs llmops-api 2>&1 | Select-Object -Last 50

Write-Host "`n===== Step 4: 验证凭证已加密 =====" -ForegroundColor Cyan
Write-Host "--- api_tool_provider headers ---" -ForegroundColor Yellow
docker exec llmops-db psql -U postgres -d llmops -c "SELECT id, left(headers::text, 80) FROM api_tool_provider LIMIT 3;" 2>&1
Write-Host "--- mcp_provider headers + env ---" -ForegroundColor Yellow
docker exec llmops-db psql -U postgres -d llmops -c "SELECT name, transport, left(headers::text, 80), left(env::text, 80) FROM mcp_provider LIMIT 5;" 2>&1

Write-Host "`n===== Step 5: 验证 mcp SDK 和 nodejs =====" -ForegroundColor Cyan
docker exec llmops-api bash -c "cd /app/api && python -c 'import mcp; from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; print(\"OK: mcp SDK imported\")'" 2>&1
docker exec llmops-api node --version 2>&1
docker exec llmops-api npx --version 2>&1
docker exec llmops-api bash -c "cd /app/api && python -c 'from internal.core.tools.mcp_tools.providers.mcp_stdio_client import McpStdioClient; print(\"OK: McpStdioClient imported\")'" 2>&1

Write-Host "`n===== Step 6: 批量导入 MCP 工具 =====" -ForegroundColor Cyan
$importScript = @'
import json
from app.http.app import app
from app.http.module import injector
from internal.service.mcp_import_service import McpImportService
from internal.model import Account
from extensions.ext_database import db

with app.app_context():
    account = db.session.query(Account).filter_by(is_setup=True).first()
    if not account:
        account = db.session.query(Account).first()
    if not account:
        print("ERROR: No admin account found")
        exit(1)
    print(f"Using account: {account.id} ({account.email})")
    import_service = injector.get(McpImportService)
    mcp_config = {
        "mcpServers": {
            "github-remote": {"type": "sse", "url": "https://api.github.com/mcp", "description": "GitHub 官方远程 MCP 服务器"},
            "cloudflare-docs": {"type": "http", "url": "https://docs.mcp.cloudflare.com/sse", "description": "Cloudflare 官方文档 MCP"},
            "cloudflare-observability": {"type": "http", "url": "https://observability.mcp.cloudflare.com/sse", "description": "Cloudflare 可观测性 MCP"},
            "filesystem": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"], "description": "文件系统操作"},
            "memory": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"], "description": "知识图谱记忆系统"},
            "fetch": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-fetch"], "description": "Web 内容抓取"},
            "sequential-thinking": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"], "description": "思维序列推理"},
            "time-mcp": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-time"], "description": "时间和时区转换"},
            "everything": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"], "description": "参考/测试 MCP 服务器"},
            "sqlite": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "/tmp/test.db"], "description": "SQLite 数据库交互"},
        }
    }
    json_str = json.dumps(mcp_config, ensure_ascii=False)
    result = import_service.import_from_mcp_json(json_str, account.id, overwrite=True)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
'@
$importScript | docker exec -i llmops-api bash -c "cd /app/api && python -c 'import sys; exec(sys.stdin.read())'"

Write-Host "`n===== Step 7: 验证导入结果 =====" -ForegroundColor Cyan
docker exec llmops-db psql -U postgres -d llmops -c "SELECT name, transport, url, command, category FROM mcp_provider ORDER BY transport, name;" 2>&1

Write-Host "`n===== Step 8: 前端构建验证 =====" -ForegroundColor Cyan
Set-Location "$ROOT\ui"
npm run build 2>&1 | Select-Object -Last 20

Write-Host "`n===== 验证完成 =====" -ForegroundColor Green
Set-Location $ROOT
