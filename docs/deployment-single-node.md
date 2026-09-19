# 单机 4C4G 部署与资源规划

> **性质**：生效文档（运维指导）。本文的**实测数值**来自本机容器与渲染镜像真机验证；**建议配额**是基于实测的推算，非代码现状。
> **适用**：4 核 4G、3 Mbps 带宽的单台云服务器（生产起步规格）。
> **前置**：渲染链路（KB-P3.7）已完成，渲染镜像与本机渲染均已实测跑通。
>
> ⚠️ **2026-09-19 现状变更（影响本文多处结论）**：渲染已**下放到用户本机**（桌面端 render worker），
> 云端 `llmops-render-worker` **默认不启动**（`profiles: ["cloud-render"]`）。因此 §0～§2 中
> 「渲染叠加导致 4.5–5.0 G」「拆机」等结论，是**云端渲染启用时**的容量测算；默认形态下渲染不占服务器资源，
> 见 §3「渲染执行位置」。云端链路完整保留、可一键接通，故相关实测与配额仍具参考价值。

---

## 0. 一句话结论

**4C4G 单机跑得起来，但很紧；拆机是更稳的选择**（前提：云端渲染启用）。稳态实测：**不含渲染**已约 3.57 G
（celery 1.54 + api 1.0 + neo4j 0.81 + kkfileview 0.58 + 其余 0.24），已逼近 4G 上限；
渲染（cgroup 实测峰值 0.9–1.4 G）再叠上去 → **总量 4.5–5.0 G**，超出 4G。

两条出路：
1. **单机硬扛**：`celery -c 2`（省 ~0.6 G）+ 渲染严格串行 + 上传/L2 错峰 → 约 2.9 G，余量 ~1 G，
   **可用但脆弱**，一次并发重活就可能 OOM；
2. **拆机（推荐）**：把渲染 worker 移到第二台机器（见 §7.1）。

> ✅ **好消息（实测修正）**：第二台**不需要 4C8G 那么贵**。曾经断言「2C2G 装不下渲染」，
> 真机把容器限额压到 2048 MiB 跑 60s/1800 帧重负载，**成功出片**（cgroup 峰值仅 0.9–1.1 G，
> 见 §3.1.2）。**2C2G 足以承担渲染**（慢一些、需排队），正合「买一台便宜机器分担」的思路。

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
- **`llmops-render` 单独处理**：3.47 GB 是最大头；渲染已下放到用户本机，云端该服务**默认不启动**
  （`profiles: ["cloud-render"]`），故单机默认**根本不需要拉取它**——仅在需要云端渲染回退时才拉；
- **在本地/其他机器 `docker save` → 上传 tar → `docker load`**，绕开逐层拉取；
- **错峰拉取**：先跑基础设施（db/redis/neo4j/kkfileview），再逐个拉业务镜像。

### 1.2 low-memory 模式：触发条件、代价、以及**可覆盖**（实测）

HyperFrames CLI 内置阈值 `LOW_MEMORY_TOTAL_MB_THRESHOLD = 8192`（**渲染镜像内 CLI 包常量**，
非本项目代码，位置 `/opt/hyperframes/node_modules/hyperframes/dist/cli.js`）。
判定式 `isLowMemorySystem()` 为 `totalMb <= 8192`，其中 `totalMb = min(宿主机内存, cgroup 限额)`。
compose 的 `memory: 2800M` 使 cgroup 为 2800 → **必然判定为 low-memory**。

**它实际做了四件事**（源码逐处核对）：

| # | 行为 | 位置 |
| --- | --- | --- |
| 1 | 强制 `forceScreenshot = true`（捕获模式由 `beginframe` 退化为 `screenshot`） | `cli.js` |
| 2 | 当 `--workers` 未显式指定时，**锁死 1 个 capture worker**（跳过自动校准） | worker 解析 |
| 3 | 强制 software GPU（`softwareGpuForced`） | config merge |
| 4 | 跳过 capture 成本校准（`capture_calibration` 记 `skipped`） | 校准阶段 |

**✅ 可用环境变量覆盖，无需改代码**（CLI 自己在日志里写明了）：
`PRODUCER_LOW_MEMORY_MODE=false` 或 `--no-low-memory-mode`。

> 透传链路已确认：`hyperframes_renderer.build_render_env` 以 `dict(os.environ)` 为基础构造
> 子进程环境，故 compose 里加一行 `PRODUCER_LOW_MEMORY_MODE: 'false'` 即可生效。

### 1.3 Node V8 堆：只是**告警**，不是 worker 数限制（源码核对 + 实测）

**worker 数**由 `computeWorkerSizing`（`cli.js`）决定，取**三路最小值**：

```
optimal = min(cpuBasedWorkers, memoryBasedWorkers, frameBasedWorkers)

cpuBasedWorkers    = max(1, cpuCount - 2)              # 8 核 → 6
memoryBasedWorkers = max(1, ⌊总内存MB × 0.5 / 1536⌋)    # 2800MB → 0 → 1
frameBasedWorkers  = ⌊总帧数 / 30⌋                      # 900 帧 → 30
```

之后还有两道**下限与争用**约束（`MIN_WORKERS=1`、`minParallelFrames` 决定 ≥2、
大任务按 `coresPerWorker` 争用收缩）。

**堆路 `heapBasedWorkers = max(1, ⌊(heapLimit − 1024) / 640⌋)` 不在上面的 min 里**，
它只用于 `exceedsHeapAdvisory = workers > heapBasedWorkers` —— 即**仅产生一条告警**，
**不会把 worker 数压下来**。告警文案（实测）：

```
[WARN] [Render] 2 capture workers may exceed this process's V8 heap
(limit 2240MB supports ~1). If the render dies with "JavaScript heap out of memory",
raise the heap (NODE_OPTIONS=--max-old-space-size=8192) or pass --workers 1.
```

> ⚠️ **修正前一轮的错误表述**：此前本文写「堆路是三路取小之一」「本镜像 worker 上限就是 1」，
> 均不准确。实测在 `NODE_OPTIONS=--max-old-space-size=2048`（堆 2240MB，`heapBasedWorkers=1`）下，
> CLI **实际使用了 2 个 capture worker**并照常出片（仅告警）。故：**堆决定告警，不决定并发**。

**堆值与 `heapBasedWorkers` 的实测对应**：

| `--max-old-space-size` | 实测 `heap_size_limit` | `heapBasedWorkers` | 2 workers 时是否告警 |
| --- | --- | --- | --- |
| 镜像默认（未设） | 1592 MB | 0 → 兜底 1 | 告警 |
| 2048（**当前 compose**） | 2240 MB | 1 | ⚠️ 告警 |
| 3072 | 3264 MB | 3 | ✅ 无告警 |
| 4096 | 4288 MB | 5 | ✅ 无告警 |

> 实测验证：`--max-old-space-size=4096` 时跑 60s/1800 帧、2 workers，告警消失、正常出片
> （耗时 71.4s / cgroup 峰值 1310MB），与 2048 下的 71.6s / 1276MB 基本一致——
> 说明**该告警在这些负载下并未真正触发 OOM**，属余量提示。

**结论**：`NODE_OPTIONS=2048` 是「够用但偏紧」；若要正式启用 2 workers 消除告警，
应提到 **3072**（`heapBasedWorkers=3`）。但见 §3.2：**生产上仍推荐 worker=1**，
因为真正昂贵的是**内存线性叠加**（§3.1），而非这条告警。

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
| `llmops-render-worker` | ~90 MB | **524 MB** | 3.47 GB | **默认不启动**（见 §3） | 视频出片；默认走用户本机，云端为接通后的回退通道（启用时 cgroup 峰值 0.9–1.4 G） |
| `llmops-db`（pgvector） | 129 MB | **99 MB** | 445 MB | 保留 | 核心 |
| `llmops-ui` | 47 MB | **66 MB** | 102 MB | 保留 | 生产用 nginx 静态版 |
| `llmops-celery-beat` | 26 MB | **63 MB** | 1.48 GB | 保留 | 定时任务调度 |
| `llmops-computer-worker` | 11 MB | **28 MB** | 1.8 GB（与 browser 共用 `llmops-worker`） | **保留** | 无桌面端用户的电脑控制回退通道；关则 Web 侧无此能力 |
| `llmops-redis` | 16 MB | **24 MB** | 114 MB | 保留 | 核心 |
| `llmops-browser-worker` | 6 MB | **17 MB** | 同上（共用同一镜像） | **保留** | 无桌面端用户的浏览器自动化回退通道 |
| `llmops-nginx` | 5 MB | **7 MB** | 62 MB | 保留 | 入口 |

**全部容器常驻合计（稳态，含 render 空闲）** ≈ **4.09 G**
（celery 1.54 + api 0.998 + neo4j 0.808 + kkfileview 0.583 + render 空闲 0.524 + db 0.099 + ui 0.066 + beat 0.063 + computer 0.028 + redis 0.024 + browser 0.017 + nginx 0.007 ≈ 4.09 G）

> ⚠️ 上表含 `render` 空闲 524 MB。**默认形态下 render worker 不启动**（`profiles: ["cloud-render"]`），
> 故实际常驻 ≈ **3.57 G**（见下）。接通云端渲染后才会回到 4.09 G。

**其中不含 render 的基础服务** ≈ **3.57 G**。

> 默认形态（云端 render worker 不启动）下，服务器只承担这 3.57 G；渲染走用户本机。
> 下面关于「渲染峰值叠加」的紧张测算，适用于**接通云端渲染**后的场景。

> ⚠️ 渲染还没开始，**3.57 G 就已逼近 4G 上限**。渲染 peak 0.9–1.4 G 一旦叠加，
> 总量直奔 4.5–5.0 G。因此 4C4G 单机**必须同时做两件事**：
> 1. `llmops-celery` 由默认 `-c 4` 降到 `-c 2`（省 ~0.6 G）；
> 2. 渲染严格串行（闸门已保证并发=1）且不与大文件上传/L2 解析同时发生。
>
> 即便两件都做，余量也仅 ~1 G；**§7.1 的「拆机」是更稳的选择**（但不强制——见 §0）。

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

### 渲染执行位置（本机优先，云端保留）

渲染默认在**用户本机**执行（桌面端 render worker，默认端口 8768，经本机 bridge 的 `/render` 出片、
`/artifact` 取回产物）；云端 `llmops-render-worker` **默认不启动**（compose 中已加
`profiles: ["cloud-render"]`），以节省服务器算力——渲染吃的是**用户自己的 CPU**，平台服务器只处理轻量内容。

| 场景 | 执行位置 | 说明 |
| --- | --- | --- |
| 已装桌面端 | 用户本机 | 首选；吃用户 CPU，不占服务器内存 |
| 未装桌面端 / 本机通道不可用 | 云端 `render` 队列 | 需接通云端 worker 且 `RENDER_CLOUD_FALLBACK_ENABLED=true`（默认 true） |

服务端渲染工具为**三级路由**：本机 bridge 优先 → 云端 Celery `render` 队列回退 → 明确报错。
判定差异：只有「通道不可用」（无注册设备 / 连不上 bridge / bridge 返回 401、502、503、504）
才回退云端；「通道可用但渲染失败」（缺二进制、脚本非法等）属业务失败，**不回退**，直接报错。

**云端渲染未删除**，服务定义与全部限流参数完整保留，可随时接通：

```bash
docker compose --profile cloud-render up -d llmops-render-worker
```

> 两个执行开关（`api/config/config.py`）：`RENDER_LOCAL_ENABLED`（默认 true，关掉则跳过本机通道）
> 与 `RENDER_CLOUD_FALLBACK_ENABLED`（默认 true，关掉则本机不可用时直接报错而非回退云端）。
>
> **以下 §3.1～§3.4 全部是对「云端 render worker 启用时」的资源配置实测与推导**——默认关闭状态下
> 这些内存/并发开销不落在服务器上；若接通云端渲染，再按本节配额与闸门约束执行。

### 3.1 内存模型：叠加，不是共享（cgroup 实测）

30s / 900 帧纯文字 composition（1920×1080 / 30fps），**关闭 low-memory、单容器内 N 个渲染同时跑**：

| 并发 | 墙钟 | 单实例均摊 | **cgroup 峰值** | RSS 口径（虚高） |
| --- | --- | --- | --- | --- |
| 1 | 36.8s | 36.8s | **1261 MB** | 1885 MB |
| 2 | 51.7s | 25.8s | **1989 MB** | 3764 MB |
| 3 | 82.4s | 27.5s | **2471 MB** | 5648 MB |

**关键结论**：
- **内存随并发增长，不是恒定的**：1261 → 1989 → 2471 MB，边际增量 **+728 / +482 MB**。
  这直接回答「一个用户跑 1G，两个三个用户是不是也 1G」——**不是**。每个渲染是独立
  Node + Chromium 进程，**互不共享**。
- 但**增长不是干净的 ×N**（3 并发 2471MB 明显低于 3×1261MB）。原因是每实例的
  Node/Chromium 运行时并非完全互斥：一部分常驻页在 cgroup 口径下只计一次。
  工程上**按「单实例 + ≥0.5 G/并发」保守预留**即可。
- **并发几乎不提升吞吐**：单实例 36.8s；2 并发总 51.7s（均摊 25.8s）；3 并发总 82.4s
  （均摊 27.5s，比 2 并发还差）。4 核下开到 3 已无收益，纯粹拿内存换不来速度。
- **「排队」不费内存**（队列里是几 KB 消息）；**「并发」才费内存**。

> ⚠️ **口径陷阱（务必用 cgroup，不要用 `ps`/RSS）**：上表 RSS 列比 cgroup 高 50%–130%，
> 因为 RSS 会把 Chromium 的**共享文件页按进程重复计数**，而 cgroup 由内核只记一次。
> 用 RSS 估算容量会严重高估。容器内取真实值的正确方式：
> `cat /sys/fs/cgroup/memory.current`（V2）或 `.../memory.usage_in_bytes`（V1）。
> **`docker stats` 显示的即 cgroup 口径，可直接采信。**

#### 3.1.1 多用户同时渲染会怎样？——**排队，不叠加**（已实测确认）

生产链路上 render worker 由 `CELERY_WORKER_AMOUNT: '1'` 固定为**单进程串行消费**
（`api/docker/entrypoint.sh` 的 `celery ... -c 1 -Q render`）。因此：

- **N 个用户同时点渲染 → 任务进 `render` 队列排队，同一时刻只有 1 个在执行**；
- 容器内存峰值恒为**单实例水平（~1.3 G）**，不随用户数增长；
- 代价是**等待时间线性增加**（第 3 个用户要等前 2 个跑完）。

所以上表的「2/3 并发」**不会在生产中出现**——它只用于证明「内存随并发增长」这个物理事实，
用来解释**为什么必须守住并发=1**：一旦把 `CELERY_WORKER_AMOUNT` 调到 2，内存立刻又多一份
（+0.5～0.7 G），2800M 限额的余量被吃掉大半。

> **结论**：你担心的「内存变 2G、3G」在**当前配置下不会发生**（靠串行化规避）。
> 但它是**配置依赖**，不是架构保证——**渲染并发必须始终锁死 1**。

#### 3.1.2 能不能改阈值、在低配机器上开快速渲染？——**可以，但方向要搞对**（实测）

**先纠正一个误区**：`LOW_MEMORY_TOTAL_MB_THRESHOLD` 是 **CLI 包内常量**，不是本项目配置项，
**改不了**（除非重建镜像）。但**不需要改它**——用 `PRODUCER_LOW_MEMORY_MODE=false` 直接
覆盖判定结果即可（§1.2），一行 compose 环境变量。

**再纠正我自己此前的错误结论**：本文曾写「2C2G 上渲染必然 OOM、渲染机至少 4C8G」。
真机实测**证伪**：把容器限额压到 **2048 MiB**，跑 60s/1800 帧重负载，两种模式**都成功出片**：

| 2 GB 限额下（60s / 1800 帧） | 耗时 | cgroup 峰值 | 输出 |
| --- | --- | --- | --- |
| low-memory（默认） | 93.97s | 1075 MB | 238231 B |
| **关闭 low-memory** | **64.9s（快 31%）** | **903 MB（省 172 MB）** | 238231 B（**完全相同**） |

**为什么「关掉省内存模式」反而更省内存**（**实测现象；机理为推断，未逐行验证**）：
low-memory 强制逐帧 `screenshot` 捕获，每帧位图需完整驻留并编码；
`beginframe` 走 CDP 增量帧协议，峰值反而更低。即 low-memory 是为**更极端**的内存环境
（如几百 MB）设计的保守兜底，在 2G 上反而**帮倒忙**。此项以实测数据为准，机理留待后续验证。

**速度提升的真实来源**（另一个反直觉点）：实测 `--workers 1` + 关 low-memory = 49.3s，
与 low-memory 的 48.5s 持平；而**自动（2 workers）** = 34.9s。
所以**加速来自并行的 2 个 capture worker，不是 beginframe 本身**。

**推荐配置（4C4G 单机、渲染与业务同机）**：

```yaml
PRODUCER_LOW_MEMORY_MODE: 'false'   # 关掉过度保守的降级，走 beginframe
# 保持 CELERY_WORKER_AMOUNT: '1'（任务级串行）；CLI 内部 2 workers 是进程内并行，
# 二者不冲突：串行保证同时只有 1 个渲染任务，进程内 2 workers 只在该任务内提速。
```

**但有一个前提要先验证**：2 workers 会触发 V8 堆告警（§1.3，堆 2240MB 时 `heapBasedWorkers=1`）。
本机重负载实测**未真正 OOM**（告警属余量提示），但若要彻底消除风险，
把 `NODE_OPTIONS` 提到 `--max-old-space-size=3072`（`heapBasedWorkers=3`）即可。

> **结论**：低配开快速渲染**可行且划算**——实测在 2G 限额下既快 31% 又省 172MB，
> 且产物字节完全一致。落地只需两行环境变量，无需改代码、无需改镜像。
> **代价**：进程内 fan-out 到 2 个 Chromium，CPU 占用翻倍——**必须配合任务级串行（并发=1）**，
> 否则多任务叠加会打爆内存。

### 3.2 建议配额

```yaml
llmops-render-worker:
  environment:
    CELERY_QUEUES: render              # 独占 render 队列
    CELERY_WORKER_AMOUNT: '1'          # 并发=1（核心护城河）
    NODE_OPTIONS: --max-old-space-size=2048   # 把 V8 堆由默认 1592 抬到 2240，稳定支撑 1 worker（见 §1.3）
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

**为什么 `memory: 2800M`**：实测容器 cgroup `memory.max = 2936012800`（恰好 2800 MiB）。
注意这个限额**也是 CLI 判定 low-memory 的输入**（`getSystemTotalMb` 读 cgroup），
2800 < 8192 → 必然走 low-memory 慢路径（§1.2）。这是刻意的取舍：限太高会挤垮同机其他服务。

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

**已验证的能力边界**：分片上传（>5MB 大文件，含全部视频素材）**已支持落盘到激活后端**（KB-P2B-2）。修复前该链路写死 `local`，会导致切到 COS 后大视频仍留在本地盘、下载继续占满 3M——这是 3M 环境下的致命瓶颈，现已解除。

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

> ⚠️ **4C4G 单机偏紧**（见 §0/§7.1）。推荐形态：**首台 4C4G（不含 render）+ 渲染机 2C2G/4C4G**。
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
# ===== 第二台（渲染机，2C2G 起；见 §7.1 跨机接线）=====
# 可选：仅当你需要「云端渲染回退」时才在独立机器上跑。默认渲染走用户本机，
# 无需为此单独准备机器。
# 3) 渲染镜像（3.47 GB，最慢的一步）
docker compose --profile cloud-render pull llmops-render-worker
docker compose --profile cloud-render up -d llmops-render-worker

# 4) 验证渲染链路（真出片）
docker compose exec llmops-render-worker \
  /opt/hyperframes/node_modules/.bin/hyperframes --version
docker compose exec llmops-render-worker ffmpeg -version | head -1
```

> ⚠️ **默认清单不含 `llmops-render-worker`**：渲染已下放到用户本机（桌面端 render worker），
> 云端该服务加 `profiles: ["cloud-render"]` **默认不启动**。需要云端回退时，用
> `docker compose --profile cloud-render up -d llmops-render-worker` 显式启用。

**首台默认启动清单**：`llmops-api`、`llmops-celery`、`llmops-celery-beat`、`llmops-ui`、`llmops-nginx`、`llmops-db`、`llmops-redis`、`llmops-neo4j`、`llmops-kkfileview`、`llmops-browser-worker`、`llmops-computer-worker`（**全部默认启动**，compose 中已无 `profiles` 裁减项）。`llmops-render-worker` 带 `cloud-render` profile，**默认不启动**，仅在需要云端渲染回退时于首台或第二台显式启用。

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
| 11 | 关闭 low-memory 降级 / 抬高 V8 堆 | 配置 | ⏳ **待定**（实测可快 31%、更省内存，见 §3.1.2；需先定 2-workers 策略） |
| 12 | 云端 render worker 默认不启动（`profiles: ["cloud-render"]`），渲染下放到用户本机 | compose+代码 | ✅ 已落地（三级路由：本机优先 → 云端回退 → 报错；开关 `RENDER_LOCAL_ENABLED` / `RENDER_CLOUD_FALLBACK_ENABLED` 默认均 true） |

**闸门实现载体**：`api/internal/service/render_guard_service.py`（`RenderGuardService`）。
准入在派发端（`render_video._dispatch_render`），归还在任务开始/结束端（`render_tasks`），
两端用同源脚本指纹（sha256 前 32 位）保证防重锁能正确释放。

> 关于第 9 项：设计原写「复用 `agent_notification`」，但实测该通道是 app 构建专用
> （`create_agent_notification` 需 `app_id`）。而成品本质是「一篇入库文档」，故改走
> **`document_index_notification`** 通道——前端（`App.vue`）已全局订阅、后端已有订阅
> 处理器与 `room = account_id` 约定，此前只缺生产者。复用后前端**零改动**。

---

## 7. 风险与验证记录

### 7.1 拆机方案（仅接通云端渲染时需要；4C4G 单机的稳妥解）

> ⚠️ **前提已变**：渲染默认在用户本机执行、云端 render worker 默认不启动（§3「渲染执行位置」），
> 因此**默认形态下无需拆机**——首台本来就不含 render 那 524 MB 与 0.9–1.4 G 峰值。
> 本节的「拆」只在**你决定接通云端渲染回退**（`profiles: ["cloud-render"]`）时才有意义：那时它
> 仍然是最稳妥的做法（把 render 放到独立机器，而非与首台共享算力）。

**为什么要拆**：稳态实测**不含渲染已 ~3.57 G**（§2），已逼近 4G 上限；渲染 peak 0.9–1.4 G。
单机只能靠 `celery -c 2` + 严格错峰硬扛，余量约 1 G、没有缓冲。

**拆什么**：只拆 `llmops-render-worker`（`render` 队列独占），首台立刻回收
**524 MB 空闲内存 + 0.9–1.4 G 渲染峰值 + 3.47 GB 镜像体积**。

**⚠️ 不要拆 browser/computer worker**：二者合计仅 **45 MB**（17 + 28），拆走省不到 50 MB，
却要新开跨机链路。**它们是镜像大（1.8 GB）不是内存大**——按内存算，拆它们性价比为零。

**⚠️ 关于渲染机规格（实测修正，推翻此前的 4C8G 结论）**：

此前本文断言「2C2G 装不下渲染、渲染机至少 4C8G」。**真机实测证伪**：
把容器限额压到 **2048 MiB**、跑 60s/1800 帧重负载，**成功出片**（cgroup 峰值仅 903～1075 MB，
见 §3.1.2）。原因是 CLI 的 `memoryBasedWorkers` 会自动收缩到 1，内存实际需求远低于早期估算。

修正后的建议：

| 规格 | 结论 |
| --- | --- |
| **2C2G** | ✅ **实测可跑**（2GB 限额下 60s/1800帧成功出片，峰值 ~1 G）。适合只服务少量用户、能接受排队 |
| **2C4G** | ✅ 稳妥起点；`memoryBasedWorkers = ⌊4096×0.5/1536⌋ = 1`，够用且有余量 |
| **4C4G+** | 若要 CLI 进程内并行 2 workers 提速（§3.1.2），需 ≥4 核 + 堆提到 3072 才无告警 |

> 判定 `totalMb <= 8192` 即降级仍然成立（§1.2），但**降级不再等于「不可用」**——
> 它只是走保守路径。用 `PRODUCER_LOW_MEMORY_MODE=false` 可主动关闭（实测更快更省）。
> **CPU 才是低配渲染的真瓶颈**：`cpuCount-2` 在 2 核上为 0（兜底 1），单 worker 下 900 帧约 50–90s。

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
不含 render：4.09 G - 0.524 G ≈ 3.57 G      （4G 上限下偏紧，但不再有渲染峰值风险）
再把 celery 降到 -c 2：3.57 - 0.6 ≈ 2.97 G  （留 ~1 G 给上传/L2 峰值，可接受）
```

**结论**：拆掉渲染 + `celery -c 2` 后，首台从「渲染叠上来必超 4G」变为「稳态 ~3 G、余量 ~1 G」。
这是 4C4G 上最稳妥的组合（不拆也能勉强跑，但缓冲更薄——见 §0）。

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
| low-memory 阈值 | `LOW_MEMORY_TOTAL_MB_THRESHOLD = 8192`（渲染镜像内 CLI 包常量，见 §1.2） |
| V8 默认堆 | 2240 MB（支持 ~1 worker） |
