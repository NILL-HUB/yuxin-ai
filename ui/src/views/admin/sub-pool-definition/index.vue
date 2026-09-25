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
import { getAgentAvatarStyle, getAgentAvatarText } from '@/utils/admin-agent-display'

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

// KPI：基于当前页列表统计（子池总量有限，分页仅用于长列表浏览）。
// 计数只为概览服务，精确总量以 total 为准，避免与分页口径混淆。
const kpi = computed(() => ({
  total: total.value,
  agent: list.value.filter((item) => item.pool_type === 'agent').length,
  tool: list.value.filter((item) => item.pool_type === 'tool').length,
  enabled: list.value.filter((item) => item.enabled).length,
}))

const columns = computed(() => [
  { title: t('admin.agentPool.subPoolType'), slotName: 'type', width: 110 },
  { title: t('admin.agentPool.subPoolName'), slotName: 'name', width: 220 },
  { title: t('admin.agentPool.subPoolLabel'), slotName: 'label', width: 140 },
  { title: t('admin.agentPool.subPoolDesc'), slotName: 'desc' },
  { title: t('admin.agentPool.subPoolVisible'), slotName: 'visible', width: 100 },
  { title: t('admin.agentPool.subPoolDefaultEnabled'), slotName: 'defaultEnabled', width: 110 },
  { title: t('admin.agentPool.keywordCount'), slotName: 'keywords', width: 110 },
  { title: t('admin.agentPool.subPoolSortOrder'), slotName: 'sort', width: 90 },
  { title: t('admin.agentPool.status'), slotName: 'status', width: 100 },
  { title: t('admin.agentPool.actions'), slotName: 'actions', width: 220 },
])

onMounted(loadList)
</script>

<template>
  <section class="space-y-6">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.agentPool.subPoolTitle') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.agentPool.subPoolDescription') }}</p>
      </div>
      <a-button type="primary" @click="openCreate">
        <template #icon><icon-plus /></template>
        {{ t('admin.agentPool.subPoolCreate') }}
      </a-button>
    </header>

    <!-- KPI 概览 -->
    <section class="grid gap-4 md:grid-cols-4">
      <article class="rounded-xl border border-slate-200 bg-white p-4">
        <p class="text-sm text-slate-500">{{ t('admin.agentPool.statTotal') }}</p>
        <strong class="mt-2 block text-3xl font-semibold text-slate-900">{{ kpi.total }}</strong>
      </article>
      <article class="rounded-xl border border-slate-200 bg-white p-4">
        <p class="text-sm text-slate-500">{{ t('admin.agentPool.subPoolTypeLabels.agent') }}</p>
        <strong class="mt-2 block text-3xl font-semibold text-blue-600">{{ kpi.agent }}</strong>
      </article>
      <article class="rounded-xl border border-slate-200 bg-white p-4">
        <p class="text-sm text-slate-500">{{ t('admin.agentPool.subPoolTypeLabels.tool') }}</p>
        <strong class="mt-2 block text-3xl font-semibold text-purple-600">{{ kpi.tool }}</strong>
      </article>
      <article class="rounded-xl border border-slate-200 bg-white p-4">
        <p class="text-sm text-slate-500">{{ t('admin.agentPool.subPoolEnabled') }}</p>
        <strong class="mt-2 block text-3xl font-semibold text-green-600">{{ kpi.enabled }}</strong>
      </article>
    </section>

    <!-- 筛选工具栏 -->
    <section class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4">
      <a-select v-model="filters.pool_type" :options="POOL_TYPE_OPTIONS" class="w-[160px]" />
      <a-select v-model="filters.enabled" :options="ENABLED_OPTIONS" class="w-[160px]" />
      <a-input
        v-model="filters.keyword"
        class="min-w-[220px] flex-1"
        :placeholder="t('admin.agentPool.subPoolSearchPlaceholder')"
        allow-clear
        @press-enter="handleSearch"
      />
      <a-button type="primary" :loading="loading" @click="handleSearch">
        {{ t('admin.agentPool.search') }}
      </a-button>
      <a-button :loading="loading" @click="loadList">
        {{ t('common.actions.refresh') }}
      </a-button>
    </section>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-50 text-slate-500">
            <tr>
              <th v-for="col in columns" :key="col.slotName" class="p-3 font-medium" :style="col.width ? { width: `${col.width}px` } : undefined">
                {{ col.title }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!list.length">
              <td class="p-6 text-center" colspan="10">
                <a-empty :description="t('admin.agentPool.subPoolEmpty')" />
              </td>
            </tr>
            <tr v-for="item in list" :key="item.id" class="border-t border-slate-100 hover:bg-slate-50/60">
              <td class="p-3">
                <a-tag :color="item.pool_type === 'agent' ? 'arcoblue' : 'purple'" size="small">
                  {{ item.pool_type === 'agent' ? t('admin.agentPool.subPoolTypeLabels.agent') : t('admin.agentPool.subPoolTypeLabels.tool') }}
                </a-tag>
              </td>
              <td class="p-3">
                <div class="flex items-center gap-2.5">
                  <span
                    class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[11px] font-semibold tracking-wide text-white"
                    :style="getAgentAvatarStyle(`${item.id}:${item.name}`)"
                  >
                    {{ getAgentAvatarText(item.label || item.name) }}
                  </span>
                  <div class="min-w-0">
                    <div class="flex items-center gap-1.5">
                      <span class="truncate font-mono text-[13px] font-medium text-slate-800">{{ item.name }}</span>
                      <a-tag v-if="item.is_system" size="small" color="gray">{{ t('admin.agentPool.subPoolIsSystem') }}</a-tag>
                    </div>
                  </div>
                </div>
              </td>
              <td class="p-3 font-medium text-slate-700">{{ item.label || '-' }}</td>
              <td class="p-3">
                <a-tooltip v-if="item.description" :content="item.description" position="tl" mini>
                  <div class="max-w-xs truncate cursor-help text-slate-500">{{ item.description }}</div>
                </a-tooltip>
                <span v-else class="text-slate-300">-</span>
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
              <td class="p-3 text-slate-600">{{ item.task_keywords?.length || 0 }}</td>
              <td class="p-3 text-slate-600">{{ item.sort_order }}</td>
              <td class="p-3">
                <a-tag :color="item.enabled ? 'green' : 'red'" size="small">
                  {{ item.enabled ? t('admin.agentPool.subPoolEnabled') : t('admin.agentPool.subPoolDisabled') }}
                </a-tag>
              </td>
              <td class="p-3">
                <a-space :size="4">
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
