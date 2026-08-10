<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  checkAgentHealth,
  createAgentPoolConfig,
  deleteAgentPoolConfig,
  getAgentPoolStats,
  listAgentPoolConfigs,
  setAgentPoolStatus,
  updateAgentPoolConfig,
} from '@/services/admin-agent-pool'
import { listAdminApps, type AdminAppRecord } from '@/services/admin-apps'
import { getErrorMessage } from '@/utils/error'
import GovernanceModeBanner from '@/components/GovernanceModeBanner.vue'

const { t } = useI18n()

// ==================== 类型定义 ====================

type AgentPoolConfig = {
  id: string
  app_id: string
  enabled: boolean
  health_status: string
  last_health_check_at?: number
  metadata?: Record<string, unknown>
  preset_prompt_summary?: string
  created_at?: number
  updated_at?: number
}

type PoolStatsItem = {
  total: number
  enabled: number
  healthy: number
}

type AppOption = {
  value: string
  label: string
  name: string
}

// ==================== 常量定义 ====================

const COST_LEVELS = ['low', 'medium', 'high']

// ==================== 标签 & 颜色映射 ====================

const costLabel = (cost: string) => t(`admin.agentPool.costLabels.${cost}`)
const healthLabel = (status: string) => t(`admin.agentPool.healthLabels.${status}`)

const healthColor = (status: string) =>
  ({ healthy: 'green', degraded: 'orange', offline: 'red', unknown: 'gray' } as Record<string, string>)[status] || 'gray'

const costColor = (cost: string) =>
  ({ low: 'green', medium: 'orange', high: 'red' } as Record<string, string>)[cost] || 'gray'

// 从 metadata 中提取 cost_level
const getCostLevel = (config: AgentPoolConfig) => {
  const metadata = config.metadata || {}
  return (metadata.cost_level as string) || 'medium'
}

// 从 metadata 中提取 capabilities
const getCapabilities = (config: AgentPoolConfig) => {
  const metadata = config.metadata || {}
  return (metadata.capabilities as string[]) || []
}

// ==================== Agent 池配置状态 ====================

const loading = ref(false)
const actionLoading = ref(false)
const configs = ref<AgentPoolConfig[]>([])
const stats = ref<PoolStatsItem[]>([])
const apps = ref<AdminAppRecord[]>([])
const appSearchLoading = ref(false)

const filters = ref({
  current_page: 1,
  page_size: 20,
})
const total = ref(0)

// App 选项：将已加载的 App 转为下拉选项
const appOptions = computed<AppOption[]>(() =>
  apps.value.map((app) => ({
    value: app.id,
    label: app.name || app.id,
    name: app.name || app.id,
  })),
)

// 根据 app_id 获取 App 名称，未命中时回退为截断的 UUID
const getAppLabel = (appId: string) => {
  const app = apps.value.find((a) => a.id === appId)
  return app?.name || `${appId.substring(0, 8)}...`
}

// 远程搜索 App，用于 a-select 的 @search 事件
const searchApps = async (keyword: string) => {
  appSearchLoading.value = true
  try {
    const data = await listAdminApps({
      current_page: 1,
      page_size: 50,
      search: keyword || undefined,
    })
    apps.value = data.list || []
  } catch {
    // 搜索失败时保留已有列表，不打断用户操作
  } finally {
    appSearchLoading.value = false
  }
}

const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const form = ref({
  app_id: '',
  enabled: true,
  cost_level: 'medium',
  capabilities: [] as string[],
  task_types: [] as string[],
})

// ==================== 统计卡片计算属性 ====================

const totalConfigs = computed(() => configs.value.length)
const enabledConfigs = computed(() => configs.value.filter((c) => c.enabled).length)
const healthyConfigs = computed(() => configs.value.filter((c) => c.health_status === 'healthy').length)

// ==================== Agent 池配置方法 ====================

const loadPoolConfigs = async () => {
  loading.value = true
  try {
    const [configResult, statsResult, appResult] = await Promise.all([
      listAgentPoolConfigs({ current_page: filters.value.current_page, page_size: filters.value.page_size }),
      getAgentPoolStats(),
      listAdminApps({ current_page: 1, page_size: 100 }),
    ])
    // request 返回完整 {code, message, data} 对象，data 中包含 list 和 paginator
    const configData = (configResult as { data?: { list?: AgentPoolConfig[]; paginator?: { total_record?: number } } }).data
    const statsData = (statsResult as { data?: { list?: PoolStatsItem[] } }).data
    configs.value = configData?.list || []
    total.value = configData?.paginator?.total_record || 0
    stats.value = statsData?.list || []
    apps.value = appResult.list || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agentPool.loadFailed')))
  } finally {
    loading.value = false
  }
}

const onPageChange = (page: number) => {
  filters.value.current_page = page
  loadPoolConfigs()
}

const onPageSizeChange = (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  loadPoolConfigs()
}

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  form.value = {
    app_id: '',
    enabled: true,
    cost_level: 'medium',
    capabilities: [],
    task_types: [],
  }
  modalVisible.value = true
}

const openEdit = (config: AgentPoolConfig) => {
  editMode.value = true
  editingId.value = config.id
  const metadata = config.metadata || {}
  form.value = {
    app_id: config.app_id,
    enabled: config.enabled,
    cost_level: (metadata.cost_level as string) || 'medium',
    capabilities: [...((metadata.capabilities as string[]) || [])],
    task_types: [...((metadata.task_types as string[]) || [])],
  }
  modalVisible.value = true
}

const submit = async () => {
  actionLoading.value = true
  try {
    const payload = {
      app_id: form.value.app_id,
      enabled: form.value.enabled,
      metadata: {
        cost_level: form.value.cost_level,
        capabilities: form.value.capabilities,
        task_types: form.value.task_types,
      },
    }
    if (editMode.value) {
      await updateAgentPoolConfig(editingId.value, payload)
      Message.success(t('admin.agentPool.updated'))
    } else {
      await createAgentPoolConfig(payload)
      Message.success(t('admin.agentPool.created'))
    }
    modalVisible.value = false
    await loadPoolConfigs()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agentPool.saveFailed')))
  } finally {
    actionLoading.value = false
  }
}

const toggleStatus = async (config: AgentPoolConfig, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setAgentPoolStatus(config.id, enabled)
    Message.success(enabled ? t('admin.agentPool.statusEnabled') : t('admin.agentPool.statusDisabled'))
    await loadPoolConfigs()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agentPool.updateStatusFailed')))
  } finally {
    actionLoading.value = false
  }
}

const runHealthCheck = async (config: AgentPoolConfig) => {
  actionLoading.value = true
  try {
    await checkAgentHealth(config.id)
    Message.success(t('admin.agentPool.healthCheckDone'))
    await loadPoolConfigs()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agentPool.healthCheckFailed')))
  } finally {
    actionLoading.value = false
  }
}

const remove = async (config: AgentPoolConfig) => {
  actionLoading.value = true
  try {
    await deleteAgentPoolConfig(config.id)
    Message.success(t('admin.agentPool.deleted'))
    await loadPoolConfigs()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agentPool.deleteFailed')))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadPoolConfigs)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.agentPool.title') }}</h1>
      <p class="mt-1 text-sm text-gray-500">{{ t('admin.agentPool.description') }}</p>
    </header>

    <!-- 治理模式状态栏 -->
    <GovernanceModeBanner />

    <!-- 统计卡片 -->
    <div class="grid gap-4 md:grid-cols-3">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.agentPool.statTotal') }}</p>
        <strong class="mt-1 block text-2xl">{{ totalConfigs }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.agentPool.statEnabled') }}</p>
        <strong class="mt-1 block text-2xl text-blue-600">{{ enabledConfigs }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.agentPool.statHealthy') }}</p>
        <strong class="mt-1 block text-2xl text-green-600">{{ healthyConfigs }}</strong>
      </article>
    </div>

    <!-- Agent 池配置列表 -->
    <div class="mb-3 flex justify-end">
      <a-button type="primary" @click="openCreate">{{ t('admin.agentPool.createConfig') }}</a-button>
    </div>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">{{ t('admin.agentPool.appId') }}</th>
              <th class="p-3" style="width: 200px">{{ t('admin.agentPool.presetPromptSummary') }}</th>
              <th class="p-3">{{ t('admin.agentPool.costLevel') }}</th>
              <th class="p-3">{{ t('admin.agentPool.capabilities') }}</th>
              <th class="p-3">{{ t('admin.agentPool.status') }}</th>
              <th class="p-3">{{ t('admin.agentPool.healthStatus') }}</th>
              <th class="p-3">{{ t('admin.agentPool.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!configs.length">
              <td class="p-6 text-center text-gray-400" colspan="7">{{ t('admin.agentPool.empty') }}</td>
            </tr>
            <tr v-for="config in configs" :key="config.id" class="border-t">
              <td class="p-3">
                <a-tooltip :content="config.app_id" position="tl" mini>
                  <div class="max-w-[180px] truncate cursor-help">{{ getAppLabel(config.app_id) }}</div>
                </a-tooltip>
              </td>
              <td class="p-3">
                <a-tooltip
                  v-if="config.preset_prompt_summary"
                  :content="config.preset_prompt_summary"
                  position="tl"
                  mini
                >
                  <div class="max-w-[200px] truncate cursor-help">{{ config.preset_prompt_summary }}</div>
                </a-tooltip>
                <span v-else class="text-gray-400">—</span>
              </td>
              <td class="p-3">
                <a-tag :color="costColor(getCostLevel(config))" size="small">{{ costLabel(getCostLevel(config)) }}</a-tag>
              </td>
              <td class="p-3">
                <div class="flex flex-wrap gap-1">
                  <a-tag v-for="cap in getCapabilities(config)" :key="cap" size="small" color="cyan">{{ cap }}</a-tag>
                  <span v-if="!getCapabilities(config).length" class="text-gray-400">-</span>
                </div>
              </td>
              <td class="p-3">
                <a-switch
                  :model-value="config.enabled"
                  :loading="actionLoading"
                  @change="(v: string | number | boolean) => toggleStatus(config, Boolean(v))"
                />
              </td>
              <td class="p-3">
                <a-tag :color="healthColor(config.health_status)" size="small">{{ healthLabel(config.health_status) }}</a-tag>
              </td>
              <td class="p-3">
                <a-space>
                  <a-button size="mini" @click="runHealthCheck(config)">{{ t('admin.agentPool.healthCheck') }}</a-button>
                  <a-button size="mini" @click="openEdit(config)">{{ t('admin.agentPool.edit') }}</a-button>
                  <a-button size="mini" status="danger" @click="remove(config)">{{ t('admin.agentPool.remove') }}</a-button>
                </a-space>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <div class="mt-3 flex justify-end">
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

    <!-- Agent 池配置 弹窗 -->
    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? t('admin.agentPool.editTitle') : t('admin.agentPool.createTitle')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="t('admin.agentPool.appId')" field="app_id">
          <a-select
            v-model="form.app_id"
            :placeholder="t('admin.agentPool.appIdPlaceholder')"
            :disabled="editMode"
            :loading="appSearchLoading"
            :options="appOptions"
            allow-search
            allow-clear
            :filterable="false"
            @search="searchApps"
          />
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.costLevel')" field="cost_level">
          <a-select v-model="form.cost_level">
            <a-option v-for="cost in COST_LEVELS" :key="cost" :value="cost">{{ costLabel(cost) }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.capabilities')" field="capabilities">
          <a-select v-model="form.capabilities" multiple allow-search allow-create :placeholder="t('admin.agentPool.capabilitiesPlaceholder')">
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.taskTypes')" field="task_types">
          <a-select v-model="form.task_types" multiple allow-search allow-create>
            <a-option value="qa">{{ t('admin.agentPool.taskTypeLabels.qa') }}</a-option>
            <a-option value="analysis">{{ t('admin.agentPool.taskTypeLabels.analysis') }}</a-option>
            <a-option value="workflow">{{ t('admin.agentPool.taskTypeLabels.workflow') }}</a-option>
            <a-option value="tool_use">{{ t('admin.agentPool.taskTypeLabels.tool_use') }}</a-option>
            <a-option value="coding">{{ t('admin.agentPool.taskTypeLabels.coding') }}</a-option>
            <a-option value="research">{{ t('admin.agentPool.taskTypeLabels.research') }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.agentPool.formEnabled')" field="enabled">
          <a-switch v-model="form.enabled" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
