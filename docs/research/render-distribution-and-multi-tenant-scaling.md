# 渲染架构与多租户扩容方案评估

> 更新日期：2026-09-18
> 定位：**调研与方案设计（设计稿，未实现）**。本文只做可行性评估与方案对比，不含代码改动。
> 非权威区：本文结论代表当前调研判断，**不代表已实现**；实现状态以 `docs/prd/modules/02-knowledge-base.md`
> §11.14 与 [deployment-single-node.md](../deployment-single-node.md) §3 为准。
> 触发背景：现架构把渲染放在平台云服务器，多租户下的算力扩容成本不可控。

---

## 0. 结论速览

1. **【纠错】「1000 用户同时渲染 → 内存天量」不成立**。生产上渲染由
   `CELERY_WORKER_AMOUNT: '1'` 固定为**单进程串行消费**，N 个用户只会**排队**，
   容器内存峰值恒为**单实例水平（~1.3 G）**，不随用户数增长。
2. **真正的瓶颈是 CPU 吞吐（等待时间），不是内存**。单槽位吞吐 ≈ 103 片/小时；
   要让 1000 个渲染在 1 小时内完成需 ~10 个并行槽位（≈20 核 + 13 G），
   10 分钟内完成需 ~58 个槽位（≈116 核 + 75 G）——**这才是「没法计算的扩容成本」的准确形式**。
3. **HyperFrames 官方本就为规模化提供了分布式渲染方案**（`planV2` / `renderChunkV2` / `assembleV2`
   + Lambda/Step Functions、Vercel Sandbox、Temporal、Cloud Run、K8s 适配器），
   许可为 Apache-2.0 **允许商用多租户 SaaS**。本项目**完全未使用这套能力**。
4. **「渲染下放到桌面客户端」方向成立**，且本仓库**已有现成的同类范式可复用**
   （桌面端自带 worker + bridge 回传 + 服务端容器作回退，browser/computer worker 就是这么做的）。
5. **但不能二选一**：纯 Web 用户没有本机 worker，服务端容器必须保留为回退通道。
   推荐**三档混合**：桌面端本机渲染（省平台成本）→ 服务端串行渲染（保底）→ 官方分布式（应对突发/大客户）。
6. **桌面端方案有三个硬约束**（见 §5）：客户端需带 ~500 MB 渲染运行时、渲染后半段强依赖服务端
   （无法完全离线）、Web 用户覆盖不到。

---

## 1. 背景：现架构与定位

### 1.1 现状（已落地，有代码与实测）

视频渲染（P3.7）当前是**纯平台云端能力**：

| 环节 | 载体 | 位置 |
| --- | --- | --- |
| 触发 | builtin 工具 `render_video` | `api/internal/core/tools/builtin_tools/providers/video_render_tools/render_video.py` |
| 准入 | `RenderGuardService`（每账号并发=1、防重锁、积压阈值） | `api/internal/service/render_guard_service.py` |
| 派发 | Celery `render` 队列 | `render_video._dispatch_render` → `render_composition_task.delay` |
| 渲染 | 专用容器 `llmops-render-worker`，独占 `render` 队列、`-c 1` | `docker/docker-compose.yaml` |
| 出片 | `npx hyperframes render`（Node ≥22 + Chromium + ffmpeg/ffprobe） | `api/internal/core/video/hyperframes_renderer.py` |
| 入库 | MP4 落 COS → 成品库建档 → 触发索引 | `KnowledgeBaseService.store_render_output` |

**关键配置**：`CELERY_WORKER_AMOUNT: '1'`（单进程串行）+ `deploy.resources.limits`（cpus 2 / mem 2800M）。

### 1.2 文档层面的缺口

全仓**没有「多租户渲染」这一议题的设计**。「多租户」一词只出现在
[Hypit 许可调研](./hypit-and-hyperframes-evaluation.md)中，且是**合规语境**（Hypit 禁止多租户 SaaS → 弃用；
HyperFrames 为 Apache-2.0 → **多租户无限制**），**不是架构维度**。

与租户相关的实际机制只有两处，均为**准入控制**而非资源隔离：
- 每账号并发 = 1（`RenderGuardService.MAX_CONCURRENT_RENDERS_PER_ACCOUNT`）
- 成品库每账号至多一个（部分唯一索引 `knowledge_base_render_output_uniq`）

**渲染算力如何计费至今未定稿**：属
[knowledge-base-product-form-design.md §11](../prd/knowledge-base-product-form-design.md) 的待确认事项
（「视频编辑的 CPU 转码是否单独计费」）。

---

## 2. 成本模型的准确形式（实测数据）

### 2.1 内存不随并发用户数增长

实测（cgroup 口径，容器内 `/sys/fs/cgroup/memory.current`）：

| 并发渲染数 | 墙钟 | cgroup 峰值 |
| --- | --- | --- |
| 1 | 36.8s | 1261 MB |
| 2 | 51.7s | 1989 MB |
| 3 | 82.4s | 2471 MB |

但**生产不会出现多并发**——`-c 1` 串行消费使 N 个用户的任务在队列中排队：

```
1000 用户同时点渲染 → 999 个在 render 队列排队，同一时刻仅 1 个执行
→ 内存峰值恒为 ~1.3 G，不随用户数增长
```

> 内存随**并发槽位数**增长（且近似线性），**不随用户数增长**。二者不可混淆。

### 2.2 真实瓶颈：CPU 吞吐 / 等待时间

单槽位渲染耗时（30s/900 帧，实测）：**35s（关 low-memory）/ 50s（默认低内存模式）**。
取 35s 保守估算：

| 目标 SLA | 所需并行槽位 | 约合 CPU | 约合内存 |
| --- | --- | --- | --- |
| 1000 片 / 1 小时 | ~10 | 20 核 | ~13 G |
| 1000 片 / 10 分钟 | ~58 | 116 核 | ~75 G |
| 1000 片 / 1 分钟 | ~583 | 1166 核 | ~750 G |

**公式**：`槽位数 = N × T_单片 / T_目标`（N=渲染数，T_单片≈35s）

这是成本失控的**准确形式**：不是内存，而是**要买到足够 CPU 才能压低等待时间**。
若要避免买常驻机器，就需要**弹性/分布式**方案（§4）或**把算力外部化**（§5）。

### 2.3 低配机器其实跑得动（为桌面端方案提供了实测依据）

实测把容器限额压到 **2048 MiB**，跑 60s/1800 帧重负载，**两种模式都成功出片**：

| 2 GB 限额下（60s/1800 帧） | 耗时 | cgroup 峰值 |
| --- | --- | --- |
| 默认（low-memory） | 93.97s | 1075 MB |
| 关闭 low-memory | **64.9s** | **903 MB** |

**推论**：渲染对内存的要求远低于早期估算，**2 GB 级别的机器即可承担**。
这直接支持「让用户自己的电脑来干这活」——普通笔记本的内存与 CPU 都远超此门槛。

---

## 3. 官方对规模化的处理方式（已核对官方文档）

### 3.1 官方明确的定位：作者在云、渲染可在本地

HyperFrames 官方指南原文：

> You author the HTML — **the user renders locally**.

即官方把「渲染在哪执行」视为**调用方的部署选择**，框架本身不限定。

官方对其确定性设计的说明也印证这一点（确定性是并行切帧的前提）：

> determinism is what allows frames to be split across parallel workers, which is how the
> same project **renders locally or on AWS Lambda without changing**.

**含义**：官方设计意图就是「同一份 composition，可在本机渲染，也可在云端分布式渲染」。
这同时支持本方案的两个方向（§4 云侧分布式、§5 本机渲染）——二者都是官方认可的用法。

### 3.2 官方提供的分布式渲染原语（`@hyperframes/producer`）

官方为「单机跑不动」的场景提供了公开的分布式渲染原语：

```javascript
import { planV2, renderChunkV2, assembleV2 } from "@hyperframes/producer/distributed";

// 控制器侧：产出不可变 manifest + 内容寻址产物
const planResult = await planV2(projectDir, { fps: 30, width: 1920, height: 1080, format: "mp4" }, "/tmp/plan-v2");
// 每台 worker 渲染一个 chunk
const chunk = await renderChunkV2("/tmp/plan-v2", 0, "/tmp/chunks/0.mp4");
// 控制器侧：拼装成最终产物
await assembleV2("/tmp/plan-v2", ["/tmp/chunks/0.mp4", "/tmp/chunks/1.mp4"], "/tmp/output.mp4");
```

官方说明这些是「**纯函数，作用于本地路径**」——网络与编排交给适配器包：

| 适配器 | 形态 |
| --- | --- |
| AWS Lambda + Step Functions | `Map(N) RenderChunk` 并行 |
| **Vercel Sandbox** | Firecracker microVM，4 vCPU 下自动 3 并行 worker，**渲染时间砍半** |
| Temporal / Cloud Run Jobs / K8s Jobs | 通用编排 |

**分布式模式的能力边界**（官方明示）：支持 `mp4` SDR、`mov` ProRes 4444、`png-sequence`；
**`webm` 与 HDR mp4 会抛 `FormatNotSupportedInDistributedError`**——本项目当前只用 mp4，不受限。

### 3.3 官方还有个 HTTP 渲染服务模式

`@hyperframes/producer` 提供 `startServer({ port })`，可直接作为 **HTTP 渲染服务**运行
（`POST /render` 接 RenderConfig）——即官方也支持「渲染服务独立部署、按请求调用」的形态。

### 3.4 本仓库内已验证的官方能力存在性

在当前渲染镜像内实测确认（`/opt/hyperframes/node_modules/hyperframes/dist/cli.js`）：

- ✅ 分布式原语已被打进 CLI 包：`planV2WithPublisher`、`FormatNotSupportedInDistributedError`、
  `planV2Errors` 等符号均存在（32 处 `renderChunk` 相关引用）
- ✅ HTTP 服务入口存在：`startServer` 函数已打包
- ❌ **但未作为公开 API 暴露**：包内**无 `public-server.js` 入口文件**，也无独立
  `@hyperframes/producer` 包目录——`startServer` 仅在入口脚本名匹配特定路径时才激活
- ❌ 当前 CLI 的 `render` 命令**仅支持本机渲染**，无「分布式渲染」子命令

**含义**：要用官方分布式能力，需**额外引入 `@hyperframes/producer` 独立包**，
不能只靠现有 CLI。这是方案的**新增依赖成本**。

### 3.5 许可与多租户（本项目已调研确认）

[hypit-and-hyperframes-evaluation.md](./hypit-and-hyperframes-evaluation.md) 已确认：

- HyperFrames 为 **Apache-2.0**，「多租户 SaaS ✅ 无限制」「可安全用于多租户商业化产品」
- 对比：Hypit 许可**明确禁止**未经授权运营多租户环境 / 托管 SaaS，故弃用

**结论**：现架构（服务端渲染）**无许可问题**；但**也不是官方推荐的规模化形态**。

---

## 4. 方案 A：接入官方分布式渲染

### 4.1 思路

把单机串行渲染改为**控制器 + 多 chunk worker**：

```
render_video → 控制器（planV2）→ 生成 manifest
                    ↓ 派发 N 个 chunk
              chunk worker × N（并行，可弹性）→ 各出一段 mp4
                    ↓
              控制器（assembleV2）→ 拼装最终 mp4 → 入库
```

### 4.2 两个层次的能力（勿混淆）

| 层次 | 机制 | 扩的是什么 | 上限 |
| --- | --- | --- | --- |
| **进程内并行** | CLI `--workers N`（实测 2 workers 即快 31%） | 单个渲染任务内部的 capture 并行度 | **单机 CPU**；内存按 worker 数叠加（实测 ~1.26 G/槽位） |
| **跨机分布式** | `planV2` / `renderChunkV2` / `assembleV2` | 把一次渲染**切成多个 chunk 分发到多台机器** | 理论上无上限（加机器即可） |

> 本项目当前**只用了串行单 worker**，上述两层能力**都没启用**。
> `--workers` 连 CLI 参数都未透传（`hyperframes_renderer.build_render_command` 仅传
> `--quality/--fps/--output`）。

### 4.3 可达载体的接入成本排序

| 载体 | 属于 | 优点 | 代价 |
| --- | --- | --- | --- |
| **原地 `--workers 2`** | 进程内 | 零新增依赖，只需透传参数 + 抬 V8 堆 | 单机 CPU 上限；内存叠加；仅 ~2× 提速 |
| **多台渲染机 + 共享队列** | 进程间（非官方分布式） | 复用现有 Celery 拓扑，加机器即扩容 | 需共享存储（或切 COS）；运维多机 |
| **K8s Jobs** | 官方分布式 | 弹性最好、可自建 | 引入 K8s（当前是单机 compose） |
| **Vercel Sandbox** | 官方分布式 | 按量付费、无常驻成本；官方模板实测 4 vCPU 自动 3 worker 提速 ~2× | 需引入 `@hyperframes/producer`；新云厂商依赖 |
| **AWS Lambda + Step Functions** | 官方分布式 | 弹性最好、有官方 CDK 构造 | 引入 `@hyperframes/producer` + AWS 生态 |

### 4.4 评价

- **优势**：真正解决「1000 并发」的吞吐问题；官方原生支持，不是自造轮子。
- **劣势**：引入新依赖与（多数选项下）新基础设施；本项目当前是**单机 compose + 3 Mbps 带宽**，
  上一整套分布式编排的运维成本可能超过渲染本身。
- **适用**：**纯 Web 用户 + 突发流量 + 平台自营的大批量渲染**。

---

## 5. 方案 B：渲染下放到桌面客户端（用户提议）

### 5.1 核心思路

装了桌面端的用户，渲染在**用户本机**执行，吃用户自己的 CPU/内存；
服务端只负责「派发任务 + 收回成品 + 入库」。

### 5.2 本仓库已有可复用的完整范式

**这是本方案最大的可行性依据**——同一模式已对 browser/computer worker 落地：

| 环节 | 现成实现 | 渲染需复用的部分 |
| --- | --- | --- |
| 客户端托管 worker | `desktop/main.js` 的 `startWorker`（随机 token、端口顺延、宿主看门狗） | 直接复用 |
| worker 统一入口 | `api/scripts/worker_super.py`（子命令白名单 `os\|browser\|computer\|wake`） | 增 `render` 子命令 |
| 本地能力桥 | `desktop/bridge.js`（路由表 + token 二次转发） | 增 `/render` 路由 |
| 设备注册 | `desktop_device` 表 + `resolve_desktop_bridge(account_id)` | **直接复用，无需改动** |
| 服务端调用 | 工具层调 `resolve_desktop_bridge` → 打桌面 bridge | 新增渲染工具或改造 `render_video` |

> ⚠️ **反面范例**：`browser_action` 的 `_call_worker` **未调用 `resolve_desktop_bridge`**，
> 只读静态 env——导致「桌面端纯动态注册」场景下打不到用户设备。渲染通道**不要重蹈此路**。

### 5.3 三个硬约束（必须先解决）

**约束 1：运行时体积 ~500 MB**

实测各组件体积：

| 组件 | 体积 | 备注 |
| --- | --- | --- |
| Chromium（`chrome-headless-shell`） | **338 M** | 必须是能响应 `--version` 的构建；**完整版 Chrome / Electron 自带 chrome.exe 不可替代**（本项目已实测：受限环境下完整版 `--version` 会挂死，CLI 判定 "Chrome cannot start"） |
| Node | **121 M** | 需 ≥ 22 |
| hyperframes CLI | 37 M | 钉死 0.8.42；**必须本地安装**（`-g` 全局装会报 `Missing RuntimeLoader manifest`） |
| ffmpeg + ffprobe | 468 K | **ffprobe 必须是真 ffprobe**（ffmpeg 冒充会因 `-print_format` 不支持而失败） |

分发方式待定（见 §7 开放问题）：随包携带 / 首用按需下载 / 探测系统已有（仿 `cua-driver-host.js`
的四级探测：显式 env → 安装包 → 用户目录 → PATH）。

**约束 2：渲染后半段强依赖服务端，无法完全离线**

核对完整链路后，**纯本地的只有 5 步**，分界点在
`api/internal/service/render_service.py` 的 `store_render_output` 调用：

```
L117-123  纯本地：建临时目录 → 编译 HTML → Node/Chromium/ffmpeg 出 MP4
L124      ←────────── 分界线 ──────────→
L124+     必须服务端：账号解析(DB) → 落对象存储 → 建成品库(DB) → 触发索引(ASR/视觉向量)
```

且链路里还有两个**隐性反向依赖**：
- `composition_builder` 生成的 HTML 引用 `cdn.jsdelivr.net` 的 GSAP，CLI 还会取 Google Fonts
  → **本机渲染同样需要外网**，或改为自托管/内联
- `media_src` 未做本地化下载，若指向对象存储 URL，渲染阶段即依赖服务端可达

**这意味着**：桌面端只能承担「出 MP4」，产物仍需回传服务端入库。
**但这也正好**——回传链路可复用现有 bridge + `store_render_output`，不必新造管道。

**约束 3：纯 Web 用户覆盖不到**

未安装桌面端的用户（浏览器直接访问）本机无 worker。
因此**服务端渲染容器不能删除，只能降级为回退通道**。

### 5.4 评价

- **优势**：把最贵的 CPU 成本转移给用户；本仓库范式成熟、改动面收敛；
  与官方定位（"user renders locally"）一致。
- **劣势**：客户端体积膨胀；本机渲染不可控（用户机器性能差异大、可能中途休眠）；
  只覆盖装了客户端的用户。
- **适用**：**已装桌面端的用户 + 平台想控制算力成本**。

---

## 6. 推荐：三档混合，而非二选一

| 场景 | 渲染执行位置 | 成本归属 | 现状 |
| --- | --- | --- | --- |
| **已装桌面端** | 用户本机（经 bridge 回传入库） | 用户 | ❌ 待做 |
| **纯 Web 用户** | 服务端 `llmops-render-worker`（串行） | 平台 | ✅ 已有 |
| **突发流量 / 大客户** | 官方分布式（弹性按量） | 平台（弹性） | ❌ 待做 |

**优先级建议**：
1. **桌面端本机渲染**——性价比最高（算力外部化），且有现成范式；
2. **保留服务端串行渲染**——保底通道，覆盖 Web 用户；
3. **官方分布式**——留待确有并发压力时再上，避免过早引入基础设施。

**同时建议补上「渲染算力计费」**：既然算力是真实成本，应向用户计价或设租户级配额。
当前该项在 [knowledge-base-product-form-design.md §11](../prd/knowledge-base-product-form-design.md) 仍是待确认事项。

---

## 7. 开放问题（待决策）

1. **客户端运行时如何分发**（~500 MB）：随包携带 vs 首用下载 vs 探测系统已有？
2. **是否引入 `@hyperframes/producer`**：分布式能力需追加依赖，是否接受？
3. **渲染算力计费模型**：CPU 转码是否单独计费？还是计入现有算力配额？
4. **本机渲染的可靠性与公平性**：用户机器性能差异、休眠中断、如何避免「靠低配机器刷免费算力」？
5. **共享存储前提**：若保留多台服务端渲染机，是否统一切 COS（当前默认 `local`，
   跨机时渲染机写的本地盘首台 API 看不见）？
6. **GSAP CDN / Google Fonts 外网依赖**：本机渲染与 3 Mbps 环境都受影响，是否自托管？

---

## 8. 相关文档

- 渲染现状与实测：[deployment-single-node.md](../deployment-single-node.md) §3（内存模型、low-memory、拆机方案）
- 渲染在产品中的定位：[02-knowledge-base.md](../prd/modules/02-knowledge-base.md) §11.14
- 桌面端架构：[09-desktop-client.md](../prd/modules/09-desktop-client.md)、[08-os-automation.md](../prd/modules/08-os-automation.md)
- 多通道路由既有方案：[desktop-sandbox-routing-plan.md](./desktop-sandbox-routing-plan.md)（真实桌面 / 云沙箱 / 云浏览器三通道）
- 引擎选型与许可：[hypit-and-hyperframes-evaluation.md](./hypit-and-hyperframes-evaluation.md)
- 渲染宿主实施记录：[2026-09-16-hyperframes-render-host.md](../archive/superpowers-plans/2026-09-16-hyperframes-render-host.md)（已归档）
