# 单机 4C4G 部署与资源规划

> **性质**：生效文档（运维指导）。本文的**实测数值**来自本机容器与渲染镜像真机验证；**建议配额**是基于实测的推算，非代码现状。
> **适用**：4 核 4G、3 Mbps 带宽的单台云服务器（生产起步规格）。
> **前置**：渲染链路（P3.7）已完成，渲染镜像与本机渲染均已实测跑通。

---

## 0. 一句话结论

**4C4G 跑不起来，必须拆机。** 稳态实测：**不含渲染**已约 3.57 G（celery 1.54 + api 1.0 + neo4j 0.81 + kkfileview 0.58 + 其余 0.24），已逼近 4G 上限；渲染峰值再叠 1.5–1.7 G → **总量 5.1 G+，必然 OOM**。

两条出路：
1. **单机硬扛（不推荐，仅应急）**：`celery -c 2`、渲染严格串行、上传/L2 错峰——没有任何余量，一次并发就崩；
2. **拆机（推荐）**：把渲染 worker 移到第二台机器（见 §7.1），单机压力立刻回到可接受区间。

> 注：`llmops-render-worker` 空闲占 524 MB（不是原文档写的 90 MB），常驻本身也有成本；
> 拆走后这笔内存与 3.47 GB 镜像体积一并离开首台机器。

---

## 1. 先看三个硬约束（决定一切）

### 1.1 带宽 3 Mbps 会拖垮首次部署（最容易被忽略）

镜像总体积（实测）：

| 镜像 | 体积 |
| --- | --- |
| `llmops-render` | **3.47 GB** |
| `llmops-worker`（browser/computer worker，二者**共用**同一镜像） | 1.8 GB |
| `keking/kkfileview` | 1.6 GB |
| `llmops-api` | 1.48 GB |
| `llmops-ui-dev` | 1.06 GB |
| `neo4j` | 637 MB |
| `postgres`/`pgvector` | 445 MB |
| `redis` | 114 MB |
| `llmops-ui` | 102 MB |
| `nginx` | 62 MB |

**全量拉取 ≈ 10.8 GB。3 Mbps ≈ 366 KB/s → 约 8.4 小时**（且期间几乎无法提供正常服务）。

> ⚠️ 注意：`llmops-worker`（1.8 GB）虽在表中单列，但 **browser 与 computer worker 共用它一份**，
> 不重复计费。`llmops-ui-dev`（1.06 GB）为开发版 UI，生产用 `llmops-ui`（102 MB），可跳过。

**对策**（择一或组合）：
- **`llmops-render` 单独处理**：3.47 GB 是最大头，且按 §7.1 它本就该部署在**第二台机器**上，
  不需要拉到首台；
- **在本地/其他机器 `docker save` → 上传 tar → `docker load`**，绕开逐层拉取；
- **错峰拉取**：先跑基础设施（db/redis/neo4j/kkfileview），再逐个拉业务镜像。

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

## 2. 服务内存清单（4C4G 实测基线）

以下为**实测常驻内存**。⚠️ 该值随运行时长显著上升（子进程膨胀 + 页面缓存），故区分两个口径：
**冷启基线**（容器刚起）与**稳态**（运行 ~1 小时后，两次读数一致）。**容量规划请用稳态值**。

| 服务 | 冷启 | **稳态** | 镜像 | 4C4G 建议 | 理由 |
| --- | --- | --- | --- | --- | --- |
| `llmops-celery` | 926 MB | **1.54 G** | 1.48 GB | **保留** | 核心业务异步任务；`-c 4` 的子进程会持续膨胀 |
| `llmops-api` | 353 MB | **998 MB** | 1.48 GB | 保留 | 核心 |
| `llmops-neo4j` | 738 MB | **808 MB** | 637 MB | **必须保留** | 记忆系统（TKG）底座；关闭则记忆系统不可用 |
| `llmops-kkfileview` | 531 MB | **583 MB** | 1.6 GB | **必须保留** | 文档在线预览；关闭则文档系统预览不可用 |
| `llmops-render-worker` | ~90 MB | **524 MB** | 3.47 GB | **常驻**（见 §3） | 视频出片；渲染时峰值 1.5–1.7 G |
| `llmops-db`（pgvector） | 129 MB | **99 MB** | 445 MB | 保留 | 核心 |
| `llmops-ui` | 47 MB | **66 MB** | 102 MB | 保留 | 生产用 nginx 静态版 |
| `llmops-celery-beat` | 26 MB | **63 MB** | 1.48 GB | 保留 | 定时任务调度 |
| `llmops-computer-worker` | 11 MB | **28 MB** | 1.8 GB（与 browser 共用 `llmops-worker`） | **保留** | 无桌面端用户的电脑控制回退通道；关则 Web 侧无此能力 |
| `llmops-redis` | 16 MB | **24 MB** | 114 MB | 保留 | 核心 |
| `llmops-browser-worker` | 6 MB | **17 MB** | 同上（共用同一镜像） | **保留** | 无桌面端用户的浏览器自动化回退通道 |
| `llmops-nginx` | 5 MB | **7 MB** | 62 MB | 保留 | 入口 |

**全部容器常驻合计（稳态，含 render 空闲）** ≈ **4.09 G**
（celery 1.54 + api 0.998 + neo4j 0.808 + kkfileview 0.583 + render 空闲 0.524 + db 0.099 + ui 0.066 + beat 0.063 + computer 0.028 + redis 0.024 + browser 0.017 + nginx 0.007 ≈ 4.09 G）

**其中不含 render 的基础服务** ≈ **3.57 G**。

> ⚠️ 渲染还没开始，**3.57 G 就已逼近 4G 上限**。渲染峰值 1.5–1.7 G 一旦叠加，
> 总量直奔 5.1–5.3 G。因此 4C4G 单机**必须同时做两件事**：
> 1. `llmops-celery` 由默认 `-c 4` 降到 `-c 2`（省 ~0.6 G）；
> 2. 渲染严格串行（闸门已保证并发=1）且不与大文件上传/L2 解析同时发生。
>
> 即便两件都做，余量也仅 ~1 G；**§7.1 的「拆机」不是优化项，是容量上的必需项**。

> ⚠️ **browser / computer worker 也不是裁减项**（此前误列为「默认已关」，已纠正）：
> 二者是「未安装桌面端的纯 Web 用户」使用浏览器自动化 / 电脑控制的**唯一通道**。关掉它们，
> 这类用户直接失去该能力。代价仅 ~45 MB（1.8 GB 是镜像体积，与内存无关）。
>
> **与桌面客户端的关系（容易混淆，务必分清）**：桌面客户端**自带**这两个 worker
> （`desktop/main.js` 的 `startWorker` 启动本机子进程，token 每次随机生成），
> 电脑控制经本机 bridge（`host.docker.internal:9876`）回传，**完全不经过这两个容器**。
> 所以「桌面端有没有电脑控制」与「这两个容器开不开」是两件独立的事：
> - 桌面端场景 → 靠桌面端自带 worker（且 cua-driver 提供后台定向控制）；
> - 纯 Web 场景 → 靠容器内的 `BROWSER_AUTOMATION_URL` / `COMPUTER_CONTROL_URL` 回退。

> ⚠️ **不要关 neo4j / kkfileview**。二者是功能必需项，不是可选组件：
> - `neo4j` 是整个记忆系统 TKG 的存储底座（`ledger_writer` / `consolidation_engine` /
>   `degradation_manager` / `cold_storage_manager` / `spread_activation` 等 12+ 个模块依赖）；
> - `kkfileview` 是文档在线预览的核心（`admin_routes_7` 生成预览地址）。
>
> 关闭它们省下的 ~1.27 G 换不来对等价值——会直接让记忆系统与文档预览不可用。二者在
> compose 中**默认启动**（无 profile）。真正省内存的杠杆是「主 worker 降并发」与
> 「渲染走独立队列」，见 §3.3 与 §6。

> ⚠️ `llmops-celery` 稳态 **1.54 G**（冷启 926 MB），是**最大的可压缩项**。它承载全部
> 业务异步任务（默认 `-c 4`，4 个子进程各约 300 MB 且会持续膨胀）。4C4G 上应降到
> `-c 2`（省约 0.6 G），代价是异步吞吐减半、可随时调回。

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

### 3.3 渲染闸门（已全部落地）

| # | 层 | 措施 | 解决的问题 |
| --- | --- | --- | --- |
| 1 | 入口 | 每账号同时只允许 1 个渲染 | 用户连点多个 |
| 2 | 入口 | 防重锁（composition+账号，Redis SETNX） | 重复派发 |
| 3 | 队列 | **主 worker 显式排除 render 队列** | 见下方隐患 |
| 4 | 执行 | `-c 1`（§3.2 已有） | 峰值锁 ~1.5G |
| 5 | 执行 | `acks_late=True` + `reject_on_worker_lost=True` | 崩溃丢任务 |
| 6 | 队列 | 积压超阈值（建议 5）拒绝并提示 | 任务堆到用户以为卡死 |
| 7 | 回退 | Celery 不可用 → **直接报错**（不回退同步） | 同步渲染打爆 |

> **✅ 隐患已修复**：`llmops-celery` 原先**未设 `CELERY_QUEUES`**，而 Celery 已声明队列含
> `render`，未传 `-Q` 的 worker 会**消费全部已声明队列**；render worker 不在时（重启间隙/未启动），
> 主 worker 会以 `-c 4` 捞走渲染任务 → **4 并发 ≈ 2.6 G+**。
> 现已在 compose 给主 worker 设 `CELERY_QUEUES: celery,mail,consolidation`（排除 render）。

> **闸门 1~7 已全部落地**（载体见 §6），不再是待办。配置项 3、4 亦已生效。

### 3.4 超时设置（已落地）

| 层 | 现状 | 说明 |
| --- | --- | --- |
| subprocess | `RENDER_TIMEOUT_SEC=900`（15 分钟） | compose 已收紧，避免长任务占满 2 核 |
| Celery | `soft_time_limit=1200`（20 分钟） | 略大于 subprocess 超时，留收尾余量（`render_tasks._SOFT_TIME_LIMIT_SEC`） |
| 队列可见性 | `visibility_timeout=86400` | 保持 |
| ffprobe 探测 | 硬编码 120s | 保持 |

### 3.5 存储后端：3M 带宽下的必选项

**结论：一旦有真实用户下载素材/成品，必须切云对象存储（COS/OSS），理由不是省钱而是解放带宽。**

| 后端 | 文件 URL | 下载是否占你的 3M 带宽 |
| --- | --- | --- |
| `local`（默认） | `/storage/local/{key}`（经你的服务器） | **占满**，且全体用户共享 3M |
| `cos` / `oss` | 直连对象存储域名 | **不占**，你的 3M 只管 API |

- 存储单价：COS 标准存储 **0.118 元/GB/月**，云硬盘约 0.35 元/GB/月；
- 流量单价：COS 外网下行 **0.5 元/GB**，轻量服务器超额流量 **0.8 元/GB**；
- **同地域** 服务器 → COS 的写入走内网，**免费**（渲染产物入库零流量成本）。

**切换方式**：admin 存储配置板块切换激活后端，**无需停机**。`upload_file.storage_backend` 记录每个文件的真实后端，下载按记录路由，历史文件仍可访问；存量文件可用 `StorageMigrationService` 批量搬迁。

**已验证的能力边界**：分片上传（>5MB 大文件，含全部视频素材）**已支持落盘到激活后端**（P2B-2）。修复前该链路写死 `local`，会导致切到 COS 后大视频仍留在本地盘、下载继续占满 3M——这是 3M 环境下的致命瓶颈，现已解除。

---

## 4. 回链（出片完成通知）

**通道现状（已查证 + 已接线）**：

| 通道 | 状态 |
| --- | --- |
| `agent_notification` | ✅ 端到端闭合，但**语义是 app 构建专用**（`create_agent_notification` 需 `app_id`），不适合渲染 |
| `document_index_notification` | ✅ **渲染回链已接入**（前端 `App.vue` 全局订阅 + 后端订阅处理器 + `room = account_id`，此前只缺生产者） |
| `schedule_task_result` | ⚠️ 后端推送，**前端未订阅** |
| L1/L2 索引 | 只写 DB 状态，靠前端轮询 |

**落地方式**：渲染完成（成功或重试耗尽失败）时，`render_tasks._notify_render_finished`
经 `NotificationService.create_notification` 落一条通知，再经
`ws_manager.emit_notification_to_user(room=account_id, event="document_index_notification")` 推送。
**复用既有通道，前端零改动**，不自造新事件。

> 与设计原案的差异：设计写「复用 `agent_notification`」，实测该通道需 `app_id`（app 构建专用）；
> 成品本质是「一篇入库文档」，故改用 `document_index_notification`——语义更贴、且前端已订阅。

---

## 5. 部署步骤

> ⚠️ **4C4G 单机不推荐**（见 §0/§7.1）。推荐形态：**首台 4C4G（不含 render）+ 渲染机 4C8G**。
> 下面步骤 1/2/4 在首台执行；步骤 3（渲染镜像）在**第二台机器**执行。

```bash
# ===== 首台（4C4G，不含 render）=====
cd docker

# 1) 先起基础设施（先验证连通）
docker compose up -d llmops-db llmops-redis llmops-neo4j llmops-kkfileview

# 2) 业务镜像（3M 下建议逐个，耐心等）
docker compose pull llmops-api llmops-ui llmops-nginx llmops-worker
docker compose up -d llmops-api llmops-celery llmops-celery-beat \
  llmops-ui llmops-nginx llmops-browser-worker llmops-computer-worker
```

```bash
# ===== 第二台（4C8G，只跑渲染；见 §7.1 跨机接线）=====
# 3) 渲染镜像（3.47 GB，最慢的一步）
docker compose pull llmops-render-worker
docker compose up -d llmops-render-worker

# 4) 验证渲染链路（真出片）
docker compose exec llmops-render-worker \
  /opt/hyperframes/node_modules/.bin/hyperframes --version
docker compose exec llmops-render-worker ffmpeg -version | head -1
```

**首台默认启动清单**：`llmops-api`、`llmops-celery`、`llmops-celery-beat`、`llmops-ui`、`llmops-nginx`、`llmops-db`、`llmops-redis`、`llmops-neo4j`、`llmops-kkfileview`、`llmops-browser-worker`、`llmops-computer-worker`（**全部默认启动**，compose 中已无 `profiles` 裁减项）。`llmops-render-worker` 在第二台启动。

---

## 6. 改动清单（已全部落地）

| # | 改动 | 类型 | 状态 |
| --- | --- | --- | --- |
| 1 | 主 worker 设 `CELERY_QUEUES` 排除 render | compose | ✅ 已落地（`celery,mail,consolidation`） |
| 2 | `neo4j`/`kkfileview`/`browser-worker`/`computer-worker` 曾加 `profiles` → **已全部回滚** | compose | ❌ 已回滚：四者均为功能必需项（见 §2），compose 中已无 `profiles` 裁减项 |
| 3 | render worker 加 `deploy.resources.limits` + `NODE_OPTIONS` | compose | ✅ 已落地（cpus 2 / mem 2800M / V8 堆 2048） |
| 4 | 每账号渲染并发上限 = 1 | 代码 | ✅ `RenderGuardService.MAX_CONCURRENT_RENDERS_PER_ACCOUNT` |
| 5 | 渲染防重锁（Redis SETNX，脚本指纹） | 代码 | ✅ `RenderGuardService.admit` |
| 6 | `acks_late` + `reject_on_worker_lost` | 代码 | ✅ `render_tasks.py` |
| 7 | 队列积压阈值拒绝（阈值 5） | 代码 | ✅ `RenderGuardService`（`mark_enqueued`/`mark_dequeued`） |
| 8 | 去掉同步回退，失败即报错 | 代码 | ✅ `render_video.py`（不再有 sync 分支） |
| 9 | 渲染完成回链 | 代码 | ✅ 复用 `document_index_notification` 通道（前端零改动） |
| 10 | `RENDER_TIMEOUT_SEC` 收紧 + Celery `soft_time_limit` | 配置+代码 | ✅ 900s / `soft_time_limit=1200s` |

**闸门实现载体**：`api/internal/service/render_guard_service.py`（`RenderGuardService`）。
准入在派发端（`render_video._dispatch_render`），归还在任务开始/结束端（`render_tasks`），
两端用同源脚本指纹（sha256 前 32 位）保证防重锁能正确释放。

> 关于第 9 项：设计原写「复用 `agent_notification`」，但实测该通道是 app 构建专用
> （`create_agent_notification` 需 `app_id`）。而成品本质是「一篇入库文档」，故改走
> **`document_index_notification`** 通道——前端（`App.vue`）已全局订阅、后端已有订阅
> 处理器与 `room = account_id` 约定，此前只缺生产者。复用后前端**零改动**。

---

## 7. 风险与验证记录

### 7.1 拆机方案（推荐；4C4G 单机的正解）

**为什么必须拆**：稳态实测**不含渲染已 ~4.09 G**（§2），已压到 4G 上限；渲染峰值再叠 1.5–1.7 G。
单机只能靠 `celery -c 2` + 严格错峰硬扛，没有任何余量。

**拆什么**：只拆 `llmops-render-worker`（`render` 队列独占），首台立刻回收 **524 MB 空闲内存 + 1.5–1.7 G 渲染峰值 + 3.47 GB 镜像体积**。

**⚠️ 不要拆 browser/computer worker**：二者合计仅 **45 MB**（17 + 28），拆走省不到 50 MB，
却要新开跨机链路。**它们是镜像大（1.8 GB）不是内存大**——按内存算，拆它们性价比为零。

**⚠️ 2C2G 装不下渲染**：渲染要求 V8 堆 2048 MB（§3.2 的 `NODE_OPTIONS`）+ Chromium，
而 HyperFrames CLI 的 `LOW_MEMORY_TOTAL_MB_THRESHOLD = 8192` 会在 <8 G 时降级。
2C2G 上渲染会因内存不足直接失败。**渲染机至少 4C8G**（8G 是为了跳出 low-memory 慢路径）。

#### 跨机接线（3 处改动）

渲染 worker 拆到独立机器后，需解决三件事：

| # | 事项 | 改法 |
| --- | --- | --- |
| 1 | **消息代理**：新机器要收 `render` 队列 | `REDIS_HOST` 指向首台 Redis。注意 compose 里 Redis 端口绑在 `127.0.0.1`（[docker-compose.yaml:L262-L263](file:///d:/DEMO/openagent-main/docker/docker-compose.yaml#L262-L263)），需改为内网可达 + 防火墙白名单，**不要**暴露公网 |
| 2 | **数据库**：渲染任务要读账号、写成品文档 | 同上，`POSTGRES_HOST` 指向首台 Postgres（现也绑 `127.0.0.1`，[L281-L282](file:///d:/DEMO/openagent-main/docker/docker-compose.yaml#L281-L282)） |
| 3 | **成品落盘**：`store_render_output` 走**激活存储后端** | ① **激活后端 = `cos`/`oss`（推荐）**：产物经 SDK 直传对象存储，两机无需共享磁盘；② 激活后端 = `local`：渲染机写的 `/app/api/storage/uploads` 首台 API 看不见 → **必须挂共享存储**（NAS/对象存储网关），否则出片后检索/预览 404 |

> **关键前提**：`store_render_output` 的上传走 `RuntimeStorageProxy`，落的永远是**当时激活的后端**
> （[knowledge_base_service.py:L478-L480](file:///d:/DEMO/openagent-main/api/internal/service/knowledge_base_service.py#L478-L480) →
> [module.py:L108-L121](file:///d:/DEMO/openagent-main/api/app/http/module.py#L108-L121) 的
> `binder.bind(CosService, to=RuntimeStorageProxy)`；默认 `STORAGE_BACKEND=local`）。
> 所以**拆机前建议先把激活后端切到 COS/OSS**，否则会踩第 3 条的坑。
> 注意：切后端只影响**产物落盘**；`storage/` 卷仍被分片暂存、本地后端历史文件、日志等使用，
> 两机都需保留该卷（渲染机至少需要分片暂存与临时目录）。

#### 首台剩余容量（拆机后，稳态）

```
不含 render：4.09 G - 0.524 G ≈ 3.57 G      （4G 上限下仍偏紧）
再把 celery 降到 -c 2：3.57 - 0.7 ≈ 2.87 G  （留 ~1.1 G 给上传/L2 峰值，可接受）
```

**结论**：拆掉渲染 + `celery -c 2` 后，首台从「必然 OOM」变为「有约 1 G 余量」。
这是 4C4G 上唯一能真正跑起来的组合。

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
