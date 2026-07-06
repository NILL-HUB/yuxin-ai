<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  confirmMemoryCandidate,
  createUserMemory,
  deleteUserMemory,
  ignoreMemoryCandidate,
  listMemoryCandidates,
  listUserMemories,
  updateUserMemory,
} from '@/services/user-memory'
import type { MemoryCandidate, UserMemory } from '@/models/memory'
import { getErrorMessage } from '@/utils/error'
import moment from 'moment'

const { t } = useI18n()

// 记忆类型元信息：value 与颜色不依赖 i18n，文案走 i18n 键
type MemoryTypeMeta = {
  value: string
  color: string
}

const MEMORY_TYPES: MemoryTypeMeta[] = [
  { value: 'profile', color: 'arcoblue' },
  { value: 'preference', color: 'green' },
  { value: 'relationship', color: 'purple' },
  { value: 'event', color: 'orange' },
  { value: 'project', color: 'cyan' },
  { value: 'secret', color: 'red' },
]

const typeMeta = (type: string): MemoryTypeMeta =>
  MEMORY_TYPES.find((item) => item.value === type) || { value: type, color: 'gray' }
const typeLabel = (type: string) => {
  const key = `memory.memoryType.${type}`
  const translated = t(key)
  return translated === key ? type : translated
}
const typeColor = (type: string) => typeMeta(type).color

// 来源字段的本地化映射，未命中时回退展示原始值
const sourceLabel = (source: string) => {
  if (!source) return '-'
  const key = `memory.source.${source}`
  const translated = t(key)
  return translated === key ? source : translated
}

const loading = ref(false)
const candidatesLoading = ref(false)
const memories = ref<UserMemory[]>([])
const candidates = ref<MemoryCandidate[]>([])
const activeTab = ref('saved')
const keyword = ref('')

const filteredMemories = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return memories.value
  return memories.value.filter((m) => m.content.toLowerCase().includes(kw))
})

const loadMemories = async () => {
  loading.value = true
  try {
    memories.value = await listUserMemories()
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.loadFailed')))
    memories.value = []
  } finally {
    loading.value = false
  }
}

const loadCandidates = async () => {
  candidatesLoading.value = true
  try {
    candidates.value = await listMemoryCandidates()
  } catch (error) {
    candidates.value = []
  } finally {
    candidatesLoading.value = false
  }
}

const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const saving = ref(false)
const form = ref({ memory_type: 'profile', content: '', confidence: 3 })

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  form.value = { memory_type: 'profile', content: '', confidence: 3 }
  modalVisible.value = true
}

const openEdit = (record: UserMemory) => {
  editMode.value = true
  editingId.value = record.id
  form.value = {
    memory_type: record.memory_type,
    content: record.content,
    confidence: typeof record.confidence === 'number' ? Math.max(1, Math.min(5, record.confidence)) : 3,
  }
  modalVisible.value = true
}

const handleSave = async () => {
  if (!form.value.content.trim()) {
    Message.warning(t('memory.contentRequired'))
    return
  }
  saving.value = true
  try {
    if (editMode.value) {
      await updateUserMemory(editingId.value, {
        content: form.value.content,
        memory_type: form.value.memory_type,
      })
    } else {
      await createUserMemory({
        memory_type: form.value.memory_type,
        content: form.value.content,
        confidence: form.value.confidence,
      })
    }
    Message.success(editMode.value ? t('memory.updateSuccess') : t('memory.createSuccess'))
    modalVisible.value = false
    await loadMemories()
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.saveFailed')))
  } finally {
    saving.value = false
  }
}

const toggleStatus = async (record: UserMemory, value: boolean) => {
  try {
    await updateUserMemory(record.id, { enabled: value })
    Message.success(value ? t('memory.enableSuccess') : t('memory.disableSuccess'))
    await loadMemories()
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.updateFailed')))
  }
}

const handleDelete = async (record: UserMemory) => {
  try {
    await deleteUserMemory(record.id)
    Message.success(t('memory.deleteSuccess'))
    await loadMemories()
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.deleteFailed')))
  }
}

const confirmingId = ref('')
const handleConfirmCandidate = async (record: MemoryCandidate) => {
  confirmingId.value = record.id
  try {
    await confirmMemoryCandidate(record.id, 'manual_confirm')
    Message.success(t('memory.confirmCandidateSuccess'))
    await Promise.all([loadMemories(), loadCandidates()])
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.confirmFailed')))
  } finally {
    confirmingId.value = ''
  }
}

const handleIgnoreCandidate = async (record: MemoryCandidate, neverRemind: boolean) => {
  try {
    await ignoreMemoryCandidate(record.id, neverRemind)
    Message.success(neverRemind ? t('memory.ignoreNeverRemindSuccess') : t('memory.ignoreSuccess'))
    await loadCandidates()
  } catch (error) {
    Message.error(getErrorMessage(error, t('memory.ignoreFailed')))
  }
}

const formatTime = (value: number | string) => {
  if (!value) return '-'
  const time = typeof value === 'number' ? (value < 1e12 ? value * 1000 : value) : value
  const date = moment(time)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm') : String(value)
}

const confidenceStars = (value: number) => {
  const n = Math.max(1, Math.min(5, Math.round(Number(value) || 0)))
  return '★'.repeat(n) + '☆'.repeat(5 - n)
}

const memoryTypeOptions = MEMORY_TYPES.map((item) => ({
  label: `${t(`memory.memoryType.${item.value}`)} · ${t(`memory.memoryTypeDesc.${item.value}`)}`,
  value: item.value,
}))

onMounted(() => {
  loadMemories()
  loadCandidates()
})
</script>

<template>
  <section class="space-y-6 p-6">
    <header class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">{{ t('memory.pageTitle') }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ t('memory.pageDescription') }}</p>
      </div>
      <a-button type="primary" data-test="create-memory-btn" @click="openCreate">
        <template #icon>
          <icon-plus />
        </template>
        {{ t('memory.createBtn') }}
      </a-button>
    </header>

    <a-tabs v-model:active-key="activeTab" type="rounded">
      <a-tab-pane key="saved" :title="t('memory.savedTab')">
        <div class="mb-3 flex items-center gap-3">
          <a-input
            v-model="keyword"
            :placeholder="t('memory.searchPlaceholder')"
            allow-clear
            class="max-w-sm"
          >
            <template #prefix>
              <icon-search />
            </template>
          </a-input>
          <span class="text-sm text-gray-400">{{ t('memory.totalCount', { count: filteredMemories.length }) }}</span>
        </div>
        <a-spin :loading="loading" class="block">
          <div
            v-if="!loading && !filteredMemories.length"
            class="flex flex-col items-center justify-center py-16 text-gray-400"
          >
            <icon-bookmark class="text-5xl mb-3" />
            <p>{{ t('memory.savedEmpty') }}</p>
          </div>
          <div v-else class="overflow-hidden rounded-lg border bg-white">
            <a-table
              :data="filteredMemories"
              :bordered="false"
              :hoverable="true"
              :pagination="false"
              row-key="id"
            >
              <template #columns>
                <a-table-column :title="t('memory.columns.type')" data-index="memory_type" :width="120">
                  <template #cell="{ record }">
                    <a-tag
                      :color="typeColor(record.memory_type)"
                      :data-memory-type="record.memory_type"
                      size="small"
                    >
                      {{ typeLabel(record.memory_type) }}
                    </a-tag>
                  </template>
                </a-table-column>
                <a-table-column :title="t('memory.columns.content')" data-index="content">
                  <template #cell="{ record }">
                    <span class="text-sm text-gray-700" :title="record.content">{{ record.content }}</span>
                  </template>
                </a-table-column>
                <a-table-column :title="t('memory.columns.confidence')" data-index="confidence" :width="130">
                  <template #cell="{ record }">
                    <span class="text-amber-500 tracking-wider" :data-confidence="record.confidence">
                      {{ confidenceStars(record.confidence) }}
                    </span>
                  </template>
                </a-table-column>
                <a-table-column :title="t('memory.columns.status')" data-index="status" :width="110">
                  <template #cell="{ record }">
                    <a-switch
                      :model-value="record.status === 'active'"
                      @change="(v: string | number | boolean) => toggleStatus(record, Boolean(v))"
                    />
                  </template>
                </a-table-column>
                <a-table-column :title="t('memory.columns.source')" data-index="created_from" :width="100">
                  <template #cell="{ record }">
                    <span class="text-sm text-gray-500">{{ sourceLabel(record.created_from) }}</span>
                  </template>
                </a-table-column>
                <a-table-column :title="t('memory.columns.createdAt')" data-index="created_at" :width="160">
                  <template #cell="{ record }">
                    <span class="text-sm text-gray-500">{{ formatTime(record.created_at) }}</span>
                  </template>
                </a-table-column>
                <a-table-column :title="t('memory.columns.actions')" :width="170">
                  <template #cell="{ record }">
                    <a-space>
                      <a-button size="mini" @click="openEdit(record)">{{ t('memory.editBtn') }}</a-button>
                      <a-popconfirm
                        :content="t('memory.deleteConfirmContent')"
                        @ok="handleDelete(record)"
                      >
                        <a-button size="mini" status="danger">{{ t('memory.deleteBtn') }}</a-button>
                      </a-popconfirm>
                    </a-space>
                  </template>
                </a-table-column>
              </template>
            </a-table>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="candidates" :title="t('memory.candidatesTab')">
        <a-spin :loading="candidatesLoading" class="block">
          <div
            v-if="!candidatesLoading && !candidates.length"
            class="flex flex-col items-center justify-center py-16 text-gray-400"
          >
            <icon-bulb class="text-5xl mb-3" />
            <p>{{ t('memory.candidateEmpty') }}</p>
          </div>
          <div v-else class="grid gap-3">
            <div
              v-for="candidate in candidates"
              :key="candidate.id"
              class="rounded-lg border bg-white p-4"
            >
              <div class="flex items-start justify-between gap-4">
                <div class="min-w-0 flex-1">
                  <div class="mb-2 flex flex-wrap items-center gap-2">
                    <a-tag
                      :color="typeColor(candidate.memory_type ?? 'profile')"
                      :data-memory-type="candidate.memory_type ?? 'profile'"
                      size="small"
                    >
                      {{ typeLabel(candidate.memory_type ?? 'profile') }}
                    </a-tag>
                    <span class="text-xs text-gray-400">
                      {{ t('memory.candidateOccurrence', { count: candidate.occurrences }) }}
                    </span>
                    <span class="text-xs text-amber-500">{{ confidenceStars(candidate.confidence) }}</span>
                  </div>
                  <p class="text-sm text-gray-700">{{ candidate.content }}</p>
                  <p class="mt-1 text-xs text-gray-400">{{ t('memory.candidateHint') }}</p>
                </div>
                <div class="flex flex-shrink-0 flex-col gap-2">
                  <a-button
                    type="primary"
                    size="small"
                    :loading="confirmingId === candidate.id"
                    @click="handleConfirmCandidate(candidate)"
                  >
                    {{ t('memory.confirmCandidate') }}
                  </a-button>
                  <a-button size="small" @click="handleIgnoreCandidate(candidate, false)">
                    {{ t('memory.ignoreCandidate') }}
                  </a-button>
                  <a-button size="small" status="warning" @click="handleIgnoreCandidate(candidate, true)">
                    {{ t('memory.neverRemind') }}
                  </a-button>
                </div>
              </div>
            </div>
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? t('memory.editTitle') : t('memory.createTitle')"
      :ok-text="editMode ? t('common.actions.save') : t('common.actions.create')"
      :cancel-text="t('common.actions.cancel')"
      :ok-loading="saving"
      @ok="handleSave"
      @cancel="modalVisible = false"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('memory.memoryTypeLabel')">
          <a-select v-model="form.memory_type" :options="memoryTypeOptions" />
        </a-form-item>
        <a-form-item :label="t('memory.memoryContentLabel')">
          <a-textarea
            v-model="form.content"
            :auto-size="{ minRows: 4, maxRows: 8 }"
            :placeholder="t('memory.contentPlaceholder')"
          />
        </a-form-item>
        <a-form-item :label="t('memory.confidenceLabel')">
          <a-slider v-model="form.confidence" :min="1" :max="5" show-input />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
