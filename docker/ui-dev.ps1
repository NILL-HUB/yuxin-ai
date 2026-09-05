# 前端开发模式：Vite 开发服务器 + 源码挂载（HMR，无需每次改代码重建镜像）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

docker compose -f "$Root/docker/docker-compose.yaml" -f "$Root/docker/docker-compose.ui-dev.yaml" up -d llmops-ui --build

Write-Host ""
Write-Host "前端开发模式已启动："
Write-Host "  直连 Vite（HMR 最完整）: http://localhost:3000"
Write-Host "  外层 Nginx 统一入口:     http://localhost:80"
Write-Host "切回生产模式请运行 docker/ui-prod.ps1"