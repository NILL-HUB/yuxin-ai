<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Message, Modal } from '@arco-design/web-vue'
import { useCredentialStore } from '@/stores/credential'
import { AUTH_REQUIRED_EVENT } from '@/utils/request'
import { isCredentialLoggedIn } from '@/utils/auth'
import { getErrorMessage } from '@/utils/error'
import { useI18n } from 'vue-i18n'
import moment from 'moment'
import { deleteUserMemory, getUserMemories, updateUserMemory } from '@/services/memory'
import type { UserMemory } from '@/models/memory'

const route = useRoute()
const credentialStore = useCredentialStore()
const { t } = useI18n()
const isLoggedIn = computed(() => isCredentialLoggedIn(credentialStore.credential))
const memories = ref<Array<UserMemory>>([])
const loading = ref(false)
const editModalVisible = ref(false)
const saving = ref(false)
const editForm = ref({
  id: '',
  content: '',
  memory_type: '',
  enabled: true,
})

const openLoginModal = () => {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent(AUTH_REQUIRED_EVENT, {
      detail: { redirect: route.fullPath },
    }),
  )
}

const loadMemories = async () => {
  if (!isLoggedIn.value) return
  loading.value = true
  try {
    const res = await getUserMemories()
    memories.value = res.data || []
  } catch (error: unknown) {
    if (!isLoggedIn.value) return
    Message.error(getErrorMessage(error, t('memory.loadFailed')))
  } finally {
    loading.value = false
  }
}

const formatCreatedAt = (value: string) => {
  if (!value) return ''
  const date = moment(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm') : value
}

const formatConfidence = (value: number) => {
  if (typeof value !== 'number' || isNaN(value)) return '-'
  const percent = value > 1 ? value : value * 100
  return `${Math.round(percent)}%`
}

const isEnabled = (status: string) => {
  return status === 'active' || status === 'enabled'
}

const openEditModal = (record: UserMemory) => {
  editForm.value = {
    id: record.id,
    content: record.content,
    memory_type: record.memory_type,
    enabled: isEnabled(record.status),
  }
  editModalVisible.value = true
}

const handleSave = async () => {
  if (!editForm.value.content.trim()) return
  saving.value = true
  try {
    await updateUserMemory(editForm.value.id, {
      content: editForm.value.content,
      memory_type: editForm.value.memory_type,
      enabled: editForm.value.enabled,
    })
    Message.success(t('memory.saveSuccess'))
    editModalVisible.value = false
    await loadMemories()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('memory.saveFailed')))
  } finally {
    saving.value = false
  }
}

const handleDelete = (record: UserMemory) => {
  Modal.warning({
    title: t('memory.deleteConfirm'),
    content: t('memory.deleteConfirmDescription'),
    hideCancel: false,
    okText: t('common.actions.confirm'),
    cancelText: t('common.actions.cancel'),
    okButtonProps: { status: 'danger' },
    onOk: async () => {
      try {
        await deleteUserMemory(record.id)
        Message.success(t('memory.deleteSuccess'))
        await loadMemories()
      } catch (error: unknown) {
        Message.error(getErrorMessage(error, t('memory.deleteFailed')))
      }
    },
  })
}

watch(
  isLoggedIn,
  async (loggedIn) => {
    if (!loggedIn) {
      memories.value = []
      return
    }
    await loadMemories()
  },
  { immediate: true },
)
</script>

<template>
  <div class="h-[calc(100vh-160px)] overflow-scroll scrollbar-w-none">
    <div
      v-if="!isLoggedIn"
      class="flex flex-col items-center justify-center h-full bg-white rounded-lg border border-gray-200"
    >
      <div class="w-24 h-24 mb-6 bg-gray-100 rounded-full flex items-center justify-center">
        <icon-user class="text-5xl text-gray-400" />
      </div>
      <h3 class="text-lg font-semibold text-gray-900 mb-2">{{ t('memory.loginRequiredTitle') }}</h3>
      <p class="text-gray-500 mb-6 text-center max-w-md">{{ t('memory.loginRequiredDescription') }}</p>
      <a-button
        type="primary"
        size="large"
        class="!rounded-lg !bg-gray-900 hover:!bg-gray-800"
        @click="openLoginModal"
      >
        {{ t('common.actions.login') }}
      </a-button>
    </div>

    <div
      v-else-if="!loading && memories.length === 0"
      class="flex flex-col items-center justify-center h-full bg-white rounded-lg border border-gray-200"
    >
      <div class="w-24 h-24 mb-6 bg-gray-100 rounded-full flex items-center justify-center">
        <icon-bookmark class="text-5xl text-gray-400" />
      </div>
      <h3 class="text-lg font-semibold text-gray-900 mb-2">{{ t('memory.noDataTitle') }}</h3>
      <p class="text-gray-500 mb-6 text-center max-w-md">
        {{ t('memory.noDataDescription') }}
      </p>
    </div>

    <div v-else class="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <a-table
        :loading="loading"
        :bordered="false"
        :data="memories"
        :hoverable="true"
        :pagination="false"
      >
        <template #columns>
          <a-table-column
            :title="t('memory.columns.content')"
            data-index="content"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <div class="text-sm text-gray-700" :title="record.content">
                {{
                  record.content.length > 60
                    ? record.content.substring(0, 60) + '...'
                    : record.content
                }}
              </div>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('memory.columns.type')"
            data-index="memory_type"
            :width="140"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <div
                class="inline-flex items-center gap-2 px-2.5 py-1 bg-blue-50 border border-blue-200 rounded text-blue-700 text-xs font-medium whitespace-nowrap"
              >
                {{ record.memory_type }}
              </div>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('memory.columns.confidence')"
            data-index="confidence"
            :width="120"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <div class="text-sm text-gray-600 whitespace-nowrap">
                {{ formatConfidence(record.confidence) }}
              </div>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('memory.columns.status')"
            data-index="status"
            :width="120"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <div
                v-if="isEnabled(record.status)"
                class="inline-flex items-center gap-2 px-2.5 py-1 bg-green-50 border border-green-200 rounded text-green-700 text-sm font-medium whitespace-nowrap"
              >
                <div class="w-1.5 h-1.5 bg-green-500 rounded-full"></div>
                {{ t('memory.enabled') }}
              </div>
              <div
                v-else
                class="inline-flex items-center gap-2 px-2.5 py-1 bg-gray-100 border border-gray-200 rounded text-gray-600 text-sm font-medium whitespace-nowrap"
              >
                <div class="w-1.5 h-1.5 bg-gray-400 rounded-full"></div>
                {{ t('memory.disabled') }}
              </div>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('memory.columns.createdAt')"
            data-index="created_at"
            :width="160"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <div class="flex items-center gap-2 text-gray-600 text-sm whitespace-nowrap">
                <icon-clock-circle class="text-gray-400 flex-shrink-0" :size="16" />
                <span>{{ formatCreatedAt(record.created_at) }}</span>
              </div>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('memory.columns.actions')"
            data-index="operator"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
            :width="160"
          >
            <template #cell="{ record }">
              <div class="flex items-center gap-3">
                <a-tooltip :content="t('memory.editTitle')">
                  <a-button
                    size="small"
                    class="!rounded !text-gray-600 hover:!text-gray-900 hover:!bg-gray-100"
                    @click="openEditModal(record)"
                  >
                    <template #icon>
                      <icon-edit />
                    </template>
                  </a-button>
                </a-tooltip>
                <a-tooltip :content="t('common.actions.delete')">
                  <a-button
                    size="small"
                    class="!rounded !text-red-600 hover:!text-red-700 hover:!bg-red-50"
                    @click="handleDelete(record)"
                  >
                    <template #icon>
                      <icon-delete />
                    </template>
                  </a-button>
                </a-tooltip>
              </div>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </div>

    <a-modal
      v-model:visible="editModalVisible"
      :title="t('memory.editTitle')"
      :ok-text="t('common.actions.save')"
      :cancel-text="t('common.actions.cancel')"
      :ok-loading="saving"
      @ok="handleSave"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('memory.contentLabel')">
          <a-textarea
            v-model="editForm.content"
            :auto-size="{ minRows: 4, maxRows: 8 }"
            :placeholder="t('memory.contentLabel')"
          />
        </a-form-item>
        <a-form-item :label="t('memory.enabledLabel')">
          <a-switch v-model="editForm.enabled" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<style scoped>
:deep(.arco-table-tr:hover) {
  background-color: rgb(249 250 251) !important;
}

:deep(.arco-switch) {
  background-color: rgb(209 213 219) !important;
}

:deep(.arco-switch-checked) {
  background-color: rgb(34 197 94) !important;
}

:deep(.arco-switch:hover) {
  opacity: 0.9;
}
</style>
