#!/bin/bash
# 前端开发模式：Vite 开发服务器 + 源码挂载（HMR，无需每次改代码重建镜像）
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

docker compose -f "$SCRIPT_DIR/docker-compose.yaml" -f "$SCRIPT_DIR/docker-compose.ui-dev.yaml" up -d llmops-ui --build

echo ""
echo "前端开发模式已启动："
echo "  直连 Vite（HMR 最完整）: http://localhost:3000"
echo "  外层 Nginx 统一入口:     http://localhost:80"
echo "切回生产模式请运行 docker/ui-prod.sh"