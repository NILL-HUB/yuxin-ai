#!/bin/bash

# 钰见我 Docker 容器启动脚本
# 注意：所有敏感信息（API Keys、密钥等）必须通过 api/.env 或 docker-compose environment 提供
# 本脚本仅设置非敏感的默认配置

# 1.启用错误检查
set -e

# 2.设置非敏感的默认配置
set_default_if_unset() {
  local key="$1"
  local default_value="$2"
  if [[ -z "${!key+x}" ]]; then
    export "${key}=${default_value}"
  fi
}

# 应用基础配置
set_default_if_unset "APP_ENV" "production"
set_default_if_unset "APP_DEBUG" "0"

# HuggingFace 镜像
set_default_if_unset "HF_ENDPOINT" "https://hf-mirror.com"

# 服务器配置
set_default_if_unset "SERVER_WORKER_AMOUNT" "1"
set_default_if_unset "SERVER_THREAD_AMOUNT" "32"
set_default_if_unset "GUNICORN_TIMEOUT" "0"
set_default_if_unset "CELERY_WORKER_AMOUNT" "4"
# ASGI 模式配置（阶段 3：渐进式 Quart 迁移）
set_default_if_unset "ASGI_WORKER_AMOUNT" "1"
set_default_if_unset "MODE" "asgi"

# 确保容器内始终可以从项目根目录导入 api 包
export PYTHONPATH="/app/api${PYTHONPATH:+:$PYTHONPATH}"

# 数据库连接池配置
set_default_if_unset "SQLALCHEMY_POOL_SIZE" "30"
set_default_if_unset "SQLALCHEMY_POOL_RECYCLE" "3600"
set_default_if_unset "SQLALCHEMY_ECHO" "false"

# Redis 配置
set_default_if_unset "REDIS_DB" "0"
set_default_if_unset "REDIS_USE_SSL" "false"

# Celery 配置
set_default_if_unset "CELERY_BROKER_DB" "1"
set_default_if_unset "CELERY_RESULT_BACKEND_DB" "1"
set_default_if_unset "CELERY_TASK_IGNORE_RESULT" "true"
set_default_if_unset "CELERY_RESULT_EXPIRES" "3600"
set_default_if_unset "CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP" "true"

# HuggingFace 离线模式
set_default_if_unset "TRANSFORMERS_OFFLINE" "0"

# 邮件服务配置（非敏感）：SMTP 参数已改为数据库持久化（mail_config 表），不再通过 env 注入

# 腾讯云 COS 配置（非敏感）
set_default_if_unset "COS_REGION" "ap-beijing"
set_default_if_unset "COS_SCHEME" "https"
set_default_if_unset "COS_TIMEOUT_SECONDS" "10"
set_default_if_unset "COS_SDK_RETRY" "1"
set_default_if_unset "COS_UPLOAD_MAX_ATTEMPTS" "3"
set_default_if_unset "COS_AUTO_SWITCH_DOMAIN_ON_RETRY" "True"
set_default_if_unset "COS_ENABLE_OLD_DOMAIN" "True"
set_default_if_unset "COS_ENABLE_INTERNAL_DOMAIN" "False"

# API 基础地址（非敏感）
set_default_if_unset "LLM_REQUEST_TIMEOUT" "300"
set_default_if_unset "AGENT_LISTEN_TIMEOUT_SECONDS" "86400"
set_default_if_unset "SANDBOX_TIMEOUT_SECONDS" "86400"
set_default_if_unset "SANDBOX_EXECUTE_TIMEOUT_SECONDS" "3600"
set_default_if_unset "LANGCHAIN_ENDPOINT" "https://api.smith.langchain.com"

# Docker 环境下优先使用容器内数据库地址拼接连接串
if [[ -n "${POSTGRES_HOST}" ]]; then
  set_default_if_unset "POSTGRES_PORT" "5432"
  if [[ -n "${POSTGRES_USER}" && -n "${POSTGRES_PASSWORD}" && -n "${POSTGRES_DB}" ]]; then
    export SQLALCHEMY_DATABASE_URI="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
  fi
fi

# 3.检查必需的环境变量（从 api/.env 或 docker-compose 提供）
check_required_env() {
  local missing_vars=()

  # 检查数据库配置
  [[ -z "${SQLALCHEMY_DATABASE_URI}" ]] && missing_vars+=("SQLALCHEMY_DATABASE_URI")

  # 检查 Redis 配置
  [[ -z "${REDIS_HOST}" ]] && missing_vars+=("REDIS_HOST")
  [[ -z "${REDIS_PORT}" ]] && missing_vars+=("REDIS_PORT")

  # 检查 JWT 密钥
  [[ -z "${JWT_SECRET_KEY}" ]] && missing_vars+=("JWT_SECRET_KEY")

  if [ ${#missing_vars[@]} -gt 0 ]; then
    echo "❌ 错误: 缺少必需的环境变量:"
    printf '  - %s\n' "${missing_vars[@]}"
    echo ""
    echo "请确保:"
    echo "  1. api/.env 文件存在并包含所有必需配置"
    echo "  2. docker-compose.yaml 中配置了 env_file: - ../api/.env"
    echo "  3. 或通过 docker-compose environment 提供这些变量"
    exit 1
  fi
}

# 4.检查必需的环境变量
check_required_env

# 5.判断是否启用的迁移数据同步 如果是则将数据库迁移同步到数据库中
if [[ "${MIGRATION_ENABLED}" == "true" ]]; then
  echo "Applying pending migrations (alembic)..."
  alembic -c internal/migration/alembic.ini upgrade head
fi

# 6.检测运行的模式(api/celery/celery-beat/asgi) 以执行不同的脚本

# 开发热重载开关（DEV_RELOAD）：源码已挂载（../api → /app/api），开启后改 Python 代码
# 即自动生效，无需重建镜像、也无需手动 restart。**默认关闭，生产务必保持关闭**：
#   - MODE=asgi                → uvicorn --reload（会强制单 worker，忽略 ASGI_WORKER_AMOUNT）
#   - MODE=celery/celery-beat  → 由 watchfiles 托管，文件变更即重启进程树
# 注意：alembic 迁移仍只在容器启动时执行一次；改了 migration 仍需 `docker restart`。
is_dev_reload_enabled() {
  case "$(printf '%s' "${DEV_RELOAD:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}
DEV_RELOAD_WATCH_DIR="${DEV_RELOAD_WATCH_DIR:-/app/api}"
# 热重载忽略目录（冒号分隔的路径前缀）：默认忽略测试目录，避免"改测试用例也重启 API/worker"。
# 注意：uvicorn 的 --reload-exclude 必须传**绝对目录**——其 FileFilter 以
# `exclude_dir in path.parents` 判定，glob 形式（如 test/*）对 test/internal/... 这类
# 嵌套路径不生效。
DEV_RELOAD_SKIP_DIRS="${DEV_RELOAD_SKIP_DIRS:-${DEV_RELOAD_WATCH_DIR}/test}"
export DEV_RELOAD_SKIP_DIRS
DEV_RELOAD_EXCLUDE_ARGS=()
IFS=':' read -r -a _dev_reload_skip_dirs <<< "${DEV_RELOAD_SKIP_DIRS}"
for _skip_dir in "${_dev_reload_skip_dirs[@]}"; do
  if [[ -n "${_skip_dir}" ]]; then
    DEV_RELOAD_EXCLUDE_ARGS+=(--reload-exclude "${_skip_dir}")
  fi
done
unset _dev_reload_skip_dirs _skip_dir

# 长驻进程统一以 exec 顶替 shell（让业务进程成为 PID 1 的直接后继），
# 确保 `docker restart`/`docker stop` 的 SIGTERM 能直达进程并优雅退出。
if [[ "${MODE}" == "asgi" ]]; then
  # 全量 Quart 迁移完成：app.http.asgi_app.quart_app 承载全部 393 个端点（含 SSE）。
  # HTTP 层仅走 ASGI；Http 容器仅作为 Celery/SocketIO 的依赖宿主。
  # 并发扩展：ASGI_WORKER_AMOUNT 起多 worker（每 worker 独立事件循环），
  # 同时按需放大 SQLALCHEMY_POOL_SIZE（默认 30，受 PostgreSQL max_connections 约束）。
  if is_dev_reload_enabled; then
    echo "Starting ASGI server (DEV_RELOAD=1 → uvicorn --reload，监听 ${DEV_RELOAD_WATCH_DIR})..."
    exec uvicorn \
      --host "${LLMOPS_BIND_ADDRESS:-0.0.0.0}" \
      --port "${LLMOPS_PORT:-5001}" \
      --reload --reload-dir "${DEV_RELOAD_WATCH_DIR}" \
      "${DEV_RELOAD_EXCLUDE_ARGS[@]}" \
      --timeout-keep-alive 75 \
      app.http.asgi_app:app
  fi
  echo "Starting ASGI server (uvicorn + quart_app + socketio)..."
  exec uvicorn \
    --host "${LLMOPS_BIND_ADDRESS:-0.0.0.0}" \
    --port "${LLMOPS_PORT:-5001}" \
    --workers ${ASGI_WORKER_AMOUNT:-1} \
    --timeout-keep-alive 75 \
    app.http.asgi_app:app
elif [[ "${MODE}" == "celery" ]]; then
  # 7.运行Celery命令（阶段 C：独立 Celery 应用，与 Flask 初始化解耦）
  # CELERY_QUEUES：可选，限定本 worker 消费哪些队列（逗号分隔，转成 celery 的 -Q）。
  # 不设置时保持原行为——celery 未传 -Q 会消费「全部已声明队列」。
  # 为何必须有这个开关：render 队列已登记进 task_queues，而渲染是分钟级长任务；
  # 若不隔离，主业务 worker 会把 render 一起消费掉，抢占业务槽位。
  # 渲染 worker 必须设 CELERY_QUEUES=render（见 docs/prd/execution-roadmap.md P3.7）。
  CELERY_QUEUE_ARGS=""
  if [[ -n "${CELERY_QUEUES:-}" ]]; then
    CELERY_QUEUE_ARGS="-Q ${CELERY_QUEUES}"
    echo "[celery] 限定消费队列：${CELERY_QUEUES}"
  else
    echo "[celery] 未设 CELERY_QUEUES，消费全部已声明队列"
  fi
  CELERY_ARGS=(
    celery -A app.http.celery_app:celery_app worker
    -P "${CELERY_WORKER_CLASS:-prefork}"
    -c "${CELERY_WORKER_AMOUNT:-1}"
    ${CELERY_QUEUE_ARGS}
    --loglevel DEBUG
  )
  if is_dev_reload_enabled; then
    echo "[dev] DEV_RELOAD=1：celery 交给 watchfiles 托管（变更即重启，监听 ${DEV_RELOAD_WATCH_DIR}）"
    exec python scripts/dev_reload.py "${CELERY_ARGS[@]}"
  fi
  exec "${CELERY_ARGS[@]}"
elif [[ "${MODE}" == "celery-beat" ]]; then
  # 7b.运行Celery Beat调度器
  if is_dev_reload_enabled; then
    echo "[dev] DEV_RELOAD=1：celery-beat 交给 watchfiles 托管（监听 ${DEV_RELOAD_WATCH_DIR}）"
    exec python scripts/dev_reload.py celery -A app.http.celery_app:celery_app beat --loglevel DEBUG
  fi
  exec celery -A app.http.celery_app:celery_app beat --loglevel DEBUG
else
  echo "Starting ASGI server (uvicorn + quart_app + socketio) [MODE=${MODE}]..."
  exec uvicorn \
    --host "${LLMOPS_BIND_ADDRESS:-0.0.0.0}" \
    --port "${LLMOPS_PORT:-5001}" \
    --workers ${ASGI_WORKER_AMOUNT:-1} \
    --timeout-keep-alive 75 \
    app.http.asgi_app:app
fi

