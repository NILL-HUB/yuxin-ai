#!/bin/bash
# 前端生产模式：编译产物塞进 nginx 镜像（体积小），切换回标准部署
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

docker compose -f "$SCRIPT_DIR/docker-compose.yaml" build llmops-ui
docker compose -f "$SCRIPT_DIR/docker-compose.yaml" up -d llmops-ui

echo ""
echo "前端生产模式已启用（编译产物已进镜像）。"
echo "如需再次进入开发模式请运行 docker/ui-dev.sh"