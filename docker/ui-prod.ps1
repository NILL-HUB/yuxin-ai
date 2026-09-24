# 前端生产模式：编译产物塞进 nginx 镜像（体积小），切换回标准部署
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

docker compose -f "$Root/docker/docker-compose.yaml" build llmops-ui
docker compose -f "$Root/docker/docker-compose.yaml" up -d llmops-ui
# UI 重建后重启 nginx，重新生成其上游配置（见项目规范：UI 重建后必须重启 nginx）
docker restart llmops-nginx

Write-Host ""
Write-Host "前端生产模式已启用（编译产物已进镜像）。"
Write-Host "如需再次进入开发模式请运行 docker/ui-dev.ps1"