<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  acceptSuggestion,
  applyPolicyChange,
  dismissSuggestion,
  getSuggestions,
  previewPolicyChange,
  type PolicyChangePreview,
  type Suggestion,
} from '@/services/admin-routing-quality-suggestion'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()
const loading = ref(false)
const suggestions = ref<Suggestion[]>([])

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewData = ref<PolicyChangePreview | null>(null)

const dismissVisible = ref(false)
const dismissSubmitting = ref(false)
const dismissTarget = ref<Suggestion | null>(null)
const dismissReason = ref('')

const applyVisible = ref(false)
const applySubmitting = ref(false)
const applyTarget = ref<Suggestion | null>(null)

const failMessage = (error: unknown) => getErrorMessage(error, t('admin.routingQuality.loadFailed'))

const severityColor = (severity: string) => {
  switch (severity) {
    case 'high':
      return 'red'
    case 'medium':
      return 'orange'
    default:
      return 'gray'
  }
}

const statusColor = (status: string) => {
  switch (status) {
    case 'open':
      return 'gray'
    case 'accepted':
      return 'blue'
    case 'dismissed':
      return 'red'
    case 'applied':
      return 'green'
    default:
      return 'gray'
  }
}

const KNOWN_STATUSES = ['open', 'accepted', 'dismissed', 'applied', 'pending', 'rolled_back']

const statusLabel = (status: string) => {
  return KNOWN_STATUSES.includes(status) ? t(`policyChange.${status}`) : status
}

const formatJson = (value: Record<string, unknown> | undefined) => {
  if (!value) return ''
  return JSON.stringify(value, null, 2)
}

const loadSuggestions = async () => {
  loading.value = true
  try {
    const res = await getSuggestions()
    suggestions.value = res.data || []
  } catch (error) {
    Message.error(failMessage(error))
  } finally {
    loading.value = false
  }
}

const handleAccept = async (record: Suggestion) => {
  try {
    await acceptSuggestion(record.id)
    Message.success(t('policyChange.acceptSuccess'))
    await loadSuggestions()
  } catch (error) {
    Message.error(failMessage(error))
  }
}

const openDismiss = (record: Suggestion) => {
  dismissTarget.value = record
  dismissReason.value = ''
  dismissVisible.value = true
}

const submitDismiss = async () => {
  if (!dismissTarget.value) return
  if (!dismissReason.value.trim()) return
  dismissSubmitting.value = true
  try {
    await dismissSuggestion(dismissTarget.value.id, dismissReason.value.trim())
    Message.success(t('policyChange.dismissSuccess'))
    dismissVisible.value = false
    await loadSuggestions()
  } catch (error) {
    Message.error(failMessage(error))
  } finally {
    dismissSubmitting.value = false
  }
}

const handlePreview = async (record: Suggestion) => {
  previewVisible.value = true
  previewLoading.value = true
  previewData.value = null
  try {
    const res = await previewPolicyChange(record.id)
    previewData.value = res.data
  } catch (error) {
    Message.error(failMessage(error))
    previewVisible.value = false
  } finally {
    previewLoading.value = false
  }
}

const openApply = (record: Suggestion) => {
  applyTarget.value = record
  applyVisible.value = true
}

const submitApply = async () => {
  if (!applyTarget.value) return
  applySubmitting.value = true
  try {
    const previewRes = await previewPolicyChange(applyTarget.value.id)
    await applyPolicyChange(applyTarget.value.id, previewRes.data)
    Message.success(t('policyChange.applySuccess'))
    applyVisible.value = false
    await loadSuggestions()
  } catch (error) {
    Message.error(failMessage(error))
  } finally {
    applySubmitting.value = false
  }
}

onMounted(loadSuggestions)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">
        {{ t('policyChange.title') }}
      </h1>
      <p class="mt-1 text-sm text-gray-500">{{ t('policyChange.suggestions') }}</p>
    </header>

    <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <a-table
        :loading="loading"
        :bordered="false"
        :data="suggestions"
        :hoverable="true"
        :pagination="false"
        row-key="id"
      >
        <template #columns>
          <a-table-column
            :title="t('policyChange.targetType')"
            data-index="target_type"
            :width="120"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <span class="text-sm text-gray-700">{{ record.target_type }}</span>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('policyChange.target')"
            data-index="target_id"
            :width="180"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <span class="text-sm text-gray-700 font-mono">{{ record.target_id }}</span>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('policyChange.suggestionType')"
            data-index="suggestion_type"
            :width="150"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <span class="text-sm text-gray-700">{{ record.suggestion_type }}</span>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('policyChange.severity')"
            data-index="severity"
            :width="110"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <a-tag :color="severityColor(record.severity)" size="small">{{ record.severity }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('policyChange.status')"
            data-index="status"
            :width="110"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <a-tag :color="statusColor(record.status)" size="small">{{ statusLabel(record.status) }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('policyChange.reason')"
            data-index="reason"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <span class="text-sm text-gray-600">{{ record.reason }}</span>
            </template>
          </a-table-column>
          <a-table-column
            :title="t('externalDataSource.operations')"
            data-index="operator"
            :width="280"
            header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
            cell-class="!py-4"
          >
            <template #cell="{ record }">
              <div class="flex flex-wrap items-center gap-2">
                <a-button
                  v-if="record.status === 'open'"
                  size="small"
                  type="primary"
                  @click="handleAccept(record)"
                >
                  {{ t('policyChange.accept') }}
                </a-button>
                <a-button
                  v-if="['open', 'accepted'].includes(record.status)"
                  size="small"
                  @click="openDismiss(record)"
                >
                  {{ t('policyChange.dismiss') }}
                </a-button>
                <a-button size="small" @click="handlePreview(record)">
                  {{ t('policyChange.preview') }}
                </a-button>
                <a-button
                  v-if="record.status === 'accepted'"
                  size="small"
                  type="primary"
                  @click="openApply(record)"
                >
                  {{ t('policyChange.apply') }}
                </a-button>
              </div>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </div>

    <a-modal
      v-model:visible="previewVisible"
      :title="t('policyChange.preview')"
      :footer="false"
      :width="720"
    >
      <a-spin :loading="previewLoading" class="block">
        <div v-if="previewData" class="space-y-4">
          <div>
            <p class="text-sm font-semibold text-gray-700 mb-1">{{ t('policyChange.beforeConfig') }}</p>
            <pre class="bg-gray-50 rounded p-3 text-xs overflow-auto max-h-60">{{ formatJson(previewData.before_config) }}</pre>
          </div>
          <div>
            <p class="text-sm font-semibold text-gray-700 mb-1">{{ t('policyChange.afterConfig') }}</p>
            <pre class="bg-gray-50 rounded p-3 text-xs overflow-auto max-h-60">{{ formatJson(previewData.after_config) }}</pre>
          </div>
          <div>
            <p class="text-sm font-semibold text-gray-700 mb-1">{{ t('policyChange.diff') }}</p>
            <pre class="bg-gray-50 rounded p-3 text-xs overflow-auto max-h-60">{{ formatJson(previewData.diff) }}</pre>
          </div>
          <div>
            <p class="text-sm font-semibold text-gray-700 mb-1">{{ t('policyChange.impact') }}</p>
            <pre class="bg-gray-50 rounded p-3 text-xs overflow-auto max-h-60">{{ formatJson(previewData.impact) }}</pre>
          </div>
        </div>
      </a-spin>
    </a-modal>

    <a-modal
      v-model:visible="dismissVisible"
      :title="t('policyChange.dismiss')"
      :ok-text="t('common.actions.confirm')"
      :cancel-text="t('common.actions.cancel')"
      :ok-loading="dismissSubmitting"
      :ok-button-props="{ disabled: !dismissReason.trim() }"
      @ok="submitDismiss"
    >
      <p class="text-sm text-gray-600 mb-2">{{ t('policyChange.confirmDismiss') }}</p>
      <a-textarea
        v-model="dismissReason"
        :auto-size="{ minRows: 3, maxRows: 6 }"
        :placeholder="t('policyChange.dismissReason')"
      />
    </a-modal>

    <a-modal
      v-model:visible="applyVisible"
      :title="t('policyChange.apply')"
      :ok-text="t('common.actions.confirm')"
      :cancel-text="t('common.actions.cancel')"
      :ok-loading="applySubmitting"
      @ok="submitApply"
    >
      <p class="text-sm text-gray-600">{{ t('policyChange.confirmApply') }}</p>
    </a-modal>
  </section>
</template>
