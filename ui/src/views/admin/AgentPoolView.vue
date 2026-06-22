<script setup lang="ts">
import { onMounted, ref } from 'vue'
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
import { getErrorMessage } from '@/utils/error'

type AgentPoolConfig = {
  id: string
  app_id: string
  primary_pool: string
  secondary_pools: string[]
  risk_level: string
  model_tier: string
  model_id: string
  routing_priority: number
  enabled: boolean
  health_status: string
  last_health_check_at?: number
  created_at?: number
  updated_at?: number
}

type PoolStatsItem = {
  pool: string
  total: number
  enabled: number
  healthy: number
}

const PRIMARY_POOLS = ['tenant', 'system', 'global']
const RISK_LEVELS = ['low', 'medium', 'high']
const MODEL_TIERS = ['cheap', 'balanced', 'strong']

const loading = ref(false)
const actionLoading = ref(false)
const configs = ref<AgentPoolConfig[]>([])
const stats = ref<PoolStatsItem[]>([])

const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const form = ref({
  app_id: '',
  primary_pool: 'tenant',
  secondary_pools: [] as string[],
  risk_level: 'medium',
  model_tier: 'balanced',
  model_id: '',
  routing_priority: 100,
  enabled: true,
})

const riskColor = (risk: string) =>
  ({ low: 'green', medium: 'orange', high: 'red' } as Record<string, string>)[risk] || 'gray'

const healthColor = (status: string) =>
  ({ healthy: 'green', degraded: 'orange', offline: 'red', unknown: 'gray' } as Record<string, string>)[status] || 'gray'

const formatTimestamp = (timestamp?: number) =>
  timestamp ? new Date(timestamp * 1000).toLocaleString() : '-'

const loadAll = async () => {
  loading.value = true
  try {
    const [configResult, statsResult] = await Promise.all([
      listAgentPoolConfigs({ current_page: 1, page_size: 50 }),
      getAgentPoolStats(),
    ])
    configs.value = (configResult as { list?: AgentPoolConfig[] }).list || []
    stats.value = (statsResult as { list?: PoolStatsItem[] }).list || []
  } catch (error) {
    Message.error(getErrorMessage(error, '加载Agent池数据失败'))
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  form.value = {
    app_id: '',
    primary_pool: 'tenant',
    secondary_pools: [],
    risk_level: 'medium',
    model_tier: 'balanced',
    model_id: '',
    routing_priority: 100,
    enabled: true,
  }
  modalVisible.value = true
}

const openEdit = (config: AgentPoolConfig) => {
  editMode.value = true
  editingId.value = config.id
  form.value = {
    app_id: config.app_id,
    primary_pool: config.primary_pool,
    secondary_pools: [...(config.secondary_pools || [])],
    risk_level: config.risk_level,
    model_tier: config.model_tier,
    model_id: config.model_id || '',
    routing_priority: config.routing_priority,
    enabled: config.enabled,
  }
  modalVisible.value = true
}

const submit = async () => {
  actionLoading.value = true
  try {
    const payload = { ...form.value }
    if (editMode.value) {
      await updateAgentPoolConfig(editingId.value, payload)
      Message.success('Agent池配置已更新')
    } else {
      await createAgentPoolConfig(payload)
      Message.success('Agent池配置已创建')
    }
    modalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '保存Agent池配置失败'))
  } finally {
    actionLoading.value = false
  }
}

const toggleStatus = async (config: AgentPoolConfig, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setAgentPoolStatus(config.id, enabled)
    Message.success(enabled ? '已启用' : '已停用')
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '更新状态失败'))
  } finally {
    actionLoading.value = false
  }
}

const runHealthCheck = async (config: AgentPoolConfig) => {
  actionLoading.value = true
  try {
    await checkAgentHealth(config.id)
    Message.success('健康检查已完成')
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '健康检查失败'))
  } finally {
    actionLoading.value = false
  }
}

const remove = async (config: AgentPoolConfig) => {
  actionLoading.value = true
  try {
    await deleteAgentPoolConfig(config.id)
    Message.success('配置已删除')
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '删除配置失败'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">Agent 池配置</h1>
      <p class="mt-1 text-sm text-gray-500">维护各应用的主备池路由、风险等级与模型档位，并执行健康检查。</p>
    </header>

    <div class="grid gap-4 md:grid-cols-3">
      <article v-if="!stats.length" class="rounded-lg border bg-white p-4 text-sm text-gray-400">
        暂无池统计数据
      </article>
      <article
        v-for="item in stats"
        :key="item.pool"
        class="rounded-lg border bg-white p-4"
      >
        <p class="text-sm text-gray-500">{{ item.pool }} 池</p>
        <div class="mt-2 flex items-baseline gap-4">
          <strong class="text-xl">{{ item.total }}</strong>
          <span class="text-sm text-gray-500">启用 {{ item.enabled }}</span>
          <span class="text-sm text-green-600">健康 {{ item.healthy }}</span>
        </div>
      </article>
    </div>

    <div class="flex justify-end">
      <a-button type="primary" @click="openCreate">新建配置</a-button>
    </div>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">应用 ID</th>
              <th class="p-3">主池</th>
              <th class="p-3">次级池</th>
              <th class="p-3">风险等级</th>
              <th class="p-3">模型档位</th>
              <th class="p-3">路由优先级</th>
              <th class="p-3">状态</th>
              <th class="p-3">健康状态</th>
              <th class="p-3">最后检查</th>
              <th class="p-3">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!configs.length">
              <td class="p-6 text-center text-gray-400" colspan="10">暂无 Agent 池配置</td>
            </tr>
            <tr v-for="config in configs" :key="config.id" class="border-t">
              <td class="p-3 font-mono">{{ config.app_id }}</td>
              <td class="p-3">{{ config.primary_pool }}</td>
              <td class="p-3">
                <a-tag v-for="pool in config.secondary_pools" :key="pool" size="small">{{ pool }}</a-tag>
                <span v-if="!config.secondary_pools?.length" class="text-gray-400">-</span>
              </td>
              <td class="p-3">
                <a-tag :color="riskColor(config.risk_level)" size="small">{{ config.risk_level }}</a-tag>
              </td>
              <td class="p-3">{{ config.model_tier }}</td>
              <td class="p-3">{{ config.routing_priority }}</td>
              <td class="p-3">
                <a-switch
                  :model-value="config.enabled"
                  :loading="actionLoading"
                  @change="(v: string | number | boolean) => toggleStatus(config, Boolean(v))"
                />
              </td>
              <td class="p-3">
                <a-tag :color="healthColor(config.health_status)" size="small">{{ config.health_status }}</a-tag>
              </td>
              <td class="p-3">{{ formatTimestamp(config.last_health_check_at) }}</td>
              <td class="p-3">
                <a-space>
                  <a-button size="mini" @click="runHealthCheck(config)">健康检查</a-button>
                  <a-button size="mini" @click="openEdit(config)">编辑</a-button>
                  <a-button size="mini" status="danger" @click="remove(config)">删除</a-button>
                </a-space>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? '编辑 Agent 池配置' : '新建 Agent 池配置'"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="应用 ID" field="app_id">
          <a-input v-model="form.app_id" placeholder="请输入应用 ID" :disabled="editMode" />
        </a-form-item>
        <a-form-item label="主池" field="primary_pool">
          <a-select v-model="form.primary_pool">
            <a-option v-for="pool in PRIMARY_POOLS" :key="pool" :value="pool">{{ pool }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="次级池" field="secondary_pools">
          <a-select v-model="form.secondary_pools" multiple allow-search allow-create>
            <a-option v-for="pool in PRIMARY_POOLS" :key="pool" :value="pool">{{ pool }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="风险等级" field="risk_level">
          <a-select v-model="form.risk_level">
            <a-option v-for="risk in RISK_LEVELS" :key="risk" :value="risk">{{ risk }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="模型档位" field="model_tier">
          <a-select v-model="form.model_tier">
            <a-option v-for="tier in MODEL_TIERS" :key="tier" :value="tier">{{ tier }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="模型 ID" field="model_id">
          <a-input v-model="form.model_id" placeholder="如 deepseek-chat" />
        </a-form-item>
        <a-form-item label="路由优先级" field="routing_priority">
          <a-input-number v-model="form.routing_priority" :min="0" :max="9999" />
        </a-form-item>
        <a-form-item label="启用" field="enabled">
          <a-switch v-model="form.enabled" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
