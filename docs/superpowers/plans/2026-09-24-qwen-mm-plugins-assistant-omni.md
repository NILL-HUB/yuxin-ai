# Qwen-MM-Plugins 接入助手对话链路（多说话人转写 / 音视频描述）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让首页助手 / 管理端 Agent 在对话内直接调用 Qwen-Omni 的多说话人转写（说话人标签 + 时间戳 + SRT）与音视频内容描述能力，且不改动任何既有 MCP 代码路径。

**Architecture:** Qwen-MM-Plugins 的 `api` 能力以 **MCP stdio server** 形式分发（官方「手动安装」路径），而本系统的 `McpToolFactory` 已原生支持 `transport=stdio` + `command/args/env/tool_names` 白名单，因此**无需改动 MCP 装配代码**即可挂载。两个真正的工程问题需要解决：(1) 插件依赖 `openai>=1,<2`，与容器内 `openai==2.24.0` 冲突 → 必须用 `uv tool install` 建**隔离环境**，不能 `pip install` 进应用 venv；(2) 助手侧 MCP 绑定每轮对话都会重新 spawn 子进程做 `tools/list` → 需加进程内 TTL 缓存，并修复 `app.py` 中指向不存在方法的预热调用（断链）。

**Tech Stack:** Python 3.12、uv（`uv tool install`）、MCP Python SDK（stdio）、ffmpeg、pytest。

**依据调研：**
- 插件仓库：<https://github.com/QwenLM/Qwen-MM-Plugins>（Apache-2.0，`requires-python>=3.10`）
- 发布 tag：`qwen-mm-plugins-api-v1.1.2`（各能力独立不可变 tag，见仓库 `plugin-versions.json`：`distribution_version=1.1.9`、`plugins.api=1.1.2`）
- 官方手动安装文档：<https://raw.githubusercontent.com/QwenLM/Qwen-MM-Plugins/main/docs/zh/installation.md>（「手动安装 Skill + MCP」节）

---

## 范围说明

本计划是**两份计划中的第一份**，只做「对话内可用」，**不碰知识库解析链路**：

| 计划 | 内容 | 状态 |
| --- | --- | --- |
| **本计划（A）** | 对话内多说话人转写 / 音视频描述（镜像依赖 + MCP 绑定 + 预热缓存 + 验证） | 本次实施 |
| 计划 B | 知识库 L2 补齐（音频说话人切分 / 视频场景切分 / 图片 OCR 坐标） | 见 [2026-09-24-kb-l2-omni-diarization.md](./2026-09-24-kb-l2-omni-diarization.md) |

**为什么 A 与 B 必须分开**：A 走 MCP 通道（短连接、每调用 spawn 进程、适合对话内按需调用），B 走直连 API + Celery（长任务、需并发与重试）。两者共用同一个上游模型但**装配机制完全不同**，混在一份计划里会让任务边界含糊。

**明确不做（YAGNI）：**
- 不接入 `core` / `search`（与本系统视觉链路、联网搜索重叠）
- 不接入 `blender` / `freecad` / `mhs` / `edu-agent` / `video-spatio` / `segmentation`（无业务场景）
- 不接入 `Qwen-Live-Harness`（macOS-only 的 Electron 桌面独立产品，与本系统 Web 端无接口边界，见「已核实的事实」表末行）
- 不在 admin 端新建 MCP 绑定管理 UI（既有架构已明确复用 `ASSISTANT_MCP_BINDINGS` 配置，见下节）

---

## 已核实的事实（写代码前先读，避免重复踩坑）

| 事实 | 位置 / 证据 |
| --- | --- |
| 本系统已原生支持 MCP stdio | `mcp_tool_factory.py`：`SUPPORTED_STDIO_TRANSPORTS = {"stdio"}`；`mcp_stdio_client.py`：`_build_stdio_params` 解析 `command`/`args`/`env`/`timeout_seconds` |
| 助手 MCP 绑定的唯一来源是运维配置 | `assistant_agent_service.py` 读 `current_app.config["ASSISTANT_MCP_BINDINGS"]`；`docs/prd/extensibility-design.md` §「装配来源」与 `docs/archive/superpowers-plans/2026-09-21-admin-agent-p5-mcp-dynamic-identity.md`（已归档）均写明「以 `ASSISTANT_MCP_BINDINGS` 为唯一来源」「不做 admin 端的 MCP 绑定管理 UI/API」 |
| 绑定必须能通过 `env` 校验，**否则整条绑定被静默跳过** | `mcp_stdio_client.py::_build_subprocess_env` 会先继承 `os.environ`，再 `decrypt_env(binding["env"])`；而 `tool_credential_encryptor.decrypt_env` 对**非密文**抛 `ValueError`（`_decrypt_value` → `InvalidToken` → `ValueError`）。异常被 `_list_remote_tools` 的 `try/except` 吞掉，只记日志 |
| → 因此 API Key **不要**放进 binding 的 `env` | 放进 `api/.env`（`docker-compose.yaml` 的 `env_file: ../api/.env` 会注入容器），binding 的 `env` 留空 `{}`，子进程通过 `os.environ` 继承。密钥类走 env 符合 `AGENTS.md`「env 允许部署基础设施/密钥」的口径 |
| `tool_names` 是**白名单**（不是黑名单） | `mcp_tool_factory.py` 非快照路径：`if allow_tool_names and tool_name not in allow_tool_names: continue`；快照路径同语义 |
| stdio 默认超时 30s，**撑不住 Omni 调用** | `mcp_stdio_client.py`：`DEFAULT_MCP_STDIO_TIMEOUT_SECONDS = 30`；须在 binding 显式给 `timeout_seconds` |
| 助手链路每轮对话都重新 `tools/list` | `assistant_agent_service.py` → `app_config_service.get_langchain_tools_by_mcp_bindings(bindings)`（**不传 snapshots**）→ `McpToolFactory().get_tools(bindings, mcp_tool_snapshots=None)` → 逐绑定 `_list_remote_tools(binding)` → stdio 分支 `list_tools_sync` **每次 spawn 子进程**；工厂每次新建实例，无任何缓存 |
| 启动预热调用指向**不存在的方法**（断链） | `app/http/app.py`：`injector.get(AppService).prewarm_assistant_mcp_tool_snapshots()`；而 `AppService` 中**无此方法**（全仓仅 `app.py` 与 `test/app/http/test_app_main.py` 出现该名字）。异常被 `except Exception: logging.exception(...)` 吞掉 → 静默失效 |
| 容器缺 `ffmpeg` / `git` / `uv` | `api/Dockerfile`：apt 只装 `libmagic1 curl tzdata fontconfig fonts-dejavu-core`；Node 24 从阶段一拷入 |
| 依赖版本**冲突**，必须隔离安装 | `api/requirements.txt`：`openai==2.24.0`；插件 `pyproject.toml`：`openai>=1,<2`。若 `pip install` 进应用 venv 会把 `openai` 降到 1.x，**破坏既有系统** |
| 插件入口与 extra 名 | 入口 `qwen-mm-plugins-api`；extra `[api]`（含 `dashscope`、`httpx[socks]`、`requests[socks]`）；Skill 目录 `src/capabilities/api/skill` |
| Omni 工具签名（实测源码） | `omni_multi_speaker_asr(file_path, num_speakers?, format=json\|srt, language?, model?, dry_run?)` → `{"speakers":[...], "segments":[{speaker,start,end,text}]}` + 带说话人标签 SRT；`omni_av_caption(file_path, fps?, max_pixels?)` → 5 段式 Markdown（时间线叙述 / 可见文字带时间戳 / 说话人档案+逐句转写 / 未成年人不宜内容合规表 / 安全结论） |
| Omni 协议硬约束 | `shared/api_omni.py`：必须 `stream=True` + `modalities=["text"]` + `stream_options={"include_usage": True}`；音频 part 形如 `{"type":"input_audio","input_audio":{"data":"data:;base64,…","format":"mp3"}}`（本计划走 MCP，由插件内部处理；此约束供计划 B 复用） |
| 工具接受 http(s)/OSS URL | `omni_multi_speaker_asr` 的 `file_path` 支持本地路径或 http(s)/OSS URL；本系统文件均在 COS 且有预签名 URL，可直接喂 URL 省去「让 API 容器读到本地文件」 |
| `Qwen-Live-Harness` 不适用 | 官方 README：「The full desktop experience currently supports **macOS 12+**…Support for other platforms, including Windows and Linux, is in progress.」且为 daemon(Node) + Host(Electron) 两进程桌面产品 |

---

## 文件结构

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `api/Dockerfile` | 安装 `ffmpeg` / `git` / `uv`，构建期用 `uv tool install` 把插件装进**隔离环境**并预热 | 修改 |
| `api/.env.example` | 增加 `DASHSCOPE_API_KEY` 与 `ASSISTANT_MCP_BINDINGS` 的示例（含白名单与超时） | 修改 |
| `api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py` | 新增进程内工具定义 TTL 缓存 + `prewarm_tool_definitions()` | 修改 |
| `api/internal/service/app_service.py` | 新增 `prewarm_assistant_mcp_tool_snapshots()`（修复断链） | 修改 |
| `api/test/internal/core/tools/test_mcp_tool_definition_cache.py` | 缓存行为测试（命中/过期/按绑定隔离） | 新建 |
| `api/test/internal/service/test_app_service_assistant_mcp_prewarm.py` | 预热方法测试 | 新建 |
| `docs/README.md` | 登记本计划（若 `docs/superpowers/` 已在导航内则只需确认） | 按需修改 |
| `docs/prd/extensibility-design.md` | 补「助手链路已挂载的 MCP provider 清单」一节 | 修改 |

---

## Task 1: 镜像安装隔离环境与系统依赖

**Files:**
- Modify: `api/Dockerfile`

- [ ] **Step 1: 在 apt 安装列表加入 `ffmpeg` 与 `git`**

修改 `api/Dockerfile` 的 apt 段（当前为 `libmagic1 curl tzdata fontconfig fonts-dejavu-core`），改为：

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 curl tzdata \
        fontconfig fonts-dejavu-core \
        ffmpeg git \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*
```

**为什么 `ffmpeg`**：Qwen-MM-Plugins 的音视频工具（`omni_multi_speaker_asr` 对本地视频只取音轨、`omni_av_caption` 转码）用 `shared.syscmd.find_tool` 查找**系统 `ffmpeg` 二进制**，不走 `imageio-ffmpeg` 兜底。缺了会直接报依赖错误。

**为什么 `git`**：`uv tool install` 从 `git+https://…@<tag>` 取包，构建期需要 `git`。

- [ ] **Step 2: 在 pip 安装依赖之后追加 uv 安装与插件安装段**

在 `api/Dockerfile` 中 `RUN pip install -r requirements.txt …` 之后、`COPY . .` **之前**插入：

```dockerfile
# ---- Qwen-MM-Plugins（MCP stdio server）：必须装进隔离环境 ----
# 为什么不用 pip install：插件 pyproject 要求 openai>=1,<2，而本应用 venv 锁定
# openai==2.24.0；直接 pip 安装会把 openai 降到 1.x，破坏既有 LLM 链路。
# uv tool install 会为该工具建独立 venv，与应用依赖互不干扰。
# 为什么在构建期装而不是运行期 uvx：运行期 uvx 需要 git+网络重新解析 ref，
# 生产环境不应依赖外网；构建期固化后，运行期只是一次本地可执行文件启动。
ENV PATH="/root/.local/bin:${PATH}" \
    UV_PYTHON_PREFERENCE=only-system \
    UV_LINK_MODE=copy

ARG QWEN_MM_PLUGINS_API_REF=qwen-mm-plugins-api-v1.1.2

RUN pip install --no-cache-dir "uv>=0.5,<1" -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && uv tool install \
        --from "qwen-mm-plugins[api] @ git+https://github.com/QwenLM/Qwen-MM-Plugins.git@${QWEN_MM_PLUGINS_API_REF}" \
        qwen-mm-plugins-api \
    && qwen-mm-plugins-api --help > /dev/null \
    && ffmpeg -version | head -n 1 \
    && rm -rf /root/.cache/uv
```

要点说明（**逐条不要省**）：
- `UV_PYTHON_PREFERENCE=only-system`：禁止 uv 下载托管 Python，强制用容器内 3.12（插件要求 `>=3.10`，满足）。
- `ARG …REF` 固化 tag：官方明确「正式能力使用彼此独立且不可变的发布 tag」，**不要跟 `main`**。升版本时只改这一个 ARG。
- `qwen-mm-plugins-api --help`：构建期自证安装成功（失败即 build 失败，不留到运行期才发现）。
- `rm -rf /root/.cache/uv` 放在 `uv tool install` **之后**：工具环境已落在 `/root/.local/share/uv/tools`，删掉的是构建缓存，减体积不影响运行。

- [ ] **Step 3: 重建镜像并验证隔离性与可用性**

```powershell
docker compose -f docker/docker-compose.yaml build llmops-api
docker compose -f docker/docker-compose.yaml up -d llmops-api
```

验证（三条都要过）：

```powershell
docker exec llmops-api qwen-mm-plugins-api --help
docker exec llmops-api python -c "import openai; print('app venv openai:', openai.__version__)"
docker exec llmops-api ffmpeg -version
```

Expected：
- 第一条打印插件 CLI 帮助（含 `--check-system` 之类的选项）
- 第二条打印 `app venv openai: 2.24.0` —— **必须仍是 2.24.0**，证明隔离生效
- 第三条打印 ffmpeg 版本

若第二条不是 `2.24.0`，说明插件装进了应用 venv，**立即停止**并检查是否误用了 `pip install`。

- [ ] **Step 4: 提交**

```bash
git add api/Dockerfile
git commit -m "build(api): 镜像内置 Qwen-MM-Plugins MCP server（隔离环境）与 ffmpeg"
```

---

## Task 2: 注册助手 MCP 绑定

**Files:**
- Modify: `api/.env.example`
- Modify: `api/.env`（本地实际生效文件，**不提交**）

- [ ] **Step 1: 在 `api/.env.example` 增加示例**

`api/.env.example` 第 40 行当前为 `ASSISTANT_MCP_BINDINGS=[]`。在其上方插入密钥说明，并把该行改为可复制的示例：

```dotenv
# Qwen-Omni 多模态理解（MCP stdio）：被 ASSISTANT_MCP_BINDINGS 引用。
# 密钥走容器环境变量而非 binding.env —— binding.env 的值会被 decrypt_env 当密文解，
# 明文会导致解密失败、整条绑定被静默跳过（详见计划 2026-09-24-qwen-mm-plugins-assistant-omni.md）。
DASHSCOPE_API_KEY=

# 首页助手 / 管理端 Agent 的 MCP 绑定（JSON 数组）。
# 注意：tool_names 是白名单；timeout_seconds 必须显式给大值（stdio 默认 30s 撑不住 Omni 调用）。
# ASSISTANT_MCP_BINDINGS=[{"name":"qwen-mm-omni","label":"Qwen 多模态理解","description":"Qwen-Omni 音视频理解：多说话人转写（说话人标签+时间戳+SRT）与音视频内容描述","transport":"stdio","command":"qwen-mm-plugins-api","args":[],"env":{},"tool_names":["omni_multi_speaker_asr","omni_av_caption"],"timeout_seconds":600,"enabled":true}]
ASSISTANT_MCP_BINDINGS=[]
```

- [ ] **Step 2: 在本地 `api/.env` 写入真实配置**

在 `api/.env` 中设置（`DASHSCOPE_API_KEY` 用真实百炼 key；区域须与 key 一致，北京/新加坡 key 不通用）：

```dotenv
DASHSCOPE_API_KEY=sk-你的百炼key
ASSISTANT_MCP_BINDINGS=[{"name":"qwen-mm-omni","label":"Qwen 多模态理解","description":"Qwen-Omni 音视频理解：多说话人转写（说话人标签+时间戳+SRT）与音视频内容描述","transport":"stdio","command":"qwen-mm-plugins-api","args":[],"env":{},"tool_names":["omni_multi_speaker_asr","omni_av_caption"],"timeout_seconds":600,"enabled":true}]
```

三个易错点，逐条核对：
1. **`env` 必须是 `{}`**。不要写 `{"DASHSCOPE_API_KEY":"sk-…"}` —— 那会让 `decrypt_env` 抛 `ValueError`，绑定被静默跳过。子进程通过 `os.environ` 继承 `DASHSCOPE_API_KEY`。
2. **`timeout_seconds` 必须显式给**（这里 600）。不写就落回 30s，长音频必然超时。
3. **`tool_names` 是白名单**。只列这两个，避免插件 13 个工具（含 `vision_chat`/`ocr`/`grounding`/`segmentation` 等）全部灌进 Agent 上下文。

- [ ] **Step 3: 重启 API 容器并确认绑定被读到**

```powershell
docker compose -f docker/docker-compose.yaml up -d llmops-api
docker exec llmops-api python -c "import os,json; print(len(json.loads(os.environ['ASSISTANT_MCP_BINDINGS'])))"
```

Expected：打印 `1`。

- [ ] **Step 4: 提交（只提交 example）**

```bash
git add api/.env.example
git commit -m "docs(api): 补充 Qwen-MM-Plugins MCP 绑定与 DashScope 密钥示例"
```

---

## Task 3: 修复预热断链并加工具定义缓存

**为什么必须做**：助手链路每轮对话都会 `_list_remote_tools` → stdio 分支 spawn 一次子进程。插件是 Python 包（`mcp` + `openai` + `pydantic` 导入），单次冷启动秒级；每轮对话都付这个代价不可接受。而 `app.py` 里本来就有「启动时预热」的意图，只是调用了不存在的方法。

**Files:**
- Modify: `api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py`
- Modify: `api/internal/service/app_service.py`
- Test: `api/test/internal/core/tools/test_mcp_tool_definition_cache.py`
- Test: `api/test/internal/service/test_app_service_assistant_mcp_prewarm.py`

- [ ] **Step 1: 写失败测试（缓存行为）**

新建 `api/test/internal/core/tools/test_mcp_tool_definition_cache.py`：

```python
"""MCP 工具定义进程内缓存测试。

动机：助手链路每轮对话都会构建工具，若无缓存则每次都要 spawn 一次
MCP stdio 子进程做 tools/list。本测试锁定缓存的三条契约：
命中不重复远端调用、TTL 过期后重取、不同绑定互不串用。
"""
import time

from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory


def _binding(name: str = "qwen-mm-omni") -> dict:
    return {
        "name": name,
        "transport": "stdio",
        "command": "qwen-mm-plugins-api",
        "args": [],
        "env": {},
        "tool_names": ["omni_multi_speaker_asr"],
        "timeout_seconds": 600,
        "enabled": True,
    }


def _definitions(tool_name: str) -> list[dict]:
    return [{"name": tool_name, "description": "d", "inputSchema": {"properties": {}}}]


def test_tool_definitions_are_cached_across_calls(monkeypatch):
    factory = McpToolFactory()
    calls: list[str] = []

    def fake_list(binding):
        calls.append(binding["name"])
        return _definitions("omni_multi_speaker_asr")

    monkeypatch.setattr(factory, "_list_remote_tools", fake_list)

    first = factory.get_tools([_binding()], mcp_tool_snapshots=None)
    second = factory.get_tools([_binding()], mcp_tool_snapshots=None)

    assert [tool.name for tool in first] == ["omni_multi_speaker_asr"]
    assert [tool.name for tool in second] == ["omni_multi_speaker_asr"]
    # 关键断言：第二次命中缓存，未再次远端调用
    assert calls == ["qwen-mm-omni"]


def test_tool_definitions_cache_expires(monkeypatch):
    factory = McpToolFactory()
    calls: list[str] = []
    monkeypatch.setattr(factory, "_list_remote_tools", lambda b: (calls.append(b["name"]), _definitions("t"))[1])

    factory.get_tools([_binding()], mcp_tool_snapshots=None)
    # 把该绑定的缓存时间戳回拨到 TTL 之前，模拟过期
    key = factory.build_binding_identity(_binding())
    with factory._tool_definition_cache_lock:  # type: ignore[attr-defined]
        for cache_key in list(factory._tool_definition_cache):  # type: ignore[attr-defined]
            if cache_key.startswith(key):
                stamp, payload = factory._tool_definition_cache[cache_key]  # type: ignore[attr-defined]
                factory._tool_definition_cache[cache_key] = (  # type: ignore[attr-defined]
                    stamp - McpToolFactory.TOOL_DEFINITION_CACHE_TTL_SECONDS - 1,
                    payload,
                )
    factory.get_tools([_binding()], mcp_tool_snapshots=None)

    assert calls == ["qwen-mm-omni", "qwen-mm-omni"]


def test_different_bindings_do_not_share_cache(monkeypatch):
    factory = McpToolFactory()
    calls: list[str] = []
    monkeypatch.setattr(factory, "_list_remote_tools", lambda b: (calls.append(b["name"]), _definitions("t"))[1])

    factory.get_tools([_binding("provider-a")], mcp_tool_snapshots=None)
    factory.get_tools([_binding("provider-b")], mcp_tool_snapshots=None)

    assert calls == ["provider-a", "provider-b"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/core/tools/test_mcp_tool_definition_cache.py -v
```

Expected：FAIL —— `AttributeError: type object 'McpToolFactory' has no attribute 'TOOL_DEFINITION_CACHE_TTL_SECONDS'`（且 `test_tool_definitions_are_cached_across_calls` 中 `calls` 会是两项）。

- [ ] **Step 3: 在工厂中实现缓存**

在 `api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py` 顶部补 `import time`（当前导入块有 `json`/`logging`/`hashlib`/`dataclass`/`lru_cache`/`datetime`/`typing`/`uuid`，**无 `time`**），并在模块常量区追加：

```python
# MCP 工具定义的进程内缓存时长（秒）。
# 为什么需要：助手链路每轮对话都会重建工具，而 stdio transport 每次
# tools/list 都要 spawn 一次子进程（Python 包冷启动秒级）。缓存后同一
# 绑定在 TTL 内只远端取一次。取 300s 是折中：既覆盖连续多轮对话，
# 又不至于让远端工具变更长时间不可见。
```

在 `McpToolFactory` 类中，`timeout_seconds` / `schema_compiler` / `_stdio_client` 字段之后追加两个字段：

```python
    TOOL_DEFINITION_CACHE_TTL_SECONDS = 300

    # 类级共享：助手链路的工厂是每次新建的（McpToolFactory()），
    # 实例级缓存等于没有缓存，故必须挂在类上。
    _tool_definition_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
    _tool_definition_cache_lock = threading.Lock()
```

同时在导入块补 `import threading`。

新增两个方法（放在 `_list_remote_tools` 之前）：

```python
    def _cached_tool_definitions(self, binding: dict[str, Any]) -> list[dict[str, Any]]:
        """取该绑定的工具定义，命中进程内缓存则不远端调用。

        缓存键 = 绑定标识 + 绑定内容 hash：绑定内容（command/args/tool_names/
        timeout）变更后 hash 变化，自动失效，不会拿到旧工具列表。
        """
        identity = self.build_binding_identity(binding)
        cache_key = f"{identity}:{self._binding_hash(binding)}"
        now = time.monotonic()

        with self._tool_definition_cache_lock:
            cached = self._tool_definition_cache.get(cache_key)
            if cached is not None and now - cached[0] < self.TOOL_DEFINITION_CACHE_TTL_SECONDS:
                return cached[1]

        # 远端调用放在锁外：stdio spawn 可能耗时数秒，持锁会让并发请求互相阻塞。
        definitions = self._list_remote_tools(binding)
        with self._tool_definition_cache_lock:
            self._tool_definition_cache[cache_key] = (now, definitions)
        return definitions

    def prewarm_tool_definitions(self, bindings: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """预热绑定的工具定义缓存，返回每个绑定的预热结果（供启动日志与排障）。

        单个绑定失败不抛错：预热是优化项，失败时应退回「首次调用时懒加载」，
        不能因此让应用启动失败（与 app.py 现有 try/except 的容错口径一致）。
        """
        results: list[dict[str, Any]] = []
        for binding in bindings or []:
            if not isinstance(binding, dict) or not self._is_binding_enabled(binding):
                continue
            name = _normalize_text(binding.get("name"))
            try:
                definitions = self._cached_tool_definitions(binding)
            except Exception as exc:
                logging.warning("MCP 工具定义预热失败，将在首次调用时重试: %s (%s)", name, exc)
                results.append({"name": name, "status": "error", "error": str(exc), "tool_names": []})
                continue
            results.append({
                "name": name,
                "status": "ready",
                "tool_names": self._snapshot_tool_names(definitions),
            })
        return results
```

然后把 `get_tools` 非快照路径中的这一行：

```python
            try:
                tool_definitions = self._list_remote_tools(binding)
            except Exception as exc:
                logging.exception("读取 MCP 工具列表失败，已跳过该绑定: %s", exc)
                continue
```

改为：

```python
            try:
                tool_definitions = self._cached_tool_definitions(binding)
            except Exception as exc:
                logging.exception("读取 MCP 工具列表失败，已跳过该绑定: %s", exc)
                continue
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/core/tools/test_mcp_tool_definition_cache.py -v
```

Expected：3 passed。

- [ ] **Step 5: 写失败测试（预热方法）**

新建 `api/test/internal/service/test_app_service_assistant_mcp_prewarm.py`：

```python
"""助手 MCP 工具定义预热测试。

app.py 启动时会调用 AppService.prewarm_assistant_mcp_tool_snapshots()，
该方法此前不存在（调用被 except 吞掉，静默失效）。本测试锁定它存在且行为正确。
"""
from types import SimpleNamespace

import pytest

from internal.service.app_service import AppService


def test_prewarm_returns_empty_when_no_bindings(monkeypatch):
    service = AppService(db=SimpleNamespace())

    class _App:
        config = {"ASSISTANT_MCP_BINDINGS": []}

    # app_service.py 目前**没有**导入 flask，故用 raising=False 允许创建属性；
    # has_app_context 也必须一起桩掉，否则在测试进程（无 Flask 上下文）里
    # 真实调用会抛 RuntimeError。
    monkeypatch.setattr("internal.service.app_service.current_app", _App(), raising=False)
    monkeypatch.setattr(
        "internal.service.app_service.has_app_context", lambda: True, raising=False
    )

    assert service.prewarm_assistant_mcp_tool_snapshots() == []


def test_prewarm_reports_tool_names(monkeypatch):
    service = AppService(db=SimpleNamespace())
    binding = {
        "name": "qwen-mm-omni",
        "transport": "stdio",
        "command": "qwen-mm-plugins-api",
        "args": [],
        "env": {},
        "tool_names": ["omni_multi_speaker_asr"],
        "timeout_seconds": 600,
        "enabled": True,
    }

    class _App:
        config = {"ASSISTANT_MCP_BINDINGS": [binding]}

    monkeypatch.setattr("internal.service.app_service.current_app", _App(), raising=False)
    monkeypatch.setattr(
        "internal.service.app_service.has_app_context", lambda: True, raising=False
    )
    monkeypatch.setattr(
        "internal.core.tools.mcp_tools.providers.mcp_tool_factory.McpToolFactory._list_remote_tools",
        lambda self, b: [{"name": "omni_multi_speaker_asr", "inputSchema": {"properties": {}}}],
    )

    result = service.prewarm_assistant_mcp_tool_snapshots()

    assert result == [
        {"name": "qwen-mm-omni", "status": "ready", "tool_names": ["omni_multi_speaker_asr"]}
    ]


def test_prewarm_does_not_raise_when_binding_unreachable(monkeypatch):
    """预热是优化项：单个绑定不可达时必须降级为 error 结果，不得抛错。"""
    service = AppService(db=SimpleNamespace())
    binding = {
        "name": "broken",
        "transport": "stdio",
        "command": "does-not-exist",
        "args": [],
        "env": {},
        "tool_names": [],
        "timeout_seconds": 5,
        "enabled": True,
    }

    class _App:
        config = {"ASSISTANT_MCP_BINDINGS": [binding]}

    monkeypatch.setattr("internal.service.app_service.current_app", _App(), raising=False)
    monkeypatch.setattr(
        "internal.service.app_service.has_app_context", lambda: True, raising=False
    )
    monkeypatch.setattr(
        "internal.core.tools.mcp_tools.providers.mcp_tool_factory.McpToolFactory._list_remote_tools",
        lambda self, b: (_ for _ in ()).throw(RuntimeError("spawn failed")),
    )

    result = service.prewarm_assistant_mcp_tool_snapshots()

    assert result[0]["status"] == "error"
    assert result[0]["tool_names"] == []
```

- [ ] **Step 6: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/service/test_app_service_assistant_mcp_prewarm.py -v
```

Expected：FAIL —— `AttributeError: 'AppService' object has no attribute 'prewarm_assistant_mcp_tool_snapshots'`。

- [ ] **Step 7: 在 `AppService` 中实现该方法**

在 `api/internal/service/app_service.py` 的 `refresh_mcp_tool_snapshots` 之后新增。

**必须先补导入**：`app_service.py` 当前**没有**导入 flask（已实测：全文只有 `import logging`，无 `flask` 相关导入）。在文件顶部导入区补：

```python
from flask import current_app, has_app_context
```

然后新增方法：

```python
    def prewarm_assistant_mcp_tool_snapshots(self) -> list[dict[str, Any]]:
        """启动时预热首页助手 / 管理端 Agent 的 MCP 工具定义缓存。

        与 App 链路不同，助手链路的绑定来自运维配置 `ASSISTANT_MCP_BINDINGS`
        （无 app_config 记录可存放快照），因此预热产物落在 McpToolFactory 的
        进程内缓存中，而不是落库。预热只影响首次调用耗时，不改变工具语义。
        """
        bindings = (
            current_app.config.get("ASSISTANT_MCP_BINDINGS", [])
            if has_app_context()
            else []
        )
        if not isinstance(bindings, list) or not bindings:
            return []

        from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory

        results = McpToolFactory().prewarm_tool_definitions(bindings)
        logging.info("助手 MCP 工具定义预热完成: %s", results)
        return results
```

- [ ] **Step 8: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/service/test_app_service_assistant_mcp_prewarm.py test/internal/core/tools/test_mcp_tool_definition_cache.py -v
```

Expected：6 passed（缓存 3 + 预热 3）。

- [ ] **Step 9: 跑既有 MCP 测试确认无回归**

```bash
docker exec llmops-api pytest test/internal/core/tools/ test/internal/service/test_mcp_service.py test/internal/service/test_mcp_runtime_adapter.py -v
```

Expected：全部 passed（缓存是新增旁路，不改变既有断言）。

- [ ] **Step 10: 重启容器确认预热生效**

```powershell
docker compose -f docker/docker-compose.yaml up -d llmops-api
docker logs llmops-api --tail 200 | Select-String "助手 MCP 工具定义预热完成"
```

Expected：出现一行 `助手 MCP 工具定义预热完成: [{'name': 'qwen-mm-omni', 'status': 'ready', 'tool_names': ['omni_multi_speaker_asr', 'omni_av_caption']}]`。

- [ ] **Step 11: 提交**

```bash
git add api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py api/internal/service/app_service.py api/test/internal/core/tools/test_mcp_tool_definition_cache.py api/test/internal/service/test_app_service_assistant_mcp_prewarm.py
git commit -m "fix(mcp): 修复助手 MCP 预热断链并新增工具定义 TTL 缓存"
```

---

## Task 4: 端到端验证

**Files:**
- 无代码改动（纯验证）

- [ ] **Step 1: 先用插件自带的系统检查确认依赖齐备**

```powershell
docker exec llmops-api qwen-mm-plugins-api --check-system
```

Expected：报告依赖齐备（无 missing 项）。`--check-system` 是官方文档给出的入口之一（`<entry> --check-system`），用于查看该能力的具体系统要求。

若报缺 ffmpeg，回 Task 1 Step 1；若报缺 uv/venv，回 Task 1 Step 2。

- [ ] **Step 2: 通过助手对话链路实测**

在 UI 首页助手对话框中，上传或引用一段多说话人音视频，发送：

```
带说话人标签和时间戳转写这段会议
```

Expected：助手调用 `omni_multi_speaker_asr`，返回形如
`{"speakers":["Speaker 1","Speaker 2"],"segments":[{"speaker":"Speaker 1","start":0.0,"end":3.2,"text":"…"}]}`
并附带带说话人标签的 SRT 文本。

再发一条验证第二个工具：

```
描述这段视频的内容，按时间线给出画面与台词
```

Expected：助手调用 `omni_av_caption`，返回 5 段式 Markdown（Storyline / Visible Text / Speakers and Transcript / Compliance Alert / Summary of Safety Findings）。

**若工具未被调用**：先在容器日志里搜 `omni` 确认子进程是否被 spawn 过（`docker logs llmops-api --tail 300 | Select-String "MCP"`），再按 Step 3 对照表排查。

- [ ] **Step 3: 排障对照表（失败时逐项核对）**

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 助手完全不调用新工具 | 绑定未生效或白名单名写错 | `docker exec llmops-api python -c "import os;print(os.environ['ASSISTANT_MCP_BINDINGS'])"`；核对 `tool_names` 与插件工具名逐字一致 |
| 日志出现 `工具凭证解密失败` | 把明文 key 写进了 binding 的 `env` | 改为 `"env": {}`，key 放 `api/.env` |
| 日志出现 `MCP stdio list_tools 超时（30s）` | 未设 `timeout_seconds` | 补 `"timeout_seconds": 600` |
| 日志出现 `No such file or directory: 'qwen-mm-plugins-api'` | 镜像未重建或 PATH 未含 `/root/.local/bin` | 重跑 Task 1 Step 3；确认 Dockerfile 的 `ENV PATH=…` 已加 |
| `ffmpeg 不可用` | 镜像未装 ffmpeg | 重跑 Task 1 Step 3 的第三条验证 |

- [ ] **Step 4: 记录实测结论（写进提交说明，不新建文档）**

提交一条空提交记录验证结论（便于追溯），或把结论补进 Task 5 的文档小节：

```bash
git commit --allow-empty -m "test(mcp): Qwen-Omni 多说话人转写端到端验证通过（对话链路）"
```

---

## Task 5: 架构文档同步

**Files:**
- Modify: `docs/prd/extensibility-design.md`
- Modify: `docs/README.md`（仅当需要登记新文档时）

- [ ] **Step 1: 在 `docs/prd/extensibility-design.md` 的 MCP 装配小节补实测清单**

在「装配来源」相关表格附近新增一段（内容须与 Task 4 实测结果一致，**不要写「待确认」**）：

```markdown
### 助手链路已挂载的 MCP provider

| provider | transport | 工具（白名单） | 上游 | 配置来源 |
| --- | --- | --- | --- | --- |
| `qwen-mm-omni`（Qwen 多模态理解） | stdio（`qwen-mm-plugins-api`） | `omni_multi_speaker_asr`、`omni_av_caption` | Qwen-MM-Plugins `api` 能力，tag `qwen-mm-plugins-api-v1.1.2` | `ASSISTANT_MCP_BINDINGS`（密钥 `DASHSCOPE_API_KEY` 走容器 env） |

- 安装方式：镜像构建期 `uv tool install` 到隔离环境（插件要求 `openai>=1,<2`，与应用 venv 的 `openai==2.24.0` 冲突，**不可 pip 装进应用 venv**）。
- 工具定义缓存：`McpToolFactory` 进程内 TTL 300s，启动时由 `AppService.prewarm_assistant_mcp_tool_snapshots()` 预热。
```

- [ ] **Step 2: 核对 `docs/README.md` 导航**

本计划位于 `docs/superpowers/plans/`（非权威区，已在导航内）。**无需新增顶层文档**，故不改 `docs/README.md`。若 Step 1 的改动落在新文件而非既有文件，则必须在 `docs/README.md` 登记。

- [ ] **Step 3: 更新知识图谱**

```bash
python -m graphify update .
```

- [ ] **Step 4: 提交**

```bash
git add docs/prd/extensibility-design.md graphify-out/
git commit -m "docs(prd): 登记助手链路 Qwen-Omni MCP provider 与安装约束"
```

---

## 验收清单（全部通过才算完成）

- [ ] `docker exec llmops-api python -c "import openai;print(openai.__version__)"` 输出 `2.24.0`（隔离生效）
- [ ] `docker exec llmops-api qwen-mm-plugins-api --check-system` 无 missing 依赖
- [ ] `docker exec llmops-api pytest test/internal/core/tools/ test/internal/service/test_app_service_assistant_mcp_prewarm.py -v` 全绿
- [ ] 容器启动日志出现「助手 MCP 工具定义预热完成」且 `status=ready`
- [ ] 对话内「带说话人标签和时间戳转写这段会议」返回 `speakers` + 带 speaker 的 `segments` + SRT
- [ ] 对话内「描述这段视频的内容，按时间线给出画面与台词」返回 5 段式 Markdown
- [ ] `docs/prd/extensibility-design.md` 已登记该 provider，措辞与实测一致
- [ ] 已执行 `python -m graphify update .`

## 接线自检（AGENTS.md 强制项）

| 新增产物 | 入口 / 触发路径 |
| --- | --- |
| `McpToolFactory._cached_tool_definitions` | `get_tools(bindings, mcp_tool_snapshots=None)` 非快照路径（`assistant_agent_service._build_tools` 与 `admin_agent_chat_service._build_tools` 每轮调用） |
| `McpToolFactory.prewarm_tool_definitions` | `AppService.prewarm_assistant_mcp_tool_snapshots()` ← `app/http/app.py` 启动钩子 |
| `AppService.prewarm_assistant_mcp_tool_snapshots` | `app/http/app.py`（启动时 `ASSISTANT_MCP_BINDINGS` 非空则调用） |
| 镜像内 `qwen-mm-plugins-api` | `ASSISTANT_MCP_BINDINGS` → `McpToolFactory` stdio 分支 `McpStdioClient.list_tools_sync` / `call_tool_sync` |
| `DASHSCOPE_API_KEY` | `api/.env` → docker-compose `env_file` → 容器 env → `McpStdioClient._build_subprocess_env` 继承 |
