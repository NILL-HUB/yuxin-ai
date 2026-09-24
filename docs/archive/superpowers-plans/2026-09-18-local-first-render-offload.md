# 重负载任务本机化（渲染优先）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把视频渲染等重负载计算从平台云服务器迁到用户本机执行，云端渲染完整保留为"可随时接通的回退路径"（默认关闭），使平台服务器只处理轻量内容、成本可控。

**Architecture:** 复用本仓库已验证的「桌面端自带 worker + 本地能力桥 + 服务端按账号动态解析」范式（browser/computer worker 已落地同一模式）。新增 `render` 作为桌面 worker 子命令，服务端渲染工具改为**三级路由**：本机 bridge（首选）→ 服务端 Celery `render` 队列（回退，受开关控制）。云端代码**不删除**，仅用配置开关下线。

**Tech Stack:** Python 3.12 / LangChain BaseTool / http.server（worker）/ Node.js + Electron（桌面宿主）/ HyperFrames CLI 0.8.42 / pytest

---

## 0. 前置背景（执行者必读）

### 0.1 本方案要解决的问题

平台当前把视频渲染放在云服务器（`llmops-render-worker` 容器独占 `render` 队列）。多租户下算力成本与用户数挂钩：要让 1000 个渲染 1 小时内完成需约 20 核 + 13 G，10 分钟内完成需约 116 核 + 75 G。把算力外部化到用户本机，可让平台服务器只承担轻量内容。

### 0.2 关键设计决策（已与用户确认）

| 决策 | 内容 |
| --- | --- |
| **云端渲染处理** | **保留代码，默认关闭**。不删除、不重构。未来可一键接通。 |
| **本机渲染** | 新增，作为首选执行路径 |
| **降级顺序** | 本机 bridge → 云端 Celery → 明确报错 |
| **是否给渲染计费** | 不改（本机执行不消耗平台算力） |

### 0.3 现有可复用资产（勿重复造）

| 能力 | 现成实现 | 说明 |
| --- | --- | --- |
| 客户端托管 worker | `desktop/main.js` `startWorker()`（约 L124-155） | 随机 token、端口顺延、宿主看门狗，**直接复用** |
| worker 统一入口 | `api/scripts/worker_super.py` | 子命令白名单在**两处**：`parse_args` 的 `choices`（约 L148）与 `_module_and_entry`（约 L158-164），**必须同时改** |
| 本地能力桥 | `desktop/bridge.js` | 路由表 `targets`（约 L5-31）需加 `/render` |
| 设备注册表 | `desktop_device` 表 + `DesktopDeviceService.resolve_bridge` | **无需改动** |
| 按账号解析桥 | `internal/service/desktop_bridge_resolver.py` `resolve_desktop_bridge(account_id, purpose=)` | **无需改动** |
| 服务端调用范式 | `providers/host_os/os_file_task.py` `_call_worker`（L84-132） | **照抄此范式** |
| 渲染执行 | `internal/core/video/hyperframes_renderer.py` | 已可直接复用（纯 subprocess） |
| 成品入库 | `KnowledgeBaseService.store_render_output` | **无需改动** |

### 0.4 ⚠️ 必须避免的反面范例

`providers/browser_automation/browser_action.py` 的 `_call_worker` **没有调用 `resolve_desktop_bridge`**，只读静态 env——导致「桌面端纯动态注册」场景下打不到用户设备（已知断链）。**本方案的 render worker 调用必须走 `resolve_desktop_bridge`。**

### 0.5 已知技术约束（实测，勿踩）

1. **Chromium 必须是能响应 `--version` 的构建**：`chrome-headless-shell` 正常；完整版 Chrome 在受限环境 `--version` 会挂死，CLI 判定 `Chrome cannot start`。**Electron 自带的 `chrome.exe` 不可替代**。
2. **ffprobe 必须是真 ffprobe**：用 ffmpeg 冒充会因 `-print_format` 不支持而失败。
3. **HyperFrames 必须「本地安装」**（`npm install hyperframes@0.8.42`），全局 `-g` 会报 `[HyperframeRuntimeLoader] Missing manifest`。
4. **渲染后半段强依赖服务端**：本机只能产出 MP4，入库/索引必须回传服务端。分界点在 `render_service.py` 的 `store_render_output`。
5. **composition 引用外网 CDN**（`cdn.jsdelivr.net` 的 GSAP、Google Fonts），本机渲染同样需要外网可达。

### 0.5.1 Node 运行时：用户**无需**自装，用 Electron 内置的 Node（版本必须对齐 24）

**问题**：HyperFrames 需要 Node 才能跑。用户装了桌面端后，是否还得自己装 Node？

**答案：不需要，但前提是把 Electron 升级到 43.7.0+。**

**依据（已实测）**：

1. **HyperFrames 有硬性版本门禁**。入口 `bin/hyperframes.mjs` 主动校验：
   ```javascript
   import { runtimeVersionError } from "../dist/runtimeVersion.js";
   const error = runtimeVersionError(process.versions.node);
   if (error) { console.error(error); process.exitCode = 1; }
   ```
   而 `runtimeVersion.js` 中 `MINIMUM_NODE_MAJOR = 22`，低于即报
   `HyperFrames requires Node.js >= 22 (current: x.y.z)` 并退出。

2. **Electron 内置 Node**，可用 `ELECTRON_RUN_AS_NODE=1` 把 `electron.exe` 当 node 用
   （实测可执行脚本、可 `import` ESM）。因此**无需随包额外分发 Node**。

3. **但项目当前 Electron 33 内置的是 Node 20.18.3，会被门禁拒绝**。实测对照：

   | Electron | 内置 Node | 是否满足 |
   | --- | --- | --- |
   | 33.4.11（**当前**） | 20.18.3 | ❌ 低于 22 |
   | 34.5.8 | 20.19.1 | ❌ |
   | 35.7.5 | 22.16.0 | ⚠️ 可用但版本与容器不一致 |
   | **43.7.2** | **24.21.0** | ✅ **与容器完全一致** |
   | 44.4.2 | 24.21.0 | ✅ |

4. **版本对齐要求（用户明确指示）**：容器 `Dockerfile.render` 用
   `ARG NODE_IMAGE=node:24-bookworm-slim`，实测容器内 `node -v` = **v24.21.0**。
   为避免「本机 22 / 云端 24」双版本导致的难排查 BUG，**桌面端必须选内置 Node 24 的
   Electron**，即 **`electron@^43.7.0`**（内置 Node 24.21.0，与容器逐位一致）。

> **为什么必须对齐**：渲染产物由本机与云端两条路径产出（§三级路由），若两边 Node
> 大版本不同，同一 composition 可能出现「本机成功、云端失败」或输出像素不一致，
> 而报错信息往往不指向 Node 版本，排查成本极高。

**落地要点**：

- `desktop/package.json`：`electron` 由 `^33.0.0` 升到 **`^43.7.0`**，
  `electron-builder` 相应升到支持该 Electron 的版本。
- **如何把 Electron 的 Node 喂给渲染子进程**（机制已实测，见下）。
- **Chromium 与 ffmpeg/ffprobe 仍需另行提供**——Electron 自带的
  `chrome.exe` / `ffmpeg.dll` **不能**用于 HyperFrames（前者 `--version` 行为不符、
  后者是 DLL 不是 CLI 可执行文件）。这部分见 §0.5.2 的分发策略。

#### 把 Electron 内置 Node 接入渲染链路（本次已实测验证）

渲染子进程的调用形态是：`hyperframes_renderer.build_render_command()` 生成
`[*_resolve_hyperframes_cli(settings), "render", ...]`，其中
`_resolve_hyperframes_cli()` 在配置了 `HYPERFRAMES_CLI_BIN` 时**只返回单个可执行文件**
（`[explicit]`）。而 HyperFrames CLI 实际是个 **Node 脚本**，需要
`node <cli.js> render ...` 两个 token——**单个可执行文件路径不够用**。

**结论：必须用 shim 包装。** 实测验证如下：

| 验证项 | 结果 |
| --- | --- |
| `electron.exe` 设 `ELECTRON_RUN_AS_NODE=1` 能否当 node 用 | ✅ 可执行外部脚本，`process.versions.node` 正确输出（当前 33 为 20.18.3） |
| 能否正确透传 CLI 参数 | ✅ `argv=["render","--quality","standard"]` 完整保留 |
| `electron.exe` 拷贝成单独文件再运行 | ❌ **失败**（退出码 `0xC0000135` = DLL 缺失）——**必须原地使用 dist 目录内的可执行文件** |
| subprocess **不带 shell** 能否执行 `.cmd` shim 并透传参数 | ✅ `SHIM_FORWARDED=["render","--quality","standard","--fps","30"]` |

因此桌面端需生成一个 shim（Windows 为 `.cmd`，macOS/Linux 为 `#!/bin/sh` 脚本），
内容等价于：

```bat
@echo off
set ELECTRON_RUN_AS_NODE=1
"<安装目录>\electron.exe" "<安装目录>\resources\render-runtime\cli.js" %*
```

然后令 `HYPERFRAMES_CLI_BIN=<该 shim 路径>`。要点：

- shim 内**必须原地引用 electron.exe**（不可拷贝单文件），并**显式设 `ELECTRON_RUN_AS_NODE=1`**；
- `cli.js` 是 HyperFrames「本地安装」产物（`node_modules/hyperframes/dist/cli.js`），
  随包放在 `resources/render-runtime/`；
- shim 路径需登记进 `build.extraResources`，且生成逻辑要在「首次运行」时确保存在
  （安装目录只读，故实际应生成到 `userData/` 并指向安装目录的 electron.exe）。

### 0.5.2 渲染运行时随包内置（不含按需下载）

**决策（用户明确指示）**：渲染所需的全部组件**随安装包一起分发**，不做按需下载。
理由：彻底消除「首次渲染时下载失败 / 被墙 / 离线不可用」这类客服问题；
安装包体积增大的代价可接受（用户不会在意 100M 还是 500M）。

**实测体积账**（在 `llmops-render-worker` 容器内实测）：

| 组件 | 原始 | 说明 |
| --- | --- | --- |
| `hyperframes` 包本体 | 37 MB | `dist/cli.js` 11 MB（**非自包含**，会 import 兄弟包） |
| `node_modules`（全部依赖） | 700 MB | 其中 `onnxruntime-node` **独占 536 MB** |
| `node_modules`（**不含 onnxruntime**，对比基线） | 164 MB | 压缩后仅 38 MB（仅供参考） |
| Chromium（`/usr/lib/chromium`） | **338 MB** | 体积主体，必须随包 |
| ffmpeg + ffprobe（**容器内 Debian 构建**） | < 1 MB | 动态链接，依赖系统 `.so`；**Windows 侧不能用这种**，须换自包含构建（各约 98 MB，见下） |

**关键结论：CLI 不是自包含的**（实测 `dist/cli.js` 单独复制后运行报
`ERR_MODULE_NOT_FOUND: Cannot find package 'esbuild'`），**必须连 `node_modules` 一起带**。

#### `onnxruntime-node` 一并打包（裁剪到 Windows/x64）

**决策（用户明确指示）**：一并打包，供后续**图片处理**（抠像 / remove-background）使用。

**体积优化（实测）**：该包的 `bin/napi-v3/` 下同时携带 **6 个平台**目录，共 536 MB，
但 `dist/binding.js` 是**按运行时平台动态选择**的：

```javascript
exports.binding = require(`../bin/napi-v3/${process.platform}/${process.arch}/onnxruntime_binding.node`);
```

因此 Windows x64 安装包**只需 `win32/x64` 一个目录**，其余可删：

| 目录 | 体积 | Windows 安装包是否需要 |
| --- | --- | --- |
| `linux/x64` | **370 MB** | ❌ 删（这是容器用的，占了大头） |
| `linux/arm64` | 34 MB | ❌ 删 |
| `darwin/x64` | 35 MB | ❌ 删 |
| `darwin/arm64` | 31 MB | ❌ 删 |
| `win32/x64` | **34 MB** | ✅ **保留**（压缩后约 15 MB） |
| `win32/arm64` | 34 MB | ⚠️ 默认删；若要支持 Windows on ARM 则保留 |

**裁剪后：536 MB → 68 MB**（仅留 win32 全 arch）或 **34 MB**（仅 win32/x64）。

> **实现要点**：`stage-render-runtime.js` 复制 `onnxruntime-node` 时，
> 删除 `bin/napi-v3/` 下除 `win32/` 外的平台目录。（不要删整个包——`dist/` 与
> `package.json` 仍需保留。）

**✅ 关键风险已实测排除：Electron 能否加载该原生模块？**

原生 `.node` 模块跨运行时（Node ↔ Electron）常有 ABI 不匹配问题，故专门验证：

| 验证项 | 结果 |
| --- | --- |
| 模块类型 | **N-API v3**（`bin/napi-v3/`，`binary.napi_versions: [3]`）——ABI 稳定接口 |
| 是否源码编译型 | 否（无 `binding.gyp`，预编译分发） |
| Electron 33（**Node 20.18.3**）能否 `require` 该 `.node` | ✅ `BINDING_LOADED=true`，导出 `InferenceSession` / `initOrtOnce` |
| 能否加载完整入口 `dist/index.js` | ✅ `FULL_ENTRY_LOADED=true`，`listSupportedBackends` 可用 |

结论：**N-API v3 的 ABI 稳定性成立，Electron 可直接加载，无需针对 Electron 重新编译**
（也不需要 `electron-rebuild`）。同时注意：这也意味着**它不依赖 Node 版本**，
即使将来调整 Node 版本也不会失效。

#### 打包体积（**实测值**，早先预估已修正）

> ⚠️ 本文早先给出的「ffmpeg + ffprobe < 1 MB、合计约 536 MB」是**基于容器内 Debian 动态链接构建**的错误推断。
> Windows 侧**必须用自包含**的 ffmpeg/ffprobe（静态构建备各约 98 MB），否则缺 DLL 启动即崩。
> 以下为 2026-09-19 真机暂存 `desktop/vendor/render-runtime/` 的实测占用：

| 组件 | 实测体积 | 说明 |
| --- | --- | --- |
| `node_modules`（含裁剪到 win32 的 onnxruntime-node） | 222 MB | onnxruntime 67 MB + hyperframes 36 MB + `@img` 19 MB + `@esbuild` 10 MB + 其余 |
| Chromium（`chrome-headless-shell` 整目录） | 268 MB | 主程序 200 MB + `locales` 42 MB + `icudtl.dat` 10 MB + DLL/pak |
| `ffmpeg.exe` + `ffprobe.exe`（gyan.dev 静态构建） | 196 MB | **各约 98 MB**（自包含的代价） |
| **合计原始** | **约 687 MB** | 压缩后（NSIS）安装包增量约 **220–260 MB** |

**可选瘦身**：`locales/`（42 MB）+ `hyphen-data/`（1.7 MB）实测**非必需**（渲染链路不读），
裁剪后约 643 MB。当前为降低风险默认保留。

> 对比：若**不裁剪** onnxruntime 的平台目录，再 **+468 MB**（`linux/x64` 独占 370 MB）。

#### 源目录来源：从容器取（保证两端同源）

**决策（用户明确指示）**：运行时源目录**从 `llmops-render-worker` 容器提取**，
而非在打包机上 `npm install`。

**理由**：与「桌面端 Node 对齐容器 24」同一思路——**保证本机渲染与云端渲染使用
完全相同的 Chromium / ffmpeg / hyperframes 版本**。若打包机自行安装，两个渠道的
版本会独立漂移，可能产生「本机成功、云端失败」或输出像素不一致，且报错往往不指向
版本差异，排查成本极高。

提取方式（容器已按 `Dockerfile.render` 构建，内含全部运行时）：

```bash
# 从容器导出运行时（node_modules + chromium + ffmpeg/ffprobe）到打包机
docker cp llmops-render-worker:/opt/hyperframes/node_modules <staging>/node_modules
docker cp llmops-render-worker:/usr/lib/chromium <staging>/chromium
docker cp llmops-render-worker:/usr/bin/ffmpeg <staging>/ffmpeg
docker cp llmops-render-worker:/usr/bin/ffprobe <staging>/ffprobe
export RENDER_RUNTIME_SOURCE_DIR=<staging>
```

> **注意**：容器内 Chromium 是 linux/x64 构建，**Windows 打包需换成 win32 构建**的
> `chrome-headless-shell`（§0.5 约束 1：必须是能响应 `--version` 的构建）。
> 故实际策略为：
> - **`node_modules`（hyperframes + onnxruntime）从容器取**——这部分是跨平台 JS + 多平台原生库，同源无碍；
> - **Chromium / ffmpeg / ffprobe 用 Windows 构建**（各自从官方渠道获取并钉住版本号，
>   版本号需与容器内一致，可在 `MANIFEST.json` 中记录以便比对）。
>
> 容器内版本基准（实测）：ffmpeg/ffprobe 来自 Debian bookworm 包、Chromium 来自
> `apt` 的 `chromium`；Windows 侧应选用**版本号对齐**的对应构建。

#### ⚠️ 容器 node_modules 并非全平台（实测推翻上文「同源无碍」的简化表述）

上文称「node_modules 是跨平台 JS + 多平台原生库」——这句**只对 onnxruntime 成立**，
对 **`esbuild` 与 `sharp` 不成立**。实测（`llmops-render-worker` 容器内）：

| 包 | 容器内目录 | `package.json` 的 os 约束 | 是否跨平台 |
| --- | --- | --- | --- |
| `onnxruntime-node` | `bin/napi-v3/{win32,darwin,linux}/` | `os: [win32,darwin,linux]` | ✅ 一份通吃（N-API v3） |
| `esbuild` | `@esbuild/linux-x64` | `os: ["linux"]` | ❌ **仅 linux** |
| `sharp` | `@img/sharp-linux-x64`、`@img/sharp-libvips-linux-x64` | `os: ["linux"]` | ❌ **仅 linux** |

**后果（实测，非推断）**：把容器提取的 `node_modules` 直接在 Windows 上跑，
`node dist/cli.js --version` 立即崩溃——

```
Error: Could not load the "sharp" module using the win32-x64 runtime
    at file:///.../sharp/dist/sharp.mjs:171:9
```

原因：`hyperframes/dist/cli.js` 在**启动阶段就 eagerly import `sharp`**（不是渲染时才用），
所以缺失 win32 构建时连 `--version` 都过不去。`esbuild` 不受影响（其 Node 包装器
只在真正调用时加载平台二进制，实测 `--version` 与 `transformSync` 均正常）。

**正确做法（已落地在 `stage-render-runtime.js`）**：

1. **裁掉**容器带来的非目标平台原生包（`@esbuild/linux-*`、`@img/sharp-linux-*`、
   `@img/sharp-libvips-linux-*`）；
2. **从 Windows 侧补齐**同版本 win32 原生包（`@esbuild/win32-x64`、`@img/sharp-win32-x64`），
   路径经 `RENDER_RUNTIME_WIN32_MODULES_DIR` 传入——在 Windows 上执行
   `npm install hyperframes@<与容器同版本>`，取其 `node_modules` 即可；
3. **自校验**：暂存结束前断言 win32 原生包存在，缺失即**报错终止打包**
   （宁可打包失败，也不要交付一个「渲染必崩」的安装包）。

```bash
# Windows 侧准备同版本原生包（版本必须与容器内一致）
mkdir -p <win32-staging> && cd <win32-staging>
npm init -y && npm install hyperframes@0.8.42 --no-audit --no-fund
export RENDER_RUNTIME_WIN32_MODULES_DIR=<win32-staging>/node_modules
```

> 实测口径：`@esbuild/win32-x64` 与 `@img/sharp-win32-x64` 须与容器内对应包**同版本**
> （实测均为 0.25.12 与 0.35.4）。跨版本混装可能触发原生绑定不兼容。

#### ⚠️ Chromium 不是单文件（实测会崩）

`chrome-headless-shell.exe` 依赖**同目录**的 `icudtl.dat` / `*.pak` / `*.dll`
（`libEGL.dll`、`libGLESv2.dll`、`vk_swiftshader.dll`、`vulkan-1.dll`、`headless_lib_*.pak` 等）。
实测只把 exe 拷到空目录后启动会**直接崩溃**（退出码 `0x80000003`），
`--version` 都过不去。故 `stage-render-runtime.js` 必须**整目录复制**
（`RENDER_RUNTIME_BROWSER_DIR` 指向目录），并断言 `chrome-headless-shell.exe` 与
`icudtl.dat` 均存在。

> `locales/`（42 MB）与 `hyphen-data/` 实测**非必需**（已在 render 实测中验证），
> 但为降低风险默认保留；若要瘦身可后续按需裁剪。

#### ⚠️ ffmpeg 需要三项能力（缺一即渲染失败）

实测：Trae 自带的 ffmpeg 6.1.1 缺 `image2pipe` 解复用器 → 渲染报
`Unknown input format: 'image2pipe'`；playwright 附带的 ffmpeg 缺 `libx264` 编码器 → 无法编码。
渲染链路实际需要：

| 能力 | 用途 | 缺失时的表现 |
| --- | --- | --- |
| `image2pipe` 解复用器 | 从 stdin 读帧序列 | `Unknown input format: 'image2pipe'` |
| `mjpeg` 解码器 | 解码捕获的 JPEG 帧 | 无法读取帧 |
| `libx264` 编码器 | 编码为 H.264 MP4 | 编码失败 |

且 ffmpeg 必须是**自包含**构建：实测 `kzip_sogou` 的 ffmpeg 依赖同目录 `avcodec-58.dll` 等，
单独拷贝后启动即报 `0xC0000135`（缺 DLL）。

**结论**：`stage-render-runtime.js` 暂存后对 ffmpeg 做三项能力探测，不达标**报错终止打包**。
实测可用：gyan.dev essentials 自包含构建（`ffmpeg-release-essentials.zip`，
本次实测为 9.0.1），Chromium 用 playwright 的 `chromium_headless_shell` 152.x。

> **版本无法与容器完全对齐**：容器是 Debian 的 ffmpeg 5.1.9 / Chromium 152.0.7977.82，
> Windows 侧不存在版本号完全一致的官方构建。这是「node_modules 同源、
> Chromium/ffmpeg 各自取本平台构建」策略的固有代价，故用 `MANIFEST.json` 记录实际版本供比对。
> 实测该组合（Chromium 152.x + ffmpeg 9.0.1）渲染产物正常（h264 / 分辨率 / 时长均正确）。

#### ⚠️ electron-builder 会剔除 `extraResources` 根部的 `node_modules`（必读）

**这是最隐蔽的一处，会导致「`npm start` 正常、安装版渲染必崩」。**

electron-builder 的 `app-builder-lib/out/util/filter.js` 中有无条件排除：

```javascript
// filter the root node_modules, but not a subnode_modules (like /appDir/others/foo/node_modules/blah)
if (relative === "node_modules") {
    return false;
}
```

即：**匹配器 `from` 目录根部**的 `node_modules` 会被整棵剪掉。若把
`vendor/render-runtime` 作为单一条目传给 `extraResources`，打包后
`resources/render-runtime/node_modules/` **完全不存在**——CLI 缺依赖，渲染必崩。

**正确配置**（已落地在 `desktop/package.json`）：拆成**两条独立** `extraResources`，
让 `node_modules` 不再是匹配器根部：

```json
    {
      "from": "vendor/render-runtime",
      "to": "render-runtime",
      "filter": ["**/*", "!node_modules/**"]
    },
    {
      "from": "vendor/render-runtime/node_modules",
      "to": "render-runtime/node_modules"
    }
```

**打包后自检命令**（必须为 True）：

```bash
ls desktop/dist-nsis/win-unpacked/resources/render-runtime/node_modules/hyperframes/dist/cli.js
```

**容器版本基准（实测，Windows 侧须对齐）**：

| 组件 | 容器内版本 | 说明 |
| --- | --- | --- |
| Node | **v24.21.0** | 桌面端由 Electron 43.x 内置（Task 0） |
| Chromium | **152.0.7977.82** | Debian bookworm 构建；Windows 侧取同版本 `chrome-headless-shell` |
| ffmpeg / ffprobe | **5.1.9-0+deb12u1** | Windows 侧取同版本构建 |
| hyperframes | **0.8.42** | `node_modules` 从容器取，天然同源 |
| onnxruntime-node | **1.21.1** | 同上 |

用于比对的采集命令（打包前跑一次，结果写入 `MANIFEST.json`）：

```bash
docker exec llmops-render-worker sh -c \
  'node -v; chromium --version; ffmpeg -version | head -1; ffprobe -version | head -1'
```

#### 落地方式：照搬既有 `stage-cua-driver.js` 范式

本仓库已有远端二进制随包的成熟模式（`desktop/scripts/stage-cua-driver.js` →
`desktop/vendor/cua-driver/` → `electron-builder` 的 `extraResources`），
**新增 `stage-render-runtime.js` 完全照此结构**，不引入新机制。

**新建文件**：

| 文件 | 职责 |
| --- | --- |
| `desktop/scripts/stage-render-runtime.js` | 暂存脚本：把 `node_modules`（含 onnxruntime，裁剪到 win32）、`cli.js`、Chromium、ffmpeg/ffprobe 复制到 `desktop/vendor/render-runtime/` |
| `desktop/render-runtime.js` | 运行时定位（见 Task 0B）：解析 vendor 路径 + 生成 CLI shim |

**`extraResources` 追加**（`desktop/package.json`）：

```json
    {
      "from": "vendor/render-runtime",
      "to": "render-runtime"
    }
```

**体积清单固定（可选但推荐）**：随包后建议写一份 `vendor/render-runtime/MANIFEST.json`
（版本号 + 各文件 sha256），便于排查「用户机上运行的是哪个版本」。

> **注意**：`desktop/vendor/` 属构建产物，不应提交（`stage-cua-driver.js` 同样如此，
> 由 `pack` / `dist` 脚本在打包前生成）。需确认 `.gitignore` 覆盖 `vendor/render-runtime/`。
>
> **ffmpeg/ffprobe 必须是真 ffprobe**（见 §0.5 约束 2）；**Chromium 必须是
> `chrome-headless-shell` 一类能响应 `--version` 的构建**（见 §0.5 约束 1），
> 不可用 Electron 自带的 `chrome.exe` 替代。

### 0.6 测试命令

```bash
cd api && python -m pytest test/ -q          # 全量
cd api && python -m pytest test/path/to/test.py::test_name -v   # 单测
```

### 0.7 本方案的复用价值（不只服务渲染）

本方案确立的是一套**「重负载任务本机化」的通用范式**，后续其他重型任务可直接套用：

```
服务端工具
  → resolve_desktop_bridge(account_id, purpose="/xxx")   # 已有，无需改动
  → 打用户本机的 xxx worker（新增 worker 子命令 + bridge 路由）
  → 本机算完，产物经 bridge 取回
  → 复用服务端既有入库能力（store_render_output 之类的落库函数）
  ← 不可用则回退云端（云端代码保留，开关控制）
```

**判定是否适合本机化的三个标准**：

| 标准 | 说明 |
| --- | --- |
| **计算密集、结果可搬运** | 吃 CPU/内存但产物是单个文件（如渲染出 MP4）→ 适合 |
| **不改平台数据** | 本机只做「算」，写库/写对象存储仍在服务端 → 适合 |
| **有可接受的降级** | 用户没装客户端时能回退云端或明确报错 → 适合 |

**典型候选**（供后续评估，本文不展开）：视频转码/剪辑、大文件批量解析、
本地模型推理（ASR/视觉）、批量 OCR、批量图像处理。

**注意事项**（渲染已踩过的坑，复用时要重查）：
- 本机运行时体积（渲染是 ~500 MB）——每个重型任务都带一份运行时不可持续，**优先复用同一份 Node/Chromium/ffmpeg 底座**；
- 外网依赖（渲染依赖 GSAP CDN + Google Fonts）；
- 用户设备性能差异与中途休眠，需要幂等 + 可重试。


---

## 1. 文件结构规划

### 新建文件

| 文件 | 职责 |
| --- | --- |
| `api/scripts/render_worker.py` | 本机渲染 worker：HTTP 服务（`POST /render`），Bearer 鉴权，调用 HyperFrames CLI 出 MP4，返回产物路径/字节 |
| `api/internal/core/tools/builtin_tools/providers/video_render_tools/local_render_runner.py` | 服务端侧「调本机 render worker」的客户端封装：解析 bridge → POST → 返回结果 |
| `api/test/scripts/test_render_worker.py` | render worker 单测 |
| `api/test/internal/core/tools/test_local_render_runner.py` | 本机渲染客户端单测 |

### 修改文件

| 文件 | 改动 |
| --- | --- |
| `desktop/package.json` | **`electron` 由 `^33.0.0` 升到 `^43.7.0`**（内置 Node 24.21.0，与容器对齐）；`electron-builder` 同步升级 |
| `api/scripts/worker_super.py` | 子命令白名单两处加 `render`；`_SERVICE_SUPPORTS_HOST_PORT` 加 `render` |
| `api/config/config.py` | 新增 `RENDER_LOCAL_ENABLED` / `RENDER_CLOUD_FALLBACK_ENABLED` 两个开关 |
| `api/internal/core/tools/builtin_tools/providers/video_render_tools/render_video.py` | `_dispatch_render` 改为三级路由（本机优先 → 云端回退） |
| `desktop/bridge.js` | `targets` 加 `/render` 与 `/artifact` 路由 |
| `desktop/main.js` | 新增 render worker 的 token/端口/startWorker/createBridge 参数；**用 Electron 内置 Node 作为渲染子进程的 node** |
| `desktop/render-runtime.js` | **新建**：运行时定位（解析随包 `resources/render-runtime/`）+ 生成 CLI shim |
| `desktop/scripts/stage-render-runtime.js` | **新建**：打包前暂存 node_modules（含 onnxruntime，裁剪到 win32）/Chromium/ffmpeg/ffprobe 到 `vendor/render-runtime/` |
| `.gitignore` | 加 `desktop/vendor/render-runtime/`（构建产物不入库） |
| `api/scripts/pyinstaller/worker.spec` | `hiddenimports` 加 `scripts.render_worker` |
| `docker/docker-compose.yaml` | 云端 render worker 改为默认不启动（保留 profile，可随时接通） |
| `docs/deployment-single-node.md` | 同步「云端渲染默认关闭、本机优先」 |
| `docs/prd/modules/09-desktop-client.md` | 登记 render worker 子命令与桥路由 |
| `docs/prd/modules/08-os-automation.md` | 桥路由表补 `/render` 与 `/artifact` |

### 不改动（重要）

- `api/internal/task/render_tasks.py`、`api/internal/service/render_service.py`、`api/internal/service/render_guard_service.py`
  —— 云端渲染链路**整体保留**，仅通过开关决定是否派发。
- `desktop_device` 表、`desktop_bridge_resolver.py`、`store_render_output`。
- `api/Dockerfile.render` 的 `node:24-bookworm-slim` —— 容器侧已是 24，**无需改动**；
  桌面端对齐的是它。

---

## Task 0: 桌面端 Electron 升级到内置 Node 24（前置任务）

**为什么必须先做**：HyperFrames 门禁要求 Node ≥ 22，而当前 Electron 33 内置 Node 20.18.3，
**渲染在本机根本起不来**。且按用户要求，须与容器（Node 24.21.0）**精确对齐**避免版本漂移。

**Files:**
- Modify: `desktop/package.json`（`devDependencies.electron`、`devDependencies.electron-builder`）
- Test: `desktop/test/electron-version.test.js`（新建）

- [x] **Step 1: 写失败的测试**

创建 `desktop/test/electron-version.test.js`：

```javascript
const { test } = require('node:test')
const assert = require('node:assert')
const { execFileSync } = require('node:child_process')
const path = require('node:path')
const fs = require('node:fs')

// 容器侧基准（api/Dockerfile.render 的 ARG NODE_IMAGE=node:24-bookworm-slim，实测 24.21.0）
const REQUIRED_NODE_MAJOR = 24

function electronBinary() {
  const base = path.join(__dirname, '..', 'node_modules', 'electron', 'dist')
  if (process.platform === 'win32') return path.join(base, 'electron.exe')
  if (process.platform === 'darwin') return path.join(base, 'Electron.app', 'Contents', 'MacOS', 'Electron')
  return path.join(base, 'electron')
}

test('desktop electron bundles Node 24 to match the render container', () => {
  const bin = electronBinary()
  assert.ok(fs.existsSync(bin), 'electron 二进制不存在，请先 npm install')
  const out = execFileSync(bin, ['-e', 'console.log(process.versions.node)'], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
    encoding: 'utf-8',
  }).trim()
  const major = Number.parseInt(out.split('.')[0], 10)
  assert.equal(
    major,
    REQUIRED_NODE_MAJOR,
    `Electron 内置 Node 为 ${out}，要求 major=${REQUIRED_NODE_MAJOR}（与容器 node:24 对齐）`,
  )
})

test('electron binary can run as node with ESM support', () => {
  const bin = electronBinary()
  const out = execFileSync(
    bin,
    ['-e', "import('node:module').then(() => console.log('esm-ok'))"],
    {
      env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
      encoding: 'utf-8',
    },
  ).trim()
  assert.match(out, /esm-ok/)
})
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd desktop && node --test test/electron-version.test.js`
Expected: FAIL（`Electron 内置 Node 为 20.18.3，要求 major=24`）

- [x] **Step 3: 升级 Electron**

修改 `desktop/package.json` 的 `devDependencies`：

```json
  "devDependencies": {
    "cross-env": "^7.0.3",
    "electron": "^43.7.0",
    "electron-builder": "^26.0.0"
  },
```

> **版本核实（已查 npm registry）**：`electron@^43.7.0` 解析到 `43.7.3`（内置 Node 24.21.0）；
> `electron-builder` 最新为 `26.15.3`，原 `^25.0.0` 需一并升级（25.x 对 Electron 43 支持不全）。
> 当前实际值：`electron: ^33.0.0`、`electron-builder: ^25.0.0`。

重新安装：

```bash
cd desktop && npm install
```

- [x] **Step 4: 运行测试确认通过**

Run: `cd desktop && node --test test/electron-version.test.js`
Expected: PASS（2 passed）——此时内置 Node 应为 24.21.0

- [x] **Step 5: 回归既有桌面端测试（跨 10 个大版本，必须验）**

Run: `cd desktop && node --test`
Expected: 全部通过。若因 Electron API 变更失败，按报错逐项修（用到的均为 `app` /
`BrowserWindow` / `ipcMain` / `shell` / `safeStorage` / `Notification` / `session` /
`Menu` / `screen` / `Tray` 等稳定 API，预期风险低）。

- [x] **Step 6: 提交**

```bash
git add desktop/package.json desktop/package-lock.json desktop/test/electron-version.test.js
git commit -m "build(desktop): upgrade electron to 43.x for bundled Node 24 aligned with render container"
```

---

## Task 0B: 渲染运行时探测与 shim（把 Electron 的 Node 接进 CLI）

**为什么需要**：`HYPERFRAMES_CLI_BIN` 只接受**单个可执行文件路径**，但 HyperFrames CLI 是
Node 脚本，需要 `node cli.js` 两段式调用；且 Electron 的 `electron.exe` 必须设
`ELECTRON_RUN_AS_NODE=1` 才能当 node 用（均已在 §0.5.1 实测确认）。故必须生成 shim。

**Files:**
- Create: `desktop/render-runtime.js`
- Modify: `desktop/package.json`（`build.files` 加 `render-runtime.js`）
- Test: `desktop/test/render-runtime.test.js`

- [x] **Step 1: 写失败的测试**

创建 `desktop/test/render-runtime.test.js`：

```javascript
const { test } = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
  resolveRuntimePaths,
  ensureCliShim,
  _shimFileName,
} = require('../render-runtime')

test('shim file name is platform specific', () => {
  const name = _shimFileName()
  if (process.platform === 'win32') {
    assert.match(name, /\.cmd$/)
  } else {
    assert.match(name, /hyperframes$/)
  }
})

test('ensureCliShim writes a shim that runs electron as node', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shim-test-'))
  try {
    const shimPath = ensureCliShim({
      electronPath: 'C:/app/electron.exe',
      cliJsPath: 'C:/app/resources/render-runtime/cli.js',
      targetDir: dir,
    })
    assert.ok(fs.existsSync(shimPath), 'shim 未生成')
    const content = fs.readFileSync(shimPath, 'utf-8')
    assert.match(content, /ELECTRON_RUN_AS_NODE/)
    assert.match(content, /render-runtime/)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('resolveRuntimePaths points at bundled runtime dir', () => {
  const paths = resolveRuntimePaths({
    env: {},
    resourcesDir: '/res',
  })
  assert.equal(paths.runtimeDir, '/res/render-runtime')
  assert.match(paths.cliJsPath, /render-runtime.*hyperframes.*cli\.js$/)
  assert.match(paths.browserPath, /render-runtime/)
  assert.match(paths.ffmpegPath, /render-runtime/)
  assert.match(paths.ffprobePath, /render-runtime/)
})

test('resolveRuntimePaths lets explicit env override bundled defaults', () => {
  const paths = resolveRuntimePaths({
    env: {
      HYPERFRAMES_BROWSER_PATH: '/custom/chrome',
      HYPERFRAMES_FFMPEG_PATH: '/custom/ffmpeg',
      HYPERFRAMES_FFPROBE_PATH: '/custom/ffprobe',
    },
    resourcesDir: '/res',
  })
  assert.equal(paths.browserPath, '/custom/chrome')
  assert.equal(paths.ffmpegPath, '/custom/ffmpeg')
  assert.equal(paths.ffprobePath, '/custom/ffprobe')
})
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd desktop && node --test test/render-runtime.test.js`
Expected: FAIL（`Cannot find module '../render-runtime'`）

- [x] **Step 3: 实现 render-runtime.js**

创建 `desktop/render-runtime.js`：

```javascript
'use strict'

const fs = require('node:fs')
const path = require('node:path')

// HyperFrames CLI 需要「node + cli.js」两段式调用，而服务端 HYPERFRAMES_CLI_BIN
// 只接受单个可执行文件路径，故必须生成 shim 把 Electron 的 Node 包在中间。
// 运行时二进制随安装包分发（见 §0.5.2），路径位于 resources/render-runtime/。
// 详见 docs/superpowers/plans/2026-09-18-local-first-render-offload.md §0.5.1。

function _shimFileName() {
  return process.platform === 'win32' ? 'hyperframes.cmd' : 'hyperframes'
}

function resolveRuntimePaths({ env, resourcesDir }) {
  const pick = (key) => String((env && env[key]) || '').trim()
  // 随包分发：运行时固定在 resources/render-runtime/（见 §0.5.2）
  const runtimeDir = path.join(resourcesDir, 'render-runtime')
  const withExe = (name) =>
    process.platform === 'win32' ? `${name}.exe` : name
  return {
    runtimeDir,
    cliJsPath: path.join(runtimeDir, 'node_modules', 'hyperframes', 'dist', 'cli.js'),
    browserPath: pick('HYPERFRAMES_BROWSER_PATH') ||
      path.join(runtimeDir, withExe('chrome-headless-shell')),
    ffmpegPath: pick('HYPERFRAMES_FFMPEG_PATH') ||
      path.join(runtimeDir, withExe('ffmpeg')),
    ffprobePath: pick('HYPERFRAMES_FFPROBE_PATH') ||
      path.join(runtimeDir, withExe('ffprobe')),
  }
}

function ensureCliShim({ electronPath, cliJsPath, targetDir }) {
  fs.mkdirSync(targetDir, { recursive: true })
  const shimPath = path.join(targetDir, _shimFileName())
  if (process.platform === 'win32') {
    const content = [
      '@echo off',
      'set ELECTRON_RUN_AS_NODE=1',
      `"${electronPath}" "${cliJsPath}" %*`,
      '',
    ].join('\r\n')
    fs.writeFileSync(shimPath, content, 'utf-8')
  } else {
    const content = [
      '#!/bin/sh',
      'export ELECTRON_RUN_AS_NODE=1',
      `exec "${electronPath}" "${cliJsPath}" "$@"`,
      '',
    ].join('\n')
    fs.writeFileSync(shimPath, content, 'utf-8')
    fs.chmodSync(shimPath, 0o755)
  }
  return shimPath
}

module.exports = { resolveRuntimePaths, ensureCliShim, _shimFileName }
```

> **注意**：shim 内必须**原地引用** `electronPath`（不可把 electron.exe 拷成单文件，
> 会缺 DLL 报 `0xC0000135`）；`electronPath` 应为 `process.execPath`。

- [x] **Step 4: 登记打包白名单**

在 `desktop/package.json` 的 `build.files` 数组末尾加入 `"render-runtime.js"`（见 Task 8 Step 4e）。

- [x] **Step 5: 运行测试确认通过**

Run: `cd desktop && node --test test/render-runtime.test.js`
Expected: PASS（4 passed）

- [x] **Step 6: 提交**

```bash
git add desktop/render-runtime.js desktop/test/render-runtime.test.js desktop/package.json
git commit -m "feat(desktop): add render runtime resolver and electron-node cli shim"
```

---

## Task 0C: 暂存渲染运行时并打进安装包

**为什么需要**：按用户决策（§0.5.2），渲染所需的 `node_modules` + Chromium + ffmpeg/ffprobe
**随安装包分发**，避免运行时下载。照搬既有 `stage-cua-driver.js` 范式。

**Files:**
- Create: `desktop/scripts/stage-render-runtime.js`
- Modify: `desktop/package.json`（`extraResources` 加 render-runtime；`scripts.pack`/`dist` 前置暂存）
- Modify: `.gitignore`（加 `desktop/vendor/render-runtime/`）
- Test: `desktop/test/stage-render-runtime.test.js`

- [x] **Step 1: 写失败的测试**

创建 `desktop/test/stage-render-runtime.test.js`：

```javascript
const { test } = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

const SCRIPT = path.join(__dirname, '..', 'scripts', 'stage-render-runtime.js')

test('stage script exists and is runnable', () => {
  assert.ok(fs.existsSync(SCRIPT), 'stage-render-runtime.js 不存在')
})

test('stage script skips gracefully when source is absent', () => {
  // 源缺失时应打印提示并以 0 退出（不阻断打包），与 stage-cua-driver.js 一致
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-rr-'))
  try {
    const out = execFileSync(process.execPath, [SCRIPT], {
      env: { ...process.env, RENDER_RUNTIME_SOURCE_DIR: dir, STAGE_TARGET_DIR: dir },
      encoding: 'utf-8',
    })
    assert.match(out + '', /skip|跳过|未找到/i)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('stage script prunes non-target onnxruntime platforms', () => {
  // 构造假的 node_modules/onnxruntime-node/bin/napi-v3/{win32,linux,darwin}
  // 断言：暂存后仅保留 win32，其余被删（536MB → 68MB 的核心优化）
  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-src-'))
  const dst = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-dst-'))
  try {
    const napi = path.join(src, 'node_modules', 'onnxruntime-node', 'bin', 'napi-v3')
    for (const p of ['win32', 'linux', 'darwin']) {
      fs.mkdirSync(path.join(napi, p, 'x64'), { recursive: true })
      fs.writeFileSync(path.join(napi, p, 'x64', 'onnxruntime_binding.node'), 'x')
    }
    // 加一个必须被保留的普通包，验证没有误删
    fs.mkdirSync(path.join(src, 'node_modules', 'hyperframes'), { recursive: true })
    fs.writeFileSync(path.join(src, 'node_modules', 'hyperframes', 'keep.txt'), 'k')

    execFileSync(process.execPath, [SCRIPT], {
      env: {
        ...process.env,
        RENDER_RUNTIME_SOURCE_DIR: src,
        STAGE_TARGET_DIR: dst,
        ORT_PLATFORMS: 'win32',
      },
      encoding: 'utf-8',
    })

    const outNapi = path.join(dst, 'node_modules', 'onnxruntime-node', 'bin', 'napi-v3')
    assert.ok(fs.existsSync(path.join(outNapi, 'win32')), 'win32 应保留')
    assert.ok(!fs.existsSync(path.join(outNapi, 'linux')), 'linux 应被裁剪')
    assert.ok(!fs.existsSync(path.join(outNapi, 'darwin')), 'darwin 应被裁剪')
    assert.ok(
      fs.existsSync(path.join(dst, 'node_modules', 'hyperframes', 'keep.txt')),
      '其它包不应被误删',
    )
  } finally {
    fs.rmSync(src, { recursive: true, force: true })
    fs.rmSync(dst, { recursive: true, force: true })
  }
})
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd desktop && node --test test/stage-render-runtime.test.js`
Expected: FAIL（脚本不存在）

- [x] **Step 3: 实现暂存脚本**

创建 `desktop/scripts/stage-render-runtime.js`（结构对照 `stage-cua-driver.js`）：

```javascript
// 把渲染运行时暂存到 desktop/vendor/render-runtime/，供 electron-builder
// extraResources 打进安装包。随包分发以彻底避免运行时下载（见 plan §0.5.2）。
//
// 需要暂存的内容：
//   1. node_modules/（**含 onnxruntime-node**，供图片处理/抠像使用）
//   2. Chromium（chrome-headless-shell）
//   3. ffmpeg + ffprobe
//
// onnxruntime-node 裁剪：其 bin/napi-v3/ 带 6 个平台共 536MB，但 dist/binding.js
// 是按 process.platform/arch 动态 require 的，故只保留 win32/ 即可：
//   536MB → 68MB（仅 win32 全 arch）
//
// 体积参考：node_modules 约 198MB（含裁剪后的 onnxruntime），Chromium 约 338MB。
// 安装包增量约 175–215MB。
//
// 源缺失时打印提示并跳过（不阻断打包），与 stage-cua-driver.js 行为一致。

const fs = require('node:fs')
const path = require('node:path')

// onnxruntime-node 跨平台裁剪：仅保留目标平台（默认 win32）
const TARGET_ORT_PLATFORMS = (process.env.ORT_PLATFORMS || 'win32')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean)

function copyDir(src, dest, { skipNames } = {}) {
  fs.mkdirSync(dest, { recursive: true })
  let count = 0
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (skipNames && skipNames.has(entry.name)) continue
    const from = path.join(src, entry.name)
    const to = path.join(dest, entry.name)
    if (entry.isDirectory()) {
      count += copyDir(from, to, { skipNames })
    } else if (entry.isFile()) {
      fs.copyFileSync(from, to)
      count += 1
    }
  }
  return count
}

function pruneOnnxPlatforms(ortDir) {
  const napiDir = path.join(ortDir, 'bin', 'napi-v3')
  if (!fs.existsSync(napiDir)) return
  for (const entry of fs.readdirSync(napiDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    if (!TARGET_ORT_PLATFORMS.includes(entry.name)) {
      fs.rmSync(path.join(napiDir, entry.name), { recursive: true, force: true })
      console.log(`[stage-render-runtime] 裁剪 onnxruntime 平台目录: ${entry.name}`)
    }
  }
}

function main() {
  const sourceDir = process.env.RENDER_RUNTIME_SOURCE_DIR || ''
  const targetDir =
    process.env.STAGE_TARGET_DIR || path.join(__dirname, '..', 'vendor', 'render-runtime')

  // 目录必须始终存在，否则 electron-builder 的 extraResources 会因源缺失而失败
  fs.mkdirSync(targetDir, { recursive: true })

  if (!sourceDir || !fs.existsSync(sourceDir)) {
    console.warn(
      '[stage-render-runtime] 未找到渲染运行时源目录（RENDER_RUNTIME_SOURCE_DIR）；' +
        '跳过捆绑，本机渲染将不可用（云端回退仍可用）。',
    )
    return
  }

  const nodeModules = path.join(sourceDir, 'node_modules')
  if (!fs.existsSync(nodeModules)) {
    console.warn(`[stage-render-runtime] ${sourceDir} 内无 node_modules，跳过`)
    return
  }

  const copied = copyDir(nodeModules, path.join(targetDir, 'node_modules'))
  console.log(`[stage-render-runtime] node_modules 已暂存（${copied} 个文件，含 onnxruntime-node）`)

  // 裁剪 onnxruntime 的非目标平台目录（536MB → 68MB）
  pruneOnnxPlatforms(path.join(targetDir, 'node_modules', 'onnxruntime-node'))

  for (const name of ['chrome-headless-shell', 'chrome-headless-shell.exe', 'ffmpeg', 'ffmpeg.exe', 'ffprobe', 'ffprobe.exe']) {
    const src = path.join(sourceDir, name)
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, path.join(targetDir, name))
      console.log(`[stage-render-runtime] copied ${name}`)
    }
  }

  fs.writeFileSync(
    path.join(targetDir, 'SOURCE.txt'),
    `Staged from ${sourceDir}\nhyperframes + Chromium + ffmpeg/ffprobe + onnxruntime-node\n` +
      `onnxruntime platforms kept: ${TARGET_ORT_PLATFORMS.join(',')}\n`,
    'utf-8',
  )
  console.log(`[stage-render-runtime] done → ${targetDir}`)
}

main()
```

- [x] **Step 4: 接线（extraResources + scripts + gitignore）**

`desktop/package.json` 的 `extraResources` 追加：

```json
    {
      "from": "vendor/render-runtime",
      "to": "render-runtime"
    }
```

`scripts` 中 `pack` / `dist` 前置暂存（与 `stage:cua` 并列）：

```json
    "stage:render": "node scripts/stage-render-runtime.js",
    "pack": "npm run stage:cua && npm run stage:render && electron-builder --dir",
    "dist": "npm run build:ui && npm run stage:cua && npm run stage:render && electron-builder --win"
```

`.gitignore` 追加（对照既有 `desktop/vendor/cua-driver/`）：

```
# 打包时暂存的渲染运行时（不入库；见 desktop/scripts/stage-render-runtime.js）
desktop/vendor/render-runtime/
```

- [x] **Step 5: 运行测试确认通过**

Run: `cd desktop && node --test test/stage-render-runtime.test.js`
Expected: PASS（3 passed）

- [x] **Step 6: 验证暂存产物被 git 忽略**

Run: `cd d:/DEMO/openagent-main && git check-ignore -v desktop/vendor/render-runtime/SOURCE.txt`
Expected: 输出命中 `.gitignore` 中新增的 `desktop/vendor/render-runtime/` 规则

- [x] **Step 7: 提交**

```bash
git add desktop/scripts/stage-render-runtime.js desktop/test/stage-render-runtime.test.js desktop/package.json .gitignore
git commit -m "build(desktop): bundle render runtime into installer via stage script"
```

---

## Task 1: 新增渲染执行开关配置

**Files:**
- Modify: `api/config/config.py`（在 §视频渲染 段，约 L213-234）
- Test: `api/test/config/test_render_execution_config.py`

- [x] **Step 1: 写失败的测试**

创建 `api/test/config/test_render_execution_config.py`：

```python
"""渲染执行目标配置：本机优先 / 云端回退 的开关语义。"""
import importlib
import os


def _load_config_with(monkeypatch, **env):
    for key in ("RENDER_LOCAL_ENABLED", "RENDER_CLOUD_FALLBACK_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config.config as module

    importlib.reload(module)
    return module.Config()


def test_defaults_local_first_and_cloud_fallback_on(monkeypatch):
    conf = _load_config_with(monkeypatch)
    assert conf.RENDER_LOCAL_ENABLED is True
    assert conf.RENDER_CLOUD_FALLBACK_ENABLED is True


def test_local_can_be_disabled(monkeypatch):
    conf = _load_config_with(monkeypatch, RENDER_LOCAL_ENABLED="false")
    assert conf.RENDER_LOCAL_ENABLED is False


def test_cloud_fallback_can_be_disabled(monkeypatch):
    """云端渲染默认关闭时，显式关掉回退即完全不派发云端。"""
    conf = _load_config_with(monkeypatch, RENDER_CLOUD_FALLBACK_ENABLED="false")
    assert conf.RENDER_CLOUD_FALLBACK_ENABLED is False


def test_env_parsing_is_case_insensitive(monkeypatch):
    conf = _load_config_with(monkeypatch, RENDER_LOCAL_ENABLED="FALSE")
    assert conf.RENDER_LOCAL_ENABLED is False
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/config/test_render_execution_config.py -q`
Expected: FAIL（`AttributeError: 'Config' object has no attribute 'RENDER_LOCAL_ENABLED'`）

- [x] **Step 3: 实现配置**

在 `api/config/config.py` 的 `RENDER_TIMEOUT_SEC` 之后（约 L233 后）追加：

```python
        # 渲染执行目标：本机优先（把重负载算力外部化到用户设备，平台只管轻量内容）。
        # 本机不可用时是否回退云端 Celery render 队列——云端链路完整保留，
        # 用该开关控制是否启用，便于未来随时接通。
        self.RENDER_LOCAL_ENABLED = (
            (_get_env("RENDER_LOCAL_ENABLED") or "true").strip().lower()
            not in {"false", "0", "no", "off"}
        )
        self.RENDER_CLOUD_FALLBACK_ENABLED = (
            (_get_env("RENDER_CLOUD_FALLBACK_ENABLED") or "true").strip().lower()
            not in {"false", "0", "no", "off"}
        )
```

- [x] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/config/test_render_execution_config.py -q`
Expected: PASS（4 passed）

- [x] **Step 5: 提交**

```bash
git add api/config/config.py api/test/config/test_render_execution_config.py
git commit -m "feat(render): add local-first render execution switches"
```

---

## Task 2: 本机渲染 worker（HTTP 服务）

**Files:**
- Create: `api/scripts/render_worker.py`
- Test: `api/test/scripts/test_render_worker.py`

- [x] **Step 1: 写失败的测试**

创建 `api/test/scripts/test_render_worker.py`：

```python
"""本机渲染 worker：鉴权、入参校验、渲染调用、错误包装。"""
import json
from pathlib import Path

import pytest

from scripts import render_worker


def test_authorized_accepts_matching_bearer(monkeypatch):
    monkeypatch.setenv("RENDER_WORKER_TOKEN", "secret-token")
    assert render_worker._authorized("Bearer secret-token") is True


def test_authorized_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("RENDER_WORKER_TOKEN", "secret-token")
    assert render_worker._authorized("Bearer wrong") is False


def test_authorized_rejects_when_token_unset(monkeypatch):
    monkeypatch.delenv("RENDER_WORKER_TOKEN", raising=False)
    assert render_worker._authorized("Bearer anything") is False


def test_validate_payload_requires_segments():
    error = render_worker._validate_payload({"composition": {"duration": 10}})
    assert error is not None
    assert "segments" in error["error"]


def test_validate_payload_requires_composition_dict():
    error = render_worker._validate_payload({"composition": "not-a-dict"})
    assert error is not None
    assert "composition" in error["error"]


def test_validate_payload_accepts_valid():
    payload = {
        "composition": {
            "composition_id": "main",
            "width": 1920,
            "height": 1080,
            "duration": 10.0,
            "segments": [{"start": 0.0, "duration": 10.0, "text": "hi"}],
        }
    }
    assert render_worker._validate_payload(payload) is None


def test_run_render_returns_error_when_env_missing(monkeypatch):
    """缺少 HYPERFRAMES_* 路径时返回可读错误，不抛异常。"""
    for key in (
        "HYPERFRAMES_BROWSER_PATH",
        "HYPERFRAMES_FFMPEG_PATH",
        "HYPERFRAMES_FFPROBE_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    payload = {
        "composition": {
            "composition_id": "main",
            "width": 1920,
            "height": 1080,
            "duration": 10.0,
            "segments": [{"start": 0.0, "duration": 10.0, "text": "hi"}],
        }
    }
    result = render_worker._run_render(payload)
    assert result["ok"] is False
    assert "HYPERFRAMES" in result["error"]


def test_run_render_invokes_renderer_with_composition(monkeypatch, tmp_path):
    """渲染成功时返回产物字节与落盘路径，并保持与原产物一致。"""
    fake_mp4 = tmp_path / "out.mp4"
    fake_mp4.write_bytes(b"FAKE_MP4_BYTES")
    captured = {}

    def fake_render(composition_spec, *, output_path, settings):
        captured["spec"] = composition_spec
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fake_mp4.read_bytes())
        return str(output_path)

    monkeypatch.setattr(render_worker, "_render_composition", fake_render)

    payload = {
        "composition": {
            "composition_id": "main",
            "width": 1920,
            "height": 1080,
            "duration": 10.0,
            "segments": [{"start": 0.0, "duration": 10.0, "text": "hi"}],
        },
        "name": "demo",
    }
    result = render_worker._run_render(payload)

    assert result["ok"] is True
    assert result["size_bytes"] == len(b"FAKE_MP4_BYTES")
    assert captured["spec"]["segments"][0]["text"] == "hi"
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/scripts/test_render_worker.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'scripts.render_worker'`）

- [x] **Step 3: 实现 worker**

创建 `api/scripts/render_worker.py`：

```python
"""本机渲染 worker（用户设备侧出片）。

由桌面客户端（Electron 主进程）托管启动，经本地能力桥（desktop/bridge.js）
的 `/render` 路由被服务端调用；也可在服务端容器内独立运行（回退通道）。

与 browser/computer worker 同一范式：ThreadingHTTPServer + Bearer 常量时间鉴权。
差异点：渲染是分钟级长任务，且**不返回产物字节流**——只回传落盘路径与体积，
由调用方（服务端）自行取回入库，避免在 HTTP body 里搬运几十 MB 视频。

安全模型：
- 仅接受 Authorization: Bearer <RENDER_WORKER_TOKEN>；
- 未配置 token 时拒绝启动；
- 仅在调用方指定的工作目录内写文件，不暴露任意路径读能力。

硬依赖（与 hyperframes_renderer 一致，缺一不可）：
HYPERFRAMES_BROWSER_PATH / HYPERFRAMES_FFMPEG_PATH / HYPERFRAMES_FFPROBE_PATH。
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import shutil
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger("render_worker")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8768

_REQUIRED_ENV_KEYS = (
    "HYPERFRAMES_BROWSER_PATH",
    "HYPERFRAMES_FFMPEG_PATH",
    "HYPERFRAMES_FFPROBE_PATH",
)


def _env(key: str, default: str = "") -> str:
    return str(os.environ.get(key, default) or "").strip()


def _authorized(header_value: str) -> bool:
    """常量时间比对 Bearer token；未配置 token 一律拒绝。"""
    expected = _env("RENDER_WORKER_TOKEN")
    if not expected:
        return False
    header = str(header_value or "")
    if not header.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(header[7:].strip(), expected)


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """校验入参，返回错误 dict 或 None。"""
    composition = payload.get("composition")
    if not isinstance(composition, dict):
        return {"ok": False, "error": "composition 必须是对象"}
    segments = composition.get("segments")
    if not isinstance(segments, list) or not segments:
        return {"ok": False, "error": "composition.segments 必须是非空列表"}
    return None


def _load_settings() -> Any:
    """构造渲染器所需配置视图（属性访问语义，与 server 侧一致）。

    本 worker 不依赖 Flask / internal.context，直接读环境变量并包成对象——
    ``hyperframes_renderer`` 全部用 ``getattr(settings, "HYPERFRAMES_*")``
    属性读取，对 dict 做 getattr 会静默落空。
    """
    return SimpleNamespace(
        HYPERFRAMES_BROWSER_PATH=_env("HYPERFRAMES_BROWSER_PATH"),
        HYPERFRAMES_FFMPEG_PATH=_env("HYPERFRAMES_FFMPEG_PATH"),
        HYPERFRAMES_FFPROBE_PATH=_env("HYPERFRAMES_FFPROBE_PATH"),
        HYPERFRAMES_CLI_VERSION=_env("HYPERFRAMES_CLI_VERSION") or "0.8.42",
        HYPERFRAMES_CLI_BIN=_env("HYPERFRAMES_CLI_BIN"),
    )


def _render_composition(
    composition_spec: dict, *, output_path: str, settings: Any
) -> str:
    """默认实现：复用服务端渲染器的 CLI 调用（测试会替换本函数）。"""
    from internal.core.video.composition_builder import build_composition_html
    from internal.core.video.hyperframes_renderer import _render as render_impl

    work_dir = Path(output_path).parent
    (work_dir / "index.html").write_text(
        build_composition_html(composition_spec), encoding="utf-8"
    )
    render_impl(
        project_dir=work_dir,
        output_path=Path(output_path),
        settings=settings,
        quality="standard",
        fps=int(composition_spec.get("fps") or 30),
    )
    return str(output_path)


def _cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _run_render(payload: dict[str, Any]) -> dict[str, Any]:
    """执行一次渲染，返回 {ok, path, size_bytes, name} 或 {ok: False, error}。"""
    validation_error = _validate_payload(payload)
    if validation_error is not None:
        return validation_error

    settings = _load_settings()
    missing = [key for key in _REQUIRED_ENV_KEYS if not getattr(settings, key, "")]
    if missing:
        return {
            "ok": False,
            "error": "渲染环境缺少必需配置：" + "、".join(missing),
        }

    composition = payload["composition"]
    name = str(payload.get("name") or "渲染成品").strip() or "渲染成品"
    work_dir = tempfile.mkdtemp(prefix="hf-local-render-")
    try:
        output_path = str(Path(work_dir) / "output.mp4")
        produced = _render_composition(
            composition, output_path=output_path, settings=settings
        )
        artifact = Path(produced)
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            _cleanup_dir(work_dir)
            return {"ok": False, "error": "渲染未产出有效文件"}
    except Exception as exc:  # noqa: BLE001 - worker 边界必须转成 JSON 错误
        logger.warning("本机渲染失败: %s", exc, exc_info=True)
        _cleanup_dir(work_dir)
        return {"ok": False, "error": f"本机渲染失败: {exc}"}

    # 成功：**保留 work_dir**——调用方随后经 `/artifact` 取回产物，
    # 取走后由 `_read_artifact` 清理该目录。
    return {
        "ok": True,
        "path": str(artifact),
        "size_bytes": artifact.stat().st_size,
        "name": name,
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
        if self.path.rstrip("/") != "/render":
            self._json_response({"ok": False, "error": "not found"}, status=404)
            return
        if not _authorized(self.headers.get("Authorization", "")):
            self._json_response({"ok": False, "error": "unauthorized"}, status=401)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self._json_response({"ok": False, "error": "invalid json"}, status=400)
            return
        result = _run_render(payload)
        self._json_response(result)

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local render worker")
    parser.add_argument("--host", default=_env("RENDER_WORKER_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port", type=int, default=int(_env("RENDER_WORKER_PORT", str(DEFAULT_PORT)))
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if not _env("RENDER_WORKER_TOKEN"):
        logger.error("RENDER_WORKER_TOKEN 未配置，拒绝启动")
        raise SystemExit(1)
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    logger.info("Local render worker listening on %s:%s", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
```

- [x] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/scripts/test_render_worker.py -q`
Expected: PASS（8 passed）

- [x] **Step 5: 提交**

```bash
git add api/scripts/render_worker.py api/test/scripts/test_render_worker.py
git commit -m "feat(render): add local render worker with bearer auth"
```

---

## Task 3: 注册 render 子命令到 worker_super

**Files:**
- Modify: `api/scripts/worker_super.py`（`parse_args` 的 `choices` 约 L148；`_SERVICE_SUPPORTS_HOST_PORT` L35；`_module_and_entry` L158-164）
- Test: `api/test/scripts/test_worker_super.py`（追加用例）

- [x] **Step 1: 写失败的测试**

在 `api/test/scripts/test_worker_super.py` 末尾追加：

```python
def test_render_subcommand_is_accepted():
    """render 必须在 choices 白名单内，否则 argparse 直接拒绝。"""
    from scripts.worker_super import parse_args

    args = parse_args(["render", "--port", "8768"])
    assert args.service == "render"
    assert args.port == 8768


def test_render_subcommand_maps_to_render_worker_module():
    """render 必须映射到 scripts.render_worker，否则 KeyError。"""
    from scripts.worker_super import _module_and_entry

    module_name, entry_name = _module_and_entry("render")
    assert module_name == "scripts.render_worker"
    assert entry_name == "main"


def test_render_worker_module_is_importable():
    import importlib

    module = importlib.import_module("scripts.render_worker")
    assert hasattr(module, "main")


def test_render_supports_host_port_injection():
    """render worker 的 main 声明了 --host/--port，须在白名单内。"""
    from scripts.worker_super import _SERVICE_SUPPORTS_HOST_PORT

    assert "render" in _SERVICE_SUPPORTS_HOST_PORT
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/scripts/test_worker_super.py -q -k render`
Expected: FAIL（argparse 报 `invalid choice: 'render'`）

- [x] **Step 3: 实现注册**

在 `api/scripts/worker_super.py` 做三处改动：

**3a. 模块 docstring 的子命令清单**（约 L6-9）改为：

```python
    yujianwo-worker.exe os       --port 8765
    yujianwo-worker.exe browser  --port 8766
    yujianwo-worker.exe computer --port 8767
    yujianwo-worker.exe render   --port 8768
    yujianwo-worker.exe wake
```

**3b. 白名单常量**（L35）：

```python
_SERVICE_SUPPORTS_HOST_PORT = frozenset(("os", "browser", "computer", "render"))
```

**3c. `choices` 与映射表**：

```python
        choices=("os", "browser", "computer", "render", "wake"),
```

```python
def _module_and_entry(service: str) -> tuple[str, str]:
    return {
        "os": ("scripts.os_automation_worker", "main"),
        "browser": ("scripts.browser_automation_worker", "main"),
        "computer": ("scripts.computer_control_worker", "main"),
        "render": ("scripts.render_worker", "main"),
        "wake": ("scripts.wake_word_worker", "main"),
    }[service]
```

- [x] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/scripts/test_worker_super.py -q`
Expected: PASS（含新增 4 例）

- [x] **Step 5: 提交**

```bash
git add api/scripts/worker_super.py api/test/scripts/test_worker_super.py
git commit -m "feat(render): register render subcommand in worker_super"
```

---

## Task 4: PyInstaller 打包登记 render worker

**Files:**
- Modify: `api/scripts/pyinstaller/worker.spec`（`hiddenimports` 约 L43-51）
- Test: `api/test/scripts/test_worker_spec.py`

- [x] **Step 1: 写失败的测试**

创建 `api/test/scripts/test_worker_spec.py`：

```python
"""worker.spec 必须显式登记每个 worker 模块（PyInstaller 不做动态发现）。"""
from pathlib import Path

SPEC = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "pyinstaller"
    / "worker.spec"
)


def test_spec_lists_all_worker_modules():
    text = SPEC.read_text(encoding="utf-8")
    for module in (
        "scripts.os_automation_worker",
        "scripts.browser_automation_worker",
        "scripts.computer_control_worker",
        "scripts.render_worker",
        "scripts.wake_word_worker",
    ):
        assert f"'{module}'" in text, f"{module} 未登记到 hiddenimports"


def test_spec_keeps_cua_driver_client():
    """既有登记不能被误删。"""
    text = SPEC.read_text(encoding="utf-8")
    assert "'scripts.cua_driver_client'" in text
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/scripts/test_worker_spec.py -q`
Expected: FAIL（`scripts.render_worker 未登记到 hiddenimports`）

- [x] **Step 3: 实现登记**

在 `api/scripts/pyinstaller/worker.spec` 的 `hiddenimports` 列表中加入一行（放在 computer 之后、cua_driver_client 之前）：

```python
        'scripts.computer_control_worker',
        # 本机渲染 worker：作为 render 子命令被 worker_super 动态导入
        'scripts.render_worker',
        # cua-driver 后端客户端：computer worker 探测 daemon 后按其路由到后台控制
        'scripts.cua_driver_client',
```

- [x] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/scripts/test_worker_spec.py -q`
Expected: PASS（2 passed）

- [x] **Step 5: 提交**

```bash
git add api/scripts/pyinstaller/worker.spec api/test/scripts/test_worker_spec.py
git commit -m "build(render): register render worker in pyinstaller spec"
```

---

## Task 5: 服务端「调本机渲染 worker」客户端

**Files:**
- Create: `api/internal/core/tools/builtin_tools/providers/video_render_tools/local_render_runner.py`
- Test: `api/test/internal/core/tools/test_local_render_runner.py`

- [x] **Step 1: 写失败的测试**

创建 `api/test/internal/core/tools/test_local_render_runner.py`：

```python
"""服务端侧本机渲染客户端：bridge 解析优先级、产物取回、错误包装。"""
import json

import pytest

from internal.core.tools.builtin_tools.providers.video_render_tools import (
    local_render_runner,
)


def _spec():
    return {
        "composition_id": "main",
        "width": 1920,
        "height": 1080,
        "duration": 10.0,
        "segments": [{"start": 0.0, "duration": 10.0, "text": "hi"}],
    }


def test_returns_not_available_when_no_bridge(monkeypatch):
    """无设备且无静态配置时返回不可用，供上层回退云端。"""
    monkeypatch.setattr(
        local_render_runner, "resolve_desktop_bridge", lambda *a, **k: None
    )
    result = local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )
    assert result["ok"] is False
    assert result["unavailable"] is True


def test_prefers_account_scoped_bridge(monkeypatch):
    calls = []

    def fake_resolve(account_id, *, purpose=""):
        calls.append((account_id, purpose))
        return ("http://host:9876", "bridge-token")

    monkeypatch.setattr(local_render_runner, "resolve_desktop_bridge", fake_resolve)
    monkeypatch.setattr(
        local_render_runner,
        "_post_render",
        lambda **kwargs: {"ok": True, "path": "/tmp/out.mp4", "size_bytes": 10},
    )
    result = local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )

    assert result["ok"] is True
    assert calls == [("acc-1", "/render")]


def test_posts_composition_to_render_route(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        local_render_runner,
        "resolve_desktop_bridge",
        lambda *a, **k: ("http://host:9876", "bridge-token"),
    )

    def fake_post(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "path": "/tmp/out.mp4", "size_bytes": 10}

    monkeypatch.setattr(local_render_runner, "_post_render", fake_post)
    local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )

    assert captured["endpoint"] == "http://host:9876/render"
    assert captured["token"] == "bridge-token"
    assert captured["payload"]["name"] == "demo"
    assert captured["payload"]["composition"]["segments"][0]["text"] == "hi"


def test_worker_error_is_not_unavailable(monkeypatch):
    """worker 明确返回失败 ≠ 通道不可用：不应触发云端回退。"""
    monkeypatch.setattr(
        local_render_runner,
        "resolve_desktop_bridge",
        lambda *a, **k: ("http://host:9876", "bridge-token"),
    )
    monkeypatch.setattr(
        local_render_runner,
        "_post_render",
        lambda **kwargs: {"ok": False, "error": "渲染环境缺少必需配置：HYPERFRAMES_BROWSER_PATH"},
    )
    result = local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )
    assert result["ok"] is False
    assert result.get("unavailable") is not True
    assert "HYPERFRAMES" in result["error"]


def test_connection_failure_is_unavailable(monkeypatch):
    """连不上桌面 bridge 视为通道不可用，允许回退云端。"""
    monkeypatch.setattr(
        local_render_runner,
        "resolve_desktop_bridge",
        lambda *a, **k: ("http://host:9876", "bridge-token"),
    )

    def boom(**kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(local_render_runner, "_post_render", boom)
    result = local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )
    assert result["ok"] is False
    assert result["unavailable"] is True
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/tools/test_local_render_runner.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [x] **Step 3: 实现客户端**

创建 `api/internal/core/tools/builtin_tools/providers/video_render_tools/local_render_runner.py`：

```python
"""在用户本机执行渲染（经桌面 bridge）。

服务端不直接跑 Node/Chromium，而是把脚本下发到用户设备上的 render worker
（`scripts/render_worker.py`），由用户机器的 CPU 出片——把重负载算力外部化。

通道解析**必须**走 `resolve_desktop_bridge`（按账号动态解析已注册设备），
不可只读静态 env：桌面端 token 每次启动随机生成，静态配置对不上（这是
`browser_action` 的已知断链，勿重蹈）。

语义区分（决定是否回退云端）：
- `unavailable=True` —— 通道本身不可用（无注册设备 / 连不上 bridge）。
  上层可据此回退云端渲染。
- `ok=False` 且无 `unavailable` —— 通道可用但渲染失败（环境缺二进制、
  脚本非法等）。属业务失败，**不回退**，直接报错给用户。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from internal.service.desktop_bridge_resolver import resolve_desktop_bridge

logger = logging.getLogger(__name__)

__all__ = ["render_on_local_device"]

# 渲染是分钟级长任务，超时必须显著大于服务端 CLI 超时（RENDER_TIMEOUT_SEC，默认 1800s）
_LOCAL_RENDER_TIMEOUT_SEC = 1900


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _post_render(*, endpoint: str, token: str, payload: dict) -> dict:
    """POST 到本机 render worker，返回解析后的 JSON。"""
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=_LOCAL_RENDER_TIMEOUT_SEC) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def render_on_local_device(
    *, composition: dict, account_id: Any, name: str = ""
) -> dict[str, Any]:
    """在用户本机渲染；返回 {ok, path, size_bytes, name} 或错误。

    失败时若为「通道不可用」，额外带 `unavailable=True` 供上层决定是否回退云端。
    """
    resolved = resolve_desktop_bridge(account_id, purpose="/render")
    if not resolved:
        return {
            "ok": False,
            "unavailable": True,
            "error": "未找到可用的桌面设备（当前账号未注册在线设备），且未配置静态桌面桥",
        }

    bridge_url, bridge_token = resolved
    endpoint = _normalize_text(bridge_url).rstrip("/") + "/render"
    payload = {"composition": composition, "name": _normalize_text(name)}

    try:
        result = _post_render(endpoint=endpoint, token=bridge_token, payload=payload)
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            error_payload = {"error": str(exc)}
        # 401/502 属通道问题（bridge 鉴权失败 / worker 不在），可回退
        if exc.code in {401, 502, 503, 504}:
            return {
                "ok": False,
                "unavailable": True,
                "error": f"本机渲染通道不可用（HTTP {exc.code}）：{error_payload.get('error', '')}",
            }
        return {"ok": False, "error": error_payload.get("error", str(exc))}
    except Exception as exc:  # noqa: BLE001 - 网络层失败统一按通道不可用处理
        logger.info("调用本机渲染 worker 失败（按通道不可用处理）: %s", exc)
        return {
            "ok": False,
            "unavailable": True,
            "error": f"无法连接本机渲染服务：{exc}",
        }

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "本机渲染失败"}

    return {
        "ok": True,
        "path": result.get("path", ""),
        "size_bytes": int(result.get("size_bytes") or 0),
        "name": result.get("name") or name or "渲染成品",
    }
```

- [x] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/tools/test_local_render_runner.py -q`
Expected: PASS（5 passed）

- [x] **Step 5: 提交**

```bash
git add api/internal/core/tools/builtin_tools/providers/video_render_tools/local_render_runner.py api/test/internal/core/tools/test_local_render_runner.py
git commit -m "feat(render): add service-side local render client via desktop bridge"
```

---

## Task 6: render_video 三级路由（本机 → 云端 → 报错）

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/video_render_tools/render_video.py`（`_dispatch_render` L45-70；`_run` L102-144）
- Test: `api/test/internal/core/tools/test_render_video_tool.py`（追加用例）

- [x] **Step 1: 写失败的测试**

> ⚠️ **同时必须改既有测试的替身装配**：`api/test/internal/core/tools/test_render_video_tool.py`
> 现有的 `_install_fakes()`（L47-84）没有关掉本机开关。改动后本机分支会**先被命中**，
> 导致既有 3 个云端用例（`test_dispatch_prefers_celery` /
> `test_dispatch_does_not_fall_back_to_sync_when_celery_unavailable` /
> `test_dispatch_rejects_when_guard_denies`）失去意义或失败。
> 在该 helper 的 `module = importlib.import_module(...)` 之后追加两行：
>
> ```python
>     # 既有用例聚焦云端链路：显式关掉本机渲染，避免命中本机分支
>     monkeypatch.setattr(module, "_local_enabled", lambda: False)
>     monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)
> ```

在本文件末尾追加：

```python
def test_prefers_local_device_over_cloud(monkeypatch):
    """本机可用时不应派发 Celery——这是成本外部化的核心断言。"""
    from internal.core.tools.builtin_tools.providers.video_render_tools import (
        render_video as module,
    )

    monkeypatch.setattr(module, "_local_enabled", lambda: True)
    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_run_local_render",
        lambda **kwargs: {"ok": True, "path": "/tmp/x.mp4", "size_bytes": 1},
    )

    def cloud_should_not_run(**kwargs):
        raise AssertionError("本机可用时不应派发云端 Celery")

    monkeypatch.setattr(module, "_dispatch_cloud_render", cloud_should_not_run)

    result = module._dispatch_render({"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo")
    assert result["mode"] == "local"


def test_falls_back_to_cloud_when_local_unavailable(monkeypatch):
    from internal.core.tools.builtin_tools.providers.video_render_tools import (
        render_video as module,
    )

    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_run_local_render",
        lambda **kwargs: {"ok": False, "unavailable": True, "error": "无设备"},
    )
    monkeypatch.setattr(
        module,
        "_dispatch_cloud_render",
        lambda **kwargs: {"mode": "celery", "result": type("R", (), {"id": "t1"})()},
    )

    result = module._dispatch_render({"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo")
    assert result["mode"] == "celery"


def test_local_business_failure_does_not_fall_back(monkeypatch):
    """本机渲染业务失败（非通道问题）应直接报错，不静默回退云端。"""
    import pytest

    from internal.core.tools.builtin_tools.providers.video_render_tools import (
        render_video as module,
    )

    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_run_local_render",
        lambda **kwargs: {"ok": False, "error": "渲染环境缺少必需配置"},
    )

    def cloud_should_not_run(**kwargs):
        raise AssertionError("业务失败不应回退云端")

    monkeypatch.setattr(module, "_dispatch_cloud_render", cloud_should_not_run)

    with pytest.raises(module.RenderExecutionError):
        module._dispatch_render(
            {"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo"
        )


def test_local_disabled_goes_straight_to_cloud(monkeypatch):
    from internal.core.tools.builtin_tools.providers.video_render_tools import (
        render_video as module,
    )

    monkeypatch.setattr(module, "_local_enabled", lambda: False)
    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_dispatch_cloud_render",
        lambda **kwargs: {"mode": "celery", "result": type("R", (), {"id": "t1"})()},
    )

    result = module._dispatch_render({"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo")
    assert result["mode"] == "celery"


def test_cloud_disabled_and_no_device_raises_clear_error(monkeypatch):
    import pytest

    from internal.core.tools.builtin_tools.providers.video_render_tools import (
        render_video as module,
    )

    monkeypatch.setattr(module, "_local_enabled", lambda: True)
    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: False)
    monkeypatch.setattr(
        module,
        "_run_local_render",
        lambda **kwargs: {"ok": False, "unavailable": True, "error": "无设备"},
    )

    with pytest.raises(module.RenderExecutionError) as exc:
        module._dispatch_render(
            {"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo"
        )
    assert "桌面端" in str(exc.value) or "本机" in str(exc.value)
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/tools/test_render_video_tool.py -q -k "local or cloud or falls_back"`
Expected: FAIL（`AttributeError: module has no attribute '_cloud_fallback_enabled'`）

- [x] **Step 3: 实现三级路由**

修改 `api/internal/core/tools/builtin_tools/providers/video_render_tools/render_video.py`：

**3a. 模块 docstring 更新**（把「必须走 Celery」改为三级路由说明）：

```python
"""渲染视频工具（对话内出片）。

小钰把编排好的视频脚本交给渲染链路：编译为 HyperFrames composition →
渲染为 MP4 → 自动存入用户的成品库（系统预置、每用户唯一）。

**执行位置（三级路由）**：
1. **用户本机优先**：经桌面 bridge 下发到用户设备上的 render worker，
   吃用户自己的 CPU——把重负载算力外部化，平台服务器只处理轻量内容；
2. **云端回退**：本机通道不可用时，派发 Celery `render` 队列（受
   `RENDER_CLOUD_FALLBACK_ENABLED` 控制，云端链路完整保留、可随时接通）；
3. **明确报错**：两者都不可用时返回可读错误。

注意「通道不可用」与「渲染业务失败」的区别：前者才回退云端，后者直接报错
（详见 local_render_runner 的语义说明）。

account 获取方式与 create_knowledge_base 一致：由运行时挂载点通过工厂参数
account_id 注入当前账号。builtin 工具没有全局 g.account，不做上下文穿透。
"""
```

**3b. 新增开关与封装函数**（插在 `_load_render_guard` 之后）：

```python
def _local_enabled() -> bool:
    """本机渲染是否启用（默认启用）。

    注意：容器 config 是**普通 dict**（不是 Flask 那种带 ``__getattr__`` 的子类），
    必须用 ``.get()`` 读取；用 ``getattr`` 会静默取到默认值、开关形同虚设。
    """
    from internal.context import current_app

    return bool(current_app.config.get("RENDER_LOCAL_ENABLED", True))


def _cloud_fallback_enabled() -> bool:
    """云端回退是否启用（默认启用）。"""
    from internal.context import current_app

    return bool(current_app.config.get("RENDER_CLOUD_FALLBACK_ENABLED", True))


def _run_local_render(*, composition: dict, account_id: str, name: str) -> dict:
    from internal.core.tools.builtin_tools.providers.video_render_tools.local_render_runner import (
        render_on_local_device,
    )

    return render_on_local_device(
        composition=composition, account_id=account_id, name=name
    )


def _dispatch_cloud_render(*, composition: dict, account_id: str, name: str) -> dict:
    """派发云端 Celery（原 _dispatch_render 的逻辑原样保留）。"""
    from internal.task.render_tasks import render_composition_task

    fingerprint = _composition_fingerprint(composition)
    guard = _load_render_guard()

    admission = guard.admit(account_id=account_id, fingerprint=fingerprint)
    if not admission.allowed:
        logger.info("渲染被闸门拒绝 account_id=%s reason=%s", account_id, admission.reason)
        raise RenderRejectedError(admission.reason)

    try:
        async_result = render_composition_task.delay(composition, account_id, name)
    except Exception:
        guard.release(account_id=account_id, fingerprint=fingerprint)
        logger.warning("渲染派发 Celery 失败 account_id=%s", account_id, exc_info=True)
        raise

    guard.mark_enqueued()
    return {"mode": "celery", "result": async_result, "fingerprint": fingerprint}
```

**3c. 新增异常类**（紧邻 `RenderRejectedError`）：

```python
class RenderExecutionError(Exception):
    """渲染执行失败（本机与云端均不可用，或本机业务失败），消息可直接展示。"""
```

**3d. `_dispatch_render` 改为编排三级路由**（整体替换原函数）：

```python
def _dispatch_render(composition: dict, account_id: str, name: str) -> dict:
    """三级路由：本机优先 → 云端回退 → 明确报错。"""
    local_attempted = False
    if _local_enabled():
        local_attempted = True
        local_result = _run_local_render(
            composition=composition, account_id=account_id, name=name
        )
        if local_result.get("ok"):
            return {
                "mode": "local",
                "result": local_result,
                "size_bytes": local_result.get("size_bytes", 0),
            }
        if not local_result.get("unavailable"):
            # 通道可用但业务失败：不回退，直接报错
            raise RenderExecutionError(
                local_result.get("error") or "本机渲染失败"
            )
        logger.info(
            "本机渲染通道不可用，尝试云端回退 account_id=%s reason=%s",
            account_id,
            local_result.get("error"),
        )
        local_error = local_result.get("error") or "本机渲染通道不可用"

    if _cloud_fallback_enabled():
        return _dispatch_cloud_render(
            composition=composition, account_id=account_id, name=name
        )

    if local_attempted:
        raise RenderExecutionError(
            f"本机渲染不可用（{local_error}），且云端渲染回退已关闭。"
            "请启动桌面客户端后重试。"
        )
    raise RenderExecutionError("渲染不可用：本机渲染未启用且云端回退已关闭。")
```

**3e. `_run` 的异常分支补充 `RenderExecutionError`**（把原有 `except RenderRejectedError` 分支改为同时捕获两者）：

```python
        try:
            dispatched = _dispatch_render(composition, account_id, normalized_name)
        except (RenderRejectedError, RenderExecutionError) as exc:
            # 闸门拒绝 / 执行不可用：提示面向用户可直接展示，不当作系统故障
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        except Exception as exc:
            logger.warning("渲染视频失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {
                    "ok": False,
                    "error": f"渲染视频失败：{exc}（渲染服务暂不可用，请稍后重试）",
                },
                ensure_ascii=False,
            )
```

**3f. 成功返回分支兼容本机模式**（把原返回体改为按 mode 区分）：

```python
        if dispatched.get("mode") == "local":
            return json.dumps(
                {
                    "ok": True,
                    "mode": "local",
                    "message": "视频已在你的电脑上渲染完成，正在存入成品库",
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(dispatched["result"], "id", "")),
                "message": "视频渲染已提交后台处理，完成后会自动存入成品库",
            },
            ensure_ascii=False,
        )
```

> **实现提示**：本机模式下「出片 → 入库」需在本机上产出 MP4 后再走服务端
> `store_render_output`。因用户设备无法直写服务端对象存储，本任务先打通「能出片」，
> 入库回传在 Task 7 完成（届时用 bridge 的 `/upload` 或服务端拉取本机路径）。

- [x] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/tools/test_render_video_tool.py -q`
Expected: PASS（含新增 5 例）

- [x] **Step 5: 提交**

```bash
git add api/internal/core/tools/builtin_tools/providers/video_render_tools/render_video.py api/test/internal/core/tools/test_render_video_tool.py
git commit -m "feat(render): route render to local device first, cloud as fallback"
```

---

## Task 7: 本机产物回传服务端入库

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/video_render_tools/local_render_runner.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/video_render_tools/render_video.py`
- Test: `api/test/internal/core/tools/test_local_render_runner.py`（追加用例）

**背景**：本机上出片的 MP4 落在用户设备临时目录，必须回传服务端才能入库（对象存储 + 成品库建档 + 索引）。这是本方案**唯一必须新增的服务端能力**，其余全部复用。

- [x] **Step 1: 写失败的测试**

在 `api/test/internal/core/tools/test_local_render_runner.py` 末尾追加：

```python
def test_fetch_artifact_returns_bytes_and_name(monkeypatch):
    """从本机 worker 取回产物字节（经 bridge /artifact 路由）。"""
    monkeypatch.setattr(
        local_render_runner,
        "resolve_desktop_bridge",
        lambda *a, **k: ("http://host:9876", "bridge-token"),
    )
    monkeypatch.setattr(
        local_render_runner,
        "_post_artifact",
        lambda **kwargs: {"ok": True, "name": "demo.mp4", "content_base64": "RkFLRQ=="},
    )

    result = local_render_runner.fetch_local_artifact(
        account_id="acc-1", artifact_path="/tmp/x.mp4"
    )
    assert result["ok"] is True
    assert result["name"] == "demo.mp4"
    assert result["content"] == b"FAKE"


def test_fetch_artifact_unavailable_when_no_bridge(monkeypatch):
    monkeypatch.setattr(
        local_render_runner, "resolve_desktop_bridge", lambda *a, **k: None
    )
    result = local_render_runner.fetch_local_artifact(
        account_id="acc-1", artifact_path="/tmp/x.mp4"
    )
    assert result["ok"] is False
    assert result["unavailable"] is True
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/tools/test_local_render_runner.py -q -k fetch_artifact`
Expected: FAIL（`AttributeError: module has no attribute 'fetch_local_artifact'`）

- [x] **Step 3: 实现产物取回**

在 `local_render_runner.py` 追加：

```python
import base64

__all__ = ["render_on_local_device", "fetch_local_artifact"]

_ARTIFACT_TIMEOUT_SEC = 300


def _post_artifact(*, endpoint: str, token: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=_ARTIFACT_TIMEOUT_SEC) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def fetch_local_artifact(*, account_id: Any, artifact_path: str) -> dict[str, Any]:
    """取回本机渲染产物字节（经 bridge `/artifact` 路由）。

    约定：bridge 侧实现 `/artifact` → render worker 的 `POST /artifact`，
    入参 {"path": ...}，返回 {"ok": True, "name": ..., "content_base64": ...}。
    """
    resolved = resolve_desktop_bridge(account_id, purpose="/artifact")
    if not resolved:
        return {
            "ok": False,
            "unavailable": True,
            "error": "未找到可用的桌面设备，无法取回本机渲染产物",
        }

    bridge_url, bridge_token = resolved
    endpoint = _normalize_text(bridge_url).rstrip("/") + "/artifact"
    try:
        result = _post_artifact(
            endpoint=endpoint,
            token=bridge_token,
            payload={"path": _normalize_text(artifact_path)},
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "unavailable": True,
            "error": f"取回本机渲染产物失败：{exc}",
        }

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "取回产物失败"}
    try:
        content = base64.b64decode(result.get("content_base64") or "")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"产物解码失败：{exc}"}
    return {
        "ok": True,
        "name": result.get("name") or "render-output.mp4",
        "content": content,
    }
```

在 `api/scripts/render_worker.py` 的 `_Handler.do_POST` 中增加 `/artifact` 分支（同文件内实现读取）：

```python
    def do_POST(self):  # noqa: N802
        route = self.path.rstrip("/")
        if route not in {"/render", "/artifact"}:
            self._json_response({"ok": False, "error": "not found"}, status=404)
            return
        if not _authorized(self.headers.get("Authorization", "")):
            self._json_response({"ok": False, "error": "unauthorized"}, status=401)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self._json_response({"ok": False, "error": "invalid json"}, status=400)
            return

        if route == "/artifact":
            self._json_response(_read_artifact(payload))
            return
        self._json_response(_run_render(payload))
```

并在 `render_worker.py` 增加：

```python
import base64
import re

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _read_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    """读取本机渲染产物（仅限渲染临时目录，防止任意路径读取）。

    安全边界：产物路径必须位于系统临时目录下且前缀为 hf-local-render-，
    否则拒绝——避免该端点被用作任意文件读取。
    """
    raw_path = str(payload.get("path") or "").strip()
    if not raw_path:
        return {"ok": False, "error": "path 不能为空"}
    artifact = Path(raw_path).resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if not str(artifact).startswith(str(tmp_root)) or "hf-local-render-" not in str(artifact):
        return {"ok": False, "error": "产物路径不在允许范围内"}
    if not artifact.is_file():
        return {"ok": False, "error": "产物不存在或已被清理"}
    safe_name = _SAFE_NAME_RE.sub("_", artifact.name) or "render-output.mp4"
    with open(artifact, "rb") as fh:
        content = fh.read()
    # 产物已取走，清理渲染临时目录，避免用户设备上残留
    _cleanup_dir(str(artifact.parent))
    return {
        "ok": True,
        "name": safe_name,
        "size_bytes": len(content),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
```

- [x] **Step 4: 接入入库（在 render_video 本机成功分支后）**

修改 `render_video.py` 的本机成功分支，取回产物并入库：

```python
        if dispatched.get("mode") == "local":
            ingest = _ingest_local_artifact(
                account_id=account_id,
                artifact_path=dispatched["result"].get("path", ""),
                name=dispatched["result"].get("name") or normalized_name,
            )
            if not ingest.get("ok"):
                return json.dumps(
                    {"ok": False, "error": ingest.get("error") or "成品入库失败"},
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "ok": True,
                    "mode": "local",
                    "document_id": ingest.get("document_id", ""),
                    "message": "视频已在你的电脑上渲染完成并存入成品库",
                },
                ensure_ascii=False,
            )
```

并新增：

```python
def _ingest_local_artifact(*, account_id: str, artifact_path: str, name: str) -> dict:
    """取回本机产物并写入成品库（复用既有 store_render_output）。"""
    from internal.core.tools.builtin_tools.providers.video_render_tools.local_render_runner import (
        fetch_local_artifact,
    )

    fetched = fetch_local_artifact(account_id=account_id, artifact_path=artifact_path)
    if not fetched.get("ok"):
        return {"ok": False, "error": fetched.get("error") or "取回本机产物失败"}

    import tempfile
    from pathlib import Path

    from app.http.module import injector
    from internal.service.account_service import AccountService
    from internal.service.knowledge_base_service import KnowledgeBaseService

    account = injector.get(AccountService).get_account(UUID(str(account_id)))
    if account is None:
        return {"ok": False, "error": f"账号不存在：{account_id}"}

    tmp_dir = Path(tempfile.mkdtemp(prefix="hf-ingest-"))
    try:
        video_path = tmp_dir / (fetched.get("name") or "render-output.mp4")
        video_path.write_bytes(fetched["content"])
        document = injector.get(KnowledgeBaseService).store_render_output(
            account=account, video_path=video_path, name=name or "渲染成品"
        )
        return {"ok": True, "document_id": str(document.id)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("本机渲染产物入库失败 account_id=%s", account_id, exc_info=True)
        return {"ok": False, "error": f"成品入库失败：{exc}"}
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)
```

`render_video.py` 顶部已有 `import logging`（L19）与 `from uuid import UUID`（L21），无需重复导入。

- [x] **Step 5: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/tools/test_local_render_runner.py test/internal/core/tools/test_render_video_tool.py -q`
Expected: PASS

- [x] **Step 6: 提交**

```bash
git add api/internal/core/tools/builtin_tools/providers/video_render_tools/ api/scripts/render_worker.py api/test/internal/core/tools/
git commit -m "feat(render): ingest local render artifact into render-output library"
```

---

## Task 8: 桌面端接线（bridge 路由 + worker 托管）

**Files:**
- Modify: `desktop/bridge.js`（`targets` L5-31）
- Modify: `desktop/main.js`（`tokens` L424-430、端口探测 L435-449、`startWorker` L451-472、`createBridge` L474-489）
- Test: `desktop/test/bridge.test.js`（追加用例）

- [x] **Step 1: 写失败的测试**

在 `desktop/test/bridge.test.js` 末尾追加（**照抄该文件既有的 `stubWorker` 辅助函数用法**，不要新造函数）：

```javascript
test('bridge forwards /render to render worker with worker token', async () => {
  let seen = null
  const { server, port } = await stubWorker('{}', (call) => {
    seen = call
  })
  const bridge = createBridge({
    token: 'secret',
    renderPort: port,
    renderToken: 'render-token',
  })
  const bridgePort = await listen(bridge)
  try {
    const result = await request(bridgePort, '/render', 'secret')
    assert.equal(result.status, 200)
    assert.ok(seen, '请求应被转发到 render worker')
    assert.equal(seen.path, '/render')
    assert.equal(seen.authorization, 'Bearer render-token')
  } finally {
    bridge.close()
    server.close()
  }
})

test('bridge forwards /artifact to render worker with worker token', async () => {
  let seen = null
  const { server, port } = await stubWorker('{}', (call) => {
    seen = call
  })
  const bridge = createBridge({
    token: 'secret',
    renderPort: port,
    renderToken: 'render-token',
  })
  const bridgePort = await listen(bridge)
  try {
    const result = await request(bridgePort, '/artifact', 'secret')
    assert.equal(result.status, 200)
    assert.ok(seen, '请求应被转发到 render worker')
    assert.equal(seen.path, '/artifact')
    assert.equal(seen.authorization, 'Bearer render-token')
  } finally {
    bridge.close()
    server.close()
  }
})
```

> 参照物：同文件 L82-104 的 `/file` 用例（`stubWorker` + `createBridge` + 断言上游 `authorization`）。`stubWorker` 定义在 L63-80，`listen` 在 L6-10，`request` 在 L12-22。

- [x] **Step 2: 运行测试确认失败**

Run: `cd desktop && node --test test/bridge.test.js`
Expected: FAIL（`/render` 返回 404）

- [x] **Step 3: 实现 bridge 路由**

在 `desktop/bridge.js` 的 `targets` 对象中，`/control` 之后追加：

```javascript
    '/render': {
      port: Number(options.renderPort || process.env.RENDER_WORKER_PORT || 8768),
      token: options.renderToken || process.env.RENDER_WORKER_TOKEN || '',
      path: '/render',
    },
    '/artifact': {
      port: Number(options.renderPort || process.env.RENDER_WORKER_PORT || 8768),
      token: options.renderToken || process.env.RENDER_WORKER_TOKEN || '',
      path: '/artifact',
    },
```

- [x] **Step 4: 实现 main.js 托管**

**4a. token 增加 render**（L424-430）：

```javascript
  const tokens = {
    os: randomToken(),
    browser: randomToken(),
    computer: randomToken(),
    render: randomToken(),
    wake: randomToken(),
    bridge: randomToken(),
  }
```

**4b. 端口探测**（L435-449，加在 computerPort 之后，注意互相排除）：

```javascript
  const preferRenderPort = Number(process.env.RENDER_WORKER_PORT || 8768)
  const renderPort = await probePort(preferRenderPort, 50, new Set([osPort, browserPort, computerPort]))
  if (renderPort !== preferRenderPort) {
    console.log(`[desktop] render worker 端口 ${preferRenderPort} 被占用，改用 ${renderPort}`)
  }
```

**4c. 启动 worker**（L451-472，加在 computer 之后）：

先用 `render-runtime.js` 解析运行时并生成 shim，再启动：
（需在文件顶部 `const path = require('node:path')` 已有则复用）

```javascript
  // 渲染运行时：Node 用 Electron 内置的（经 shim 包装），Chromium/ffmpeg/ffprobe
  // 随安装包分发（resources/render-runtime/，见 §0.5.2）。缺失时 worker 返回可读错误而非崩溃。
  const { resolveRuntimePaths, ensureCliShim } = require('./render-runtime')
  const runtime = resolveRuntimePaths({
    env: process.env,
    resourcesDir: process.resourcesPath,
  })
  const shimDir = path.join(app.getPath('userData'), 'render-runtime-bin')
  const cliShim = ensureCliShim({
    electronPath: process.execPath,          // 必须原地引用，不可拷贝单文件
    cliJsPath: runtime.cliJsPath,
    targetDir: shimDir,
  })

  startWorker('render', {
    RENDER_WORKER_TOKEN: tokens.render,
    RENDER_WORKER_PORT: String(renderPort),
    HYPERFRAMES_CLI_BIN: cliShim,
    HYPERFRAMES_BROWSER_PATH: runtime.browserPath,
    HYPERFRAMES_FFMPEG_PATH: runtime.ffmpegPath,
    HYPERFRAMES_FFPROBE_PATH: runtime.ffprobePath,
  })
```

**4d. createBridge 参数**（L474-489）：

```javascript
    renderPort,
    renderToken: tokens.render,
```

**4e. ⚠️ 打包白名单登记（必做，否则安装版崩而开发环境正常）**

`desktop/package.json` 的 `build.files` 是**显式白名单**，未登记的文件不会进入安装包。
若新增 `render-runtime.js`（Task 8 之外的模块）必须一并登记，否则出现
「`npm start` 正常、安装版启动报 `Cannot find module`」——这是 Electron 项目高发的
打包遗漏。检查当前白名单内容并补充：

```json
  "files": [
    "main.js",
    "preload.js",
    "server-config.js",
    "credential-store.js",
    "device-registry.js",
    "cua-driver-host.js",
    "bridge.js",
    "tray.js",
    "updater.js",
    "window-state.js",
    "render-runtime.js"
  ],
```

> 若本任务未新建 `render-runtime.js`，则此处无需改动；**只要新增了任何 `.js` 模块就必须加**。
> 同时注意 `extraResources` 是否需登记随包内置的 ffmpeg/ffprobe（见 §0.5.2 第 2 级策略）。

- [x] **Step 5: 运行测试确认通过**

Run: `cd desktop && node --test test/bridge.test.js`
Expected: PASS

- [x] **Step 6: 提交**

```bash
git add desktop/bridge.js desktop/main.js desktop/package.json desktop/test/bridge.test.js
git commit -m "feat(desktop): host render worker and expose /render bridge route"
```

---

## Task 9: 云端渲染默认关闭（保留可接通路径）

**Files:**
- Modify: `docker/docker-compose.yaml`（`llmops-render-worker` 服务，约 L120-169）
- Modify: `api/.env.example`（渲染段）
- Test: `api/test/deploy/test_render_worker_profile.py`

- [x] **Step 1: 写失败的测试**

创建 `api/test/deploy/test_render_worker_profile.py`：

```python
"""云端 render worker 必须「保留但默认不启动」——可随时接通。"""
from pathlib import Path

COMPOSE = (
    Path(__file__).resolve().parents[3] / "docker" / "docker-compose.yaml"
)


def _render_service_block() -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    start = text.index("llmops-render-worker:")
    # 到下一个顶层服务定义（两个空格 + 非空字符）为止
    rest = text[start:]
    lines = rest.splitlines()
    block = [lines[0]]
    for line in lines[1:]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        block.append(line)
    return "\n".join(block)


def test_render_worker_has_profile_so_it_can_be_re_enabled():
    """用 profile 下线：docker compose --profile cloud-render up -d llmops-render-worker"""
    block = _render_service_block()
    assert "cloud-render" in block, "云端渲染未用 profile 下线，无法保留可接通路径"


def test_render_worker_definition_is_retained():
    """服务定义整体保留，不删除——这是「未来可随时接通」的前提。"""
    text = COMPOSE.read_text(encoding="utf-8")
    assert "llmops-render-worker:" in text
    assert "CELERY_QUEUES: render" in text


def test_render_worker_keeps_resource_limits():
    """离线不等于删除限流：重新启用时仍受内存限额保护。"""
    block = _render_service_block()
    assert "memory: 2800M" in block
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/deploy/test_render_worker_profile.py -q`
Expected: FAIL（`云端渲染未用 profile 下线`）

- [x] **Step 3: 实现下线（保留定义）**

在 `docker/docker-compose.yaml` 的 `llmops-render-worker` 服务内，`container_name` 之后加注释与 profile：

```yaml
    container_name: llmops-render-worker
    # 【默认关闭】渲染已下放到用户本机（桌面端 render worker），云端不再常驻，
    # 以节省服务器算力成本。服务定义与全部限流参数**完整保留**，需要时一键接通：
    #   docker compose --profile cloud-render up -d llmops-render-worker
    # 配合 api/.env 的 RENDER_CLOUD_FALLBACK_ENABLED=true 即恢复云端渲染路径。
    profiles: ["cloud-render"]
```

在 `api/.env.example` 渲染段追加：

```dotenv
# 渲染执行目标：本机优先（桌面端 render worker），本机不可用时是否回退云端
RENDER_LOCAL_ENABLED=true
RENDER_CLOUD_FALLBACK_ENABLED=true
```

- [x] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/deploy/test_render_worker_profile.py -q`
Expected: PASS（3 passed）

- [x] **Step 5: 验证 compose 默认清单不含 render worker**

Run: `cd docker && docker compose config --services`
Expected: 输出**不含** `llmops-render-worker`（默认已下线）

Run: `cd docker && docker compose --profile cloud-render config --services`
Expected: 输出**含** `llmops-render-worker`（可随时接通）

- [x] **Step 6: 提交**

```bash
git add docker/docker-compose.yaml api/.env.example api/test/deploy/test_render_worker_profile.py
git commit -m "chore(render): disable cloud render worker by default, keep it re-enablable"
```

---

## Task 10: 文档同步

**Files:**
- Modify: `docs/prd/modules/09-desktop-client.md`
- Modify: `docs/prd/modules/08-os-automation.md`
- Modify: `docs/deployment-single-node.md`
- Modify: `desktop/README.md`
- Modify: `docs/README.md`（若新增顶层文档才需登记；本任务不新增，故不改）

- [x] **Step 1: 更新桌面端模块文档**

在 `docs/prd/modules/09-desktop-client.md` 的 worker 清单处，把子命令从 `os|browser|computer|wake` 更新为 `os|browser|computer|render|wake`，并补一段：

```markdown
### render worker（本机出片）

- **子命令**：`yujianwo-worker.exe render --port 8768`
- **职责**：在本机执行 HyperFrames 渲染（Node + Chromium + ffmpeg），把重负载算力
  从平台服务器转移到用户设备；平台服务器只处理轻量内容，成本可控。
- **桥路由**：`/render`（出片）、`/artifact`（取回产物字节）
- **硬依赖**：`HYPERFRAMES_BROWSER_PATH` / `HYPERFRAMES_FFMPEG_PATH` /
  `HYPERFRAMES_FFPROBE_PATH`，缺一即返回可读错误。**浏览器必须是能响应 `--version`
  的构建（chrome-headless-shell）**，Electron 自带 chrome.exe 不可替代。
- **回传**：产物在用户设备临时目录，服务端经 `/artifact` 取回后复用
  `KnowledgeBaseService.store_render_output` 入库。
```

- [x] **Step 2: 更新 08-os-automation 的桥路由表**

在 `docs/prd/modules/08-os-automation.md` 的桥路由表中补 `/render` 与 `/artifact` 两行（指向 render worker:8768），并注明「服务端工具经 `resolve_desktop_bridge` 解析，勿只读静态 env」。

- [x] **Step 3: 更新部署文档**

在 `docs/deployment-single-node.md` 的渲染段补一节：

```markdown
### 渲染执行位置（本机优先，云端保留）

渲染默认在**用户本机**执行（桌面端 render worker），云端 `llmops-render-worker`
**默认不启动**（`profiles: ["cloud-render"]`），以节省服务器算力。

| 场景 | 执行位置 | 说明 |
| --- | --- | --- |
| 已装桌面端 | 用户本机 | 首选；吃用户 CPU |
| 未装桌面端 / 本机不可用 | 云端 `render` 队列 | 需 `RENDER_CLOUD_FALLBACK_ENABLED=true`（默认开） |

**云端渲染未删除**，可随时接通：
```bash
docker compose --profile cloud-render up -d llmops-render-worker
```
```

- [x] **Step 4: 更新 desktop/README.md**

在 worker 清单与桥路由表处补 render worker 与 `/render`、`/artifact`。

- [x] **Step 5: 提交**

```bash
git add docs/prd/modules/09-desktop-client.md docs/prd/modules/08-os-automation.md docs/deployment-single-node.md desktop/README.md
git commit -m "docs(render): document local-first render with cloud path retained"
```

---

## Task 11: 接线审查与全量回归

**Files:**（无代码改动，仅验证）

- [x] **Step 1: 逐个新符号点名入口（AGENTS.md 强制要求）**

对照下表逐项确认，任一项找不到调用方即为断链：

| 新符号 | 必须存在的入口 | 复核命令 |
| --- | --- | --- |
| `scripts/render_worker.main` | `worker_super._module_and_entry("render")` | `python -m pytest test/scripts/test_worker_super.py -q -k render` |
| `scripts.render_worker` | `worker.spec` hiddenimports | `python -m pytest test/scripts/test_worker_spec.py -q` |
| `desktop /render 路由` | `bridge.js targets` + `main.js renderPort/renderToken` | `cd desktop && node --test` |
| `desktop /artifact 路由` | `bridge.js targets` + `local_render_runner.fetch_local_artifact` | 同上 |
| `render-runtime.ensureCliShim` | `main.js` 的 `startWorker('render', {HYPERFRAMES_CLI_BIN: cliShim})` | `cd desktop && node --test test/render-runtime.test.js` |
| `render-runtime.resolveRuntimePaths` | 同上（提供 browser/ffmpeg/ffprobe 三路径） | 同上 |
| `electron 内置 Node 24` | `main.js` 用 `process.execPath` 作 shim 的 node | `cd desktop && node --test test/electron-version.test.js` |
| `render-runtime.js` 打包登记 | `package.json` 的 `build.files` 数组 | 目视核对（缺则安装版崩） |
| `local_render_runner.render_on_local_device` | `render_video._run_local_render` | `python -m pytest test/internal/core/tools/test_render_video_tool.py -q` |
| `local_render_runner.fetch_local_artifact` | `render_video._ingest_local_artifact` | 同上 |
| `Config.RENDER_LOCAL_ENABLED` | `render_video._local_enabled()` | `python -m pytest test/config/test_render_execution_config.py -q` |
| `Config.RENDER_CLOUD_FALLBACK_ENABLED` | `render_video._cloud_fallback_enabled()` | 同上 |
| `cloud-render` profile | compose + `deployment-single-node.md` | `docker compose --profile cloud-render config --services` |

- [x] **Step 2: 全仓搜索新符号的引用方（排除测试与文档）**

Run:
```bash
cd d:/DEMO/openagent-main
grep -rn "render_on_local_device\|fetch_local_artifact\|RENDER_CLOUD_FALLBACK_ENABLED\|render_worker" --include=*.py api/ | grep -v "/test/" | grep -v "\.pyc"
grep -rn "ensureCliShim\|resolveRuntimePaths\|render-runtime" desktop/ --include=*.js | grep -v "test/"
```
Expected: 每个符号都能在**非测试**代码中找到引用（定义处 + 调用处）

- [x] **Step 3: 运行时一致性验证（Node 版本必须两端相同）**

Run:
```bash
docker exec llmops-render-worker node -v
cd desktop && node -e "console.log(require('electron/package.json').version)"
cd desktop && ELECTRON_RUN_AS_NODE=1 node_modules/electron/dist/electron.exe -e "console.log(process.versions.node)" 2>/dev/null || true
```
Expected: 容器 `v24.x` 与桌面端 Electron 内置 Node **major 相同（24）**。
若不一致，说明 Task 0 未生效或版本被改回，**属阻断问题，必须修复后再继续**。

- [x] **Step 4: 运行全量后端测试**

Run: `cd api && python -m pytest test/ -q`
Expected: 全部通过（允许存在与本改动无关的既有环境失败，需逐条确认）
记录：passed 数、failed 列表

- [x] **Step 5: 运行桌面端测试**

Run: `cd desktop && node --test`
Expected: 全部通过

- [x] **Step 6: 真机端到端验证（本机渲染闭环）**

前置：本机具备 chrome-headless-shell + ffmpeg/ffprobe（Node 由 Electron 提供）。

```bash
# 1) 启动 render worker（本机直接跑，模拟桌面端托管）
cd api
RENDER_WORKER_TOKEN=dev-render-token \
HYPERFRAMES_CLI_BIN=<shim 路径> \
HYPERFRAMES_BROWSER_PATH=<chrome-headless-shell 路径> \
HYPERFRAMES_FFMPEG_PATH=<ffmpeg 路径> \
HYPERFRAMES_FFPROBE_PATH=<ffprobe 路径> \
python scripts/worker_super.py render --port 8768

# 2) 另开终端，直接打 worker 验证出片
curl -s -X POST http://127.0.0.1:8768/render \
  -H "Authorization: Bearer dev-render-token" \
  -H "Content-Type: application/json" \
  -d '{"composition":{"composition_id":"main","width":1920,"height":1080,"duration":5,"segments":[{"start":0,"duration":5,"text":"本机渲染验证"}]},"name":"e2e"}'
```

Expected: 返回 `{"ok": true, "path": "...", "size_bytes": <正数>}`，且 `ffprobe <path>` 能读出 h264 与正时长。

> **Node 版本门禁验证**：若 shim 未正确带 `ELECTRON_RUN_AS_NODE=1`，或 Electron 仍是 33，
> 此处会返回 `HyperFrames requires Node.js >= 22 (current: 20.x)`——出现该错误即证明
> Task 0（升级）或 Task 0B（shim）未生效。

- [x] **Step 7: 验证云端开关行为**

Run: `cd docker && docker compose config --services | grep render`
Expected: **无输出**（默认不含 render worker）

Run: `docker compose --profile cloud-render config --services | grep render`
Expected: `llmops-render-worker`

- [x] **Step 8: 提交验证记录（若有文档更新）**

```bash
git add api/ desktop/ docs/ docker/
git commit -m "test(render): verify local-first render wiring end to end"
```

---

## 自检清单（执行者收尾时逐项打勾）

- [x] **桌面端 Electron 内置 Node 为 24**，与容器 `node:24-bookworm-slim`（v24.21.0）major 一致
- [x] **用户无需自装 Node**：渲染走 Electron 内置 Node（经 shim + `ELECTRON_RUN_AS_NODE=1`）
- [x] shim **原地引用** `process.execPath`（未拷贝 electron.exe 单文件，否则 DLL 缺失报 `0xC0000135`）
- [x] **渲染运行时随包分发**（无按需下载）：`stage-render-runtime.js` 产出 `vendor/render-runtime/`，
      已挂进 `extraResources` 与 `pack`/`dist` 脚本
- [x] **`onnxruntime-node` 已含入并裁剪到 win32**（536MB → 68MB；图片处理可用）
- [x] **已验证 Electron 能加载 onnxruntime 原生模块**（N-API v3，ABI 稳定，无需 electron-rebuild）
- [x] `vendor/render-runtime/` 已在 `.gitignore` 中（构建产物不入库）
- [x] 新增的 `render-runtime.js` 已登记进 `package.json` 的 `build.files`（否则安装版崩）
- [x] 云端渲染代码**未被删除或重构**，仅通过 `profiles` 与 env 开关下线
- [x] 本机渲染调用**走 `resolve_desktop_bridge`**（未重蹈 `browser_action` 静态 env 的断链）
- [x] `worker_super` 的**两处**白名单（`choices` + `_module_and_entry`）都已加 `render`
- [x] `_SERVICE_SUPPORTS_HOST_PORT` 已含 `render`（否则 `--port` 不生效）
- [x] 「通道不可用」与「渲染业务失败」语义已区分：前者回退云端，后者直接报错
- [x] 每个新符号都能指向调用方（Task 11 Step 1 表格逐项通过）
- [x] `docker compose config --services` 默认不含 `llmops-render-worker`
- [x] 文档四处已同步（09 / 08 / deployment / desktop README）
- [x] 全量回归通过，既有失败已逐条确认为环境问题
