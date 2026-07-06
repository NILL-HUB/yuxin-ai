<script setup lang="ts">
defineOptions({ name: 'SubPoolDefinitionView' })

import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  createSubPoolDefinition,
  deleteSubPoolDefinition,
  listSubPoolDefinitions,
  setSubPoolDefinitionStatus,
  updateSubPoolDefinition,
  type SubPoolDefinition,
  type SubPoolType,
} from '@/services/sub-pool-definition'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

const POOL_TYPE_OPTIONS = computed(() => [
  { label: t('admin.agentPool.subPoolFilterAllTypes'), value: '' },
  { label: t('admin.agentPool.subPoolTypeLabels.agent'), value: 'agent' },
  { label: t('admin.agentPool.subPoolTypeLabels.tool'), value: 'tool' },
])

const ENABLED_OPTIONS = computed(() => [
  { label: t('admin.agentPool.subPoolFilterAllStatus'), value: '' },
  { label: t('admin.agentPool.subPoolFilterEnabled'), value: 'true' },
  { label: t('admin.agentPool.subPoolFilterDisabled'), value: 'false' },
])

const loading = ref(false)
const actionLoading = ref(false)
const list = ref<SubPoolDefinition[]>([])
const total = ref(0)

const filters = ref({
  pool_type: '' as SubPoolType | '',
  enabled: '' as '' | 'true' | 'false',
  keyword: '',
  current_page: 1,
  page_size: 20,
})

const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const form = ref({
  pool_type: 'agent' as SubPoolType,
  name: '',
  label: '',
  description: '',
  visible_to_user: true,
  default_enabled: false,
  default_capabilities: [] as string[],
  task_keywords: [] as string[],
  sort_order: 0,
})

const loadList = async () => {
  loading.value = true
  try {
    const enabledParam: boolean | undefined =
      filters.value.enabled === '' ? undefined : filters.value.enabled === 'true'
    const res = await listSubPoolDefinitions({
      pool_type: filters.value.pool_type || undefined,
      enabled: enabledParam,
      keyword: filters.value.keyword || undefined,
      current_page: filters.value.current_page,
      page_size: filters.value.page_size,
    })
    list.value = res.data.list || []
    total.value = res.data.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agentPool.subPoolLoadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await loadList()
}

const onPageChange = async (page: number) => {
  filters.value.current_page = page
  await loadList()
}

const onPageSizeChange = async (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  await loadList()
}

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  form.value = {
    pool_type: 'agent',
    name: '',
    label: '',
    description: '',
    visible_to_user: true,
    default_enabled: false,
    default_capabilities: [],
    task_keywords: [],
    sort_order: 0,
  }
  modalVisible.value = true
}

const openEdit = (item: SubPoolDefinition) => {
  editMode.value = true
  editingId.value = item.id
  form.value = {
    pool_type: item.pool_type,
    name: item.name,
    label: item.label,
    description: item.description || '',
    visible_to_user: item.visible_to_user,
    default_enabled: item.default_enabled,
    default_capabilities: [...(item.default_capabilities || [])],
    task_keywords: [...(item.task_keywords || [])],
    sort_order: item.sort_order,
  }
  modalVisible.value = true
}

const submit = async () => {
  if (!form.value.name) {
    Message.warning(t('admin.agentPool.subPoolNameRequired'))
    return
  }
  if (!form.value.label) {
    Message.warning(t('admin.agentPool.subPoolLabelRequired'))
    return
  }
  actionLoading.value = true
  try {
    const payload = {
      pool_type: form.value.pool_type,
      name: form.value.name,
      label: form.value.label,
      description: form.value.description,
      visible_to_user: form.value.visible_to_user,
      default_enabled: form.value.default_enabled,
      default_capabilities: form.value.default_capabilities,
      task_keywords: form.value.task_keywords,
      sort_order: form.value.sort_order,
    }
    if (editMode.value) {
      await updateSubPoolDefinition(editingId.value, payload)
      Message.success(t('admin.agentPool.subPoolUpdated'))
    } else {
      await createSubPoolDefinition(payload)
      Message.success(t('admin.agentPool.subPoolCreated'))
    }
    modalVisible.value = false
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agentPool.subPoolSaveFailed')))
  } finally {
    actionLoading.value = false
  }
}

const toggleStatus = async (item: SubPoolDefinition, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setSubPoolDefinitionStatus(item.id, enabled)
    Message.success(enabled ? t('admin.agentPool.statusEnabled') : t('admin.agentPool.statusDisabled'))
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agentPool.updateStatusFailed')))
  } finally {
    actionLoading.value = false
  }
}

const remove = async (item: SubPoolDefinition) => {
  if (item.is_system) {
    Message.warning(t('admin.agentPool.subPoolSystemNoDelete'))
    return
  }
  actionLoading.value = true
  try {
    await deleteSubPoolDefinition(item.id)
    Message.success(t('admin.agentPool.subPoolDeleted'))
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agentPool.subPoolDeleteFailed')))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadList)
</script>

<template>
  <section class="space-y-6 p-6">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.agentPool.subPoolTitle') }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ t('admin.agentPool.subPoolDescription') }}</p>
      </div>
      <a-button type="primary" @click="openCreate">{{ t('admin.agentPool.subPoolCreate') }}</a-button>
    </header>

    <div class="rounded-lg border bg-white p-4">
      <div class="grid gap-3 md:grid-cols-4">
        <a-select v-model="filters.pool_type" :options="POOL_TYPE_OPTIONS" />
        <a-select v-model="filters.enabled" :options="ENABLED_OPTIONS" />
        <a-input
          v-model="filters.keyword"
          :placeholder="t('admin.agentPool.subPoolSearchPlaceholder')"
          allow-clear
          @press-enter="handleSearch"
        />
        <a-button type="primary" :loading="loading" @click="handleSearch">{{ t('admin.agentPool.search') }}</a-button>
      </div>
    </div>

    <a-spin :loading="loading" class="block">
      <div class="overflow-x-auto rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">{{ t('admin.agentPool.subPoolType') }}</th>
              <th class="p-3">{{ t('admin.agentPool.subPoolName') }}</th>
              <th class="p-3">{{ t('admin.agentPool.subPoolLabel') }}</th>
              <th class="p-3">{{ t('admin.agentPool.subPoolDesc') }}</th>
              <th class="p-3">{{ t('admin.agentPool.subPoolVisible') }}</th>
              <th class="p-3">{{ t('admin.agentPool.subPoolDefaultEnabled') }}</th>
              <th class="p-3">{{ t('admin.agentPool.keywordCount') }}</th>
              <th class="p-3">{{ t('admin.agentPool.subPoolSortOrder') }}</th>
              <th class="p-3">{{ t('admin.agentPool.status') }}</th>
              <th class="p-3">{{ t('admin.agentPool.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!list.length">
              <td class="p-6 text-center text-gray-400" colspan="10">{{ t('admin.agentPool.subPoolEmpty') }}</td>
            </tr>
            <tr v-for="item in list" :key="item.id" class="border-t">
              <td class="p-3">
                <a-tag :color="item.pool_type === 'agent' ? 'arcoblue' : 'purple'" size="small">
                  {{ item.pool_type === 'agent' ? t('admin.agentPool.subPoolTypeLabels.agent') : t('admin.agentPool.subPoolTypeLabels.tool') }}
                </a-tag>
              </td>
              <td class="p-3 font-mono">
                {{ item.name }}
                <a-tag v-if="item.is_system" size="small" color="gray">{{ t('admin.agentPool.subPoolIsSystem') }}</a-tag>
              </td>
              <td class="p-3">{{ item.label || '-' }}</td>
              <td class="p-3 max-w-xs truncate text-gray-500" :title="item.description">
                {{ item.description || '-' }}
              </td>
              <td class="p-3">
                <a-tag :color="item.visible_to_user ? 'green' : 'gray'" size="small">
                  {{ item.visible_to_user ? t('common.yes') : t('common.no') }}
                </a-tag>
              </td>
              <td class="p-3">
                <a-tag :color="item.default_enabled ? 'green' : 'gray'" size="small">
                  {{ item.default_enabled ? t('common.yes') : t('common.no') }}
                </a-tag>
              </td>
              <td class="p-3">{{ item.task_keywords?.length || 0 }}</td>
              <td class="p-3">{{ item.sort_order }}</td>
              <td class="p-3">
                <a-tag :color="item.enabled ? 'green' : 'red'" size="small">
                  {{ item.enabled ? t('admin.agentPool.subPoolEnabled') : t('admin.agentPool.subPoolDisabled') }}
                </a-tag>
              </td>
              <td class="p-3">
                <a-space>
                  <a-button size="mini" @click="openEdit(item)">{{ t('admin.agentPool.subPoolEdit') }}</a-button>
                  <a-button
                    v-if="!item.enabled"
                    size="mini"
                    type="primary"
                    :loading="actionLoading"
                    @click="toggleStatus(item, true)"
                  >{{ t('admin.agentPool.subPoolEnabled') }}</a-button>
                  <a-button
                    v-else
                    size="mini"
                    :loading="actionLoading"
                    @click="toggleStatus(item, false)"
                  >{{ t('admin.agentPool.subPoolDisabled') }}</a-button>
                  <a-tooltip v-if="item.is_system" :content="t('admin.agentPool.subPoolSystemNoDelete')">
                    <span>
                      <a-button size="mini" status="danger" disabled>{{ t('admin.agentPool.subPoolRemove') }}</a-button>
                    </span>
                  </a-tooltip>
                  <a-button
                    v-else
                    size="mini"
                    status="danger"
                    :loading="actionLoading"
                    @click="remove(item)"
                  >{{ t('admin.agentPool.subPoolRemove') }}</a-button>
                </a-space>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <div class="flex justify-end">
      <a-pagination
        :total="total"
        :current="filters.current_page"
        :page-size="filters.page_size"
        show-total
        show-page-size
        :page-size-options="[10, 20, 50, 100]"
        @change="onPageChange"
        @page-size-change="onPageSizeChange"
      />
    </div>

    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? t('admin.agentPool.subPoolEditTitle') : t('admin.agentPool.subPoolCreateTitle')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="t('admin.agentPool.subPoolType')" field="pool_type">
          <a-select v-model="form.pool_type" :disabled="editMode">
            <a-option value="agent">{{ t('admin.agentPool.subPoolTypeLabels.agent') }}</a-option>
            <a-option value="tool">{{ t('admin.agentPool.subPoolTypeLabels.tool') }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.subPoolName')" field="name">
          <a-input v-model="form.name" :disabled="editMode" :placeholder="t('admin.agentPool.subPoolNamePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.subPoolLabel')" field="label">
          <a-input v-model="form.label" :placeholder="t('admin.agentPool.subPoolLabelInputPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.subPoolDesc')" field="description">
          <a-textarea v-model="form.description" :placeholder="t('admin.agentPool.subPoolDescPlaceholder')" :auto-size="{ minRows: 2, maxRows: 4 }" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.subPoolVisible')" field="visible_to_user">
          <a-switch v-model="form.visible_to_user" />
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.subPoolDefaultEnabled')" field="default_enabled">
          <a-switch v-model="form.default_enabled" />
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.subPoolCapabilities')" field="default_capabilities">
          <a-input-tag v-model="form.default_capabilities" :placeholder="t('admin.agentPool.capabilitiesPlaceholder')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.subPoolKeywords')" field="task_keywords">
          <a-input-tag v-model="form.task_keywords" :placeholder="t('admin.agentPool.keywordsPlaceholder')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.subPoolSortOrder')" field="sort_order">
          <a-input-number v-model="form.sort_order" :min="0" :step="1" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
