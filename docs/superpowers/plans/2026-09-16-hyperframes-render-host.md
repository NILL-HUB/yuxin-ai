# HyperFrames 渲染宿主与成品库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让结构化的视频脚本在服务端编译为 HyperFrames composition、渲染为 MP4、自动落入「每用户唯一、系统托管」的成品库并可被检索复用；全部由对话内工具触发。

**Architecture:** 三层——**编**（`composition_builder.py` 纯函数：结构化 spec → HyperFrames HTML）、**渲**（`hyperframes_renderer.py`：写工程目录 → subprocess 调 `npx hyperframes render` → ffprobe 校验产物）、**库**（`KnowledgeBaseService.get_or_create_render_output_base` + `store_render_output`：MP4 落 COS → 成品库建档 → 索引入库）。渲染是分钟级长任务，走 Celery 专用 `render` 队列（失败回退同步），对话入口是 builtin 工具 `render_video`。

**Tech Stack:** Python 3.12、HyperFrames CLI 0.8.42（Node ≥ 22 + Chromium + ffmpeg/ffprobe）、SQLAlchemy/Alembic（PostgreSQL 部分唯一索引）、Celery、pytest。

**依据规格：** [2026-09-16-video-production-p4-design.md](../specs/2026-09-16-video-production-p4-design.md) §3（编/生/渲三层）、§3.2（渲染宿主）、§4（成品入库与分类拆分）、§6.3（成品配额宽让）、§10（验收要点）。

**上游已完成：** 计划 1（L1 动态抽帧 + 帧配额）、计划 2（L2 区间密抽）——`time_offset`、抽帧、配额释放均已落地。

---

## 本机实测事实（写计划前已亲自跑通，非推测）

以下全部为在 `d:\DEMO\openagent-main` 上**实测**的结果，是本计划的关键前提：

| 事实 | 实测证据 |
| --- | --- |
| `npx hyperframes` 可用 | 版本 **0.8.42**（`npx --yes hyperframes --version`） |
| `init` / `lint` 可用 | `init --example blank --non-interactive` 生成工程；`lint` 输出 `0 errors, 0 warnings` |
| **`render` 能产出真 MP4** | `rendered.mp4`：**h264 / 1920x1080 / 30fps / 10.0s / 22,935 字节**，`ffprobe` 校验通过 |
| 渲染**必须**显式给 3 个路径 | `HYPERFRAMES_BROWSER_PATH`、`HYPERFRAMES_FFMPEG_PATH`、`HYPERFRAMES_FFPROBE_PATH`（否则 doctor/render 报缺） |
| **浏览器必须是能响应 `--version` 的 Chrome** | `chrome-headless-shell.exe --version` → `Google Chrome for Testing 152.0.7977.8`（正常）；而完整版 `chrome.exe --version` 在本机会**挂死**（sandbox 拒绝访问），导致 render 直接拒绝启动 |
| **ffprobe 必须是真 ffprobe** | 用 ffmpeg 二进制冒充 ffprobe 会失败：`Unrecognized option 'print_format'`（`-print_format` 是 ffprobe 专有参数）。换成真 ffprobe 后渲染 100% 成功 |
| HyperFrames 自己的 docker 渲染器形态 | 其 `Dockerfile.render` 为 `FROM node:22-bookworm-slim` + `ARG HYPERFRAMES_VERSION` + `npm install -g hyperframes@${HYPERFRAMES_VERSION}` |
| 现有两个镜像都不适合作渲染底座 | `api/Dockerfile` 有 node 但**无 chromium/ffmpeg**；`api/Dockerfile.worker` 有 playwright+chromium 但**无 node、无 ffmpeg** |
| 迁移图当前**单 head** | `v0d1e2f3a4b5`（`v0d1e2f3a4b5_extend_recycle_bin_admin_agent.py`），共 153 个已跟踪迁移 |

**composition 契约（取自 `init` 生成的官方 scaffold，非臆造）：**

```html
<div id="root"
     data-composition-id="main"
     data-start="0" data-duration="10"
     data-width="1920" data-height="1080">
  <h1 id="title" class="clip" data-start="0" data-duration="10" data-track-index="0">Title</h1>
</div>
<script>
  const tl = gsap.timeline({ paused: true });
  window.__timelines["main"] = tl;
  tl.seek(0);
</script>
```

规则：每个定时元素需 `data-start`（+ 时长）；视觉元素加 `class="clip"`；每个 composition 在 `window.__timelines` 注册**一个 paused 根时间轴**；只允许确定性逻辑（禁 `Date.now()` / `Math.random()` / 网络请求）。

### 已实测的渲染命令与产物形态

```bash
# 在 composition 工程目录内执行（cwd = 工程目录）
npx --yes hyperframes@0.8.42 render --quality draft --fps 30 --output <绝对输出路径>
```

成功时 stderr 末尾形态（据此判定成功）：

```
◇  D:\...\rendered.mp4
   22.4 KB · 10.0s video · rendered in 11.1s
```

失败时 CLI 退出码非 0 并在 stderr 给出 `✗  Render failed` + 原因（如 `Render artifact duration probe failed ...`）。

> **重要**：CLI 内部先写临时目录（`.rendered.hf-transaction-*/`）再落最终路径；**产物是否有效以「文件存在 + ffprobe 能读出 duration」为准**，不要只信退出码。

### 本计划的范围边界

- **在范围内**：编/渲/库三层 + Celery `render` 队列 + 对话内工具入口。这些在本机**可完整 TDD 验证**（渲染真跑通已实证）。
- **不在范围内（另立部署计划）**：渲染 worker 镜像（Node+Chromium+ffmpeg 打包）、`-Q render` 的容器隔离编排、`api/Dockerfile.render`。原因：本机 Docker registry 与 GitHub 均不可达，镜像无法构建，**无法实测**。本计划会在文档中标注该缺口。

---

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `api/config/config.py` | 修改 | 渲染运行时配置项（CLI 版本钉死 + 三个二进制路径 + 超时） |
| `api/.env.example` | 修改 | 渲染配置项样例与说明 |
| `api/internal/entity/knowledge_entity.py` | 修改 | `KnowledgeCreatedFrom` 增 `RENDER_OUTPUT` |
| `api/internal/model/knowledge.py` | 修改 | `KnowledgeBase.__table_args__` 增成品库部分唯一索引（与迁移一致） |
| `api/internal/migration/versions/w1e2f3a4b5c6_add_render_output_base_unique.py` | 新建 | 成品库部分唯一索引（每账号至多一个） |
| `api/internal/service/knowledge_base_service.py` | 修改 | 成品库 `get_or_create` + 禁止上传 + 成品入库 |
| `api/internal/service/storage_quota_service.py` | 修改 | `check_quota_allow_overflow`（成品宽让，设计 §6.3） |
| `api/internal/service/storage/runtime_storage_service.py` | 修改 | `upload_bytes(allow_overflow=...)` 策略选择 |
| `api/internal/service/render_service.py` | 新建 | 渲染编排：编 → 渲 → 库 |
| `api/internal/core/video/__init__.py` | 新建 | 视频制作包（导出编译/渲染入口） |
| `api/internal/core/video/composition_builder.py` | 新建 | 纯函数：结构化 spec → HyperFrames HTML |
| `api/internal/core/video/hyperframes_renderer.py` | 新建 | 写工程目录 + 调 CLI 渲染 + ffprobe 校验 |
| `api/internal/task/render_tasks.py` | 新建 | Celery `render` 队列任务 |
| `api/config/config.py` | 修改 | 渲染配置项 + `Queue("render")` + 任务路由 |
| `api/app/http/celery_app.py` | 修改 | `TASK_MODULES` 登记 + 显式 import + 路由 |
| `api/internal/core/tools/builtin_tools/providers/video_render_tools/` | 新建 | 对话内入口：`render_video.py` + `.yaml` + `positions.yaml` + `__init__.py` |
| `api/internal/core/tools/builtin_tools/providers/providers.yaml` | 修改 | 登记 `video_render_tools` provider |
| `api/internal/service/assistant_agent_service.py` | 修改 | **运行时挂载点**（不挂 = 断链） |
| `api/test/internal/{core/video,service,task,migration,core/tools}/` | 新建 | 各任务对应测试（见各任务 Test 行） |
| `docs/prd/modules/02-knowledge-base.md` | 修改 | 成品库章节（§11.13） |
| `docs/prd/execution-roadmap.md` | 修改 | P3.7 渲染宿主（已完成） |
| `docs/prd/knowledge-base-product-form-design.md` | 修改 | 修正「视频轻量编辑 ⬜ 规划」为实际落地状态 |

---

## Task 1: 渲染运行时配置项

渲染需要三个二进制路径与一个钉死的 CLI 版本；配置项缺失时渲染会直接失败，因此先落地配置。

**Files:**
- Modify: `api/config/config.py`（在文件存储配置段之后插入）
- Modify: `api/.env.example`
- Test: `api/test/internal/core/video/test_render_config.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/core/video/test_render_config.py`：

```python
"""渲染运行时配置项测试。

HyperFrames 硬依赖三个外部二进制（浏览器 / ffmpeg / ffprobe），
且 CLI 版本必须钉死以保证「同一 composition 重复渲染结果一致」。
这些配置项缺失时渲染会在启动阶段直接失败，故用测试锁定默认值与覆盖行为。
"""
import importlib
import os
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[3]


def _load_config(monkeypatch, **env):
    """在干净环境下重新构造 Config，避免被其他测试的 env 污染。"""
    for key in (
        "HYPERFRAMES_CLI_VERSION",
        "HYPERFRAMES_BROWSER_PATH",
        "HYPERFRAMES_FFMPEG_PATH",
        "HYPERFRAMES_FFPROBE_PATH",
        "RENDER_TIMEOUT_SEC",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config.config as module

    importlib.reload(module)
    return module


def test_render_config_has_defaults(monkeypatch):
    module = _load_config(monkeypatch)
    config = module.Config()

    assert config.HYPERFRAMES_CLI_VERSION == "0.8.42"
    assert config.HYPERFRAMES_BROWSER_PATH == ""
    assert config.HYPERFRAMES_FFMPEG_PATH == ""
    assert config.HYPERFRAMES_FFPROBE_PATH == ""
    assert config.RENDER_TIMEOUT_SEC == 1800


def test_render_config_reads_env(monkeypatch):
    module = _load_config(
        monkeypatch,
        HYPERFRAMES_CLI_VERSION="0.9.0",
        HYPERFRAMES_BROWSER_PATH=r"C:\chrome\headless_shell.exe",
        HYPERFRAMES_FFMPEG_PATH=r"C:\ffmpeg\ffmpeg.exe",
        HYPERFRAMES_FFPROBE_PATH=r"C:\ffmpeg\ffprobe.exe",
        RENDER_TIMEOUT_SEC="600",
    )
    config = module.Config()

    assert config.HYPERFRAMES_CLI_VERSION == "0.9.0"
    assert config.HYPERFRAMES_BROWSER_PATH == r"C:\chrome\headless_shell.exe"
    assert config.HYPERFRAMES_FFPROBE_PATH == r"C:\ffmpeg\ffprobe.exe"
    assert config.RENDER_TIMEOUT_SEC == 600
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/video/test_render_config.py -q --no-header --no-cov`

Expected: FAIL —— `AttributeError: 'Config' object has no attribute 'HYPERFRAMES_CLI_VERSION'`

- [ ] **Step 3: 实现**

在 `api/config/config.py` 中，紧跟本地文件存储配置（`self.LOCAL_STORAGE_BASE_URL = ...`）之后插入：

```python
        # ==================== 视频渲染（HyperFrames）====================
        # 渲染宿主硬依赖三个外部二进制；三者为空时渲染服务会显式报错，
        # 不做「猜路径」——猜错会把分钟级渲染变成静默失败。
        #
        # 浏览器路径经验证需指向「能响应 --version 的 Chrome 构建」：
        # chrome-headless-shell 可正常响应，部分完整版 Chrome 在受限环境下
        # --version 会挂死，导致 HyperFrames 判定 "Chrome cannot start" 而拒绝渲染。
        self.HYPERFRAMES_BROWSER_PATH = _get_env("HYPERFRAMES_BROWSER_PATH")
        self.HYPERFRAMES_FFMPEG_PATH = _get_env("HYPERFRAMES_FFMPEG_PATH")
        # 必须是真 ffprobe：用 ffmpeg 冒充会因 `-print_format` 不支持而渲染失败
        self.HYPERFRAMES_FFPROBE_PATH = _get_env("HYPERFRAMES_FFPROBE_PATH")
        # 钉死 CLI 版本，保证同一 composition 重复渲染结果一致
        self.HYPERFRAMES_CLI_VERSION = (
            _get_env("HYPERFRAMES_CLI_VERSION") or "0.8.42"
        )
        # 渲染是分钟级长任务，超时按「长视频 + 慢机器」放宽
        self.RENDER_TIMEOUT_SEC = int(_get_env("RENDER_TIMEOUT_SEC") or 1800)
```

在 `api/.env.example` 末尾追加：

```dotenv
# ==================== 视频渲染（HyperFrames）====================
# 渲染宿主硬依赖三个外部二进制，路径为空时渲染任务会显式失败。
# 浏览器建议指向 chrome-headless-shell（完整版 Chrome 在受限环境下
# 可能出现 `--version` 挂死，使 HyperFrames 判定浏览器不可用）。
HYPERFRAMES_BROWSER_PATH=
HYPERFRAMES_FFMPEG_PATH=
# 必须是真 ffprobe（ffmpeg 冒充会因 -print_format 不支持而渲染失败）
HYPERFRAMES_FFPROBE_PATH=
# 钉死 CLI 版本，保证重复渲染结果一致
HYPERFRAMES_CLI_VERSION=0.8.42
# 单次渲染超时（秒）
RENDER_TIMEOUT_SEC=1800
```

> 若 `_get_env` 对未设置项返回 `None`，上述 `config.HYPERFRAMES_BROWSER_PATH == ""` 断言需相应改为 `is None`——实施时**先读 `_get_env` 的真实实现**再定断言，不要照抄。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/video/test_render_config.py -q --no-header --no-cov`

Expected: PASS（2 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/config/config.py api/.env.example api/test/internal/core/video/test_render_config.py
git commit -m "feat(video): add HyperFrames render runtime config"
```

---

## Task 2: 成品库标识与唯一约束迁移

成品库是「每用户唯一、系统托管」的归集处，靠 `created_from` 标识 + **部分唯一索引**兜底并发创建。不能用普通唯一约束：`manual_upload` 等同账号下允许多个。

**Files:**
- Modify: `api/internal/entity/knowledge_entity.py:58-63`
- Create: `api/internal/migration/versions/w1e2f3a4b5c6_add_render_output_base_unique.py`
- Test: `api/test/internal/migration/test_render_output_base_migration.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/migration/test_render_output_base_migration.py`：

```python
"""成品库标识与唯一约束守卫。

成品库必须「每账号至多一个」且由系统托管。唯一性靠 PostgreSQL 部分唯一索引
（created_from='render_output'）兜底：普通唯一约束会把同账号的多个
manual_upload 库也判为冲突，语义错误。
"""
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "w1e2f3a4b5c6_add_render_output_base_unique.py"


def test_render_output_enum_exists():
    from internal.entity.knowledge_entity import KnowledgeCreatedFrom

    assert KnowledgeCreatedFrom.RENDER_OUTPUT.value == "render_output"


def test_migration_file_exists_with_correct_down_revision():
    assert MIGRATION.is_file(), "缺少成品库唯一索引迁移"
    source = MIGRATION.read_text(encoding="utf-8")

    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
    assert down is not None, "迁移必须声明 down_revision"
    assert down.group(1) == "v0d1e2f3a4b5", (
        "down_revision 必须指向当前单 head（v0d1e2f3a4b5）；"
        "指向其他分支会造成多 head，alembic upgrade head 直接失败"
    )


def test_migration_creates_partial_unique_index():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "unique=True" in source
    assert "postgresql_where" in source, "必须是部分唯一索引，而非全表唯一约束"
    assert "render_output" in source


def test_migration_is_reversible():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "def downgrade" in source
    assert "drop_index" in source
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/migration/test_render_output_base_migration.py -q --no-header --no-cov`

Expected: FAIL —— `AttributeError: RENDER_OUTPUT` 与「缺少成品库唯一索引迁移」

- [ ] **Step 3: 实现枚举**

在 `api/internal/entity/knowledge_entity.py` 的 `KnowledgeCreatedFrom` 中，`WORKFLOW_IMPORT` 之后追加一行：

```python
    RENDER_OUTPUT = "render_output"  # 渲染成品（系统托管成品库）
```

- [ ] **Step 4: 实现迁移**

新建 `api/internal/migration/versions/w1e2f3a4b5c6_add_render_output_base_unique.py`：

```python
"""add partial unique index for render output knowledge base

设计依据：docs/superpowers/specs/2026-09-16-video-production-p4-design.md §4.1/§4.2。

成品库是「每用户唯一、系统托管」的归集处：用户不应能随手建多个「成品库」。
仅靠代码里的 get_or_create 无法防并发创建（两个请求同时查不到就各建一个），
故用 PostgreSQL 部分唯一索引兜底。

为什么是「部分」唯一索引而非普通唯一约束：
    created_from='manual_upload' 等取值在同一账号下是允许重复的（用户可建多个
    素材库），只有 render_output 要求每账号至多一个。全表唯一约束会把
    正常的多库场景误判为冲突。

Revision ID: w1e2f3a4b5c6
Revises: v0d1e2f3a4b5
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  （迁移风格一致性）

revision = "w1e2f3a4b5c6"
down_revision = "v0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "knowledge_base_render_output_uniq",
        "knowledge_base",
        ["owner_account_id"],
        unique=True,
        postgresql_where=sa.text("created_from = 'render_output'"),
    )


def downgrade():
    op.drop_index("knowledge_base_render_output_uniq", table_name="knowledge_base")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest test/internal/migration/test_render_output_base_migration.py -q --no-header --no-cov`

Expected: PASS（4 个用例）

- [ ] **Step 6: 更新模型 `__table_args__`（保持模型与迁移一致）**

在 `api/internal/model/knowledge.py` 的 `KnowledgeBase.__table_args__` 元组末尾追加：

```python
        Index(
            "knowledge_base_render_output_uniq",
            "owner_account_id",
            unique=True,
            postgresql_where=text("created_from = 'render_output'"),
        ),
```

- [ ] **Step 7: 运行迁移图守卫与模型测试**

Run: `python -m pytest test/internal/migration -q --no-header --no-cov`

Expected: PASS（含「单 head」断言；若报多 head，说明 `down_revision` 写错了）

- [ ] **Step 8: 提交**

```bash
git add api/internal/entity/knowledge_entity.py api/internal/model/knowledge.py api/internal/migration/versions/w1e2f3a4b5c6_add_render_output_base_unique.py api/test/internal/migration/test_render_output_base_migration.py
git commit -m "feat(knowledge): add render output base marker and unique index"
```

---

## Task 3: 成品库幂等创建（get_or_create）

首次出片时才建库（不给从未出片的用户平白建库），且必须并发安全：查不到就建，建冲突就重查。

**Files:**
- Modify: `api/internal/service/knowledge_base_service.py`（在 `create_system_base` 之后插入）
- Test: `api/test/internal/service/test_render_output_base.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_render_output_base.py`：

```python
"""成品库幂等创建测试。

设计 §4.2：首次需要写成品时幂等创建（get_or_create），不给从未出片的用户平白建库；
并发创建靠部分唯一索引兜底，因此 get_or_create 必须在 IntegriityError 后重查而不是抛错。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.knowledge_entity import (
    KnowledgeBaseType,
    KnowledgeCreatedFrom,
    KnowledgeScope,
)
from internal.service.knowledge_base_service import (
    RENDER_OUTPUT_BASE_NAME,
    KnowledgeBaseService,
)


class _Query:
    def __init__(self, results):
        self._results = list(results)

    def filter_by(self, **kwargs):
        self._kwargs = kwargs
        return self

    def one_or_none(self):
        return self._results[0] if self._results else None

    def one(self):
        if not self._results:
            raise AssertionError("one() 被调用但无结果，应改为重查逻辑")
        return self._results[0]


class _Session:
    def __init__(self, results):
        self._results = results
        self.rollbacks = 0

    def query(self, model):
        return _Query(self._results)

    def rollback(self):
        self.rollbacks += 1


class _DB:
    def __init__(self, results):
        self.session = _Session(results)


def _service(results, created=None, raise_integrity=False):
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.db = _DB(results)

    def _create(model, **kwargs):
        if raise_integrity:
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("stmt", {}, Exception("duplicate key"))
        if created is not None:
            created.update(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)

    service.create = _create
    service.auto_select_embedding_model = lambda: SimpleNamespace(id=uuid4())
    service.update = lambda model, **kwargs: model
    return service


def test_existing_base_is_reused():
    existing = SimpleNamespace(id=uuid4(), created_from="render_output")
    service = _service([existing])
    account = SimpleNamespace(id=uuid4())

    result = service.get_or_create_render_output_base(account)

    assert result is existing, "已存在成品库时必须复用，不能重复建"


def test_missing_base_is_created_with_marker():
    created = {}
    service = _service([], created=created)
    account = SimpleNamespace(id=uuid4())

    service.get_or_create_render_output_base(account)

    assert created["name"] == RENDER_OUTPUT_BASE_NAME
    assert created["created_from"] == KnowledgeCreatedFrom.RENDER_OUTPUT.value
    assert created["knowledge_scope"] == KnowledgeScope.USER_CONTENT.value
    assert created["base_type"] == KnowledgeBaseType.VIDEO.value
    assert created["owner_account_id"] == account.id


def test_existing_base_query_filters_by_render_output_marker():
    """必须按 created_from 查，不能按名称查——用户可能已手建同名库。"""
    service = _service([])
    captured = {}

    class _RecordingQuery(_Query):
        def filter_by(self, **kwargs):
            captured.update(kwargs)
            return self

    service.db.session.query = lambda model: _RecordingQuery([])

    service.get_or_create_render_output_base(SimpleNamespace(id=uuid4()))

    assert captured.get("created_from") == KnowledgeCreatedFrom.RENDER_OUTPUT.value


def test_concurrent_create_conflict_is_recovered():
    """并发下另一请求已建库 -> IntegrityError -> 重查返回既有库。"""
    existing = SimpleNamespace(id=uuid4(), created_from="render_output")
    service = _service([], raise_integrity=True)

    calls = {"n": 0}
    original_query = service.db.session.query

    def _query(model):
        calls["n"] += 1
        # 第一次查（创建前）为空；冲突重查时返回既有库
        return _Query([existing] if calls["n"] > 1 else [])

    service.db.session.query = _query

    result = service.get_or_create_render_output_base(SimpleNamespace(id=uuid4()))

    assert result is existing
    assert service.db.session.rollbacks == 1, "冲突后必须 rollback 再重查"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_render_output_base.py -q --no-header --no-cov`

Expected: FAIL —— `ImportError: cannot import name 'RENDER_OUTPUT_BASE_NAME'`

- [ ] **Step 3: 实现**

在 `api/internal/service/knowledge_base_service.py` 模块顶部 import 段补齐（若已存在则跳过）：

```python
from sqlalchemy.exc import IntegrityError
```

在类体外、`class KnowledgeBaseService` 之前定义常量：

```python
# 系统预置成品库的固定名称（每用户唯一，系统托管，禁止手动上传）
RENDER_OUTPUT_BASE_NAME = "成品库"
```

在 `KnowledgeBaseService` 的 `create_system_base` 之后插入：

```python
    def get_or_create_render_output_base(self, account: Account) -> KnowledgeBase:
        """取当前账号的系统预置成品库，不存在则幂等创建。

        设计 §4.2：首次需要写成品时才建库，避免给从未出片的用户平白建库。

        并发安全：两个请求可能同时查不到而各建一个。DB 侧的
        `knowledge_base_render_output_uniq`（部分唯一索引）会拒绝第二个，
        此处捕获 IntegrityError 后 rollback 并重查，返回先建成的那个。

        按 `created_from` 查而非按名称查——用户完全可能已手建一个叫「成品库」
        的普通素材库，按名称查会错误地复用它。
        """
        def _find() -> KnowledgeBase | None:
            return (
                self.db.session.query(KnowledgeBase)
                .filter_by(
                    owner_account_id=account.id,
                    created_from=KnowledgeCreatedFrom.RENDER_OUTPUT.value,
                )
                .one_or_none()
            )

        existing = _find()
        if existing is not None:
            return existing

        try:
            knowledge_base = self.create(
                KnowledgeBase,
                name=RENDER_OUTPUT_BASE_NAME,
                description="系统预置：渲染成品的归集处（系统托管，不支持手动上传）",
                knowledge_scope=KnowledgeScope.USER_CONTENT.value,
                base_type=KnowledgeBaseType.VIDEO.value,
                partition_mode=PartitionMode.NONE.value,
                owner_account_id=account.id,
                owner_admin_user_id=None,
                operation_context=OperationContext.USER.value,
                visibility_scope=VisibilityScope.PRIVATE.value,
                created_from=KnowledgeCreatedFrom.RENDER_OUTPUT.value,
                settings={"operation_context": OperationContext.USER.value},
            )
        except IntegrityError:
            # 并发下已被另一请求建成：回滚后取既有库
            self.db.session.rollback()
            concurrent = _find()
            if concurrent is None:
                raise
            return concurrent

        # 与 create_user_content_base_with_req 同口径：自动选 embedding 模型，
        # 使成品可被检索复用（设计 §4.1「用户可让小钰从成品库翻旧片翻新」）
        selected_model = self.auto_select_embedding_model()
        return self.update(knowledge_base, embedding_model_id=selected_model.id)
```

补齐本条用到的枚举 import（若文件顶部尚未导入）：

```python
from internal.entity.knowledge_entity import (
    KnowledgeBaseType,
    KnowledgeCreatedFrom,
    KnowledgeScope,
    OperationContext,
    PartitionMode,
    VisibilityScope,
)
```

> 实施时先看文件顶部已有的 import，**按实际缺什么补什么**，不要整段覆盖。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_render_output_base.py -q --no-header --no-cov`

Expected: PASS（4 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_base_service.py api/test/internal/service/test_render_output_base.py
git commit -m "feat(knowledge): idempotent get_or_create for render output base"
```

---

## Task 4: 成品库禁止手动上传

成品库语义是「系统写入的成品」，用户手动上传会污染该语义（设计 §4.1）。三条上传入口都要挡：直传、分片合并建档、分片预校验。

**Files:**
- Modify: `api/internal/service/knowledge_base_service.py`
- Test: `api/test/internal/service/test_render_output_upload_rejected.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_render_output_upload_rejected.py`：

```python
"""成品库禁止手动上传测试（设计 §4.1）。

成品库由系统写入渲染产物；用户手动上传会污染「成品」语义。
三条上传入口都必须挡住：upload_document / create_document_from_upload_file /
assert_upload_allowed（分片上传在合并前预校验走这条）。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.knowledge_entity import KnowledgeCreatedFrom
from internal.exception import ForbiddenException
from internal.service.knowledge_base_service import KnowledgeBaseService


def _service(base):
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.get_accessible_base = lambda kb_id, account: base
    return service


def _render_base():
    return SimpleNamespace(
        id=uuid4(),
        base_type="video",
        created_from=KnowledgeCreatedFrom.RENDER_OUTPUT.value,
    )


def _normal_base():
    return SimpleNamespace(
        id=uuid4(),
        base_type="video",
        created_from=KnowledgeCreatedFrom.MANUAL_UPLOAD.value,
    )


def test_upload_document_rejected_for_render_base():
    service = _service(_render_base())

    with pytest.raises(ForbiddenException):
        service.upload_document(uuid4(), SimpleNamespace(filename="a.mp4"), SimpleNamespace(id=uuid4()))


def test_create_document_from_upload_file_rejected():
    service = _service(_render_base())
    upload_file = SimpleNamespace(id=uuid4(), extension="mp4", name="a.mp4")

    with pytest.raises(ForbiddenException):
        service.create_document_from_upload_file(
            knowledge_base_id=uuid4(), upload_file=upload_file, account=SimpleNamespace(id=uuid4())
        )


def test_assert_upload_allowed_rejected():
    service = _service(_render_base())

    with pytest.raises(ForbiddenException):
        service.assert_upload_allowed(uuid4(), "mp4", SimpleNamespace(id=uuid4()))


def test_normal_base_still_allows_video_upload():
    """回归保护：普通视频库不受影响（否则会误伤全部上传）。"""
    service = _service(_normal_base())

    result = service.assert_upload_allowed(uuid4(), "mp4", SimpleNamespace(id=uuid4()))

    assert result is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_render_output_upload_rejected.py -q --no-header --no-cov`

Expected: FAIL —— 未抛 `ForbiddenException`（当前无任何成品库判断）

- [ ] **Step 3: 实现**

在 `KnowledgeBaseService` 中新增静态方法（放在 `_assert_media_type_allowed` 之前）：

```python
    @staticmethod
    def _assert_not_render_output_base(knowledge_base: KnowledgeBase) -> None:
        """成品库为系统托管，禁止任何手动上传（设计 §4.1）。

        系统自身的成品写入走 store_render_output()，不经此校验——
        本校验只拦「用户上传」这条路径。
        """
        if (
            getattr(knowledge_base, "created_from", None)
            == KnowledgeCreatedFrom.RENDER_OUTPUT.value
        ):
            raise ForbiddenException("成品库为系统托管，不支持手动上传素材，请在素材库中上传")
```

在三处入口调用它：

1. `upload_document` —— 在 `knowledge_base = self.get_accessible_base(...)` 之后、校验扩展名之前：

```python
        self._assert_not_render_output_base(knowledge_base)
```

2. `create_document_from_upload_file` —— 在 `knowledge_base = self.get_accessible_base(...)` 之后：

```python
        self._assert_not_render_output_base(knowledge_base)
```

3. `assert_upload_allowed` —— 在 `knowledge_base = self.get_accessible_base(...)` 之后：

```python
        self._assert_not_render_output_base(knowledge_base)
```

> `ForbiddenException` 若未被 import，在文件顶部按既有风格补 `from internal.exception import ForbiddenException`（先看现有 import 是否已含）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_render_output_upload_rejected.py test/internal/service/test_knowledge_base_service.py -q --no-header --no-cov`

Expected: PASS（4 个新用例 + 既有知识库服务测试全绿）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_base_service.py api/test/internal/service/test_render_output_upload_rejected.py
git commit -m "feat(knowledge): reject manual upload into render output base"
```

---

## Task 5: composition 编译器（结构化 spec → HyperFrames HTML）

「编」层：把结构化脚本编译成 HyperFrames 能渲染的 HTML。必须是**纯函数**，便于穷举单测；输出必须满足已实测的契约（`data-composition-id` / `data-start` / `class="clip"` / `window.__timelines` 注册）。

**Files:**
- Create: `api/internal/core/video/__init__.py`
- Create: `api/internal/core/video/composition_builder.py`
- Test: `api/test/internal/core/video/test_composition_builder.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/core/video/test_composition_builder.py`：

```python
"""composition 编译器测试（纯函数，无 IO）。

输出必须满足 HyperFrames 已实测契约：
- 画布元素带 data-composition-id / data-start / data-duration / data-width / data-height
- 定时视觉元素带 class="clip" + data-start + data-duration
- 在 window.__timelines 注册该 composition 的 paused 根时间轴
- 文本必须 HTML 转义（防注入，脚本里出现 </script> 会破坏文档结构）
"""
import re

import pytest

from internal.core.video.composition_builder import (
    CompositionSpecError,
    build_composition_html,
)


def _spec(**overrides):
    spec = {
        "composition_id": "main",
        "width": 1920,
        "height": 1080,
        "duration": 10.0,
        "segments": [
            {"start": 0.0, "duration": 5.0, "text": "开场标题", "track_index": 0},
            {"start": 5.0, "duration": 5.0, "text": "第二幕", "track_index": 1},
        ],
    }
    spec.update(overrides)
    return spec


def test_canvas_carries_composition_contract():
    html = build_composition_html(_spec())

    assert 'data-composition-id="main"' in html
    assert 'data-width="1920"' in html
    assert 'data-height="1080"' in html
    assert 'data-duration="10"' in html or 'data-duration="10.0"' in html


def test_every_segment_becomes_a_timed_clip():
    html = build_composition_html(_spec())

    assert html.count('class="clip"') == 2
    assert 'data-start="0"' in html
    assert 'data-start="5"' in html
    assert 'data-duration="5"' in html


def test_root_timeline_is_registered_and_paused():
    html = build_composition_html(_spec())

    assert "window.__timelines" in html
    assert 'window.__timelines["main"]' in html
    assert "paused: true" in html


def test_segment_text_is_html_escaped():
    html = build_composition_html(
        _spec(segments=[{"start": 0.0, "duration": 1.0, "text": "<b>x</b>&y"}]),
    )

    assert "&lt;b&gt;x&lt;/b&gt;&amp;y" in html
    assert "<b>x</b>&y" not in html


def test_script_breakout_is_neutralized():
    """segment 文本含 </script> 不能逃逸出脚本块。"""
    html = build_composition_html(
        _spec(segments=[{"start": 0.0, "duration": 1.0, "text": "</script><script>x"}]),
    )

    assert html.count("<script>") == html.count("</script>") == 1


def test_media_segment_emits_video_with_media_start():
    """带素材的 segment 生成 <video>，并用 data-media-start 裁切源。"""
    html = build_composition_html(
        _spec(
            segments=[
                {
                    "start": 0.0,
                    "duration": 3.0,
                    "media_src": "clip.mp4",
                    "media_start": 2.5,
                    "track_index": 0,
                }
            ]
        ),
    )

    assert "<video" in html
    assert 'data-media-start="2.5"' in html
    assert 'src="clip.mp4"' in html


def test_video_is_muted_per_hyperframes_rule():
    """HyperFrames 规则：视频须 muted，音轨另用 <audio>。"""
    html = build_composition_html(
        _spec(segments=[{"start": 0.0, "duration": 3.0, "media_src": "clip.mp4"}])
    )

    video_tag = re.search(r"<video[^>]*>", html).group(0)
    assert "muted" in video_tag


def test_empty_segments_rejected():
    with pytest.raises(CompositionSpecError):
        build_composition_html(_spec(segments=[]))


def test_negative_start_rejected():
    with pytest.raises(CompositionSpecError):
        build_composition_html(
            _spec(segments=[{"start": -1.0, "duration": 1.0, "text": "x"}])
        )


def test_non_positive_duration_rejected():
    with pytest.raises(CompositionSpecError):
        build_composition_html(
            _spec(segments=[{"start": 0.0, "duration": 0, "text": "x"}])
        )


def test_blank_composition_id_rejected():
    with pytest.raises(CompositionSpecError):
        build_composition_html(_spec(composition_id="  "))


def test_output_has_no_nondeterministic_calls():
    """HyperFrames 要求确定性：不得出现 Date.now / Math.random。"""
    html = build_composition_html(_spec())

    assert "Date.now" not in html
    assert "Math.random" not in html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/video/test_composition_builder.py -q --no-header --no-cov`

Expected: FAIL —— `ModuleNotFoundError: No module named 'internal.core.video'`

- [ ] **Step 3: 实现**

新建 `api/internal/core/video/__init__.py`：

```python
"""视频制作核心能力：composition 编译与 HyperFrames 渲染。"""
from .composition_builder import CompositionSpecError, build_composition_html

__all__ = ["CompositionSpecError", "build_composition_html"]
```

新建 `api/internal/core/video/composition_builder.py`：

```python
"""把结构化视频脚本编译为 HyperFrames composition（HTML）。

「编」层：一个 segment（台词/镜头）= 一个容器，挂载素材/文本。
编译结果是 HyperFrames 可直接 lint/render 的 index.html。

契约（取自 HyperFrames 0.8.42 官方 scaffold，已实测渲染通过）：
- 画布元素：data-composition-id / data-start / data-duration / data-width / data-height
- 定时视觉元素：class="clip" + data-start + data-duration（+ 可选 data-track-index）
- 每个 composition 在 window.__timelines 注册一个 paused 根时间轴
- 确定性：禁 Date.now() / Math.random() / 网络请求

安全：所有用户可控文本一律 HTML 转义；否则文本里的 </script> 会逃逸出脚本块
（实测该场景会破坏文档结构）。
"""
from __future__ import annotations

import html as _html
from typing import Any

__all__ = ["CompositionSpecError", "build_composition_html"]


class CompositionSpecError(ValueError):
    """composition spec 非法（字段缺失/类型不符/数值越界）。"""


def _require_number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompositionSpecError(f"{field} 必须是数字，实际为 {type(value).__name__}")
    number = float(value)
    if minimum is not None and number < minimum:
        raise CompositionSpecError(f"{field} 不能小于 {minimum}，实际为 {number}")
    return number


def _format_seconds(value: float) -> str:
    """秒数格式化：整数去掉小数点（10.0 -> "10"），保留小数（2.5 -> "2.5"）。"""
    return str(int(value)) if float(value).is_integer() else str(value)


def _build_segment(segment: dict, index: int) -> str:
    if not isinstance(segment, dict):
        raise CompositionSpecError(f"segments[{index}] 必须是对象")

    start = _require_number(segment.get("start", 0.0), f"segments[{index}].start", minimum=0.0)
    duration = _require_number(segment.get("duration"), f"segments[{index}].duration")
    if duration <= 0:
        raise CompositionSpecError(f"segments[{index}].duration 必须大于 0")

    track_index = segment.get("track_index")
    track_attr = (
        f' data-track-index="{int(track_index)}"' if track_index is not None else ""
    )
    timing = (
        f'class="clip" data-start="{_format_seconds(start)}"'
        f' data-duration="{_format_seconds(duration)}"{track_attr}'
    )

    media_src = segment.get("media_src")
    if media_src:
        # HyperFrames 规则：视频须 muted，音轨另用 <audio> 元素承载
        media_start = segment.get("media_start")
        media_attr = (
            f' data-media-start="{_format_seconds(_require_number(media_start, f"segments[{index}].media_start", minimum=0.0))}"'
            if media_start is not None
            else ""
        )
        return (
            f'    <video id="seg-{index}" {timing}{media_attr}'
            f' src="{_html.escape(str(media_src), quote=True)}" muted playsinline></video>'
        )

    text = _html.escape(str(segment.get("text") or ""), quote=True)
    return f'    <div id="seg-{index}" {timing}>{text}</div>'


def build_composition_html(spec: dict) -> str:
    """把结构化 spec 编译为 HyperFrames composition 的 index.html 内容。

    spec 形状::

        {
          "composition_id": "main",
          "width": 1920, "height": 1080, "duration": 10.0,
          "segments": [
            {"start": 0.0, "duration": 5.0, "text": "开场"},                  # 文本段
            {"start": 5.0, "duration": 5.0, "media_src": "a.mp4",
             "media_start": 2.5, "track_index": 0},                          # 素材段
          ],
        }
    """
    if not isinstance(spec, dict):
        raise CompositionSpecError("spec 必须是对象")

    composition_id = str(spec.get("composition_id") or "").strip()
    if not composition_id:
        raise CompositionSpecError("composition_id 不能为空")

    width = _require_number(spec.get("width", 1920), "width")
    height = _require_number(spec.get("height", 1080), "height")
    duration = _require_number(spec.get("duration"), "duration")
    if duration <= 0:
        raise CompositionSpecError("duration 必须大于 0")

    segments = spec.get("segments")
    if not isinstance(segments, list) or not segments:
        raise CompositionSpecError("segments 必须是非空列表")

    body = "\n".join(
        _build_segment(segment, index) for index, segment in enumerate(segments)
    )
    safe_id = _html.escape(composition_id, quote=True)

    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={_format_seconds(width)}, height={_format_seconds(height)}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        margin: 0;
        width: {_format_seconds(width)}px;
        height: {_format_seconds(height)}px;
        overflow: hidden;
        background: #0a0a0a;
      }}
      #root {{
        position: relative;
        width: 100%;
        height: 100%;
        font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      }}
      .clip {{
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #f4f4f5;
        font-size: 64px;
        font-weight: 600;
      }}
      video.clip {{ object-fit: cover; }}
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="{safe_id}"
      data-start="0"
      data-duration="{_format_seconds(duration)}"
      data-width="{_format_seconds(width)}"
      data-height="{_format_seconds(height)}"
    >
{body}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      window.__timelines["{composition_id}"] = gsap.timeline({{ paused: true }});
      window.__timelines["{composition_id}"].seek(0);
    </script>
  </body>
</html>
"""
```

> **注意**：`composition_id` 用于 JS 字符串字面量，除 HTML 转义外还须是安全标识符。上面用 `_html.escape` 处理引号即可满足 `"..."` 场景；若实施时想更严，可加白名单断言 `re.fullmatch(r"[A-Za-z0-9_-]+", composition_id)`，但**需同步放宽 `test_blank_composition_id_rejected` 之外无其他约束**。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/video/test_composition_builder.py -q --no-header --no-cov`

Expected: PASS（13 个用例）

- [ ] **Step 5: 用真实 CLI 验证产物可 lint（集成验证，非 mock）**

把上一步产物写盘并用 HyperFrames **真实 lint** 校验契约（本机已实测 CLI 可用）：

```bash
python -c "import sys, json, pathlib; sys.path.insert(0,'.'); from internal.core.video.composition_builder import build_composition_html; d=pathlib.Path('tmp/composition_poc'); d.mkdir(parents=True, exist_ok=True); (d/'index.html').write_text(build_composition_html({'composition_id':'main','width':1920,'height':1080,'duration':10.0,'segments':[{'start':0.0,'duration':5.0,'text':'开场'},{'start':5.0,'duration':5.0,'text':'第二幕'}]}), encoding='utf-8'); print('written')"
cd tmp/composition_poc && npx --yes hyperframes lint
```

Expected: `0 errors, 0 warnings`（`lint` 会校验 `data-composition-id`、轨道重叠、时间轴注册）

> 环境前置：`hyperframes` 需要 Node ≥ 22。若本机没装 ffmpeg/Chromium，`lint` 仍可跑（只有 `render` 需要它们）。

- [ ] **Step 6: 清理临时目录并提交**

```bash
rm -rf api/tmp/composition_poc
git add api/internal/core/video/__init__.py api/internal/core/video/composition_builder.py api/test/internal/core/video/test_composition_builder.py
git commit -m "feat(video): compile structured spec into HyperFrames composition"
```

---

## Task 6: HyperFrames 渲染执行器

「渲」层：把 composition 写进工程目录，调 CLI 渲染出 MP4，并用 ffprobe 校验产物真实有效。**判定成功不能只看退出码**——CLI 曾在产物已生成后仍因最后一步探测失败而返回非 0（本机实测到该场景）。

**Files:**
- Create: `api/internal/core/video/hyperframes_renderer.py`
- Test: `api/test/internal/core/video/test_hyperframes_renderer.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/core/video/test_hyperframes_renderer.py`：

```python
"""HyperFrames 渲染执行器测试。

只对「可确定性判定」的部分做单测（命令构造 / 环境变量注入 / 产物校验 /
错误分型）；真实渲染调用通过注入的 runner 替身验证，避免单测依赖 Chromium。
"""
import subprocess
from pathlib import Path

import pytest

from internal.core.video.hyperframes_renderer import (
    RenderEnvironmentError,
    RenderFailedError,
    build_render_command,
    build_render_env,
    render_composition,
    verify_artifact,
)


class _Settings:
    HYPERFRAMES_CLI_VERSION = "0.8.42"
    HYPERFRAMES_BROWSER_PATH = r"C:\chrome\headless_shell.exe"
    HYPERFRAMES_FFMPEG_PATH = r"C:\ff\ffmpeg.exe"
    HYPERFRAMES_FFPROBE_PATH = r"C:\ff\ffprobe.exe"
    RENDER_TIMEOUT_SEC = 1800


def test_build_render_env_injects_three_paths():
    env = build_render_env(_Settings())

    assert env["HYPERFRAMES_BROWSER_PATH"] == r"C:\chrome\headless_shell.exe"
    assert env["HYPERFRAMES_FFMPEG_PATH"] == r"C:\ff\ffmpeg.exe"
    assert env["HYPERFRAMES_FFPROBE_PATH"] == r"C:\ff\ffprobe.exe"


def test_build_render_env_missing_ffprobe_raises():
    class _Missing(_Settings):
        HYPERFRAMES_FFPROBE_PATH = ""

    with pytest.raises(RenderEnvironmentError) as exc:
        build_render_env(_Missing())

    assert "HYPERFRAMES_FFPROBE_PATH" in str(exc.value)


def test_build_render_command_pins_cli_version():
    cmd = build_render_command(
        _Settings(), output_path=Path("out.mp4"), quality="draft", fps=30
    )

    assert cmd[0] == "npx"
    assert "hyperframes@0.8.42" in cmd, "CLI 版本必须钉死以保证结果可复现"
    assert "render" in cmd
    assert "out.mp4" in " ".join(cmd)
    assert "--quality" in cmd and "draft" in cmd


def test_unsupported_quality_rejected():
    with pytest.raises(RenderFailedError):
        build_render_command(
            _Settings(), output_path=Path("o.mp4"), quality="ultra", fps=30
        )


def test_render_composition_raises_when_artifact_missing(tmp_path):
    """CLI 退出码为 0 但没产物 -> 必须报错，不能返回不存在的文件。"""
    def _runner(cmd, cwd, env, timeout):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(RenderFailedError):
        render_composition(
            project_dir=tmp_path,
            output_path=tmp_path / "missing.mp4",
            settings=_Settings(),
            runner=_runner,
            prober=lambda path: 10.0,
        )


def test_render_composition_succeeds_when_artifact_and_probe_ok(tmp_path):
    output = tmp_path / "ok.mp4"

    def _runner(cmd, cwd, env, timeout):
        output.write_bytes(b"fake-mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    result = render_composition(
        project_dir=tmp_path,
        output_path=output,
        settings=_Settings(),
        runner=_runner,
        prober=lambda path: 10.0,
    )

    assert result == output


def test_render_composition_nonzero_exit_with_valid_artifact_still_fails(tmp_path):
    """本机实测：CLI 可能产物已生成但最后一步探测失败而非 0 退出。

    此时必须报错（让上层重试/报错），不能因为「产物在」就宣称成功——
    否则会把一个渲染流程被判失败的半成品当成品入库。
    """
    output = tmp_path / "half.mp4"

    def _runner(cmd, cwd, env, timeout):
        output.write_bytes(b"fake-mp4")
        return subprocess.CompletedProcess(cmd, 1, "", "Render artifact duration probe failed")

    with pytest.raises(RenderFailedError):
        render_composition(
            project_dir=tmp_path,
            output_path=output,
            settings=_Settings(),
            runner=_runner,
            prober=lambda path: 10.0,
        )


def test_verify_artifact_rejects_zero_duration(tmp_path):
    output = tmp_path / "bad.mp4"
    output.write_bytes(b"x")

    with pytest.raises(RenderFailedError):
        verify_artifact(output, prober=lambda path: 0.0)


def test_verify_artifact_rejects_empty_file(tmp_path):
    output = tmp_path / "empty.mp4"
    output.write_bytes(b"")

    with pytest.raises(RenderFailedError):
        verify_artifact(output, prober=lambda path: 10.0)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/video/test_hyperframes_renderer.py -q --no-header --no-cov`

Expected: FAIL —— `ImportError: cannot import name 'build_render_command'`

- [ ] **Step 3: 实现**

新建 `api/internal/core/video/hyperframes_renderer.py`：

```python
"""调用 HyperFrames CLI 把 composition 渲染为 MP4。

「渲」层。已实测要点（勿改，改了会静默坏）：

1. 必须注入三个路径环境变量：HYPERFRAMES_BROWSER_PATH / HYPERFRAMES_FFMPEG_PATH
   / HYPERFRAMES_FFPROBE_PATH；缺任一 CLI 会在启动阶段拒绝渲染。
2. 浏览器必须是「能响应 --version」的构建。实测 chrome-headless-shell 正常；
   部分完整版 Chrome 在受限环境下 --version 挂死，CLI 会判定
   "Chrome cannot start" 而拒绝启动。
3. ffprobe 必须是**真 ffprobe**：用 ffmpeg 冒充会因 `-print_format` 不支持而失败。
4. CLI 版本必须钉死（hyperframes@X.Y.Z），否则同一 composition 跨时间渲染结果可能漂移。
5. **退出码为 0 不等于成功、非 0 也不等于产物无用**：实测出现过「300 帧全部捕获
   并编码完成、产物已落盘，但最后一步 ffprobe 时长探测失败 → 非 0 退出」。
   因此本模块的判定是「退出码为 0 **且** 产物存在非空 **且** ffprobe 能读出正时长」，
   三者同时满足才返回成功；任一不满足一律抛错，交给上层重试，
   绝不把半成品当成品入库。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = [
    "RenderEnvironmentError",
    "RenderFailedError",
    "build_render_command",
    "build_render_env",
    "render_composition",
    "verify_artifact",
]

_SUPPORTED_QUALITIES = ("draft", "standard", "high")
_SUPPORTED_FPS = (24, 30, 60)

_REQUIRED_ENV_KEYS = (
    "HYPERFRAMES_BROWSER_PATH",
    "HYPERFRAMES_FFMPEG_PATH",
    "HYPERFRAMES_FFPROBE_PATH",
)


class RenderEnvironmentError(RuntimeError):
    """渲染环境不完整（缺二进制路径等）——属配置问题，重试无用。"""


class RenderFailedError(RuntimeError):
    """渲染失败（CLI 报错 / 产物缺失 / 产物无效）。"""


def build_render_env(settings: Any) -> dict[str, str]:
    """构造渲染子进程环境：继承当前环境 + 注入 HyperFrames 三个路径。

    三个路径缺任一直接报错并指名缺哪个——渲染是分钟级长任务，
    与其跑到一半失败，不如在启动前拦下。
    """
    env = dict(os.environ)
    missing: list[str] = []
    for key in _REQUIRED_ENV_KEYS:
        value = getattr(settings, key, "") or ""
        if not value:
            missing.append(key)
            continue
        env[key] = value
    if missing:
        raise RenderEnvironmentError(
            "渲染环境缺少必需配置：" + "、".join(missing) + "（见 .env.example 的渲染段）"
        )
    return env


def build_render_command(
    settings: Any, *, output_path: Path, quality: str = "standard", fps: int = 30
) -> list[str]:
    """构造渲染命令。CLI 版本钉死，参数白名单校验。"""
    if quality not in _SUPPORTED_QUALITIES:
        raise RenderFailedError(
            f"不支持的渲染质量：{quality}，可选：{list(_SUPPORTED_QUALITIES)}"
        )
    if int(fps) not in _SUPPORTED_FPS:
        raise RenderFailedError(f"不支持的帧率：{fps}，可选：{list(_SUPPORTED_FPS)}")

    version = getattr(settings, "HYPERFRAMES_CLI_VERSION", "") or "0.8.42"
    return [
        "npx",
        "--yes",
        f"hyperframes@{version}",
        "render",
        "--quality",
        quality,
        "--fps",
        str(int(fps)),
        "--output",
        str(output_path),
    ]


def probe_duration_sec(video_path: Path, settings: Any) -> float:
    """用真 ffprobe 读时长（秒）；读不出返回 0.0。

    不额外依赖外部 ffprobe 时也可复用 internal/core/vision/vision_invoke.py
    的探测思路，但那里解析的是 ffmpeg 的 stderr，产出的是「源文件时长」，
    与「渲染产物是否有效」是两件事，故此处独立实现。
    """
    ffprobe = getattr(settings, "HYPERFRAMES_FFPROBE_PATH", "") or "ffprobe"
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        logger.warning("ffprobe 探测失败 path=%s", video_path, exc_info=True)
        return 0.0
    if result.returncode != 0:
        return 0.0
    try:
        payload = json.loads(result.stdout or "{}")
        return float((payload.get("format") or {}).get("duration") or 0.0)
    except (ValueError, TypeError):
        return 0.0


def verify_artifact(
    output_path: Path, *, prober: Callable[[Path], float] | None = None
) -> float:
    """校验渲染产物：文件存在、非空、能读出正时长。返回时长秒数。"""
    probe = prober or (lambda path: 0.0)
    if not output_path.is_file():
        raise RenderFailedError(f"渲染产物不存在：{output_path}")
    if output_path.stat().st_size <= 0:
        raise RenderFailedError(f"渲染产物为空文件：{output_path}")
    duration = probe(output_path)
    if not duration or duration <= 0:
        raise RenderFailedError(f"渲染产物时长无效（{duration}），文件可能损坏：{output_path}")
    return float(duration)


def render_composition(
    *,
    project_dir: Path,
    output_path: Path,
    settings: Any,
    quality: str = "standard",
    fps: int = 30,
    timeout_sec: int | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    prober: Callable[[Path], float] | None = None,
) -> Path:
    """在 project_dir 内渲染 composition 到 output_path，返回校验通过的产物路径。

    `runner` / `prober` 为测试注入点（默认走真实 subprocess 与 ffprobe）。
    """
    project_dir = Path(project_dir)
    output_path = Path(output_path)
    if not (project_dir / "index.html").is_file():
        raise RenderFailedError(f"工程目录缺少 index.html：{project_dir}")

    env = build_render_env(settings)
    cmd = build_render_command(
        settings, output_path=output_path, quality=quality, fps=fps
    )
    run = runner or (
        lambda command, cwd, env, timeout: subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
    )
    if prober is None:
        prober = lambda path: probe_duration_sec(path, settings)

    timeout = int(timeout_sec or getattr(settings, "RENDER_TIMEOUT_SEC", 1800))
    logger.info("开始渲染 composition dir=%s output=%s", project_dir, output_path)

    try:
        result = run(cmd, str(project_dir), env, timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderFailedError(f"渲染超时（{timeout}s）：{project_dir}") from exc

    stdout = (getattr(result, "stdout", "") or "").strip()
    stderr = (getattr(result, "stderr", "") or "").strip()
    if result.returncode != 0:
        tail = (stderr or stdout)[-800:]
        raise RenderFailedError(f"渲染失败（exit={result.returncode}）：{tail}")

    duration = verify_artifact(output_path, prober=prober)
    logger.info("渲染完成 output=%s duration=%.2fs", output_path, duration)
    return output_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/video/test_hyperframes_renderer.py -q --no-header --no-cov`

Expected: PASS（10 个用例）

- [ ] **Step 5: 端到端真实渲染验证（关键，勿跳过）**

用真实 CLI 渲染 Task 5 生成的 composition，确认产出真 MP4：

```bash
python -c "import sys, pathlib; sys.path.insert(0,'.'); from internal.core.video.composition_builder import build_composition_html; d=pathlib.Path('tmp/render_e2e'); d.mkdir(parents=True, exist_ok=True); (d/'index.html').write_text(build_composition_html({'composition_id':'main','width':1920,'height':1080,'duration':10.0,'segments':[{'start':0.0,'duration':5.0,'text':'开场'},{'start':5.0,'duration':5.0,'text':'第二幕'}]}), encoding='utf-8'); print('ok')"
```

然后**先设置三个环境变量**（值按本机实际路径填；`.env` 里的 `HYPERFRAMES_*` 同样生效）：

```powershell
$env:HYPERFRAMES_BROWSER_PATH="<chrome-headless-shell 路径>"
$env:HYPERFRAMES_FFMPEG_PATH="<ffmpeg 路径>"
$env:HYPERFRAMES_FFPROBE_PATH="<真 ffprobe 路径>"
```

再渲染并用 ffprobe 复核：

```bash
cd tmp/render_e2e && npx --yes hyperframes@0.8.42 render --quality draft --fps 30 --output out.mp4
python -c "import json,subprocess,os; p=os.environ['HYPERFRAMES_FFPROBE_PATH']; r=subprocess.run([p,'-v','error','-show_entries','format=duration,format_name','-show_entries','stream=codec_name,width,height','-of','json','tmp/render_e2e/out.mp4'],capture_output=True,text=True); print(r.stdout or r.stderr)"
```

Expected: 生成 `out.mp4` 且 ffprobe 输出含 `h264`、`1920`、`1080` 与正 duration（本机实测为 `h264 / 1920x1080 / 30fps / 10.0s`）。

> 若此处失败，**先跑 `npx hyperframes doctor`** 定位是浏览器、ffmpeg 还是 ffprobe 不达标，不要改代码绕过。

- [ ] **Step 6: 清理并提交**

```bash
rm -rf api/tmp/render_e2e
git add api/internal/core/video/hyperframes_renderer.py api/test/internal/core/video/test_hyperframes_renderer.py
git commit -m "feat(video): render composition via HyperFrames CLI with artifact validation"
```

---

## Task 7: 成品配额宽让（设计 §6.3）

成品由**系统**写入，若因配额差一点而失败，会导致**整轮渲染白干**。故成品入库采用「宽让」语义：剩余 > 0 即放行（允许溢出）、恰好为 0 才拒绝。素材上传仍走严格路径，两者不能混。

**现状（已核实）**：配额收口在 `RuntimeStorageProxy.upload_bytes`，它无条件调 `check_quota(account_id, len(content))`（只读、无锁）+ `add_usage`。`check_quota` 超限抛 `ForbiddenException`（`data.reason_code="storage_quota_exceeded"`）。**没有任何 `allow_overflow` 类开关**，需要新增。

**Files:**
- Modify: `api/internal/service/storage_quota_service.py`
- Modify: `api/internal/service/storage/runtime_storage_service.py`
- Test: `api/test/internal/service/test_render_output_quota_relaxed.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_render_output_quota_relaxed.py`：

```python
"""成品入库的配额宽让测试（设计 §6.3）。

| | 素材上传（严格） | 成品入库（宽让） |
| 超限行为 | 拒绝 | 允许溢出 |
| 恰好剩余 0 | 拒绝 | 拒绝 |

理由：成品由系统写入，因配额差一点失败会让整轮渲染白干；
但「剩余 > 0」这道闸防止已超额用户无限产片。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException
from internal.service.storage_quota_service import StorageQuotaService


def _service(total, used):
    service = StorageQuotaService.__new__(StorageQuotaService)
    service.resolve_total_quota_bytes = lambda account_id: total
    service.get_used_bytes = lambda account_id: used
    return service


def test_relaxed_allows_overflow_when_remaining_positive():
    """剩余 1 字节但待写入 100MB -> 放行（允许溢出）。"""
    service = _service(total=1000, used=999)

    service.check_quota_allow_overflow(uuid4(), 100 * 1024 * 1024)


def test_relaxed_rejects_when_remaining_zero():
    service = _service(total=1000, used=1000)

    with pytest.raises(ForbiddenException) as exc:
        service.check_quota_allow_overflow(uuid4(), 1)

    assert exc.value.data["reason_code"] == "storage_quota_exceeded"


def test_relaxed_rejects_when_already_over_quota():
    service = _service(total=1000, used=2000)

    with pytest.raises(ForbiddenException):
        service.check_quota_allow_overflow(uuid4(), 1)


def test_strict_check_still_rejects_marginal_overflow():
    """回归保护：严格路径没被改松（否则素材上传会被顺带放开）。"""
    service = _service(total=1000, used=999)

    with pytest.raises(ForbiddenException):
        service.check_quota(uuid4(), 100)


def test_proxy_upload_bytes_uses_relaxed_checker_when_flagged():
    calls = []
    proxy = SimpleNamespace(
        storage_quota_service=SimpleNamespace(
            check_quota=lambda account_id, n: calls.append(("strict", n)),
            check_quota_allow_overflow=lambda account_id, n: calls.append(("relaxed", n)),
        ),
        _get_service=lambda: SimpleNamespace(
            upload_bytes=lambda **kwargs: SimpleNamespace(size=10)
        ),
    )
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    RuntimeStorageProxy.upload_bytes(
        proxy, filename="a.mp4", content=b"x" * 10, account_id=uuid4(), allow_overflow=True
    )

    assert calls and calls[0][0] == "relaxed", "allow_overflow=True 必须走宽让校验"


def test_proxy_upload_bytes_defaults_to_strict():
    calls = []
    proxy = SimpleNamespace(
        storage_quota_service=SimpleNamespace(
            check_quota=lambda account_id, n: calls.append(("strict", n)),
            check_quota_allow_overflow=lambda account_id, n: calls.append(("relaxed", n)),
        ),
        _get_service=lambda: SimpleNamespace(
            upload_bytes=lambda **kwargs: SimpleNamespace(size=10)
        ),
    )
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    RuntimeStorageProxy.upload_bytes(
        proxy, filename="a.mp4", content=b"x" * 10, account_id=uuid4()
    )

    assert calls and calls[0][0] == "strict", "缺省必须保持严格，不能顺带放开素材上传"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_render_output_quota_relaxed.py -q --no-header --no-cov`

Expected: FAIL —— `AttributeError: 'StorageQuotaService' object has no attribute 'check_quota_allow_overflow'`

- [ ] **Step 3: 增加宽让校验**

在 `api/internal/service/storage_quota_service.py` 的 `check_quota` 之后插入：

```python
    def check_quota_allow_overflow(self, account_id: UUID, incoming_bytes: int) -> None:
        """成品入库的**宽让**校验（设计 §6.3）：仅当剩余 <= 0 时拒绝，允许超量溢出。

        与 `check_quota` 的差别只在超限行为：
        - 素材上传（严格）：`used + incoming > total` 即拒绝；
        - 成品入库（宽让）：只要还有剩余就放行，写入后可能超额。

        为什么宽让：成品由系统写入，因配额差一点失败会让整轮渲染白干。
        为什么仍设闸：`remaining <= 0` 才拒绝，防止已超额用户无限产片。
        """
        total = self.resolve_total_quota_bytes(account_id)
        used = self.get_used_bytes(account_id)
        if total - used <= 0:
            raise ForbiddenException(
                "存储空间已满，请购买存储扩展包后重试",
                {
                    "total_bytes": total,
                    "used_bytes": used,
                    "incoming_bytes": incoming_bytes,
                    "reason_code": "storage_quota_exceeded",
                },
            )
```

> `ForbiddenException` 与 `UUID` 若已在文件中使用则无需重复导入（`_assert_within_quota` 已抛 `ForbiddenException`）。

- [ ] **Step 4: 让代理支持显式选择策略**

在 `api/internal/service/storage/runtime_storage_service.py` 的 `upload_bytes` 上增加 `allow_overflow` 参数（**默认 False，保持既有调用方行为不变**）：

```python
    def upload_bytes(
        self, *, filename, content, account_id, mime_type=None, folder="artifacts",
        allow_overflow: bool = False,
    ):
        """上传内存字节到当前激活后端并创建 UploadFile 记录。

        account_id 非空时受配额约束。
        `allow_overflow=True` 走宽让校验（仅当剩余 <= 0 拒绝），供系统写入成品使用
        （设计 §6.3）；其余场景保持严格，不要随意打开。
        """
        if account_id is not None:
            checker = (
                self.storage_quota_service.check_quota_allow_overflow
                if allow_overflow
                else self.storage_quota_service.check_quota
            )
            checker(account_id, len(content))

        upload_file = self._get_service().upload_bytes(
            filename=filename, content=content, account_id=account_id,
            mime_type=mime_type, folder=folder,
        )

        if account_id is not None:
            # 宽让也照常记账：溢出的部分要真实反映在用量里（网盘式语义）
            self.storage_quota_service.add_usage(account_id, upload_file.size or 0)
        return upload_file
```

> 实施时**保留原方法体内既有细节**（如 `mime_type`/`folder` 的传递方式），只在配额分支与签名上做上述改动，避免改变既有行为。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_render_output_quota_relaxed.py -q --no-header --no-cov`

Expected: PASS（6 个用例）

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/storage_quota_service.py api/internal/service/storage/runtime_storage_service.py api/test/internal/service/test_render_output_quota_relaxed.py
git commit -m "feat(storage): allow overflow quota policy for system-written render output"
```

---

## Task 8: 成品入库（MP4 → COS → 成品库 → 索引）

副本产物落到成品库并建索引，才能「被检索复用」（设计 §4.1）。这条是**系统写入**路径，绕开「禁止手动上传」校验，并按 Task 7 的宽让策略计价。

**Files:**
- Modify: `api/internal/service/knowledge_base_service.py`
- Modify: `api/internal/core/video/__init__.py`
- Test: `api/test/internal/service/test_store_render_output.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_store_render_output.py`：

```python
"""渲染成品入库测试。

成品由系统写入成品库：走 store_render_output（不经用户上传校验），
需落 COS、建 KnowledgeDocument、并触发索引（否则成品不可检索 = 白存）。
"""
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.knowledge_entity import KnowledgeCreatedFrom
from internal.service.knowledge_base_service import KnowledgeBaseService


class _Cos:
    def __init__(self):
        self.calls = []

    def upload_bytes(self, *, filename, content, account_id, mime_type="", allow_overflow=False):
        self.calls.append(
            {
                "filename": filename,
                "size": len(content),
                "mime_type": mime_type,
                "allow_overflow": allow_overflow,
            }
        )
        return SimpleNamespace(id=uuid4(), name=filename, extension="mp4")


def _service(base, cos, indexing):
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.get_or_create_render_output_base = lambda account: base
    service._get_cos_service = lambda: cos
    service._get_knowledge_indexing_service = lambda: indexing
    created = {}

    def _create(model, **kwargs):
        created.update(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)

    service.create = _create
    service.created_payload = created
    return service


def test_render_output_is_stored_and_indexed(tmp_path):
    video = tmp_path / "out.mp4"
    video.write_bytes(b"x" * 1024)
    base = SimpleNamespace(id=uuid4(), created_from=KnowledgeCreatedFrom.RENDER_OUTPUT.value)
    cos, indexing = _Cos(), SimpleNamespace(calls=[])
    indexing.build_document = lambda doc_id, account: indexing.calls.append(doc_id)
    service = _service(base, cos, indexing)
    account = SimpleNamespace(id=uuid4())

    document = service.store_render_output(
        account=account, video_path=video, name="我的短片"
    )

    assert cos.calls and cos.calls[0]["size"] == 1024
    assert cos.calls[0]["mime_type"] == "video/mp4"
    assert cos.calls[0]["allow_overflow"] is True, "成品入库必须走宽让配额（设计 §6.3）"
    assert service.created_payload["knowledge_base_id"] == base.id
    assert service.created_payload["media_type"] == "video"
    assert service.created_payload["source_type"] == KnowledgeCreatedFrom.RENDER_OUTPUT.value
    assert indexing.calls == [document.id], "必须触发索引，否则成品不可检索"


def test_missing_video_file_rejected(tmp_path):
    service = _service(SimpleNamespace(id=uuid4()), _Cos(), SimpleNamespace())
    account = SimpleNamespace(id=uuid4())

    with pytest.raises(Exception):
        service.store_render_output(
            account=account, video_path=tmp_path / "nope.mp4", name="x"
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_store_render_output.py -q --no-header --no-cov`

Expected: FAIL —— `AttributeError: 'KnowledgeBaseService' object has no attribute 'store_render_output'`

- [ ] **Step 3: 实现**

在 `api/internal/service/knowledge_base_service.py` 的 `create_document_from_upload_file` 之后插入：

```python
    def store_render_output(
        self,
        *,
        account: Account,
        video_path,
        name: str,
        base: KnowledgeBase | None = None,
    ) -> KnowledgeDocument:
        """把渲染成品写入成品库并建索引（设计 §4）。

        这是**系统写入**路径，供渲染链路调用，因此**不**经过
        `_assert_not_render_output_base`（那条只拦用户手动上传）。

        步骤：取/建成品库 → MP4 落 COS → 建 KnowledgeDocument → 触发索引。
        索引不可省：不建索引的成品检索不到，「可复用」即落空。
        """
        path = Path(video_path)
        if not path.is_file():
            raise NotFoundException(f"渲染产物不存在：{path}")

        knowledge_base = base or self.get_or_create_render_output_base(account)

        content = path.read_bytes()
        # 成品是系统写入，按设计 §6.3 走「宽让」配额：剩余 > 0 即放行（允许溢出），
        # 避免因配额差一点让整轮渲染白干；恰好为 0 仍拒绝。
        upload_file = self._get_cos_service().upload_bytes(
            filename=path.name,
            content=content,
            account_id=account.id,
            mime_type="video/mp4",
            allow_overflow=True,
        )

        document = self.create(
            KnowledgeDocument,
            knowledge_base_id=knowledge_base.id,
            owner_account_id=account.id,
            name=(name or path.stem),
            content_type="document",
            source_type=KnowledgeCreatedFrom.RENDER_OUTPUT.value,
            source_id=str(upload_file.id),
            upload_file_id=upload_file.id,
            partition_id=None,
            media_type=DocumentMediaType.VIDEO.value,
            parse_profile={},
            metadata_={
                "upload_file_id": str(upload_file.id),
                "operation_context": OperationContext.USER.value,
            },
            character_count=0,
            status=DocumentStatus.WAITING.value,
        )

        self._get_knowledge_indexing_service().build_document(document.id, account)
        return document
```

补齐 import（按文件实际缺什么补）：

```python
from pathlib import Path

from internal.entity.knowledge_entity import DocumentMediaType
from internal.model import KnowledgeDocument
```

> `DocumentMediaType` 与 `DocumentStatus` 若已在文件中使用（`create_document_from_upload_file` 用了 `media_type_for_extension` 与 `DocumentStatus.WAITING`），**按现有 import 风格补齐**，不要重复导入。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_store_render_output.py -q --no-header --no-cov`

Expected: PASS（2 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_base_service.py api/internal/core/video/__init__.py api/test/internal/service/test_store_render_output.py
git commit -m "feat(knowledge): store rendered output into render output base with indexing"
```

---

## Task 9: `render` Celery 队列与渲染任务

渲染是分钟级长任务（本机实测 10s 视频约 11s，长视频会到分钟级）。按设计 §3.2 用**独立 `render` 队列**，任务注册与派发点缺一不可。

> **依赖顺序说明**：本任务的任务体在**调用时**才经 `injector` 取 `RenderService`
> （Task 10 创建）。因此本任务的测试（只校验注册/路由/错误处理文本）此刻即可通过；
> 真正的派发点与可调用性在 Task 10 的工具挂载后成立。不要在本任务里提前实现渲染编排。

**Files:**
- Modify: `api/config/config.py:163-172`（队列与路由）
- Create: `api/internal/task/render_tasks.py`
- Modify: `api/app/http/celery_app.py:73-101,143-151`
- Test: `api/test/internal/task/test_render_tasks.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/task/test_render_tasks.py`：

```python
"""渲染 Celery 任务注册与队列隔离测试。

渲染任务必须同时具备：任务函数、TASK_MODULES 登记、显式 import、队列路由。
只有函数没有登记/路由 = 断链（AGENTS.md 强制审查项）。
"""
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
CELERY_APP = API_ROOT / "app/http/celery_app.py"
CONFIG = API_ROOT / "config/config.py"
TASK_FILE = API_ROOT / "internal/task/render_tasks.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_task_module_exists():
    assert TASK_FILE.is_file(), "缺少渲染任务模块"


def test_task_module_registered_in_celery():
    source = _read(CELERY_APP)
    assert "render_tasks" in source, "任务模块必须登记进 TASK_MODULES"


def test_task_module_explicitly_imported():
    source = _read(CELERY_APP)
    assert "internal.task.render_tasks as" in source


def test_render_queue_declared_and_routed():
    source = _read(CONFIG)
    assert 'Queue("render")' in source, "必须声明 render 队列"
    assert "internal.task.render_tasks.*" in source, "必须把渲染任务路由到 render 队列"


def test_task_uses_shared_task_with_explicit_name():
    source = _read(TASK_FILE)
    assert "@shared_task" in source
    assert "internal.task.render_tasks." in source


def test_task_is_retryable_and_uses_injector():
    source = _read(TASK_FILE)
    assert "max_retries" in source
    assert "self.retry" in source
    assert "injector" in source
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/task/test_render_tasks.py -q --no-header --no-cov`

Expected: FAIL —— 「缺少渲染任务模块」等

- [ ] **Step 3: 声明队列与路由**

在 `api/config/config.py` 的 `task_queues` 元组末尾追加 `Queue("render")`：

```python
            "task_queues": (
                Queue("celery"),
                Queue("mail"),
                Queue("consolidation"),
                # 渲染是分钟级长任务，独立队列以免与业务任务争抢 worker
                # （消费方必须显式 `-Q render`，见 Dockerfile.render / entrypoint）
                Queue("render"),
            ),
```

在 `task_routes` 字典末尾追加：

```python
                "internal.task.render_tasks.*": {"queue": "render"},
```

- [ ] **Step 4: 实现任务模块**

新建 `api/internal/task/render_tasks.py`：

```python
"""渲染任务：把 composition 渲染为 MP4 并写入成品库。

长任务（分钟级），走独立 `render` 队列；消费 worker 必须显式 `-Q render`，
否则会与业务任务争抢（设计 §3.2）。

失败重试策略：渲染失败多为环境/资源瞬时问题（浏览器崩溃、超时），
故 retry 2 次、间隔 60s；环境配置类错误（缺二进制路径）不重试——
重试也必然失败，只浪费时间。
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.render_tasks.render_composition_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def render_composition_task(self, composition_spec: dict, account_id: str, name: str = ""):
    """渲染一段 composition 并把成品写入成品库。

    入参：composition_spec（结构化脚本，见 composition_builder）、
    account_id（成品的归属账号）、name（成品名称，缺省用文件名）。
    """
    from app.http.module import injector
    from internal.core.video.hyperframes_renderer import (
        RenderEnvironmentError,
        RenderFailedError,
    )
    from internal.service.render_service import RenderService

    try:
        service = injector.get(RenderService)
        return service.render_to_render_output_base(
            composition_spec=composition_spec, account_id=account_id, name=name
        )
    except RenderEnvironmentError:
        # 配置问题：重试无意义，直接失败并留下可读日志
        logger.exception("渲染环境配置不完整，放弃重试")
        raise
    except RenderFailedError as exc:
        logger.warning("渲染失败，准备重试：%s", exc, exc_info=True)
        raise self.retry(exc=exc)
```

- [ ] **Step 5: 注册到 Celery**

在 `api/app/http/celery_app.py` 的 `TASK_MODULES` 列表末尾追加：

```python
    "internal.task.render_tasks",
```

在同文件的显式 import 段末尾追加：

```python
import internal.task.render_tasks as _task_render  # noqa: F401,E402
```

在 `task_routes.update({...})` 中追加：

```python
        "internal.task.render_tasks.*": {"queue": "render"},
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest test/internal/task/test_render_tasks.py -q --no-header --no-cov`

Expected: PASS（6 个用例）

- [ ] **Step 7: 提交**

```bash
git add api/config/config.py api/app/http/celery_app.py api/internal/task/render_tasks.py api/test/internal/task/test_render_tasks.py
git commit -m "feat(video): add dedicated render queue and render task"
```

---

## Task 10: 渲染服务与对话内入口

把「编 → 渲 → 库」串成服务，并接到对话内工具。**两处必做，否则断链**：
(1) 工具必须有**运行时挂载点**；(2) 工具必须**派发 Celery `render` 任务**（Task 9），
否则该任务永远无调用方。

**Files:**
- Create: `api/internal/service/render_service.py`
- Create: `api/internal/core/tools/builtin_tools/providers/video_render_tools/{__init__.py,render_video.py,render_video.yaml,positions.yaml}`
- Modify: `api/internal/core/tools/builtin_tools/providers/providers.yaml`
- Modify: `api/internal/service/assistant_agent_service.py`
- Test: `api/test/internal/service/test_render_service.py`
- Test: `api/test/internal/core/tools/test_render_video_tool.py`

- [ ] **Step 1: 写失败测试（服务层）**

新建 `api/test/internal/service/test_render_service.py`：

```python
"""渲染服务编排测试：编 -> 渲 必须串起来。

用替身隔离真实 subprocess、DB 与 Flask app context，只验证编排契约：
spec 交给编译器、编译产物写盘为 index.html、渲染器拿到工程目录与产物路径。
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from internal.service.render_service import RenderService


def _spec():
    return {
        "composition_id": "main",
        "duration": 5.0,
        "segments": [{"start": 0, "duration": 5, "text": "x"}],
    }


def _wire(monkeypatch, calls):
    """把编译/渲染/配置三处替换为替身（monkeypatch 模块级符号与类方法）。"""
    import internal.service.render_service as module

    def _build(self, spec):
        calls["spec"] = spec
        return "<html>compiled</html>"

    def _render(self, *, project_dir, output_path, settings, quality, fps):
        calls["project_dir"] = Path(project_dir)
        calls["output_path"] = Path(output_path)
        calls["quality"] = quality
        calls["fps"] = fps
        if calls.get("fail"):
            raise calls["fail"]
        Path(output_path).write_bytes(b"mp4")

    monkeypatch.setattr(RenderService, "_build_composition", _build)
    monkeypatch.setattr(RenderService, "_render", _render)
    monkeypatch.setattr(module, "_load_settings", lambda: SimpleNamespace())


def test_render_writes_composition_and_invokes_renderer(tmp_path, monkeypatch):
    calls = {}
    _wire(monkeypatch, calls)
    service = RenderService.__new__(RenderService)

    result = service.render_composition(
        composition_spec=_spec(), work_dir=tmp_path / "job1", quality="draft", fps=30
    )

    assert calls["spec"] == _spec()
    assert (calls["project_dir"] / "index.html").read_text(encoding="utf-8") == "<html>compiled</html>"
    assert calls["output_path"] == calls["project_dir"] / "output.mp4"
    assert calls["quality"] == "draft" and calls["fps"] == 30
    assert result.endswith(".mp4")


def test_render_propagates_failure(tmp_path, monkeypatch):
    from internal.core.video.hyperframes_renderer import RenderFailedError

    calls = {"fail": RenderFailedError("boom")}
    _wire(monkeypatch, calls)
    service = RenderService.__new__(RenderService)

    with pytest.raises(RenderFailedError):
        service.render_composition(
            composition_spec=_spec(), work_dir=tmp_path / "job2", quality="draft", fps=30
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_render_service.py -q --no-header --no-cov`

Expected: FAIL —— `ModuleNotFoundError: No module named 'internal.service.render_service'`

- [ ] **Step 3: 实现渲染服务**

新建 `api/internal/service/render_service.py`：

```python
"""渲染编排服务：编（compile）→ 渲（render）→ 库（store）。

把三个纯/半纯部件串起来，并负责工作目录生命周期与账号解析。
渲染产物落成品库后返回 KnowledgeDocument，供上层回链给用户。
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from injector import inject

from internal.core.video.composition_builder import build_composition_html
from internal.core.video.hyperframes_renderer import render_composition as _render
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

logger = logging.getLogger(__name__)


def _load_settings():
    """取渲染所需的运行时配置（Flask config）。

    独立成模块级函数便于测试替换——渲染服务本身不需要 app context 的其他部分。
    """
    from flask import current_app

    return current_app.config


@inject
@dataclass
class RenderService(BaseService):
    """视频渲染编排。

    依赖注入遵循本仓库既有约定：`@inject` + `@dataclass`，`db` 为注入字段
    （参见 `StorageQuotaService`）。不要改成手写 `__init__`——injector 依赖该形态构造。
    """
    db: SQLAlchemy

    # ---- 可替换点：测试 monkeypatch 这两处，隔离真实编译/渲染 ----
    def _build_composition(self, spec: dict) -> str:
        return build_composition_html(spec)

    def _render(self, *, project_dir, output_path, settings, quality, fps):
        return _render(
            project_dir=Path(project_dir),
            output_path=Path(output_path),
            settings=settings,
            quality=quality,
            fps=fps,
        )

    def render_composition(
        self,
        *,
        composition_spec: dict,
        work_dir=None,
        quality: str = "standard",
        fps: int = 30,
    ) -> str:
        """编译并渲染，返回产物 MP4 的绝对路径字符串。

        work_dir 缺省时用临时目录，调用方负责清理（见 _cleanup）。
        """
        owns_dir = work_dir is None
        directory = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="hf-render-"))
        directory.mkdir(parents=True, exist_ok=True)

        (directory / "index.html").write_text(
            self._build_composition(composition_spec), encoding="utf-8"
        )
        output_path = directory / "output.mp4"
        try:
            self._render(
                project_dir=directory,
                output_path=output_path,
                settings=_load_settings(),
                quality=quality,
                fps=fps,
            )
        except Exception:
            if owns_dir:
                shutil.rmtree(directory, ignore_errors=True)
            raise
        return str(output_path)

    def render_to_render_output_base(
        self, *, composition_spec: dict, account_id, name: str = "", quality: str = "standard"
    ) -> dict:
        """渲染并写入成品库，返回可回给用户的结果。"""
        from internal.service.account_service import AccountService
        from internal.service.knowledge_base_service import KnowledgeBaseService

        account = self._get_service(AccountService).get_account(UUID(str(account_id)))
        if account is None:
            raise ValueError(f"账号不存在：{account_id}")

        work_dir = Path(tempfile.mkdtemp(prefix="hf-job-"))
        try:
            output_path = self.render_composition(
                composition_spec=composition_spec,
                work_dir=work_dir,
                quality=quality,
            )
            document = self._get_service(KnowledgeBaseService).store_render_output(
                account=account, video_path=output_path, name=name or "渲染成品"
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        return {
            "document_id": str(document.id),
            "knowledge_base_id": str(document.knowledge_base_id),
            "name": document.name,
        }

    def _get_service(self, cls):
        from app.http.module import injector

        return injector.get(cls)
```

> `_build_composition` / `_render` 是**测试替换点**：测试用
> `monkeypatch.setattr(RenderService, "_build_composition", ...)` 隔离真实编译与渲染，
> 因此它们必须是**实例方法**（首个参数 `self`），不要改成静态方法或模块级函数。
> 同理 `_load_settings` 保持模块级函数，测试 patch 模块属性即可。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_render_service.py -q --no-header --no-cov`

Expected: PASS（2 个用例）

- [ ] **Step 5: 写失败测试（工具层）**

新建 `api/test/internal/core/tools/test_render_video_tool.py`：

```python
"""render_video 工具测试：参数校验与错误可读化。

工具不抛异常到 Agent 层，一律返回 {"ok": false, "error": ...}。
"""
import json

import pytest

from internal.core.tools.builtin_tools.providers.video_render_tools.render_video import (
    render_video,
)


def test_missing_account_returns_readable_error():
    tool = render_video()
    payload = json.loads(
        tool._run(
            composition={"composition_id": "main", "duration": 1.0, "segments": [{"start": 0, "duration": 1, "text": "x"}]}
        )
    )

    assert payload["ok"] is False
    assert "账号" in payload["error"]


def test_missing_composition_returns_readable_error():
    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    payload = json.loads(tool._run(composition={}))

    assert payload["ok"] is False
    assert "脚本" in payload["error"] or "composition" in payload["error"]


def test_empty_segments_returns_readable_error():
    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    payload = json.loads(tool._run(composition={"composition_id": "main", "duration": 1.0, "segments": []}))

    assert payload["ok"] is False


def test_factory_binds_account_id():
    tool = render_video(account_id="abc")

    assert tool.account_id == "abc"


def test_dispatch_prefers_celery(monkeypatch):
    """Celery 可用时必须走后台渲染，不能同步阻塞对话请求。"""
    import sys
    from types import ModuleType, SimpleNamespace

    import internal.core.tools.builtin_tools.providers.video_render_tools.render_video as module

    dispatched = {}

    class _Task:
        def delay(self, composition, account_id, name):
            dispatched["args"] = (composition, account_id, name)
            return SimpleNamespace(id="task-1")

    fake = ModuleType("internal.task.render_tasks")
    fake.render_composition_task = _Task()
    monkeypatch.setitem(sys.modules, "internal.task.render_tasks", fake)

    def _boom(*args, **kwargs):
        raise AssertionError("Celery 可用时不得走同步执行")

    monkeypatch.setattr(module, "_load_render_service", _boom)

    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    composition = {
        "composition_id": "main",
        "duration": 1.0,
        "segments": [{"start": 0, "duration": 1, "text": "x"}],
    }
    payload = json.loads(tool._run(composition=composition, name="片"))

    assert payload["ok"] is True
    assert payload["dispatched"] is True
    assert payload["task_id"] == "task-1"
    assert dispatched["args"][0] is composition, "脚本必须原样透传给任务"


def test_dispatch_falls_back_to_sync_when_celery_unavailable(monkeypatch):
    """派发失败必须回退同步执行，不能把请求丢掉（与 L2 触发同口径）。"""
    import sys
    from types import ModuleType

    import internal.core.tools.builtin_tools.providers.video_render_tools.render_video as module

    class _Task:
        def delay(self, *args, **kwargs):
            raise RuntimeError("broker down")

    fake = ModuleType("internal.task.render_tasks")
    fake.render_composition_task = _Task()
    monkeypatch.setitem(sys.modules, "internal.task.render_tasks", fake)

    called = {}

    class _Service:
        def render_to_render_output_base(self, *, composition_spec, account_id, name):
            called["name"] = name
            return {"document_id": "d1", "knowledge_base_id": "k1", "name": name}

    monkeypatch.setattr(module, "_load_render_service", lambda: _Service())

    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    composition = {
        "composition_id": "main",
        "duration": 1.0,
        "segments": [{"start": 0, "duration": 1, "text": "x"}],
    }
    payload = json.loads(tool._run(composition=composition, name="片"))

    assert payload["ok"] is True
    assert payload["dispatched"] is False
    assert payload["document_id"] == "d1"
    assert called["name"] == "片"
```

- [ ] **Step 6: 运行测试确认失败**

Run: `python -m pytest test/internal/core/tools/test_render_video_tool.py -q --no-header --no-cov`

Expected: FAIL —— `ModuleNotFoundError: ...video_render_tools`

- [ ] **Step 7: 实现工具（四件套）**

新建 `api/internal/core/tools/builtin_tools/providers/video_render_tools/__init__.py`：

```python
"""视频渲染工具包。"""
from .render_video import render_video

__all__ = ["render_video"]
```

新建 `api/internal/core/tools/builtin_tools/providers/video_render_tools/positions.yaml`：

```yaml
- render_video
```

新建 `api/internal/core/tools/builtin_tools/providers/video_render_tools/render_video.yaml`：

```yaml
name: render_video
label: 渲染视频
description: 把小钰编排好的视频脚本渲染成 MP4 成品，并自动存入用户的成品库，可在成品库中检索与复用。
params:
- name: composition
  label: 视频脚本
  type: string
  required: true
- name: name
  label: 成品名称
  type: string
  required: false
task_keywords:
- 渲染视频
- 生成视频
- 导出视频
- 出片
- 制作视频
- 剪视频
- 合成视频
- render video
```

新建 `api/internal/core/tools/builtin_tools/providers/video_render_tools/render_video.py`：

```python
"""渲染视频工具（对话内出片）。

小钰把编排好的视频脚本交给渲染链路：编译为 HyperFrames composition →
渲染为 MP4 → 自动存入用户的成品库（系统预置、每用户唯一）。

account 获取方式与 create_knowledge_base 一致：由运行时挂载点通过工厂参数
account_id 注入当前账号。builtin 工具没有全局 g.account，不做上下文穿透。

渲染是分钟级长任务：优先派发 Celery `render` 队列，不可用时回退同步执行，
避免请求静默丢失（与 L2 触发同一容错口径）。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_render_service():
    from app.http.module import injector
    from internal.service.render_service import RenderService

    return injector.get(RenderService)


def _dispatch_render(composition: dict, account_id: str, name: str) -> dict:
    """派发渲染：Celery `render` 队列优先，不可用时回退同步执行。

    渲染是分钟级长任务，必须走后台，否则会把对话请求挂住。但派发本身可能失败
    （broker 不可用），此时**回退同步**而不是把请求丢掉——与 L2 触发同一容错口径
    （`KnowledgeBaseService._dispatch_document_l2`）。

    返回 {"mode": "celery"|"sync", "result": ...}。
    """
    try:
        from internal.task.render_tasks import render_composition_task

        async_result = render_composition_task.delay(composition, account_id, name)
        return {"mode": "celery", "result": async_result}
    except Exception:
        logger.warning(
            "渲染派发 Celery 失败，回退同步执行 account_id=%s", account_id, exc_info=True
        )
        service = _load_render_service()
        return {
            "mode": "sync",
            "result": service.render_to_render_output_base(
                composition_spec=composition, account_id=account_id, name=name
            ),
        }


class RenderVideoInput(BaseModel):
    """渲染视频的输入模型。"""

    composition: dict = Field(
        ...,
        description=(
            "视频脚本。形如 {composition_id, width, height, duration, segments}，"
            "segments 每项含 start（秒）、duration（秒）、以及 text 或 media_src（素材路径）"
        ),
    )
    name: str = Field("", description="成品名称，可选")


class RenderVideoTool(BaseTool):
    """把视频脚本渲染为 MP4 并存入成品库。"""

    name: str = "render_video"
    description: str = (
        "当用户要求生成/渲染/制作/导出视频成片时调用。"
        "传入结构化视频脚本，系统会渲染为 MP4 并自动存入用户的成品库（可在成品库检索复用）。"
        "渲染耗时较长（分钟级），会转入后台执行。"
    )
    args_schema: type[BaseModel] = RenderVideoInput
    account_id: str = ""

    def _run(
        self,
        composition: dict | None = None,
        name: str = "",
        **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps(
                {"ok": False, "error": "缺少当前账号信息，无法出片"}, ensure_ascii=False
            )

        if not isinstance(composition, dict) or not composition.get("segments"):
            return json.dumps(
                {"ok": False, "error": "视频脚本为空：需要 composition.segments 至少一段"},
                ensure_ascii=False,
            )

        normalized_name = str(name or "").strip()
        try:
            dispatched = _dispatch_render(composition, account_id, normalized_name)
        except Exception as exc:
            logger.warning("渲染视频失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"渲染视频失败：{exc}"}, ensure_ascii=False
            )

        if dispatched["mode"] == "celery":
            return json.dumps(
                {
                    "ok": True,
                    "dispatched": True,
                    "task_id": str(getattr(dispatched["result"], "id", "")),
                    "message": "视频渲染已提交后台处理，完成后会自动存入成品库",
                },
                ensure_ascii=False,
            )

        result = dispatched["result"]
        return json.dumps(
            {
                "ok": True,
                "dispatched": False,
                "document_id": result.get("document_id", ""),
                "knowledge_base_id": result.get("knowledge_base_id", ""),
                "name": result.get("name", ""),
                "message": "视频已渲染完成并存入成品库",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self, composition: dict | None = None, name: str = "", **kwargs: Any
    ) -> str:
        return self._run(composition=composition, name=name, **kwargs)


def render_video(**kwargs: Any) -> BaseTool:
    """工厂函数：返回渲染视频的 LangChain 工具。"""
    return RenderVideoTool(account_id=str(kwargs.get("account_id") or "").strip())
```

- [ ] **Step 8: 登记 provider**

在 `api/internal/core/tools/builtin_tools/providers/providers.yaml` 末尾追加：

```yaml
- name: video_render_tools
  label: 视频渲染工具
  description: 视频渲染能力，支持 Agent 在对话内把视频脚本渲染为 MP4 并存入成品库。
  icon: ""
  background: "#F3E8FF"
  category: video
  created_at: 1789200000
```

- [ ] **Step 9: 补运行时挂载点（不做 = 断链）**

在 `api/internal/service/assistant_agent_service.py` 的 `_build_assistant_runtime_tools` 中，紧接 `create_knowledge_base` 挂载块之后追加：

```python
            # 视频渲染工具：Agent 可在对话内把脚本渲染成 MP4 并存入成品库。
            render_tool_factory = self.app_config_service.builtin_provider_manager.get_tool(
                "video_render_tools",
                "render_video",
            )
            if render_tool_factory is not None:
                tools.append(render_tool_factory(account_id=str(account_id)))
```

> 与相邻挂载块保持同样的 `try/except` 容错风格——若相邻块已把整段包在 try 里，直接放进同一 try；否则给本段单独包一层并只打 warning。

- [ ] **Step 10: 运行全部新测试**

Run: `python -m pytest test/internal/core/tools/test_render_video_tool.py test/internal/service/test_render_service.py test/internal/core/video -q --no-header --no-cov`

Expected: PASS

- [ ] **Step 11: 提交**

```bash
git add api/internal/service/render_service.py api/internal/core/tools/builtin_tools/providers/video_render_tools api/internal/core/tools/builtin_tools/providers/providers.yaml api/internal/service/assistant_agent_service.py api/test/internal/service/test_render_service.py api/test/internal/core/tools/test_render_video_tool.py
git commit -m "feat(video): add render service and in-conversation render_video tool"
```

---

## Task 11: 同步架构文档

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/prd/execution-roadmap.md`
- Modify: `docs/prd/knowledge-base-product-form-design.md`

- [ ] **Step 1: 02-knowledge-base.md 增成品库章节**

在 §11.12 之后追加：

```markdown
### 11.13 系统预置成品库（P4 已落地）

渲染成品需要一个**确定的、唯一的、系统托管的**归集处，故不新增 `base_type`，
而是每用户预置一个成品库（设计 §4.1）。

| 项 | 值 |
| --- | --- |
| 标识 | `knowledge_base.created_from = 'render_output'`（`KnowledgeCreatedFrom.RENDER_OUTPUT`） |
| 名称 | `成品库`（常量 `RENDER_OUTPUT_BASE_NAME`） |
| 归属 | 用户私有（`knowledge_scope=user_content`、`owner_account_id=账号`），每账号**至多一个** |
| 唯一性 | PostgreSQL **部分唯一索引** `knowledge_base_render_output_uniq`（`WHERE created_from='render_output'`）；不能用全表唯一约束——`manual_upload` 等同账号下允许多个 |
| 创建时机 | 首次写成品时 `get_or_create_render_output_base` 幂等创建（不给从未出片的用户平白建库）；并发冲突靠唯一索引兜底后重查 |
| 禁止手动上传 | `upload_document` / `create_document_from_upload_file` / `assert_upload_allowed` 三处均经 `_assert_not_render_output_base` 拒绝 |
| 系统写入 | `KnowledgeBaseService.store_render_output()` —— 落 COS → 建成品库 `KnowledgeDocument`（`source_type='render_output'`、`media_type=video`）→ 触发索引。**该路径不经「禁止上传」校验**（那条只拦用户上传） |

成品库走**同一套 P3 检索**（分区/媒体类型/标签/相似度阈值），因此「可复用」天然成立——
用户可让小钰从成品库翻旧片翻新。
```

- [ ] **Step 2: execution-roadmap.md 追加 P3.7**

在 P3.6 小节之后追加：

```markdown
### 知识库产品形态 P3.7：HyperFrames 渲染宿主与成品库（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **渲染运行时配置** | `config/config.py`（`HYPERFRAMES_BROWSER_PATH` / `HYPERFRAMES_FFMPEG_PATH` / `HYPERFRAMES_FFPROBE_PATH` / `HYPERFRAMES_CLI_VERSION` / `RENDER_TIMEOUT_SEC`） | ✅ 已落地；CLI 版本钉死 0.8.42 |
| **成品库标识与唯一约束** | `knowledge_entity.py`（`RENDER_OUTPUT`）+ 迁移 `w1e2f3a4b5c6` | ✅ 已落地；部分唯一索引保证每账号至多一个 |
| **成品库幂等创建与禁上传** | `knowledge_base_service.py`（`get_or_create_render_output_base` / `_assert_not_render_output_base`） | ✅ 已落地；三条上传入口均拒绝 |
| **composition 编译器** | `internal/core/video/composition_builder.py`（`build_composition_html`） | ✅ 已落地；纯函数，输出经真实 `hyperframes lint` 校验（0 errors） |
| **渲染执行器** | `internal/core/video/hyperframes_renderer.py`（`render_composition` / `verify_artifact`） | ✅ 已落地；**实测产出 h264 1920x1080 MP4** |
| **成品入库** | `knowledge_base_service.py`（`store_render_output`） | ✅ 已落地；落 COS + 建档 + 触发索引 |
| **成品配额宽让** | `storage_quota_service.py`（`check_quota_allow_overflow`）+ `runtime_storage_service.py`（`upload_bytes(allow_overflow=True)`） | ✅ 已落地；剩余 > 0 即放行（允许溢出），恰好为 0 拒绝（设计 §6.3）。**素材上传仍严格** |
| **render 队列与任务** | `config/config.py`（`Queue("render")`）+ `internal/task/render_tasks.py` | ✅ 已落地；已登记 `TASK_MODULES` 并配路由；派发点见下 |
| **对话内入口** | `video_render_tools`（`render_video`）+ 挂载点 `assistant_agent_service._build_assistant_runtime_tools` | ✅ 已落地；工具派发 `render_composition_task`（Celery 优先、失败回退同步） |

> **尚未落地（另立部署计划）**：渲染 worker 镜像与 `-Q render` 容器隔离编排
> （`api/Dockerfile.render` 等）。渲染底座需 Node ≥ 22 + Chromium + ffmpeg/ffprobe 三件齐全；
> 现有 `api/Dockerfile`（有 node、无 chromium/ffmpeg）与 `api/Dockerfile.worker`
> （有 playwright/chromium、无 node/ffmpeg）**都不能直接复用**。
> 参考 HyperFrames 自有渲染镜像的形态：`FROM node:22-bookworm-slim` + `npm i -g hyperframes@<钉死版本>`。
> 在镜像就绪前，`render` 队列任务需由具备上述三件的环境消费。
```

- [ ] **Step 3: 修正 product-form 文档的过时状态**

`docs/prd/knowledge-base-product-form-design.md` 中把：

```
| 视频轻量编辑工具（新增） | `video_trim` / `video_concat` / `video_subtitle` | ⬜ 规划（P4） |
```

改为照实描述（**不要写成已实现 `video_trim` 等工具——它们并未实现**）：

```
| 视频渲染出片（新增） | `render_video`（builtin provider `video_render_tools`）+ 成品库 | ✅ **已落地**（P4）：结构化脚本 → HyperFrames 编译 → 渲染 MP4 → 存入成品库。`video_trim` / `video_concat` / `video_subtitle` 三个独立编辑工具**未实现**——当前经 composition 的 `data-media-start` 裁切与多轨排布实现同等能力 |
```

- [ ] **Step 4: 提交**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/execution-roadmap.md docs/prd/knowledge-base-product-form-design.md
git commit -m "docs(knowledge): document HyperFrames render host and render output base"
```

- [ ] **Step 5: 刷新知识图谱**

Run: `python -m graphify update .`

---

## 自检清单（实施者收尾前逐项确认）

- [ ] **每个新符号都点名入口**：
  - `build_composition_html` → `RenderService._build_composition` → `render_composition_task`
  - `render_composition`（执行器）→ `RenderService._render`
  - `store_render_output` → `RenderService.render_to_render_output_base`
  - `get_or_create_render_output_base` → `store_render_output`
  - `check_quota_allow_overflow` → `RuntimeStorageProxy.upload_bytes(allow_overflow=True)` → `store_render_output`
  - `render_composition_task` → **派发点**：`render_video` 工具的 `_dispatch_render`（Celery 优先、失败回退同步）
  - `render_video` 工具 → **挂载点** `AssistantAgentService._build_assistant_runtime_tools`
- [ ] **Celery 任务三件齐**：任务函数 + `TASK_MODULES` 登记 + **队列路由**（`Queue("render")` + `task_routes` 指向 `render`）
- [ ] **Celery 任务有派发点**：`_dispatch_render` 内 `render_composition_task.delay(...)`，且有测试锁定「Celery 可用走后台、不可用回退同步」
- [ ] **builtin 工具四件齐**：`.py` + `.yaml` + `providers.yaml` 登记 + **运行时挂载点**
- [ ] **配额双模式生效**：成品入库 `allow_overflow=True`（剩余 > 0 放行），素材上传仍严格（有回归测试锁定严格路径没被改松）
- [ ] **迁移 `down_revision`** 指向 `v0d1e2f3a4b5`，且 `python -m pytest test/internal/migration -q` 断言**单 head**
- [ ] **真实渲染已实测**：Task 6 Step 5 产出 MP4 且 ffprobe 读出 h264/1920x1080/正时长
- [ ] 用调用方搜索验证无断链：对每个新符号全仓搜引用（排除 `test/`），命中不能只有定义处
- [ ] 前端无需改动（成品库走既有知识库列表接口 `GET /space/knowledge-bases`，`list_user_content_bases` 已按 `owner_account_id + user_content` 过滤，成品库自动出现在列表中）
- [ ] 全量回归：`python -m pytest test -q --no-header --no-cov`
