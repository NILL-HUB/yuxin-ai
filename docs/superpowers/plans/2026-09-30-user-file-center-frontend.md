# 用户文件中心（Plan 5 · 前端）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地用户侧文件中心页面 `/space/files`——左目录树 + 右文件列表，支持建目录/上传/重命名/移动/删除，文件预览复用 kkfileview。

**Architecture:** 新增 `file-center.ts`（API 服务）、`ListView.vue`（页面）；路由挂 `/space/files`；文案全部走 i18n（zh/en 同步）。上传复用既有 `/upload-files/file`，再调 `/space/files/import` 入目录（避免重复实现配额/分片逻辑）。

**Tech Stack:** Vue 3 + TypeScript + Ant Design Vue + vue-i18n + vitest。

**依赖与衔接**
- **前置**：Plan 1（`/space/files/*` 六端点）。
- **规格**：`.../specs/2026-09-30-user-file-center-design.md` §4.7。
- **仓库强制规则**：i18n 键必须 zh/en 双侧同步，提交前 `npx vitest run src/i18n/__tests__/parity.spec.ts` 必须通过。

**前置条件：** 只 `git add` 本任务列举的文件。前端命令在 `ui/` 下运行。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `ui/src/services/file-center.ts` | 新建：`/space/files/*` API 封装 |
| `ui/src/models/file-center.ts` | 新建：类型定义 |
| `ui/src/views/space/files/ListView.vue` | 新建：文件中心页面 |
| `ui/src/router/index.ts` | 修改：注册路由 |
| `ui/src/i18n/messages/zh-CN/space/files.ts` | 新建：中文文案 |
| `ui/src/i18n/messages/en-US/space/files.ts` | 新建：英文文案 |
| `ui/src/i18n/messages/{zh-CN,en-US}/space/index.ts` | 修改：聚合注册（若无该 index 则按仓库现有 space 目录组织方式登记） |

---

## Task 1: 类型与 API 服务

**Files:**
- Create: `ui/src/models/file-center.ts`
- Create: `ui/src/services/file-center.ts`

- [ ] **Step 1: 类型定义**

创建 `ui/src/models/file-center.ts`：

```ts
export interface FileCenterEntry {
  id: string
  parent_id: string | null
  name: string
  is_folder: boolean
  upload_file_id: string | null
  source: string
  origin: string | null
}

export interface FileCenterChildren {
  items: FileCenterEntry[]
  parent_id: string | null
}
```

- [ ] **Step 2: API 服务**

创建 `ui/src/services/file-center.ts`（沿用仓库 axios 实例封装范式，`import api from '@/services/api'` 或仓库既有 get/post 封装）：

```ts
import api from '@/services/api'
import type { FileCenterChildren, FileCenterEntry } from '@/models/file-center'

export function listFileCenter(parentId: string | null = null) {
  return api.get<FileCenterChildren>('/space/files', {
    params: parentId ? { parent_id: parentId } : {},
  })
}

export function createFolder(parentId: string | null, name: string) {
  return api.post<FileCenterEntry>('/space/files/folders', { parent_id: parentId, name })
}

export function updateEntry(entryId: string, payload: { name?: string; parent_id?: string | null }) {
  return api.patch<FileCenterEntry>(`/space/files/${entryId}`, payload)
}

export function deleteEntry(entryId: string) {
  return api.delete(`/space/files/${entryId}`)
}

export function importUploadFile(uploadFileId: string, parentId: string | null, name: string) {
  return api.post<FileCenterEntry>('/space/files/import', {
    upload_file_id: uploadFileId,
    parent_id: parentId,
    name,
  })
}
```

> 若仓库统一用 `ui/src/services/http.ts` 之类的封装而非 `services/api`，改为仓库既有范式。

- [ ] **Step 3: 类型检查**

Run: `npx vue-tsc --noEmit`（或仓库既有 typecheck 脚本）
Expected: 无新增类型错误

- [ ] **Step 4: Commit**

```bash
git add ui/src/models/file-center.ts ui/src/services/file-center.ts
git commit -m "feat(file-center): frontend API service and types"
```

---

## Task 2: 页面 `ListView.vue`

**Files:**
- Create: `ui/src/views/space/files/ListView.vue`

- [ ] **Step 1: 写页面**

创建 `ui/src/views/space/files/ListView.vue`（左树右列表；文案用 `t('space.files.*')`）：

```vue
<template>
  <div class="file-center">
    <a-card :title="t('space.files.title')" :bordered="false">
      <a-row :gutter="16">
        <a-col :span="6">
          <a-tree :tree-data="treeData" @select="onSelectFolder" />
        </a-col>
        <a-col :span="18">
          <a-space class="toolbar">
            <a-button type="primary" @click="onCreateFolder">{{ t('space.files.newFolder') }}</a-button>
            <a-upload :show-upload-list="false" :custom-request="onUpload">
              <a-button>{{ t('space.files.upload') }}</a-button>
            </a-upload>
          </a-space>
          <a-table
            :data-source="entries"
            :columns="columns"
            row-key="id"
            :pagination="false"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <span v-if="record.is_folder" class="folder" @click="onSelectFolder([record.id])">
                  {{ record.name }}
                </span>
                <a v-else :href="previewUrl(record)" target="_blank">{{ record.name }}</a>
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a @click="onRename(record)">{{ t('space.files.rename') }}</a>
                  <a @click="onMove(record)">{{ t('space.files.move') }}</a>
                  <a class="danger" @click="onDelete(record)">{{ t('space.files.delete') }}</a>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-col>
      </a-row>
    </a-card>
  </div>
</template>
```

`<script setup lang="ts">`：
- `const { t } = useI18n()`
- loading + 拉取：`loadTree()` 迭代 `listFileCenter` 组装 `treeData`（按 parent 递归；首屏只拉根+当前层，展开时按需拉）。
- `onSelectFolder(keys)` → `parentId = keys[0]` → `loadEntries()`。
- `onCreateFolder()` → `Modal` 输入名 → `createFolder` → 刷新。
- `onRename(record)` → `updateEntry(record.id, { name })`。
- `onMove(record)` → 选目标目录 → `updateEntry(record.id, { parent_id })`。
- `onDelete(record)` → `Modal.confirm` → `deleteEntry` → 刷新（提示「已移入回收站」）。
- `onUpload({ file })` → 走既有上传接口拿 `upload_file_id` → `importUploadFile(id, parentId, file.name)` → 刷新。
- `previewUrl(record)` → `record.upload_file_id` 对应 kkfileview 预览地址（由后端返回，或前端按 `/kkfileview/onlinePreview?url=<base64>` 组装；**优先用后端字段，避免前端重复实现 base64 逻辑**）。

> 交互细节（Modal 输入/目录选择器）按仓库既有同类页面（如 `ui/src/views/space/datasets/ListView.vue`）的写法实现，保持风格一致。

- [ ] **Step 2: 类型检查**

Run: `npx vue-tsc --noEmit`
Expected: 无新增类型错误

- [ ] **Step 3: Commit**

```bash
git add ui/src/views/space/files/ListView.vue
git commit -m "feat(file-center): /space/files page (tree + list + actions)"
```

---

## Task 3: 路由 + i18n

**Files:**
- Modify: `ui/src/router/index.ts`
- Create: `ui/src/i18n/messages/zh-CN/space/files.ts`
- Create: `ui/src/i18n/messages/en-US/space/files.ts`
- Modify: `ui/src/i18n/messages/{zh-CN,en-US}/space/index.ts`

- [ ] **Step 1: 加路由**

在 `ui/src/router/index.ts` 的 space 相关路由处追加：

```ts
{
  path: 'files',
  name: 'space-files',
  component: () => import('@/views/space/files/ListView.vue'),
},
```

- [ ] **Step 2: 加 i18n（zh/en 各一份，键完全一致）**

`ui/src/i18n/messages/zh-CN/space/files.ts`：

```ts
export default {
  title: '文件中心',
  newFolder: '新建文件夹',
  upload: '上传',
  rename: '重命名',
  move: '移动',
  delete: '删除',
  deleteConfirm: '删除后将移入回收站，可在回收站恢复。',
  namePlaceholder: '请输入名称',
}
```

`ui/src/i18n/messages/en-US/space/files.ts`：

```ts
export default {
  title: 'File Center',
  newFolder: 'New Folder',
  upload: 'Upload',
  rename: 'Rename',
  move: 'Move',
  delete: 'Delete',
  deleteConfirm: 'Deleted items go to the recycle bin and can be restored.',
  namePlaceholder: 'Enter a name',
}
```

在该 locale 的 space 聚合文件（`space/index.ts`）中登记 `files`（若无该文件则按仓库现有 `space` 目录的聚合方式登记）。

- [ ] **Step 3: i18n parity 校验**

Run: `npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected: PASS（zh/en 键集合一致、代码引用的键均可解析）

- [ ] **Step 4: Commit**

```bash
git add ui/src/router/index.ts ui/src/i18n/messages/zh-CN/space/files.ts ui/src/i18n/messages/en-US/space/files.ts ui/src/i18n/messages/zh-CN/space/index.ts ui/src/i18n/messages/en-US/space/index.ts
git commit -m "feat(file-center): route /space/files + i18n (zh/en)"
```

---

## 收尾（写进回复）
- 入口：前端 `/space/files` → `ui/src/services/file-center.ts` → `/space/files/*`。
- i18n parity 已通过；无硬编码文案。

## 全链路回顾（Plan 1 → 5）
1. Plan 1 后端核心（表/服务/路由）
2. Plan 2 回收站原目录恢复
3. Plan 3 Agent 工具（`file_center`）
4. Plan 4 产物收编
5. Plan 5 前端页面
