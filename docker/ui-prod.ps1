# 前端生产模式：编译产物塞进 nginx 镜像（体积小），切换回标准部署
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

docker compose -f "$Root/docker/docker-compose.yaml" build llmops-ui
docker compose -f "$Root/docker/docker-compose.yaml" up -d llmops-ui

Write-Host ""
Write-Host "前端生产模式已启用（编译产物已进镜像）。"
Write-Host "如需再次进入开发模式请运行 docker/ui-dev.ps1"