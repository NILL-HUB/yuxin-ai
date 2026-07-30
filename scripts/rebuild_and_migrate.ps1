# 重建并重启 API 容器，应用最新代码
# 用法: powershell -File scripts/rebuild_and_migrate.ps1
$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Step 1: Rebuilding llmops-api container..."
docker compose -f "$RepoRoot\docker-compose.yml" up -d --force-recreate --build llmops-api

Write-Host "Step 2: Waiting for container to be ready..."
Start-Sleep -Seconds 15

Write-Host "Step 3: Checking container status..."
docker ps --filter "name=llmops-api" --format "{{.Names}} {{.Status}}"

Write-Host "Step 4: Running alembic migration..."
docker exec llmops-api bash -c "cd /app/api && alembic upgrade head 2>&1 | tail -20"

Write-Host "Step 5: Checking alembic current revision..."
docker exec llmops-api bash -c "cd /app/api && alembic current 2>&1 | tail -5"

Write-Host "Step 6: Verifying api_tool table has task_keywords column..."
docker exec llmops-postgres bash -c "psql -U postgres -d llmops -c \"\\d api_tool\" 2>&1 | grep -i task_keywords"

Write-Host "Step 7: Verifying mcp_provider/skill_package/workflow have task_keywords..."
docker exec llmops-postgres bash -c "psql -U postgres -d llmops -c \"\\d mcp_provider\" 2>&1 | grep -i task_keywords"
docker exec llmops-postgres bash -c "psql -U postgres -d llmops -c \"\\d skill_package\" 2>&1 | grep -i task_keywords"
docker exec llmops-postgres bash -c "psql -U postgres -d llmops -c \"\\d workflow\" 2>&1 | grep -i task_keywords"

Write-Host "Done!"
