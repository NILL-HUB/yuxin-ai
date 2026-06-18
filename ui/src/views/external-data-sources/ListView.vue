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
import {
  authorizeExternalDataSource,
  deleteExternalDataSource,
  getExternalDataSources,
  syncExternalDataSource,
} from '@/services/external-data-source'
import type { ExternalDataSource } from '@/services/external-data-source'

const route = useRoute()
const credentialStore = useCredentialStore()
const { t } = useI18n()
const isLoggedIn = computed(() => isCredentialLoggedIn(credentialStore.credential))
const dataSources = ref<Array<ExternalDataSource>>([])
const loading = ref(false)
const syncingIds = ref<Record<string, boolean>>({})
const authorizingIds = ref<Record<string, boolean>>({})

const openLoginModal = () => {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent(AUTH_REQUIRED_EVENT, {
      detail: { redirect: route.fullPath },
    }),
  )
}

const loadDataSources = async () => {
  if (!isLoggedIn.value) return
  loading.value = true
  try {
    const res = await getExternalDataSources()
    dataSources.value = res.data || []
  } catch (error: unknown) {
    if (!isLoggedIn.value) return
    Message.error(getErrorMessage(error, t('externalDataSource.syncFailed')))
  } finally {
    loading.value = false
  }
}

const formatLastSyncedAt = (value: string) => {
  if (!value) return '-'
  const date = moment(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm') : value
}

const sourceTypeLabel = (sourceType: string) => {
  switch (sourceType) {
    case 'lark':
      return t('externalDataSource.lark')
    case 'drive':
      return t('externalDataSource.drive')
    case 'enterprise_knowledge':
      return t('externalDataSource.enterpriseKnowledge')
    default:
      return sourceType
  }
}

const sourceTypeColor = (sourceType: string) => {
  switch (sourceType) {
    case 'lark':
      return 'arcoblue'
    case 'drive':
      return 'cyan'
    case 'enterprise_knowledge':
      return 'purple'
    default:
      return 'gray'
  }
}

const authorizationStatusLabel = (status: string) => {
  switch (status) {
    case 'pending':
      return t('externalDataSource.pending')
    case 'granted':
      return t('externalDataSource.granted')
    case 'revoked':
      return t('externalDataSource.revoked')
    case 'expired':
      return t('externalDataSource.expired')
    default:
      return status
  }
}

const authorizationStatusColor = (status: string) => {
  switch (status) {
    case 'granted':
      return 'green'
    case 'pending':
      return 'gray'
    case 'revoked':
      return 'red'
    case 'expired':
      return 'orange'
    default:
      return 'gray'
  }
}

const syncStatusLabel = (status: string) => {
  switch (status) {
    case 'idle':
      return t('externalDataSource.idle')
    case 'syncing':
      return t('externalDataSource.syncing')
    case 'success':
      return t('externalDataSource.success')
    case 'failed':
      return t('externalDataSource.failed')
    default:
      return status
  }
}

const syncStatusColor = (status: string) => {
  switch (status) {
    case 'syncing':
      return 'arcoblue'
    case 'success':
      return 'green'
    case 'failed':
      return 'red'
    case 'idle':
    default:
      return 'gray'
  }
}

const handleAuthorize = async (record: ExternalDataSource) => {
  if (authorizingIds.value[record.id]) return
  authorizingIds.value[record.id] = true
  try {
    await authorizeExternalDataSource(record.id, {})
    Message.success(t('externalDataSource.granted'))
    await loadDataSources()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('externalDataSource.syncFailed')))
  } finally {
    authorizingIds.value[record.id] = false
  }
}

const handleSync = async (record: ExternalDataSource) => {
  if (syncingIds.value[record.id]) return
  syncingIds.value[record.id] = true
  try {
    const res = await syncExternalDataSource(record.id)
    const result = res.data
    if (result && result.sync_status === 'success') {
      Message.success(
        t('externalDataSource.syncSuccess', {
          document: result.document_count,
          segment: result.segment_count,
        }),
      )
    } else {
      Message.error(
        result?.last_error
          ? `${t('externalDataSource.syncFailed')}: ${result.last_error}`
          : t('externalDataSource.syncFailed'),
      )
    }
    await loadDataSources()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('externalDataSource.syncFailed')))
  } finally {
    syncingIds.value[record.id] = false
  }
}

const handleDelete = (record: ExternalDataSource) => {
  Modal.warning({
    title: t('externalDataSource.confirmDelete'),
    content: t('externalDataSource.confirmDeleteDescription'),
    hideCancel: false,
    okText: t('externalDataSource.delete'),
    cancelText: t('common.actions.cancel'),
    okButtonProps: { status: 'danger' },
    onOk: async () => {
      try {
        await deleteExternalDataSource(record.id)
        Message.success(t('externalDataSource.delete'))
        await loadDataSources()
      } catch (error: unknown) {
        Message.error(getErrorMessage(error, t('externalDataSource.syncFailed')))
      }
    },
  })
}

watch(
  isLoggedIn,
  async (loggedIn) => {
    if (!loggedIn) {
      dataSources.value = []
      return
    }
    await loadDataSources()
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
      <h3 class="text-lg font-semibold text-gray-900 mb-2">{{ t('externalDataSource.loginRequiredTitle') }}</h3>
      <p class="text-gray-500 mb-6 text-center max-w-md">{{ t('externalDataSource.loginRequiredDescription') }}</p>
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
      v-else-if="!loading && dataSources.length === 0"
      class="flex flex-col items-center justify-center h-full bg-white rounded-lg border border-gray-200"
    >
      <div class="w-24 h-24 mb-6 bg-gray-100 rounded-full flex items-center justify-center">
        <icon-storage class="text-5xl text-gray-400" />
      </div>
      <h3 class="text-lg font-semibold text-gray-900 mb-2">{{ t('externalDataSource.title') }}</h3>
      <p class="text-gray-500 mb-6 text-center max-w-md">
        {{ t('externalDataSource.noData') }}
      </p>
    </div>

    <div v-else>
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-xl font-semibold text-gray-900">{{ t('externalDataSource.title') }}</h2>
      </div>
      <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <a-table
          :loading="loading"
          :bordered="false"
          :data="dataSources"
          :hoverable="true"
          :pagination="false"
          row-key="id"
        >
          <template #columns>
            <a-table-column
              :title="t('externalDataSource.sourceName')"
              data-index="source_name"
              header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
              cell-class="!py-4"
            >
              <template #cell="{ record }">
                <div class="text-sm font-medium text-gray-900" :title="record.source_name">
                  {{ record.source_name }}
                </div>
              </template>
            </a-table-column>
            <a-table-column
              :title="t('externalDataSource.sourceType')"
              data-index="source_type"
              :width="140"
              header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
              cell-class="!py-4"
            >
              <template #cell="{ record }">
                <a-tag :color="sourceTypeColor(record.source_type)" size="small">
                  {{ sourceTypeLabel(record.source_type) }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column
              :title="t('externalDataSource.authorizationStatus')"
              data-index="authorization_status"
              :width="120"
              header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
              cell-class="!py-4"
            >
              <template #cell="{ record }">
                <a-tag
                  :color="authorizationStatusColor(record.authorization_status)"
                  size="small"
                >
                  {{ authorizationStatusLabel(record.authorization_status) }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column
              :title="t('externalDataSource.syncStatus')"
              data-index="sync_status"
              :width="120"
              header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
              cell-class="!py-4"
            >
              <template #cell="{ record }">
                <a-tag :color="syncStatusColor(record.sync_status)" size="small">
                  {{ syncStatusLabel(record.sync_status) }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column
              :title="t('externalDataSource.lastSyncedAt')"
              data-index="last_synced_at"
              :width="180"
              header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
              cell-class="!py-4"
            >
              <template #cell="{ record }">
                <div class="flex items-center gap-2 text-gray-600 text-sm whitespace-nowrap">
                  <icon-clock-circle class="text-gray-400 flex-shrink-0" :size="16" />
                  <span>{{ formatLastSyncedAt(record.last_synced_at) }}</span>
                </div>
              </template>
            </a-table-column>
            <a-table-column
              :title="t('externalDataSource.operations')"
              data-index="operator"
              header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
              cell-class="!py-4"
              :width="220"
            >
              <template #cell="{ record }">
                <div class="flex items-center gap-2">
                  <a-button
                    size="small"
                    :loading="!!authorizingIds[record.id]"
                    class="!rounded"
                    @click="handleAuthorize(record)"
                  >
                    {{ t('externalDataSource.authorize') }}
                  </a-button>
                  <a-button
                    size="small"
                    type="outline"
                    :loading="!!syncingIds[record.id]"
                    class="!rounded"
                    @click="handleSync(record)"
                  >
                    {{ t('externalDataSource.sync') }}
                  </a-button>
                  <a-button
                    size="small"
                    class="!rounded !text-red-600 hover:!text-red-700 hover:!bg-red-50"
                    @click="handleDelete(record)"
                  >
                    {{ t('externalDataSource.delete') }}
                  </a-button>
                </div>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
    </div>
  </div>
</template>

<style scoped>
:deep(.arco-table-tr:hover) {
  background-color: rgb(249 250 251) !important;
}
</style>
