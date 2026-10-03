<script setup lang="ts">
/**
 * 用户文件中心 — 虚拟目录树管理面。
 *
 * 视图：「我的文件」（目录浏览，网格卡片）/「全部文件」（平铺分页）。
 * 删除进入回收站（可恢复）；文件点击经接口返回的 url 打开。
 * 按钮统一走 AppButton（颜色与圆角全部来自主题 token）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import AppButton from '@/components/AppButton.vue'
import {
  createFileCenterFolder,
  deleteFileCenterEntry,
  listAllFileCenterFiles,
  listFileCenterEntries,
  updateFileCenterEntry,
} from '@/services/file-center'
import type { FileCenterAllFile, FileCenterEntry } from '@/models/file-center'
import { getErrorMessage } from '@/utils/error'

const { t, te } = useI18n()

type ViewKey = 'browse' | 'all'
const activeView = ref<ViewKey>('browse')

/* ---------------- 展示辅助 ---------------- */

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']
const VIDEO_EXTS = ['mp4', 'mov', 'webm', 'avi', 'mkv']
const AUDIO_EXTS = ['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac']

const extOf = (name: string) => name.split('.').pop()?.toLowerCase() || ''
const isImageName = (name: string) => IMAGE_EXTS.includes(extOf(name))

/** 按扩展名映射文件图标（未注册的图标名会解析失败，新增时同步 plugins/arco.ts） */
const fileIconName = (name: string) => {
  const ext = extOf(name)
  if (IMAGE_EXTS.includes(ext)) return 'icon-file-image'
  if (ext === 'pdf') return 'icon-file-pdf'
  if (VIDEO_EXTS.includes(ext)) return 'icon-file-video'
  if (AUDIO_EXTS.includes(ext)) return 'icon-file-audio'
  return 'icon-file'
}

const sourceLabel = (source: string) => {
  const key = `fileCenter.sources.${source}`
  return te(key) ? t(key) : source
}

/** 缩略图加载失败的节点（回退为类型图标） */
const thumbErrors = ref<Record<string, boolean>>({})
const markThumbError = (id: string) => {
  thumbErrors.value = { ...thumbErrors.value, [id]: true }
}
const canUseThumb = (id: string, name: string, url: string | null, isFolder = false) =>
  !isFolder && !!url && isImageName(name) && !thumbErrors.value[id]

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
            <article
              v-for="entry in entries"
              :key="entry.id"
              class="file-card"
              @click="openEntry(entry)"
            >
              <div class="file-card__thumb">
                <img
                  v-if="canUseThumb(entry.id, entry.name, entry.url, entry.is_folder)"
                  :src="entry.url as string"
                  :alt="entry.name"
                  loading="lazy"
                  @error="markThumbError(entry.id)"
                />
                <component
                  :is="entry.is_folder ? 'icon-folder' : fileIconName(entry.name)"
                  v-else
                  class="file-card__icon"
                  :class="{ 'is-folder': entry.is_folder }"
                />
              </div>
              <div class="file-card__body">
                <span class="file-card__name" :title="entry.name">{{ entry.name }}</span>
                <span class="file-card__source">{{ sourceLabel(entry.source) }}</span>
              </div>
              <div class="file-card__ops" @click.stop>
                <AppButton
                  variant="ghost"
                  size="mini"
                  icon-only
                  :title="t('fileCenter.rename')"
                  @click="onRename(entry)"
                >
                  <template #icon><icon-edit /></template>
                </AppButton>
                <AppButton
                  variant="ghost"
                  size="mini"
                  icon-only
                  :title="t('fileCenter.move')"
                  @click="onMove(entry)"
                >
                  <template #icon><icon-relation /></template>
                </AppButton>
                <AppButton
                  variant="ghost"
                  size="mini"
                  icon-only
                  status="danger"
                  :title="t('fileCenter.delete')"
                  @click="onDelete(entry)"
                >
                  <template #icon><icon-delete /></template>
                </AppButton>
              </div>
            </article>
          </div>

          <div v-else-if="!loading" class="file-empty">
            <div class="file-empty__icon"><icon-folder /></div>
            <p class="file-empty__title">{{ t('fileCenter.empty') }}</p>
            <p class="file-empty__hint">{{ t('fileCenter.emptyBrowseHint') }}</p>
            <AppButton variant="primary" @click="onCreateFolder">
              <template #icon><icon-folder-add /></template>
              {{ t('fileCenter.newFolder') }}
            </AppButton>
          </div>
        </a-spin>
      </a-tab-pane>

      <!-- 全部文件：平铺分页 -->
      <a-tab-pane key="all" :title="t('fileCenter.tabs.all')">
        <a-spin :loading="allLoading" class="file-spin">
          <div v-if="allFiles.length" class="file-grid">
            <article
              v-for="item in allFiles"
              :key="item.entry_id"
              class="file-card"
              @click="openFile(item)"
            >
              <div class="file-card__thumb">
                <img
                  v-if="canUseThumb(item.entry_id, item.name, item.url)"
                  :src="item.url as string"
                  :alt="item.name"
                  loading="lazy"
                  @error="markThumbError(item.entry_id)"
                />
                <component :is="fileIconName(item.name)" v-else class="file-card__icon" />
              </div>
              <div class="file-card__body">
                <span class="file-card__name" :title="item.name">{{ item.name }}</span>
                <span class="file-card__source">{{ sourceLabel(item.source) }}</span>
              </div>
            </article>
          </div>

          <div v-else-if="!allLoading" class="file-empty">
            <div class="file-empty__icon"><icon-folder /></div>
            <p class="file-empty__title">{{ t('fileCenter.empty') }}</p>
            <p class="file-empty__hint">{{ t('fileCenter.emptyAllHint') }}</p>
          </div>
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
    <a-modal v-model:visible="showNameModal.visible" :title="showNameModal.title" :footer="false">
      <a-input
        v-model="nameModalValue"
        :placeholder="t('fileCenter.namePlaceholder')"
        allow-clear
        @press-enter="submitNameModal"
      />
      <div class="file-modal-footer">
        <AppButton variant="text" @click="showNameModal.visible = false">
          {{ t('fileCenter.cancel') }}
        </AppButton>
        <AppButton variant="primary" :loading="nameSubmitting" @click="submitNameModal">
          {{ t('fileCenter.confirm') }}
        </AppButton>
      </div>
    </a-modal>

    <!-- 移动到 -->
    <a-modal
      v-model:visible="moveModalVisible"
      :title="t('fileCenter.moveTitle')"
      :footer="false"
    >
      <a-select v-model="moveToFolder" :placeholder="t('fileCenter.movePlaceholder')">
        <a-option value="">{{ t('fileCenter.root') }}</a-option>
        <a-option v-for="option in folderOptions" :key="option.value" :value="option.value">
          {{ option.label }}
        </a-option>
      </a-select>
      <div class="file-modal-footer">
        <AppButton variant="text" @click="moveModalVisible = false">
          {{ t('fileCenter.cancel') }}
        </AppButton>
        <AppButton variant="primary" :loading="moveSubmitting" @click="submitMove">
          {{ t('fileCenter.confirm') }}
        </AppButton>
      </div>
    </a-modal>

    <!-- 删除确认（移入回收站，可恢复） -->
    <a-modal v-model:visible="deleteVisible" :title="t('fileCenter.deleteTitle')" :footer="false">
      <p class="file-delete-text">
        {{ t('fileCenter.deleteConfirm') }}
      </p>
      <p v-if="deleteTarget" class="file-delete-target">{{ deleteTarget.name }}</p>
      <div class="file-modal-footer">
        <AppButton variant="text" @click="deleteVisible = false">
          {{ t('fileCenter.cancel') }}
        </AppButton>
        <AppButton variant="danger" :loading="deleteSubmitting" @click="submitDelete">
          {{ t('fileCenter.deleteAction') }}
        </AppButton>
      </div>
    </a-modal>
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

/* ---------------- 网格与卡片 ---------------- */

.file-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
}

.file-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  cursor: pointer;
  transition: border-color 0.16s, box-shadow 0.16s, transform 0.16s;
}

.file-card:hover {
  border-color: var(--aicss-border-strong);
  box-shadow: var(--aicss-shadow-card);
  transform: translateY(-2px);
}

.file-card__thumb {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 4 / 3;
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-bg-subtle);
  overflow: hidden;
}

.file-card__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-card__icon {
  font-size: 34px;
  color: var(--aicss-muted);
}

.file-card__icon.is-folder {
  color: var(--aicss-accent);
}

.file-card__body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.file-card__name {
  font-size: 13px;
  color: var(--aicss-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-card__source {
  align-self: flex-start;
  font-size: 11px;
  line-height: 1.5;
  padding: 0 8px;
  border-radius: 999px;
  color: var(--aicss-accent-text);
  background: var(--aicss-accent-soft);
}

.file-card__ops {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--aicss-border);
  border-radius: 999px;
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
  opacity: 0;
  transition: opacity 0.16s;
}

.file-card:hover .file-card__ops {
  opacity: 1;
}

/* ---------------- 空状态 ---------------- */

.file-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 56px 16px;
  text-align: center;
}

.file-empty__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  margin-bottom: 4px;
  border-radius: 50%;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent);
  font-size: 30px;
}

.file-empty__title {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--aicss-text);
}

.file-empty__hint {
  margin: 0 0 8px;
  max-width: 420px;
  font-size: 13px;
  color: var(--aicss-muted);
}

/* ---------------- 分页与弹窗 ---------------- */

.file-pagination {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}

.file-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}

.file-delete-text {
  margin: 0;
  font-size: 13px;
  color: var(--aicss-text-2);
}

.file-delete-target {
  margin: 8px 0 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--aicss-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
