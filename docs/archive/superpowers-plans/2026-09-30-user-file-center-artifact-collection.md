# 用户文件中心（Plan 4 · 产物收编）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「只有写入、没有管理面」的 Agent 产物**收编**进文件中心——生成图片建 `UploadFile` 记录并入树；Agent 文本产物自动入树。

**Architecture:** 不改存储层，只把散落的产物写入点**收敛**为「建记录 + 在文件中心建节点」（属 AGENTS.md 的「补洞口」，非平行机制）。图片/文本产物都归 `file_center_entry`，`source="artifact"`。

**Tech Stack:** Python / injector / pytest。

**依赖与衔接**
- **前置**：Plan 1（`FileCenterService.import_upload_file`）、Plan 3（`save_artifact` 已定义产物落点 `产物/`）。
- **后续**：Plan 5（前端）。
- **规格**：`.../specs/2026-09-30-user-file-center-design.md` §4.6。

**前置条件：** 只 `git add` 本任务列举的文件；测试在 `api/` 下运行。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `api/internal/core/tools/builtin_tools/providers/qwen/image_persistence.py` | 修改：生成图片由无记录改为建记录并入树 |
| `api/internal/core/agent/agents/deep_thinking_agent.py` | 修改：文本产物建节点 |
| `api/test/internal/service/test_file_center_artifact_intake.py` | 新建：收编单测 |

---

## Task 1: 侦察产物写入现状

**Files:** 只读，无改动。

- [ ] **Step 1: 读现状**

读并用文字记录（供后续任务对齐真实签名）：
- `api/internal/core/tools/builtin_tools/providers/qwen/image_persistence.py` 的 `persist_remote_image` 签名、它当前调用的存储方法与调用方（谁传入/可拿到 `account_id`）。
- `api/internal/core/agent/agents/deep_thinking_agent.py` 的 `_upload_plain_text_artifact` 签名与调用点（是否可拿到 `account_id`）。
- `api/internal/service/file_center_service.py` 的 `import_upload_file` 签名（Plan 1 已定义）。

- [ ] **Step 2: 记录**

把上述真实签名记录到本任务的执行日志，作为 Task 2/3 的依据。无代码改动，无需 commit。

---

## Task 2: 生成图片建记录并入树

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/qwen/image_persistence.py`
- Create: `api/test/internal/service/test_file_center_artifact_intake.py`

- [ ] **Step 1: 写失败测试（服务层约束）**

创建 `api/test/internal/service/test_file_center_artifact_intake.py`：

```python
"""产物收编：入树语义单测（不依赖真实外网/存储）。"""
import uuid

from internal.service.file_center_service import FileCenterService


class _FakeUploadFile:
    def __init__(self, name):
        self.id = uuid.uuid4()
        self.name = name


def test_artifact_import_records_source_and_node():
    svc = FileCenterService()
    acc = uuid.uuid4()
    uf = _FakeUploadFile("gen.png")
    entry = svc.import_upload_file(
        acc, upload_file_id=uf.id, parent_id=None, name=uf.name, source="artifact"
    )
    assert entry.source == "artifact"
    assert entry.upload_file_id == uf.id
```

- [ ] **Step 2: 运行确认失败/通过**

Run: `python -m pytest test/internal/service/test_file_center_artifact_intake.py -q`
Expected: 该用例应 PASS（Plan 1 已提供 `import_upload_file`）——若失败说明 Plan 1 未落地，先完成 Plan 1。

- [ ] **Step 3: 改 `persist_remote_image`**

按 Task 1 记录的签名，把生成图片的落盘由「无记录」改为「建记录 + 入树」：将原先的
`upload_bytes_without_record(...)`（不建 `UploadFile`、不计配额）改为注入 `ObjectStoragePort` 的
`upload_bytes(*, filename, content, account_id, folder="generated-images")`（建记录、计配额），
随后经 `injector.get(FileCenterService).import_upload_file(account_id, upload_file_id=..., name=..., source="artifact")` 入树。

- [ ] **Step 4: 回归（对话内展示不破坏）**

Run: `python -m pytest test/internal/core/tools/ -q -k "image or qwen"`
Expected: 全部 PASS（生成图片在对话消息内的展示路径不变）。

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/tools/builtin_tools/providers/qwen/image_persistence.py api/test/internal/service/test_file_center_artifact_intake.py
git commit -m "feat(file-center): generated images create UploadFile record and file_center node"
```

---

## Task 3: Agent 文本产物入树

**Files:**
- Modify: `api/internal/core/agent/agents/deep_thinking_agent.py`

- [ ] **Step 1: 改 `_upload_plain_text_artifact`**

按 Task 1 记录的签名，在文本产物落库（已有 `UploadFile` 记录）之后，追加入树调用：

```python
        from app.http.module import injector
        from internal.service.file_center_service import FileCenterService

        try:
            injector.get(FileCenterService).import_upload_file(
                account_id,
                upload_file_id=upload_file.id,
                parent_id=None,
                name=upload_file.name,
                source="artifact",
            )
        except Exception:
            logger.warning("文本产物入文件中心失败，不影响返回", exc_info=True)
```

> `account_id` 若在当前位置不可得，从调用链上溯取出（Task 1 已记录）；**不得**改成无账号的平行写入。

- [ ] **Step 2: 回归**

Run: `python -m pytest test/internal/core/agent/test_deep_thinking_agent.py -q`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add api/internal/core/agent/agents/deep_thinking_agent.py
git commit -m "feat(file-center): deep-thinking text artifacts flow into file center"
```

---

## 收编自检（写进回复）
- 收编清单：生成图片（`image_persistence`）、Agent 文本产物（`deep_thinking_agent`）——均**并入** `UploadFile` + `file_center_entry`，未新建第二套产物体系。
- 沙箱产物若已可选，可在后续增量按同一范式接入（登记到 `docs/research/config-inventory.md`）。

## 下一份计划
- Plan 5 `2026-09-30-user-file-center-frontend.md`
