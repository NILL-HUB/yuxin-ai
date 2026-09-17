# 单机 4C4G 部署与资源规划

> **性质**：生效文档（运维指导）。本文的**实测数值**来自本机容器与渲染镜像真机验证；**建议配额**是基于实测的推算，非代码现状。
> **适用**：4 核 4G、3 Mbps 带宽的单台云服务器（生产起步规格）。
> **前置**：渲染链路（P3.7）已完成，渲染镜像与本机渲染均已实测跑通。

---

## 0. 一句话结论

**4C4G 可以跑，但没有余量。** 渲染峰值 ~1.7G 叠加基础服务 ~1.5G 已接近 3.2G，一旦并发业务请求（大文件上传、L2 解析）同时发生，OOM 风险真实存在。真正的解法是把渲染拆到独立机器；单机方案是「能用」而非「充裕」。

---

## 1. 先看三个硬约束（决定一切）

### 1.1 带宽 3 Mbps 会拖垮首次部署（最容易被忽略）

镜像总体积（实测）：

| 镜像 | 体积 |
| --- | --- |
| `llmops-render` | **3.47 GB** |
| `llmops-worker`（浏览器/电脑 worker，默认不启动） | 1.8 GB |
| `keking/kkfileview` | 1.6 GB |
| `llmops-api` | 1.48 GB |
| `llmops-ui-dev` | 1.06 GB |
| `neo4j` | 637 MB |
| `postgres`/`pgvector` | 445 MB |
| `minio` | 175 MB |
| `redis` | 114 MB |
| `llmops-ui` | 102 MB |
| `nginx` | 62 MB |

**全量拉取 ≈ 10.9 GB。3 Mbps ≈ 366 KB/s → 约 8.4 小时**（且期间几乎无法提供正常服务）。

**对策**（择一或组合）：
- **裁减服务**（见 §2）：只拉必需镜像（api + ui + nginx + pgvector + redis + render ≈ 5.7 GB），约 4.4 小时；
- **在本地/其他机器 `docker save` → 上传 tar → `docker load`**，绕开逐层拉取；
- **错峰拉取**：先跑基础设施（db/redis），再逐个拉业务镜像。

### 1.2 渲染在 4G 上必然进入 low-memory 模式

HyperFrames CLI 内置阈值 `LOW_MEMORY_TOTAL_MB_THRESHOLD = 8192`（源码常量，非配置项）。**容器内存 < 8G 时自动降级**：锁死 1 worker + 强制逐帧截图。

也就是说，**4C4G 上渲染永远走慢路径**，这是设计使然、不是故障。实测差异：

| 组合 | low-memory（4G 必现） | 关闭 low-memory |
| --- | --- | --- |
| 10s/300 帧（纯文字） | 20.3s | 12.6s |
| 30s/900 帧（含视频素材） | 62s | 38s |

> 关闭可快 ~40%，但会超 V8 默认堆（见 §3.4），**不建议在 4G 上关闭**。

### 1.3 Node V8 默认堆上限会限制并发

CLI 自报：默认堆上限 2240 MB 只支持约 1 个 capture worker。超过即告警：

```
[WARN] 2 capture workers may exceed this process's V8 heap (limit 2240MB supports ~1)
```

**结论**：4C4G 上「渲染并发 = 1」不只是内存选择，也是 V8 堆的硬约束。

---

## 2. 服务裁减清单（4C4G 必做）

以下为**实测常驻内存**（本机 idle 基线，非峰值；峰值更高）：

| 服务 | 实测内存 | 镜像 | 4C4G 建议 | 理由 |
| --- | --- | --- | --- | --- |
| `llmops-celery` | **926 MB** | 1.48 GB | **保留** | 核心业务异步任务 |
| `llmops-neo4j` | **738 MB** | 637 MB | **关闭** | 仅记忆系统 TKG 使用；单机上是最大奢侈项 |
| `llmops-kkfileview` | **531 MB** | 1.6 GB | **关闭** | 文档在线预览，非核心链路 |
| `llmops-api` | 353 MB | 1.48 GB | 保留 | 核心 |
| `llmops-db`（pgvector） | 129 MB | 445 MB | 保留 | 核心 |
| `llmops-minio` | 67 MB | 175 MB | **关闭** | 改用本地存储或 COS（`STORAGE_BACKEND=local\|cos`） |
| `llmops-ui` | 47 MB | 102 MB | 保留 | 生产用 nginx 静态版 |
| `llmops-celery-beat` | 26 MB | 1.48 GB | 保留 | 定时任务调度 |
| `llmops-redis` | 16 MB | 114 MB | 保留 | 核心 |
| `llmops-nginx` | 5 MB | 62 MB | 保留 | 入口 |
| `llmops-browser-worker` | 6 MB | 1.8 GB | **默认已关** | `profiles: local-workers` |
| `llmops-computer-worker` | 11 MB | 1.8 GB | **默认已关** | 同上 |
| `llmops-render-worker` | 渲染时 1.5–1.7 G | 3.47 GB | **常驻**（见 §3） | 视频出片 |

**关闭后估算**：基础服务 ~1.5 G（api 353 + celery 926 + db 129 + redis 16 + ui 47 + beat 26 + nginx 5 ≈ 1.5 G）。

> ⚠️ `llmops-celery` 926 MB 偏高且**未设内存配额**。它承载全部业务异步任务，随负载增长。若 OOM，优先查它。

**关闭方法**：为这几个服务加 `profiles: ["optional"]`（当前 `neo4j`/`minio`/`kkfileview` **无 profile，默认会启动**），或用 `--scale` 排除。**这是待做的配置改动**（见 §6）。

---

## 3. 渲染资源分配

### 3.1 内存模型：叠加，不是共享（实测）

同一容器内、同样的 30s/900 帧含视频素材任务：

| 并发渲染数 | 墙钟 | 内存峰值 |
| --- | --- | --- |
| 1 | 59s | **1470 MB** |
| 2 | 62s | **2567 MB** |
| 3 | 83s | **2679 MB** |
| 3 个**串行**（同时 1 个） | 178s | **1659 MB** |

**关键结论**：
- 内存 ≈ **1.5 G × 并发数**，每个渲染是独立 Node + Chromium 进程，互不复用；
- **并发不提升吞吐**：4 核已满，2 并发只快 3 秒、3 并发反而更慢；
- **「排队」本身不省内存**（队列里是几 KB 消息），**「并发=1」才是护城河**。

### 3.2 建议配额

```yaml
llmops-render-worker:
  environment:
    CELERY_QUEUES: render              # 独占 render 队列
    CELERY_WORKER_AMOUNT: '1'          # 并发=1（核心护城河）
    NODE_OPTIONS: --max-old-space-size=2048   # 显式给 V8 堆，默认 2240 已临界
    HYPERFRAMES_BROWSER_PATH: /usr/bin/chromium
    HYPERFRAMES_FFMPEG_PATH: /usr/bin/ffmpeg
    HYPERFRAMES_FFPROBE_PATH: /usr/bin/ffprobe
    HYPERFRAMES_CLI_BIN: /opt/hyperframes/node_modules/.bin/hyperframes
    HYPERFRAMES_CLI_VERSION: '0.8.42'
  deploy:
    resources:
      limits: { cpus: '2', memory: 2800M }   # 留 ~1.2G 给基础服务
```

**为什么 `cpus: '2'`**：4 核总量，渲染是 CPU 密集型，占 2 核可保证 api/celery 仍能响应。

### 3.3 渲染闸门（设计已定，代码待做）

| # | 层 | 措施 | 解决的问题 |
| --- | --- | --- | --- |
| 1 | 入口 | 每账号同时只允许 1 个渲染 | 用户连点多个 |
| 2 | 入口 | 防重锁（composition+账号，Redis SETNX） | 重复派发 |
| 3 | 队列 | **主 worker 显式排除 render 队列** | 见下方隐患 |
| 4 | 执行 | `-c 1`（§3.2 已有） | 峰值锁 ~1.5G |
| 5 | 执行 | `acks_late=True` + `reject_on_worker_lost=True` | 崩溃丢任务 |
| 6 | 队列 | 积压超阈值（建议 5）拒绝并提示 | 任务堆到用户以为卡死 |
| 7 | 回退 | Celery 不可用 → **直接报错**（不回退同步） | 同步渲染打爆 |

> **⚠️ 隐患（已实测确认，必须先修）**：`llmops-celery` 当前**未设 `CELERY_QUEUES`**。
> 实测该容器环境仅含 `MODE=celery`，无 `CELERY_QUEUES`；而 Celery 已声明队列为
> `['celery', 'mail', 'consolidation', 'render']`（含 render），未传 `-Q` 的 worker 会**消费全部已声明队列**。
> 因此 render worker 不在时（重启间隙/未启动），主 worker 会以 `-c 4` 捞走渲染任务 → **4 并发 ≈ 2.6 G+**。
> 修复：给主 worker 设 `CELERY_QUEUES: celery,mail,consolidation`（排除 render）。

> **闸门 1、2、5、6、7 属代码改动，尚未实现**；3、4 属配置改动。不要误以为已生效。

### 3.4 超时设置

| 层 | 现状 | 建议 |
| --- | --- | --- |
| subprocess | `RENDER_TIMEOUT_SEC=1800`（30 分钟） | 4C4G 上可收紧到 **900s**，避免长任务占满 |
| Celery | **无 `task_time_limit`** | 建议加 `soft_time_limit`（略大于 subprocess 超时） |
| 队列可见性 | `visibility_timeout=86400` | 保持 |
| ffprobe 探测 | 硬编码 120s | 保持 |

---

## 4. 回链（出片完成通知）

**现状（查证结论）**：

| 通道 | 状态 |
| --- | --- |
| `agent_notification` | ✅ **唯一端到端闭合**（room + 事件 + 前端 hook + 5s 轮询兜底） |
| `document_index_notification` | ⚠️ 前端在等，**但无生产者**（历史重构中摘除） |
| `schedule_task_result` | ⚠️ 后端推送，**前端未订阅** |
| L1/L2 索引 | 只写 DB 状态，靠前端轮询 |

**方案**：渲染完成事件**复用 `agent_notification` 通道**（room = `agent:{account_id}`），前端**零改动**即可收到通知。**不自造新机制。**

> 待做；当前 `render_video` 工具派发后只返回 task_id，用户需自行去成品库查看。

---

## 5. 部署步骤（4C4G）

```bash
# 1) 先起基础设施（体积小，先验证连通）
cd docker
docker compose up -d llmops-db llmops-redis

# 2) 拉业务镜像（3M 下建议逐个，耐心等）
docker compose pull llmops-api llmops-ui llmops-nginx
docker compose up -d llmops-api llmops-celery llmops-celery-beat llmops-ui llmops-nginx

# 3) 渲染镜像（3.47 GB，最慢的一步）
docker compose pull llmops-render-worker
docker compose up -d llmops-render-worker

# 4) 验证渲染链路（真出片）
docker compose exec llmops-render-worker \
  /opt/hyperframes/node_modules/.bin/hyperframes --version
docker compose exec llmops-render-worker ffmpeg -version | head -1
```

**不启动的服务**（裁减项）：`llmops-neo4j`、`llmops-kkfileview`、`llmops-minio`、`llmops-browser-worker`、`llmops-computer-worker`。

**注意**：若关闭 neo4j/minio/kkfileview，需在 `api/.env` 中确认相关功能降级不会报错（记忆系统 TKG、对象存储改用 local/cos、文档预览不可用）。

---

## 6. 待做的改动清单（本文只出方案，未改代码）

| # | 改动 | 类型 | 影响 |
| --- | --- | --- | --- |
| 1 | 主 worker 设 `CELERY_QUEUES` 排除 render | compose | 堵 §3.3 隐患 |
| 2 | `neo4j`/`minio`/`kkfileview` 加 `profiles: ["optional"]` | compose | 默认不启动 |
| 3 | render worker 加 `deploy.resources.limits` + `NODE_OPTIONS` | compose | 内存隔离 |
| 4 | 每账号渲染并发上限 = 1 | 代码 | 闸门 1 |
| 5 | 渲染防重锁（Redis SETNX） | 代码 | 闸门 2 |
| 6 | `acks_late` + `reject_on_worker_lost` | 代码 | 闸门 5 |
| 7 | 队列积压阈值拒绝 | 代码 | 闸门 6 |
| 8 | 去掉同步回退，失败即报错 | 代码 | 闸门 7 |
| 9 | 渲染完成回链（复用 agent_notification） | 代码 | §4 |
| 10 | `RENDER_TIMEOUT_SEC` 收紧 + Celery `soft_time_limit` | 配置+代码 | §3.4 |

---

## 7. 风险与验证记录

### 7.1 内存超卖风险（真实存在）

即使做完 §6，4C4G 上：渲染峰值 1.7 G + 基础服务 1.5 G ≈ 3.2 G，**剩 0.8 G**。以下场景会同时发生内存占用：
- 用户上传 100 MB+ 视频（素材解析 + 抽帧 + 视觉向量）
- L2 深度解析（每帧视觉调用 + 向量写入）
- 多个用户同时对话（celery 任务堆积）

**建议**：起步阶段对上传体积与 L2 触发做额外限制；监控 `docker stats` 的 `llmops-celery` 与 `llmops-render-worker`。

### 7.2 第三方 CDN 依赖（3M 环境需注意）

`composition_builder` 生成的 composition 引用 `cdn.jsdelivr.net` 的 GSAP；CLI 渲染时还会从 Google Fonts 取字体（缓存到 `/root/.cache/hyperframes/fonts`）。**均需外网可达**。3M 环境下建议：
- 预热字体缓存（首次渲染前手动跑一次）；
- 或把 GSAP 内联/自托管，去掉 CDN 依赖。

> 容器重建会丢失运行时缓存（`/root/.cache` 不在挂载卷内），需重新预热。

### 7.3 本机实测记录（供复核）

| 项 | 数值 |
| --- | --- |
| 渲染产物 | h264 / 1920×1080 / 30fps，ffprobe 校验通过 |
| 单渲染（10s/300帧，4C/4G 限流） | 20.3s，峰值 ~1.5 G |
| 单渲染（30s/900帧+素材，4C/4G） | 62s，峰值 1470 MB |
| 2 并发 | 62s，峰值 2567 MB |
| 3 并发 | 83s，峰值 2679 MB |
| 3 串行（同时 1 个） | 178s，峰值 1659 MB |
| low-memory 阈值 | `LOW_MEMORY_TOTAL_MB_THRESHOLD = 8192`（源码常量） |
| V8 默认堆 | 2240 MB（支持 ~1 worker） |
