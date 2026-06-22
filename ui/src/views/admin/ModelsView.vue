<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  createModel,
  createModelKey,
  deleteModel,
  deleteModelKey,
  listCostPolicies,
  listModelKeys,
  listModels,
  listTierPolicies,
  setModelKeyStatus,
  setModelStatus,
  updateCostPolicy,
  updateModel,
  updateTierPolicy,
} from '@/services/admin-model-pool'
import { getErrorMessage } from '@/utils/error'

type ModelRecord = {
  id: string
  provider: string
  model_name: string
  display_name: string
  tier: string
  capabilities: string[]
  price_per_1k_tokens: string
  max_tokens: number
  status: string
  created_at?: number
  updated_at?: number
}

type ModelKeyRecord = {
  id: string
  provider: string
  key_alias: string
  key_mask: string
  tenant_quota: string
  status: string
  failure_count: number
  created_at?: number
  updated_at?: number
}

type TierPolicy = {
  id: string
  tier_code: string
  allowed_models: string[]
  default_model: string
  routing_rules: Record<string, unknown>
  created_at?: number
  updated_at?: number
}

type CostPolicy = {
  id: string
  policy_name: string
  model_tier: string
  max_cost_per_request: string
  billing_mode: string
  upgrade_threshold: string
  created_at?: number
  updated_at?: number
}

const MODEL_TIERS = ['cheap', 'standard', 'strong']
const PROVIDERS = ['openai', 'anthropic', 'deepseek', 'qwen', 'zhipu', 'other']
const BILLING_MODES = ['token', 'request', 'credit']

const loading = ref(false)
const actionLoading = ref(false)
const activeTab = ref('models')

const models = ref<ModelRecord[]>([])
const keys = ref<ModelKeyRecord[]>([])
const tiers = ref<TierPolicy[]>([])
const costPolicies = ref<CostPolicy[]>([])

const stats = computed(() => ({
  modelTotal: models.value.length,
  modelEnabled: models.value.filter((item) => item.status === 'active').length,
  keyTotal: keys.value.length,
  tierTotal: tiers.value.length,
}))

const modelModalVisible = ref(false)
const modelEditMode = ref(false)
const editingModelId = ref('')
const modelForm = ref({
  provider: 'openai',
  model_name: '',
  display_name: '',
  tier: 'standard',
  capabilities: [] as string[],
  price_per_1k_tokens: '0.000000',
  max_tokens: 0,
})

const keyModalVisible = ref(false)
const keyForm = ref({
  provider: 'openai',
  key_alias: '',
  key_value: '',
  tenant_quota: '0.0000',
})

const tierModalVisible = ref(false)
const editingTierCode = ref('')
const tierForm = ref({
  tier_code: '',
  allowed_models: [] as string[],
  default_model: '',
})

const costModalVisible = ref(false)
const editingCostId = ref('')
const costForm = ref({
  policy_name: '',
  model_tier: 'standard',
  max_cost_per_request: '0.000000',
  billing_mode: 'token',
  upgrade_threshold: '0.000000',
})

const loadAll = async () => {
  loading.value = true
  try {
    const [modelResult, keyResult, tierResult, costResult] = await Promise.all([
      listModels({ current_page: 1, page_size: 50 }),
      listModelKeys({ current_page: 1, page_size: 50 }),
      listTierPolicies(),
      listCostPolicies(),
    ])
    models.value = (modelResult as { list?: ModelRecord[] }).list || []
    keys.value = (keyResult as { list?: ModelKeyRecord[] }).list || []
    tiers.value = (tierResult as { list?: TierPolicy[] }).list || []
    costPolicies.value = (costResult as { list?: CostPolicy[] }).list || []
  } catch (error) {
    Message.error(getErrorMessage(error, '加载模型池数据失败'))
  } finally {
    loading.value = false
  }
}

const openCreateModel = () => {
  modelEditMode.value = false
  editingModelId.value = ''
  modelForm.value = {
    provider: 'openai',
    model_name: '',
    display_name: '',
    tier: 'standard',
    capabilities: [],
    price_per_1k_tokens: '0.000000',
    max_tokens: 0,
  }
  modelModalVisible.value = true
}

const openEditModel = (model: ModelRecord) => {
  modelEditMode.value = true
  editingModelId.value = model.id
  modelForm.value = {
    provider: model.provider,
    model_name: model.model_name,
    display_name: model.display_name,
    tier: model.tier,
    capabilities: [...(model.capabilities || [])],
    price_per_1k_tokens: model.price_per_1k_tokens,
    max_tokens: model.max_tokens,
  }
  modelModalVisible.value = true
}

const submitModel = async () => {
  actionLoading.value = true
  try {
    if (modelEditMode.value) {
      await updateModel(editingModelId.value, { ...modelForm.value })
      Message.success('模型已更新')
    } else {
      await createModel({ ...modelForm.value })
      Message.success('模型已创建')
    }
    modelModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '保存模型失败'))
  } finally {
    actionLoading.value = false
  }
}

const toggleModel = async (model: ModelRecord, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setModelStatus(model.id, enabled)
    Message.success(enabled ? '模型已启用' : '模型已停用')
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '更新模型状态失败'))
  } finally {
    actionLoading.value = false
  }
}

const removeModel = async (model: ModelRecord) => {
  actionLoading.value = true
  try {
    await deleteModel(model.id)
    Message.success('模型已删除')
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '删除模型失败'))
  } finally {
    actionLoading.value = false
  }
}

const openCreateKey = () => {
  keyForm.value = { provider: 'openai', key_alias: '', key_value: '', tenant_quota: '0.0000' }
  keyModalVisible.value = true
}

const submitKey = async () => {
  actionLoading.value = true
  try {
    await createModelKey({ ...keyForm.value })
    Message.success('模型Key已创建')
    keyModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '创建模型Key失败'))
  } finally {
    actionLoading.value = false
  }
}

const toggleKey = async (key: ModelKeyRecord, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setModelKeyStatus(key.id, enabled)
    Message.success(enabled ? 'Key已启用' : 'Key已停用')
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '更新Key状态失败'))
  } finally {
    actionLoading.value = false
  }
}

const removeKey = async (key: ModelKeyRecord) => {
  actionLoading.value = true
  try {
    await deleteModelKey(key.id)
    Message.success('Key已删除')
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '删除Key失败'))
  } finally {
    actionLoading.value = false
  }
}

const openEditTier = (tier: TierPolicy) => {
  editingTierCode.value = tier.tier_code
  tierForm.value = {
    tier_code: tier.tier_code,
    allowed_models: [...(tier.allowed_models || [])],
    default_model: tier.default_model,
  }
  tierModalVisible.value = true
}

const submitTier = async () => {
  actionLoading.value = true
  try {
    await updateTierPolicy(editingTierCode.value, {
      allowed_models: tierForm.value.allowed_models,
      default_model: tierForm.value.default_model,
    })
    Message.success('档位策略已更新')
    tierModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '更新档位策略失败'))
  } finally {
    actionLoading.value = false
  }
}

const openEditCost = (policy: CostPolicy) => {
  editingCostId.value = policy.id
  costForm.value = {
    policy_name: policy.policy_name,
    model_tier: policy.model_tier,
    max_cost_per_request: policy.max_cost_per_request,
    billing_mode: policy.billing_mode,
    upgrade_threshold: policy.upgrade_threshold,
  }
  costModalVisible.value = true
}

const submitCost = async () => {
  actionLoading.value = true
  try {
    await updateCostPolicy(editingCostId.value, {
      model_tier: costForm.value.model_tier,
      max_cost_per_request: costForm.value.max_cost_per_request,
      billing_mode: costForm.value.billing_mode,
      upgrade_threshold: costForm.value.upgrade_threshold,
    })
    Message.success('成本策略已更新')
    costModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '更新成本策略失败'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">模型池管理</h1>
      <p class="mt-1 text-sm text-gray-500">维护模型配置、Key 凭据、档位策略与成本策略。</p>
    </header>

    <div class="grid gap-4 md:grid-cols-4">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">模型总数</p>
        <strong class="text-xl">{{ stats.modelTotal }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">启用模型</p>
        <strong class="text-xl">{{ stats.modelEnabled }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">Key 总数</p>
        <strong class="text-xl">{{ stats.keyTotal }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">档位策略数</p>
        <strong class="text-xl">{{ stats.tierTotal }}</strong>
      </article>
    </div>

    <a-tabs v-model:active-key="activeTab" type="rounded">
      <a-tab-pane key="models" title="模型配置">
        <div class="mb-3 flex justify-end">
          <a-button type="primary" @click="openCreateModel">新建模型</a-button>
        </div>
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">供应商</th>
                  <th class="p-3">模型名</th>
                  <th class="p-3">显示名</th>
                  <th class="p-3">档位</th>
                  <th class="p-3">能力</th>
                  <th class="p-3">单价/1k</th>
                  <th class="p-3">最大Tokens</th>
                  <th class="p-3">状态</th>
                  <th class="p-3">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!models.length">
                  <td class="p-6 text-center text-gray-400" colspan="9">暂无模型数据</td>
                </tr>
                <tr v-for="model in models" :key="model.id" class="border-t">
                  <td class="p-3">{{ model.provider }}</td>
                  <td class="p-3">{{ model.model_name }}</td>
                  <td class="p-3">{{ model.display_name || '-' }}</td>
                  <td class="p-3">{{ model.tier }}</td>
                  <td class="p-3">
                    <a-tag v-for="cap in model.capabilities" :key="cap" size="small" color="arcoblue">{{ cap }}</a-tag>
                    <span v-if="!model.capabilities?.length" class="text-gray-400">-</span>
                  </td>
                  <td class="p-3">{{ model.price_per_1k_tokens }}</td>
                  <td class="p-3">{{ model.max_tokens }}</td>
                  <td class="p-3">
                    <a-switch
                      :model-value="model.status === 'active'"
                      :loading="actionLoading"
                      @change="(v: string | number | boolean) => toggleModel(model, Boolean(v))"
                    />
                  </td>
                  <td class="p-3">
                    <a-space>
                      <a-button size="mini" @click="openEditModel(model)">编辑</a-button>
                      <a-button size="mini" status="danger" @click="removeModel(model)">删除</a-button>
                    </a-space>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="keys" title="Key 管理">
        <div class="mb-3 flex justify-end">
          <a-button type="primary" @click="openCreateKey">新建 Key</a-button>
        </div>
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">供应商</th>
                  <th class="p-3">别名</th>
                  <th class="p-3">Key 掩码</th>
                  <th class="p-3">租户配额</th>
                  <th class="p-3">失败次数</th>
                  <th class="p-3">状态</th>
                  <th class="p-3">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!keys.length">
                  <td class="p-6 text-center text-gray-400" colspan="7">暂无 Key 数据</td>
                </tr>
                <tr v-for="key in keys" :key="key.id" class="border-t">
                  <td class="p-3">{{ key.provider }}</td>
                  <td class="p-3">{{ key.key_alias }}</td>
                  <td class="p-3 font-mono">{{ key.key_mask }}</td>
                  <td class="p-3">{{ key.tenant_quota }}</td>
                  <td class="p-3">{{ key.failure_count }}</td>
                  <td class="p-3">
                    <a-switch
                      :model-value="key.status === 'active'"
                      :loading="actionLoading"
                      @change="(v: string | number | boolean) => toggleKey(key, Boolean(v))"
                    />
                  </td>
                  <td class="p-3">
                    <a-button size="mini" status="danger" @click="removeKey(key)">删除</a-button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="tiers" title="档位策略">
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">档位编码</th>
                  <th class="p-3">允许模型</th>
                  <th class="p-3">默认模型</th>
                  <th class="p-3">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!tiers.length">
                  <td class="p-6 text-center text-gray-400" colspan="4">暂无档位策略</td>
                </tr>
                <tr v-for="tier in tiers" :key="tier.id" class="border-t">
                  <td class="p-3">{{ tier.tier_code }}</td>
                  <td class="p-3">
                    <a-tag v-for="m in tier.allowed_models" :key="m" size="small">{{ m }}</a-tag>
                    <span v-if="!tier.allowed_models?.length" class="text-gray-400">-</span>
                  </td>
                  <td class="p-3">{{ tier.default_model || '-' }}</td>
                  <td class="p-3">
                    <a-button size="mini" @click="openEditTier(tier)">编辑</a-button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="cost" title="成本策略">
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">策略名称</th>
                  <th class="p-3">模型档位</th>
                  <th class="p-3">单请求最大成本</th>
                  <th class="p-3">计费模式</th>
                  <th class="p-3">升级阈值</th>
                  <th class="p-3">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!costPolicies.length">
                  <td class="p-6 text-center text-gray-400" colspan="6">暂无成本策略</td>
                </tr>
                <tr v-for="policy in costPolicies" :key="policy.id" class="border-t">
                  <td class="p-3">{{ policy.policy_name }}</td>
                  <td class="p-3">{{ policy.model_tier }}</td>
                  <td class="p-3">{{ policy.max_cost_per_request }}</td>
                  <td class="p-3">{{ policy.billing_mode }}</td>
                  <td class="p-3">{{ policy.upgrade_threshold }}</td>
                  <td class="p-3">
                    <a-button size="mini" @click="openEditCost(policy)">编辑</a-button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <a-modal
      v-model:visible="modelModalVisible"
      :title="modelEditMode ? '编辑模型' : '新建模型'"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitModel"
    >
      <a-form :model="modelForm" layout="vertical">
        <a-form-item label="供应商" field="provider">
          <a-select v-model="modelForm.provider">
            <a-option v-for="p in PROVIDERS" :key="p" :value="p">{{ p }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="模型名" field="model_name">
          <a-input v-model="modelForm.model_name" placeholder="如 gpt-4o" />
        </a-form-item>
        <a-form-item label="显示名" field="display_name">
          <a-input v-model="modelForm.display_name" placeholder="如 GPT-4o" />
        </a-form-item>
        <a-form-item label="档位" field="tier">
          <a-select v-model="modelForm.tier">
            <a-option v-for="t in MODEL_TIERS" :key="t" :value="t">{{ t }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="能力" field="capabilities">
          <a-input-tag v-model="modelForm.capabilities" placeholder="输入能力标签后回车" allow-clear />
        </a-form-item>
        <a-form-item label="单价 (每 1k tokens)" field="price_per_1k_tokens">
          <a-input v-model="modelForm.price_per_1k_tokens" placeholder="0.000000" />
        </a-form-item>
        <a-form-item label="最大 Tokens" field="max_tokens">
          <a-input-number v-model="modelForm.max_tokens" :min="0" :step="1000" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:visible="keyModalVisible"
      title="新建 Key"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitKey"
    >
      <a-form :model="keyForm" layout="vertical">
        <a-form-item label="供应商" field="provider">
          <a-select v-model="keyForm.provider">
            <a-option v-for="p in PROVIDERS" :key="p" :value="p">{{ p }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="别名" field="key_alias">
          <a-input v-model="keyForm.key_alias" placeholder="如 main-key" />
        </a-form-item>
        <a-form-item label="Key 明文" field="key_value">
          <a-input v-model="keyForm.key_value" placeholder="仅创建时输入，后续仅保留掩码" />
        </a-form-item>
        <a-form-item label="租户配额" field="tenant_quota">
          <a-input v-model="keyForm.tenant_quota" placeholder="0.0000" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:visible="tierModalVisible"
      title="编辑档位策略"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitTier"
    >
      <a-form :model="tierForm" layout="vertical">
        <a-form-item label="档位编码" field="tier_code">
          <a-input v-model="tierForm.tier_code" disabled />
        </a-form-item>
        <a-form-item label="允许模型" field="allowed_models">
          <a-input-tag v-model="tierForm.allowed_models" placeholder="输入模型名后回车" allow-clear />
        </a-form-item>
        <a-form-item label="默认模型" field="default_model">
          <a-input v-model="tierForm.default_model" placeholder="如 gpt-4o" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:visible="costModalVisible"
      title="编辑成本策略"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitCost"
    >
      <a-form :model="costForm" layout="vertical">
        <a-form-item label="策略名称" field="policy_name">
          <a-input v-model="costForm.policy_name" disabled />
        </a-form-item>
        <a-form-item label="模型档位" field="model_tier">
          <a-select v-model="costForm.model_tier">
            <a-option v-for="t in MODEL_TIERS" :key="t" :value="t">{{ t }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="单请求最大成本" field="max_cost_per_request">
          <a-input v-model="costForm.max_cost_per_request" placeholder="0.000000" />
        </a-form-item>
        <a-form-item label="计费模式" field="billing_mode">
          <a-select v-model="costForm.billing_mode">
            <a-option v-for="m in BILLING_MODES" :key="m" :value="m">{{ m }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="升级阈值" field="upgrade_threshold">
          <a-input v-model="costForm.upgrade_threshold" placeholder="0.000000" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
