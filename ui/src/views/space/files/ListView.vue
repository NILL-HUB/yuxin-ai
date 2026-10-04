<script setup lang="ts">
/**
 * 用户文件中心 — 虚拟目录树管理面。
 *
 * 视图：「我的文件」（目录浏览，网格卡片）/「全部文件」（平铺分页）。
 * 删除进入回收站（可恢复）；文件点击经接口返回的 url 打开。
 * 按钮与卡片均走统一抽象层：AppButton + AppCard 基座派生的 FileCard。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import AppButton from '@/components/AppButton.vue'
import AppConfirmModal from '@/components/AppConfirmModal.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppModal from '@/components/AppModal.vue'
import FileCard from './components/FileCard.vue'
import {
  createFileCenterFolder,
  deleteFileCenterEntry,
  listAllFileCenterFiles,
  listFileCenterEntries,
  updateFileCenterEntry,
} from '@/services/file-center'
import type { FileCenterAllFile, FileCenterEntry } from '@/models/file-center'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

type ViewKey = 'browse' | 'all'
const activeView = ref<ViewKey>('browse')

/* ---------------- 我的文件（目录浏览） ---------------- */

const loading = ref(false)
const entries = ref<FileCenterEntry[]>([])
const pathStack = ref<Array<{ id: string; name: string }>>([])
const currentParentId = computed(() =>
  pathStack.value.length ? pathStack.value[pathStack.value.length - 1].id : null,
)

const loadEntries = async () => {
  loading.value = true
  try {
    const result = await listFileCenterEntries(currentParentId.value)
    entries.value = result.items || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('fileCenter.loadFailed')))
  } finally {
    loading.value = false
  }
}

const enterFolder = (entry: FileCenterEntry) => {
  pathStack.value.push({ id: entry.id, name: entry.name })
  void loadEntries()
}

const jumpTo = (index: number) => {
  pathStack.value = pathStack.value.slice(0, index)
  void loadEntries()
}

const refresh = () => {
  void loadEntries()
}

const openFile = (entry: { name: string; url: string | null }) => {
  if (entry.url) {
    window.open(entry.url, '_blank')
  } else {
    Message.info(t('fileCenter.noPreview'))
  }
}

const openEntry = (entry: FileCenterEntry) => {
  if (entry.is_folder) {
    enterFolder(entry)
  } else {
    openFile(entry)
  }
}

/* ---------------- 全部文件（平铺分页） ---------------- */

const allLoading = ref(false)
const allFiles = ref<FileCenterAllFile[]>([])
const allPage = ref(1)
const allPageSize = ref(24)
const allTotal = ref(0)

const loadAllFiles = async () => {
  allLoading.value = true
  try {
    const result = await listAllFileCenterFiles(allPage.value, allPageSize.value)
    allFiles.value = result.items || []
    allTotal.value = result.total || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('fileCenter.loadFailed')))
  } finally {
    allLoading.value = false
  }
}

const onAllPageChange = (page: number) => {
  allPage.value = page
  void loadAllFiles()
}

watch(activeView, (view) => {
  if (view === 'all') {
    void loadAllFiles()
  }
})

/* ---------------- 新建 / 重命名 ---------------- */

type NameModalState = {
  visible: boolean
  title: string
  action: 'mkdir' | 'rename'
  entry: FileCenterEntry | null
}
const showNameModal = ref<NameModalState>({
  visible: false,
  title: '',
  action: 'mkdir',
  entry: null,
})
const nameModalValue = ref('')
const nameSubmitting = ref(false)

const onCreateFolder = () => {
  nameModalValue.value = ''
  showNameModal.value = {
    visible: true,
    title: t('fileCenter.newFolderTitle'),
    action: 'mkdir',
    entry: null,
  }
}

const onRename = (entry: FileCenterEntry) => {
  nameModalValue.value = entry.name
  showNameModal.value = { visible: true, title: t('fileCenter.renameTitle'), action: 'rename', entry }
}

const submitNameModal = async () => {
  const value = nameModalValue.value.trim()
  if (!value) {
    Message.warning(t('fileCenter.nameRequired'))
    return
  }
  nameSubmitting.value = true
  try {
    if (showNameModal.value.action === 'mkdir') {
      await createFileCenterFolder(currentParentId.value, value)
    } else if (showNameModal.value.entry) {
      await updateFileCenterEntry(showNameModal.value.entry.id, { name: value })
    }
    showNameModal.value.visible = false
    refresh()
  } catch (error) {
    Message.error(getErrorMessage(error, t('fileCenter.operateFailed')))
  } finally {
    nameSubmitting.value = false
  }
}

/* ---------------- 移动 ---------------- */

const moveModalVisible = ref(false)
const moveSubmitting = ref(false)
const moveTarget = ref<FileCenterEntry | null>(null)
/** 空串表示账号根目录 */
const moveToFolder = ref<string>('')
const folderOptions = ref<Array<{ value: string; label: string; depth: number }>>([])

// 移动：加载全部目录树（BFS），弹窗选择目标目录
const loadFolderOptions = async () => {
  const options: Array<{ value: string; label: string; depth: number }> = []
  const queue: Array<{ id: string | null; label: string; depth: number }> = [
    { id: null, label: t('fileCenter.root'), depth: 0 },
  ]
  while (queue.length) {
    const node = queue.shift()!
    if (node.id) options.push({ value: node.id, label: node.label, depth: node.depth })
    if (node.depth >= 6) continue
    const result = await listFileCenterEntries(node.id)
    for (const item of result.items || []) {
      if (item.is_folder) {
        queue.push({
          id: item.id,
          label: `${'　'.repeat(node.depth + 1)}${item.name}`,
          depth: node.depth + 1,
        })
      }
    }
  }
  folderOptions.value = options
}

const onMove = async (entry: FileCenterEntry) => {
  moveTarget.value = entry
  moveToFolder.value = ''
  try {
    await loadFolderOptions()
    moveModalVisible.value = true
  } catch (error) {
    Message.error(getErrorMessage(error, t('fileCenter.loadFailed')))
  }
}

const submitMove = async () => {
  if (!moveTarget.value) return
  if (moveTarget.value.is_folder && moveToFolder.value === moveTarget.value.id) {
    Message.warning(t('fileCenter.moveIntoItself'))
    return
  }
  moveSubmitting.value = true
  try {
    await updateFileCenterEntry(moveTarget.value.id, {
      parent_id: moveToFolder.value || null,
    })
    moveModalVisible.value = false
    refresh()
  } catch (error) {
    Message.error(getErrorMessage(error, t('fileCenter.operateFailed')))
  } finally {
    moveSubmitting.value = false
  }
}

/* ---------------- 删除（回收站，可恢复） ---------------- */

const deleteVisible = ref(false)
const deleteSubmitting = ref(false)
const deleteTarget = ref<FileCenterEntry | null>(null)

const onDelete = (entry: FileCenterEntry) => {
  deleteTarget.value = entry
  deleteVisible.value = true
}

const submitDelete = async () => {
  if (!deleteTarget.value) return
  deleteSubmitting.value = true
  try {
    await deleteFileCenterEntry(deleteTarget.value.id)
    Message.success(t('fileCenter.deleteSuccess'))
    deleteVisible.value = false
    refresh()
  } catch (error) {
    Message.error(getErrorMessage(error, t('fileCenter.operateFailed')))
  } finally {
    deleteSubmitting.value = false
  }
}

onMounted(() => {
  void loadEntries()
})
</script>

<template>
  <div class="file-center-page">
    <a-tabs v-model:active-key="activeView" class="file-center-tabs">
      <!-- 我的文件：目录浏览 -->
      <a-tab-pane key="browse" :title="t('fileCenter.tabs.browse')">
        <div class="file-toolbar">
          <nav class="file-breadcrumb">
            <button
              type="button"
              class="crumb"
              :class="{ 'is-leaf': pathStack.length === 0 }"
              @click="jumpTo(0)"
            >
              <icon-home />
              <span>{{ t('fileCenter.root') }}</span>
            </button>
            <template v-for="(node, index) in pathStack" :key="node.id">
              <span class="crumb-sep">/</span>
              <button
                type="button"
                class="crumb"
                :class="{ 'is-leaf': index === pathStack.length - 1 }"
                @click="jumpTo(index + 1)"
              >
                {{ node.name }}
              </button>
            </template>
          </nav>
          <div class="file-toolbar__actions">
            <AppButton variant="primary" size="small" @click="onCreateFolder">
              <template #icon><icon-folder-add /></template>
              {{ t('fileCenter.newFolder') }}
            </AppButton>
            <AppButton
              variant="outline"
              size="small"
              icon-only
              :title="t('fileCenter.refresh')"
              @click="refresh"
            >
              <template #icon><icon-refresh /></template>
            </AppButton>
          </div>
        </div>

        <a-spin :loading="loading" class="file-spin">
          <div v-if="entries.length" class="file-grid">
            <FileCard
              v-for="entry in entries"
              :key="entry.id"
              :name="entry.name"
              :is-folder="entry.is_folder"
              :source="entry.source"
              :url="entry.url"
              @click="openEntry(entry)"
              @rename="onRename(entry)"
              @move="onMove(entry)"
              @delete="onDelete(entry)"
            />
          </div>

          <AppEmpty
            v-else-if="!loading"
            variant="page"
            :title="t('fileCenter.empty')"
            :hint="t('fileCenter.emptyBrowseHint')"
          >
            <template #icon><icon-folder /></template>
            <template #actions>
              <AppButton variant="primary" @click="onCreateFolder">
                <template #icon><icon-folder-add /></template>
                {{ t('fileCenter.newFolder') }}
              </AppButton>
            </template>
          </AppEmpty>
        </a-spin>
      </a-tab-pane>

      <!-- 全部文件：平铺分页 -->
      <a-tab-pane key="all" :title="t('fileCenter.tabs.all')">
        <a-spin :loading="allLoading" class="file-spin">
          <div v-if="allFiles.length" class="file-grid">
            <FileCard
              v-for="item in allFiles"
              :key="item.entry_id"
              :name="item.name"
              :source="item.source"
              :url="item.url"
              :show-ops="false"
              @click="openFile(item)"
            />
          </div>

          <AppEmpty
            v-else-if="!allLoading"
            variant="page"
            :title="t('fileCenter.empty')"
            :hint="t('fileCenter.emptyAllHint')"
          >
            <template #icon><icon-folder /></template>
          </AppEmpty>
        </a-spin>

        <div v-if="allTotal > allPageSize" class="file-pagination">
          <a-pagination
            :current="allPage"
            :page-size="allPageSize"
            :total="allTotal"
            size="small"
            show-total
            @change="onAllPageChange"
          />
        </div>
      </a-tab-pane>
    </a-tabs>

    <!-- 新建 / 重命名 -->
    <AppModal
      v-model:visible="showNameModal.visible"
      :title="showNameModal.title"
      :confirm-text="t('fileCenter.confirm')"
      :loading="nameSubmitting"
      @confirm="submitNameModal"
    >
      <a-input
        v-model="nameModalValue"
        :placeholder="t('fileCenter.namePlaceholder')"
        allow-clear
        @press-enter="submitNameModal"
      />
    </AppModal>

    <!-- 移动到 -->
    <AppModal
      v-model:visible="moveModalVisible"
      :title="t('fileCenter.moveTitle')"
      :confirm-text="t('fileCenter.confirm')"
      :loading="moveSubmitting"
      @confirm="submitMove"
    >
      <a-select v-model="moveToFolder" :placeholder="t('fileCenter.movePlaceholder')">
        <a-option value="">{{ t('fileCenter.root') }}</a-option>
        <a-option v-for="option in folderOptions" :key="option.value" :value="option.value">
          {{ option.label }}
        </a-option>
      </a-select>
    </AppModal>

    <!-- 删除确认（移入回收站，可恢复） -->
    <AppConfirmModal
      v-model:visible="deleteVisible"
      :title="t('fileCenter.deleteTitle')"
      :message="t('fileCenter.deleteConfirm')"
      :target="deleteTarget?.name || ''"
      :confirm-text="t('fileCenter.deleteAction')"
      :loading="deleteSubmitting"
      @confirm="submitDelete"
    />
  </div>
</template>

<style scoped>
.file-center-page {
  padding: 16px;
}

.file-spin {
  display: block;
  min-height: 240px;
}

/* ---------------- 工具栏 ---------------- */

.file-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.file-toolbar__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-breadcrumb {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
  min-width: 0;
}

.crumb {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 220px;
  padding: 4px 8px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 13px;
  color: var(--aicss-muted);
  border-radius: var(--aicss-radius-sm);
  transition: color 0.16s, background 0.16s;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.crumb:hover {
  color: var(--aicss-accent);
  background: var(--aicss-accent-soft);
}

.crumb.is-leaf {
  color: var(--aicss-text);
  font-weight: 500;
}

.crumb-sep {
  color: var(--aicss-subtle);
  font-size: 12px;
}

/* ---------------- 网格（卡片视觉见 AppCard / FileCard） ---------------- */

.file-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
}

/* ---------------- 分页 ---------------- */

.file-pagination {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
