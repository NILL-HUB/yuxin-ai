# 钰心 AI（YuxinAI）

钰心 AI（钰心AI）是一个「设备级 Agent + 合伙人共创生态」平台：基于 **Quart + LangChain / LangGraph** 的后端，搭配 **Vue 3** 工作台，提供可视化工作流编排、设备工具、技能（Skills）、数字分身与 OpenAPI 交付能力。

[访问官网](https://openllm.cloud) · [API 文档](https://s.apifox.cn/c76bd530-fd50-429c-94cc-f0e41c2675d1/api-305434417) · [GitHub](https://github.com/NILL-HUB/yuxin-ai) · [深入问答（DeepWiki）](https://deepwiki.com/NILL-HUB/yuxin-ai)

![Python 3.11](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)
![Quart ASGI](https://img.shields.io/badge/quart-asgi-20B2AA?logo=python&logoColor=white)
![Vue 3](https://img.shields.io/badge/vue-3-4FC08D?logo=vue.js&logoColor=white)
![Docker Compose](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-vector%20db-4169E1)
![Neo4j](https://img.shields.io/badge/neo4j-tkg%20graph-008CC1?logo=neo4j&logoColor=white)
![MinIO](https://img.shields.io/badge/minio-object%20storage-F8583D?logo=minio&logoColor=white)

> 本项目由 [Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=yuxin-ai) 赞助支持。

## 目录

- [项目简介](#项目简介)
- [架构](#架构)
- [技术栈](#技术栈)
- [供应商生态](#供应商生态)
- [快速开始](#快速开始)
- [功能展示](#功能展示)
- [项目结构](#项目结构)
- [文档与说明](#文档与说明)
- [测试](#测试)
- [联系方式](#联系方式)
- [鸣谢](#鸣谢)

## 项目简介

![钰心AI 产品总览](https://github.com/user-attachments/assets/0f8f7517-1622-46ea-9554-fb13af4841a1)

> 当前定位：钰心AI 正在向「设备 Agent + 合伙人共创生态」转型。以下内容描述的是当前实现底座，后续会随新架构逐步演进。

钰心AI 是结合设备级 Agent 控制、技能（Skill）封装、数字分身与合伙人收益生态的平台。仓库目前包含：Quart 后端、Celery 异步任务与定时调度、Vue 3 前端工作台、可视化工作流编排、工具治理、模型路由、技能、记忆、计费，以及基于 OpenAPI 的对外交付能力。

当前代码库已覆盖的核心能力：

- 首页助手通过 A2A 将用户问题路由到应用广场中已发布的公共 Agent，也可以把自然语言需求转成新的 AI Agent / 应用创建流程。
- 在独立工作台中创建和管理 AI 应用，支持草稿、发布、分析、版本对比和提示词对比。
- 通过可视化节点编排工作流，节点涵盖 LLM、工具调用、知识库检索、代码执行、HTTP 请求、条件分支、文本处理、模板转换和参数提取。
- 管理数据集、上传文档、查看切片，并把检索能力接入工作流或应用。
- 通过类似应用商店的页面浏览公共应用、工具和工作流。
- 通过 `POST /api/openapi/chat` 以 REST 或流式方式调用已发布应用。
- 记忆系统基于 Neo4j（TKG 时序知识图谱）与 MinIO（对象存储）沉淀长期记忆。
- 内置浏览器自动化与电脑控制 Worker，可挂载设备级操作能力。

## 架构

![基础对话架构](https://github.com/user-attachments/assets/f6bdccf2-a6ff-4924-b68b-ec4d3581796e)

[查看原始大图](https://github.com/user-attachments/assets/f6bdccf2-a6ff-4924-b68b-ec4d3581796e)

### 技术栈

- **AI 框架与编排**：LangChain、LangGraph、Workflow 编排、工具调用、A2A 委派、Skill、Memory
- **知识与检索**：RAG、语义检索、全文检索、混合检索、pgvector、FAISS、rerank
- **记忆系统**：Neo4j（TKG 时序知识图谱）、MinIO（对象存储）
- **后端**：Python 3.12、Quart（ASGI / uvicorn）、SQLAlchemy、Celery、Celery Beat、Socket.IO、Redis、PostgreSQL（pgvector）
- **前端**：Vue 3、JavaScript / TypeScript、Vite、TailwindCSS、Pinia、Vue Flow、Arco Design
- **基础设施与交付**：Docker Compose、Nginx、kkFileView、OpenAPI、SSE
- **模型接入**：OpenAI、Atlas Cloud、DeepSeek、Grok、Google、月之暗面（Moonshot）、通义、文心、Ollama、智谱

### 供应商生态

![Atlas Cloud](ui/public/atlas-cloudXyuxin-ai.jpg)

- Atlas Cloud 现已作为 OpenAI 兼容提供商接入，可通过 `ATLASCLOUD_API_KEY` 与 `ATLASCLOUD_API_BASE` 使用。
- 官方网站：[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=yuxin-ai)
- 接入文档：[https://www.atlascloud.ai/docs](https://www.atlascloud.ai/docs)

## 快速开始

### 环境要求

- Docker 20.10+ 与 Docker Compose 2.x
- 推荐 8 GB 以上内存运行完整栈
- 至少准备一个可用的模型提供商 API Key

### 安装与启动

1. 克隆仓库：

   ```bash
   git clone https://github.com/NILL-HUB/yuxin-ai.git
   cd yuxin-ai
   ```

2. 创建运行时环境文件：

   ```bash
   cp api/.env.example api/.env
   ```

3. 检查 `api/.env` 中的最小必填项：

   - `JWT_SECRET_KEY` — JWT 签名密钥（可用 `openssl rand -hex 32` 生成）
   - `POSTGRES_PASSWORD` — PostgreSQL 数据库密码
   - `REDIS_PASSWORD` — Redis 密码
   - `MODEL_KEY_ENCRYPTION_KEY` — 工具凭证加密密钥（Fernet，生产环境必配，缺失会启动失败）
   - `NEO4J_PASSWORD` — 记忆系统 Neo4j 密码（务必替换默认值）
   - `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` — 记忆系统 MinIO 凭据（务必替换默认值）
   - `ADMIN_INITIAL_PASSWORD` — 首次启动自动创建的超级管理员密码（服务端拒绝弱口令）
   - `VITE_API_PREFIX` — 前端 API 前缀（UI 构建时读取，缺失会构建失败）
   - 模型提供商 Key 通过管理后台统一配置（数据库加密存储）；`ATLASCLOUD_API_KEY` 保留为运行时兜底

4. 启动 Docker 编排：

   ```bash
   cd docker
   docker compose up -d --build
   ```

5. 打开本地服务：

   | 服务 | 地址 | 说明 |
   | --- | --- | --- |
   | 前端 | http://localhost | 经 Nginx 访问（默认入口） |
   | 前端（直连） | http://localhost:3000 | Vue 3 Web 界面 |
   | API | http://localhost:5001 | Quart REST API（ASGI） |
   | Neo4j | http://localhost:7474 | 记忆系统 TKG 管理界面 |
   | MinIO | http://localhost:9001 | 记忆系统对象存储控制台 |

### 本地开发

后端：

```bash
cd api
pip install -r requirements.txt
uvicorn app.http.asgi_app:app --host 0.0.0.0 --port 5001
```

后台任务（Celery，可选）：

```bash
cd api
celery -A app.http.celery_app:celery_app worker --loglevel=info
```

前端：

```bash
cd ui
npm install
npm run serve
```

Vite 默认在 `5173` 端口提供服务。前端基于 `VITE_API_PREFIX` 解析 API 地址，本地开发时通常通过 `/api` 代理到 Quart 后端。

也可以仅用 Docker 启动基础设施（数据库、Redis、记忆系统），代码在宿主机运行：

```bash
cd docker
docker compose up -d llmops-db llmops-redis llmops-neo4j llmops-minio
```

常用命令：

```bash
cd api
pytest
```

```bash
cd ui
npm run type-check
npm run lint
npm run build
npm run test:unit -- --run
```

## 功能展示

### 1. 首页助手体验

![钰心AI 首页助手](https://github.com/user-attachments/assets/7ebb7827-838b-4bd2-b522-9f544f32416a)

首页作为默认的 AI 助手入口，通过 A2A 将用户问题路由到应用广场中最相关的已发布公共 Agent，也可以把自然语言需求转成新的 AI Agent / 应用创建流程。同一入口还支持多轮对话、推荐问题、图片上传和语音输入。

### 2. 应用工作台与深度思考

![钰心AI 应用工作台](https://github.com/user-attachments/assets/2dd4dc3e-f216-4c8d-96e4-7a2f81e138ae)

应用工作台是 AI 应用的主工作区：左侧负责模型、提示词和能力绑定，右侧负责调试对话、执行轨迹与结果检查。截图中的 Deep Research 对应代码中的深度思考模式 `enable_deep_thinking`。

主要能力：

- 配置与版本管理：集中处理模型切换、人设与回复逻辑、草稿、发布、版本对比、提示词对比和应用复制。
- 能力接入：统一绑定插件、MCP、Skills、Agent 子应用、工作流和知识库。
- 复杂任务执行：开启深度思考后，应用可拆解任务并调度已绑定能力完成多步骤处理。
- 沙箱与产物输出：支持脚本执行、代码处理、文件生成和附件导出。
- 调试与结果验证：右侧调试区用于发起真实对话，查看深入思考轨迹、任务状态、生成产物与最终结果。

### 3. 可视化工作流编辑器

![钰心AI 工作流编辑器](https://github.com/user-attachments/assets/23b510e2-1232-4f52-9262-812a7523ae21)

工作流支持通过节点方式编排，包括 LLM、工具调用、数据集检索、代码执行、HTTP 请求、模板转换、文本处理、变量赋值、参数提取、条件分支、开始节点和结束节点。

### 4. 数据集与检索

![钰心AI 数据集管理](https://github.com/user-attachments/assets/6f000681-db56-461a-bac9-a2dd5d6cd009)

创建数据集、上传文档、查看文档切片，并将检索能力接入工作流或 AI 应用，实现知识增强行为。

### 5. OpenAPI 交付

![钰心AI OpenAPI](https://github.com/user-attachments/assets/40769d35-89e1-4b76-9686-a431a77a42c7)

应用发布后，可以通过 `POST /api/openapi/chat` 进行标准调用或流式调用，并支持多轮对话所需的会话标识。

## 项目结构

```text
.
├── api/            # Quart 后端（服务、任务、迁移、测试）
├── ui/             # Vue 3 前端（Vite、路由、组件、测试）
├── desktop/        # Electron 桌面壳（Web UI + 本地 Worker 桥）
├── mobile/         # Capacitor 移动端（Android / iOS）
├── docker/         # Docker Compose 编排、Nginx、PostgreSQL 初始化
├── scripts/        # 辅助脚本与校验工具
├── skills/         # 内置技能包
├── docs/           # 架构与设计文档
└── README.md       # 项目说明
```

## 文档与说明

- [docker/README.md](docker/README.md) — Docker 部署配置说明
- [ui/README.md](ui/README.md) — 前端说明
- [desktop/README.md](desktop/README.md) — 桌面壳说明
- [docs/README.md](docs/README.md) — 架构与设计文档索引
- [api/.env.example](api/.env.example) — 环境变量参考

## 测试

仓库已包含自动化的后端与前端测试。

- 后端：`cd api && pytest`
- 前端单元测试：`cd ui && npm run test:unit -- --run`
- 前端类型检查：`cd ui && npm run type-check`
- 前端构建校验：`cd ui && npm run build`

## 联系方式

- 项目地址：[https://github.com/NILL-HUB/yuxin-ai](https://github.com/NILL-HUB/yuxin-ai)
- 官网：[https://openllm.cloud](https://openllm.cloud)
- API 文档：[https://s.apifox.cn/c76bd530-fd50-429c-94cc-f0e41c2675d1/api-305434417](https://s.apifox.cn/c76bd530-fd50-429c-94cc-f0e41c2675d1/api-305434417)
- DeepWiki：[https://deepwiki.com/NILL-HUB/yuxin-ai](https://deepwiki.com/NILL-HUB/yuxin-ai)

## 鸣谢

- 感谢 [Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=yuxin-ai) 为钰心AI 提供支持。
- 感谢 Rui Yang 与 Haoyu Wang（Johns Hopkins University）以负责任披露的方式报告了内置工具图标 URL 构造中的 Host Header 污染（Host Header poisoning）问题，帮助项目进一步提升安全性。