<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  confirmMemoryCandidate,
  createUserMemory,
  deleteUserMemory,
  ignoreMemoryCandidate,
  listMemoryCandidates,
  listUserMemories,
  updateUserMemory,
} from '@/services/user-memory'
import type { MemoryCandidate, UserMemory } from '@/services/user-memory'
import { getErrorMessage } from '@/utils/error'
import moment from 'moment'

type MemoryTypeMeta = {
  value: string
  label: string
  color: string
  desc: string
}

const MEMORY_TYPES: MemoryTypeMeta[] = [
  { value: 'profile', label: '个人资料', color: 'arcoblue', desc: '用户的基本身份信息，如姓名、职业等' },
  { value: 'preference', label: '偏好', color: 'green', desc: '用户喜好与习惯，如语言、风格偏好' },
  { value: 'relationship', label: '关系', color: 'purple', desc: '用户与他人或事物的关联关系' },
  { value: 'event', label: '事件', color: 'orange', desc: '发生过的具体事件或时间节点' },
  { value: 'project', label: '项目', color: 'cyan', desc: '用户参与的项目或长期目标' },
  { value: 'secret', label: '机密', color: 'red', desc: '敏感信息，使用时需格外谨慎' },
]

const typeMeta = (type: string): MemoryTypeMeta =>
  MEMORY_TYPES.find((item) => item.value === type) || { value: type, label: type, color: 'gray', desc: '' }
const typeLabel = (type: string) => typeMeta(type).label
const typeColor = (type: string) => typeMeta(type).color

const sourceLabel = (source: string) => {
  const map: Record<string, string> = {
    manual_input: '手动',
    llm_extracted: '自动抽取',
    confirmed: '已确认',
    auto_save: '自动保存',
  }
  return map[source] || source || '-'
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
    Message.error(getErrorMessage(error, '加载记忆失败'))
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
    Message.warning('请输入记忆内容')
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
    Message.success(editMode.value ? '更新成功' : '创建成功')
    modalVisible.value = false
    await loadMemories()
  } catch (error) {
    Message.error(getErrorMessage(error, '保存失败'))
  } finally {
    saving.value = false
  }
}

const toggleStatus = async (record: UserMemory, value: boolean) => {
  try {
    await updateUserMemory(record.id, { enabled: value })
    Message.success(value ? '已启用' : '已禁用')
    await loadMemories()
  } catch (error) {
    Message.error(getErrorMessage(error, '更新失败'))
  }
}

const handleDelete = async (record: UserMemory) => {
  try {
    await deleteUserMemory(record.id)
    Message.success('删除成功')
    await loadMemories()
  } catch (error) {
    Message.error(getErrorMessage(error, '删除失败'))
  }
}

const confirmingId = ref('')
const handleConfirmCandidate = async (record: MemoryCandidate) => {
  confirmingId.value = record.id
  try {
    await confirmMemoryCandidate(record.id, 'manual_confirm')
    Message.success('已保存为正式记忆')
    await Promise.all([loadMemories(), loadCandidates()])
  } catch (error) {
    Message.error(getErrorMessage(error, '确认失败'))
  } finally {
    confirmingId.value = ''
  }
}

const handleIgnoreCandidate = async (record: MemoryCandidate, neverRemind: boolean) => {
  try {
    await ignoreMemoryCandidate(record.id, neverRemind)
    Message.success(neverRemind ? '已忽略并不再提醒' : '已忽略')
    await loadCandidates()
  } catch (error) {
    Message.error(getErrorMessage(error, '忽略失败'))
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
  label: `${item.label} · ${item.desc}`,
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
        <h1 class="text-2xl font-semibold text-gray-900">长期记忆管理</h1>
        <p class="mt-1 text-sm text-gray-500">
          管理你的长期记忆与待确认候选，记忆会在对话中自动召回以提供更贴合的回复。
        </p>
      </div>
      <a-button type="primary" data-test="create-memory-btn" @click="openCreate">
        <template #icon>
          <icon-plus />
        </template>
        新建记忆
      </a-button>
    </header>

    <a-tabs v-model:active-key="activeTab" type="rounded">
      <a-tab-pane key="saved" title="已保存记忆">
        <div class="mb-3 flex items-center gap-3">
          <a-input
            v-model="keyword"
            placeholder="按内容搜索记忆"
            allow-clear
            class="max-w-sm"
          >
            <template #prefix>
              <icon-search />
            </template>
          </a-input>
          <span class="text-sm text-gray-400">共 {{ filteredMemories.length }} 条</span>
        </div>
        <a-spin :loading="loading" class="block">
          <div
            v-if="!loading && !filteredMemories.length"
            class="flex flex-col items-center justify-center py-16 text-gray-400"
          >
            <icon-bookmark class="text-5xl mb-3" />
            <p>暂无已保存的记忆</p>
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
                <a-table-column title="类型" data-index="memory_type" :width="120">
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
                <a-table-column title="内容" data-index="content">
                  <template #cell="{ record }">
                    <span class="text-sm text-gray-700" :title="record.content">{{ record.content }}</span>
                  </template>
                </a-table-column>
                <a-table-column title="置信度" data-index="confidence" :width="130">
                  <template #cell="{ record }">
                    <span class="text-amber-500 tracking-wider" :data-confidence="record.confidence">
                      {{ confidenceStars(record.confidence) }}
                    </span>
                  </template>
                </a-table-column>
                <a-table-column title="状态" data-index="status" :width="110">
                  <template #cell="{ record }">
                    <a-switch
                      :model-value="record.status === 'active'"
                      @change="(v: string | number | boolean) => toggleStatus(record, Boolean(v))"
                    />
                  </template>
                </a-table-column>
                <a-table-column title="来源" data-index="created_from" :width="100">
                  <template #cell="{ record }">
                    <span class="text-sm text-gray-500">{{ sourceLabel(record.created_from) }}</span>
                  </template>
                </a-table-column>
                <a-table-column title="创建时间" data-index="created_at" :width="160">
                  <template #cell="{ record }">
                    <span class="text-sm text-gray-500">{{ formatTime(record.created_at) }}</span>
                  </template>
                </a-table-column>
                <a-table-column title="操作" :width="170">
                  <template #cell="{ record }">
                    <a-space>
                      <a-button size="mini" @click="openEdit(record)">编辑</a-button>
                      <a-popconfirm
                        content="确定删除这条记忆吗？删除后无法恢复。"
                        @ok="handleDelete(record)"
                      >
                        <a-button size="mini" status="danger">删除</a-button>
                      </a-popconfirm>
                    </a-space>
                  </template>
                </a-table-column>
              </template>
            </a-table>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="candidates" title="待确认候选">
        <a-spin :loading="candidatesLoading" class="block">
          <div
            v-if="!candidatesLoading && !candidates.length"
            class="flex flex-col items-center justify-center py-16 text-gray-400"
          >
            <icon-bulb class="text-5xl mb-3" />
            <p>暂无待确认的记忆候选</p>
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
                      :color="typeColor(candidate.memory_type)"
                      :data-memory-type="candidate.memory_type"
                      size="small"
                    >
                      {{ typeLabel(candidate.memory_type) }}
                    </a-tag>
                    <span class="text-xs text-gray-400">出现 {{ candidate.occurrences }} 次</span>
                    <span class="text-xs text-amber-500">{{ confidenceStars(candidate.confidence) }}</span>
                  </div>
                  <p class="text-sm text-gray-700">{{ candidate.content }}</p>
                  <p class="mt-1 text-xs text-gray-400">
                    系统在对话中识别到该信息，确认后将作为正式长期记忆参与召回。
                  </p>
                </div>
                <div class="flex flex-shrink-0 flex-col gap-2">
                  <a-button
                    type="primary"
                    size="small"
                    :loading="confirmingId === candidate.id"
                    @click="handleConfirmCandidate(candidate)"
                  >
                    确认保存
                  </a-button>
                  <a-button size="small" @click="handleIgnoreCandidate(candidate, false)">忽略</a-button>
                  <a-button size="small" status="warning" @click="handleIgnoreCandidate(candidate, true)">
                    不再提醒
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
      :title="editMode ? '编辑记忆' : '新建记忆'"
      :ok-text="editMode ? '保存' : '创建'"
      cancel-text="取消"
      :ok-loading="saving"
      @ok="handleSave"
      @cancel="modalVisible = false"
    >
      <a-form layout="vertical">
        <a-form-item label="记忆类型">
          <a-select v-model="form.memory_type" :options="memoryTypeOptions" />
        </a-form-item>
        <a-form-item label="记忆内容">
          <a-textarea
            v-model="form.content"
            :auto-size="{ minRows: 4, maxRows: 8 }"
            placeholder="请输入记忆内容"
          />
        </a-form-item>
        <a-form-item label="置信度">
          <a-slider v-model="form.confidence" :min="1" :max="5" show-input />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
