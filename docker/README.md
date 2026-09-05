# Docker 部署配置说明

> 钰心AI Docker 部署文档。
> 项目已完成整体重构：HTTP 层全部迁移到 Quart ASGI（uvicorn），记忆系统使用 Neo4j + MinIO（TKG 时序知识图谱 + 对象存储），旧组件（Weaviate、Flask/gunicorn、`docker/.env` 基础设施配置）已移除。本文档以当前 `docker-compose.yaml` 实际配置为准。

## ⚠️ 安全提示

**所有敏感信息（API Keys、密钥、数据库/Redis/Neo4j/MinIO 密码）必须存储在 `api/.env` 文件中，绝不提交到 Git！**

部署前请运行安全检查脚本：

```bash
cd docker
./security-check.sh
```

## 配置文件结构

```
api/
├── .env                    # 唯一配置源（业务 + 基础设施 + 端口 + 镜像版本）
└── .env.example            # 配置模板（复制为 .env 后填写）

docker/
├── docker-compose.yaml     # 生产环境服务编排
├── docker-compose.dev.yaml # 本地开发覆盖文件（前端热更新）
├── start.sh                # 交互式启动脚本
├── security-check.sh       # 敏感信息安全检查
├── nginx/                  # Nginx 反向代理（entrypoint.sh 动态生成配置）
│   ├── entrypoint.sh
│   ├── nginx.conf
│   └── proxy.conf
├── postgres/init.sql       # PostgreSQL 初始化（uuid / pgvector 扩展）
└── volumes/                # 数据卷（已被 .gitignore 忽略）
    ├── db/                 # PostgreSQL 数据
    ├── redis/              # Redis 数据
    ├── neo4j/              # Neo4j 数据
    ├── minio/              # MinIO 数据
    └── app/storage/        # 应用文件存储
```

> **重构说明**：旧版依赖 `docker/.env` 存放基础设施配置的用法已废弃，所有配置统一收敛到 `api/.env`（`docker-compose.yaml` 通过 `env_file` 注入所有容器）。`start.sh` 仍保留对 `docker/.env` 的可选读取作为兼容项。

## 配置优先级

### 1. `api/.env`（唯一配置源）

是所有容器的基础配置，包括：

- 应用基础配置（`APP_ENV`、`APP_DEBUG`）
- 前端构建配置（`VITE_API_PREFIX`，UI 镜像在构建阶段直接读取，缺失即构建失败）
- 安全配置（`JWT_SECRET_KEY`、`MODEL_KEY_ENCRYPTION_KEY`、`ADMIN_INITIAL_*` 等）
- 数据库 / Redis 配置（`POSTGRES_*`、`REDIS_*`、`SQLALCHEMY_*`）
- 记忆系统配置（`NEO4J_*`、`MINIO_*`）
- 端口与镜像版本（`UI_PORT`、`API_PORT`、`NGINX_HTTP_PORT`、`IMAGE_VERSION` 等）
- LLM / 第三方服务 / OAuth / 存储后端 / 邮件等业务配置

### 2. `docker-compose.yaml` 环境变量覆盖（最高优先级）

在 compose 的 `environment` 段覆盖 `.env` 中的同名配置，主要用于：

- `MODE`：运行模式（`asgi` / `celery` / `celery-beat`）
- `MIGRATION_ENABLED`：是否执行 Alembic 迁移（仅 `llmops-api` 为 `true`）
- 数据库 / Redis / Neo4j / MinIO 连接地址（使用 Docker 服务名，如 `llmops-db`）
- `APP_ENV`、`APP_DEBUG` 等运行时行为

## 服务拓扑

| 服务 | 说明 | 镜像 | 宿主机端口（默认值） |
| --- | --- | --- | --- |
| `llmops-ui` | Vue 3 前端（Nginx 静态托管，构建时注入 `VITE_API_PREFIX`） | `llmops-ui:${IMAGE_VERSION:-0.1.0}` | `127.0.0.1:${UI_PORT:-3000}` |
| `llmops-api` | Quart ASGI 应用（uvicorn，`MODE=asgi`），健康检查 `/healthz` | `llmops-api:${IMAGE_VERSION:-0.1.0}` | `127.0.0.1:${API_PORT:-5001}` |
| `llmops-celery` | Celery worker（`MODE=celery`） | `llmops-api:${IMAGE_VERSION:-0.1.0}` | - |
| `llmops-celery-beat` | Celery Beat 定时调度（`MODE=celery-beat`） | `llmops-api:${IMAGE_VERSION:-0.1.0}` | - |
| `llmops-redis` | 缓存与 Celery broker（`redis-server --requirepass`，密码来自 `api/.env` 的 `REDIS_PASSWORD`） | `redis:8-alpine` | `127.0.0.1:${REDIS_PORT:-16379}` |
| `llmops-db` | PostgreSQL 18 + pgvector（向量检索），启动时执行 `postgres/init.sql` | `pgvector/pgvector:pg18` | `127.0.0.1:${POSTGRES_PORT:-5432}` |
| `llmops-nginx` | 对外反向代理：`/api/`、`/api/socket.io/`、`/storage/local/`、`/kkfileview/` | `nginx:1.30-alpine` | `${NGINX_HTTP_PORT:-80}` / `${NGINX_HTTPS_PORT:-443}` |
| `llmops-kkfileview` | kkFileView 多格式文件在线预览 | `keking/kkfileview:latest` | `127.0.0.1:${KKFILEVIEW_PORT:-8012}` |
| `llmops-neo4j` | 记忆系统 TKG 时序知识图谱（含 APOC 插件） | `neo4j:2026-community` | `127.0.0.1:${NEO4J_HTTP_PORT:-7474}` / `127.0.0.1:${NEO4J_BOLT_PORT:-7687}` |
| `llmops-minio` | 记忆系统对象存储 | `minio/minio` | `${MINIO_API_PORT:-9000}` / `${MINIO_CONSOLE_PORT:-9001}` |
| `llmops-browser-worker` | 浏览器自动化 worker（`profile: local-workers`） | `llmops-worker:${IMAGE_VERSION:-0.1.0}` | `127.0.0.1:${BROWSER_AUTOMATION_PORT:-8766}` |
| `llmops-computer-worker` | 电脑控制 worker（`profile: local-workers`） | `llmops-worker:${IMAGE_VERSION:-0.1.0}` | `127.0.0.1:${COMPUTER_CONTROL_PORT:-8767}` |

说明：

- 默认端口为 compose 兜底值，均可通过 `api/.env` 覆盖
- 除 `llmops-nginx`（80/443）与 `llmops-minio`（9000/9001）外，其余服务默认仅绑定宿主机回环地址 `127.0.0.1`

## 快速启动

### 方式一：直接使用 `docker compose`（推荐）

1. 创建并配置 `api/.env`：

   ```bash
   cp api/.env.example api/.env
   ```

   至少需要配置：`VITE_API_PREFIX`、`JWT_SECRET_KEY`、`MODEL_KEY_ENCRYPTION_KEY`、`ADMIN_INITIAL_PASSWORD`，以及 `NEO4J_PASSWORD`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`（均须替换默认/占位值）。

2. 启动服务：

   ```bash
   cd docker
   docker compose up -d --build
   ```

3. 查看状态：

   ```bash
   docker compose ps
   ```

4. 访问入口：

   - 前端：http://localhost（经 Nginx）或 http://localhost:3000（直连 UI）
   - API：http://localhost/api（经 Nginx）或 http://localhost:5001（直连）
   - Neo4j 浏览器：http://localhost:7474
   - MinIO 控制台：http://localhost:9001

### 方式二：启动脚本

```bash
cd docker
./start.sh
```

脚本会校验 `api/.env` 与 compose 配置，打印访问地址后构建并启动全部服务。

### 可选 worker（浏览器自动化 / 电脑控制）

浏览器自动化与电脑控制 worker 通过 `local-workers` profile 单独启用：

```bash
cd docker
docker compose --profile local-workers up -d
```

## 本地开发

### 方式一：Docker 基础设施 + 宿主机运行代码

1. 仅启动基础设施（数据库、Redis、记忆系统）：

   ```bash
   cd docker
   docker compose up -d llmops-db llmops-redis llmops-neo4j llmops-minio
   ```

2. 本地运行 API、Celery 与 UI：

   ```bash
   # 终端 1: 启动 API（Quart ASGI）
   cd api
   uvicorn app.http.asgi_app:app --host 0.0.0.0 --port 5001

   # 终端 2: 启动 Celery worker
   cd api
   celery -A app.http.celery_app:celery_app worker --loglevel=info

   # 终端 3: 启动 UI（Vite 开发服务器，热更新）
   cd ui
   npm run serve
   ```

### 方式二：开发模式 Compose（前端热更新）

```bash
cd docker
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml up -d llmops-api llmops-ui
```

- `llmops-api` 以开发模式运行（`APP_DEBUG=1`、`MIGRATION_ENABLED=true`）
- `llmops-ui` 使用 `node:24-alpine` 运行 Vite 开发服务器（http://127.0.0.1:5173，热更新，`VITE_PROXY_TARGET` 指向 `llmops-api`）
- `llmops-nginx` 通过 profile 自动禁用

## 常见场景

### 场景 1：修改 LLM API Key / 业务配置

只需修改 `api/.env` 后重启相关服务：

```bash
# 编辑 api/.env
ATLASCLOUD_API_KEY=your-new-key

cd docker
docker compose restart llmops-api llmops-celery llmops-celery-beat
```

### 场景 2：修改数据库 / Redis / Neo4j / MinIO 密码

修改 `api/.env` 后重建容器：

```bash
# 编辑 api/.env
POSTGRES_PASSWORD=new-password
REDIS_PASSWORD=new-password
NEO4J_PASSWORD=new-password
MINIO_ACCESS_KEY=new-access-key
MINIO_SECRET_KEY=new-secret-key

cd docker
docker compose down
docker compose up -d --build
```

### 场景 3：修改端口映射

修改 `api/.env`：

```bash
API_PORT=8001
UI_PORT=8080
```

重新创建容器：

```bash
cd docker
docker compose down
docker compose up -d --build
```

### 场景 4：修改前端 API 前缀

修改 `api/.env` 中的 `VITE_API_PREFIX` 后，需重新构建 `llmops-ui` 镜像：

```bash
cd docker
docker compose build llmops-ui
docker compose up -d llmops-ui
```

## 注意事项

1. **网络隔离**：容器内部使用 Docker 服务名通信（如 `llmops-db`、`llmops-redis`），宿主机本地开发使用 `localhost`
2. **配置同步**：`api/.env` 是唯一配置源；修改 `VITE_API_PREFIX` 后必须重新 build `llmops-ui`
3. **密钥安全**：不要将包含真实密钥的 `.env` 提交到 Git；部署前运行 `docker/security-check.sh`
4. **健康检查**：数据库与 Redis 配置了健康检查，API / Celery 会等待其就绪后再启动；`llmops-api` 自身暴露 `/healthz`
5. **数据持久化**：PostgreSQL、Redis、Neo4j、MinIO 及应用存储均挂载到 `docker/volumes/` 目录
6. **数据库迁移**：Alembic 迁移仅在 `llmops-api`（`MIGRATION_ENABLED=true`）启动时执行，Celery / Beat 不执行
7. **生产必配项**：`MODEL_KEY_ENCRYPTION_KEY`（Fernet）在 `APP_ENV=production` 时缺失会导致启动失败（fail-fast）；`ADMIN_INITIAL_PASSWORD`、`NEO4J_PASSWORD`、`MINIO_*` 等务必替换默认值并拒绝弱口令（服务端会拒绝 `admin`/`123456` 等常见弱口令）
8. **对外暴露端口**：`llmops-nginx`（80/443）与 `llmops-minio`（9000/9001）默认监听所有网卡，生产环境注意防火墙与访问控制

## 故障排查

### 容器无法启动

```bash
docker compose logs llmops-api
docker compose logs llmops-celery
docker compose ps
```

### 数据库连接失败

- 检查 `api/.env` 中 `POSTGRES_*` 与 entrypoint 拼接的 `SQLALCHEMY_DATABASE_URI` 是否一致
- 确认 `llmops-db` 容器健康状态（`docker compose ps` 中显示 healthy）

### 服务启动即报错退出

通常由缺少必需环境变量导致，入口脚本会列出缺失项：

- 生产环境未配置 `MODEL_KEY_ENCRYPTION_KEY` 会 fail-fast，生成方式：
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- 缺少 `JWT_SECRET_KEY`、`REDIS_HOST` / `REDIS_PORT`、`SQLALCHEMY_DATABASE_URI` 时入口脚本直接报错退出

### API Key 无效 / LangSmith 403 刷屏

- 检查 `api/.env` 中的 Key 是否正确配置
- `LANGCHAIN_API_KEY` 为空或占位符时，应用启动时会自动降级关闭 tracing，避免请求 403

### 弱密码被扫描器接管（Neo4j / MinIO）

Neo4j 与 MinIO 使用默认弱口令（`openagent123` / `minioadmin`）极易被扫描器接管，部署前务必替换 `api/.env` 中的 `NEO4J_PASSWORD`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY` 为强凭据。

## 清理与重置

```bash
# 停止所有服务
docker compose down

# 删除所有数据（谨慎操作!）
sudo rm -rf volumes/

# 重新启动
docker compose up -d --build
```