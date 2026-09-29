<script setup lang="ts">
/**
 * 用户文件中心 — 虚拟目录树管理面。
 *
 * 数据源：/space/files（列目录、建目录、重命名、移动、删除、导入）。
 * 删除进入回收站（可恢复）；文件预览使用接口返回的 url 直接打开。
 */
import { computed, onMounted, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  createFileCenterFolder,
  deleteFileCenterEntry,
  listFileCenterEntries,
  updateFileCenterEntry,
} from '@/services/file-center'
import type { FileCenterEntry } from '@/models/file-center'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

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

const onCreateFolder = () => {
  nameModalValue.value = ''
  showNameModal.value = {
    visible: true,
    title: t('fileCenter.newFolderTitle'),
    action: 'mkdir',
    entry: null,
  }
}

type NameModalState = {
  visible: boolean
  title: string
  action: 'mkdir' | 'rename'
  entry: FileCenterEntry | null
}
const showNameModal = ref<NameModalState>({ visible: false, title: '', action: 'mkdir', entry: null })
const nameModalValue = ref('')

const submitNameModal = async () => {
  const value = nameModalValue.value.trim()
  if (!value) {
    Message.warning(t('fileCenter.nameRequired'))
    return
  }
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
  }
}

const onRename = (entry: FileCenterEntry) => {
  nameModalValue.value = entry.name
  showNameModal.value = { visible: true, title: t('fileCenter.renameTitle'), action: 'rename', entry }
}

// 移动：加载全部目录树（BFS），弹窗选择目标目录
const moveModalVisible = ref(false)
const moveTarget = ref<FileCenterEntry | null>(null)
const folderOptions = ref<Array<{ value: string; label: string; depth: number }>>([])

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
  try {
    await loadFolderOptions()
    moveModalVisible.value = true
  } catch (error) {
    Message.error(getErrorMessage(error, t('fileCenter.loadFailed')))
  }
}

const moveToFolder = ref<string | null>(null)
const submitMove = async () => {
  if (!moveTarget.value) return
  if (moveTarget.value.is_folder && moveToFolder.value === moveTarget.value.id) {
    Message.warning(t('fileCenter.moveIntoItself'))
    return
  }
  try {
    await updateFileCenterEntry(moveTarget.value.id, { parent_id: moveToFolder.value })
    moveModalVisible.value = false
    refresh()
  } catch (error) {
    Message.error(getErrorMessage(error, t('fileCenter.operateFailed')))
  }
}

const onDelete = (entry: FileCenterEntry) => {
  Modal.warning({
    title: t('fileCenter.deleteTitle'),
    content: t('fileCenter.deleteConfirm'),
    hideCancel: false,
    onOk: async () => {
      try {
        await deleteFileCenterEntry(entry.id)
        Message.success(t('fileCenter.deleteSuccess'))
        refresh()
      } catch (error) {
        Message.error(getErrorMessage(error, t('fileCenter.operateFailed')))
      }
    },
  })
}

const openFile = (entry: FileCenterEntry) => {
  if (entry.url) {
    window.open(entry.url, '_blank')
  } else {
    Message.info(t('fileCenter.noPreview'))
  }
}

onMounted(() => {
  void loadEntries()
})
</script>

<template>
  <div class="file-center-page">
    <a-card :bordered="false">
      <div class="file-center-toolbar">
        <a-breadcrumb>
          <a-breadcrumb-item>
            <a-link @click="jumpTo(0)">{{ t('fileCenter.root') }}</a-link>
          </a-breadcrumb-item>
          <a-breadcrumb-item v-for="(node, index) in pathStack" :key="node.id">
            <a-link @click="jumpTo(index + 1)">{{ node.name }}</a-link>
          </a-breadcrumb-item>
        </a-breadcrumb>
        <a-space>
          <a-button type="primary" @click="onCreateFolder">
            {{ t('fileCenter.newFolder') }}
          </a-button>
          <a-button @click="refresh">{{ t('fileCenter.refresh') }}</a-button>
        </a-space>
      </div>

      <a-table
        :data="entries"
        :loading="loading"
        row-key="id"
        :pagination="false"
        size="small"
      >
        <template #columns>
          <a-table-column :title="t('fileCenter.columns.name')">
            <template #cell="{ record }">
              <a-space>
                <icon-folder v-if="record.is_folder" />
                <icon-file v-else />
                <a-link v-if="record.is_folder" @click="enterFolder(record)">
                  {{ record.name }}
                </a-link>
                <a-link v-else @click="openFile(record)">{{ record.name }}</a-link>
              </a-space>
            </template>
          </a-table-column>
          <a-table-column :title="t('fileCenter.columns.type')" :width="120">
            <template #cell="{ record }">
              {{ record.is_folder ? t('fileCenter.typeFolder') : t('fileCenter.typeFile') }}
            </template>
          </a-table-column>
          <a-table-column :title="t('fileCenter.columns.source')" :width="140">
            <template #cell="{ record }">
              {{ t(`fileCenter.sources.${record.source}`) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('fileCenter.columns.actions')" :width="220">
            <template #cell="{ record }">
              <a-space>
                <a-link @click="onRename(record)">{{ t('fileCenter.rename') }}</a-link>
                <a-link @click="onMove(record)">{{ t('fileCenter.move') }}</a-link>
                <a-link status="danger" @click="onDelete(record)">
                  {{ t('fileCenter.delete') }}
                </a-link>
              </a-space>
            </template>
          </a-table-column>
        </template>
        <template #empty>
          <a-empty :description="t('fileCenter.empty')" />
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:visible="showNameModal.visible"
      :title="showNameModal.title"
      @ok="submitNameModal"
    >
      <a-input
        v-model="nameModalValue"
        :placeholder="t('fileCenter.namePlaceholder')"
        allow-clear
      />
    </a-modal>

    <a-modal
      v-model:visible="moveModalVisible"
      :title="t('fileCenter.moveTitle')"
      @ok="submitMove"
    >
      <a-select v-model="moveToFolder" :placeholder="t('fileCenter.movePlaceholder')">
        <a-option :value="null">{{ t('fileCenter.root') }}</a-option>
        <a-option v-for="option in folderOptions" :key="option.value" :value="option.value">
          {{ option.label }}
        </a-option>
      </a-select>
    </a-modal>
  </div>
</template>

<style scoped>
.file-center-page {
  padding: 16px;
}

.file-center-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
</style>