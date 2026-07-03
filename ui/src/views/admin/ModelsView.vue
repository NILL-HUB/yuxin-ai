<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  createModel,
  createModelKey,
  deleteModel,
  deleteModelKey,
  listModelKeys,
  listModels,
  listTierPolicies,
  setModelKeyStatus,
  setModelStatus,
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
  fallback_model_id?: string
  priority?: number
  base_url?: string
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
  effective_at?: number
  expires_at?: number
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

const { t } = useI18n()

const MODEL_TIERS = ['cheap', 'standard', 'strong']
const MODEL_TIER_LABELS: Record<string, string> = {
  cheap: t('admin.models.tierLabels.cheap'),
  standard: t('admin.models.tierLabels.standard'),
  strong: t('admin.models.tierLabels.strong'),
}
const PROVIDERS = ['openai', 'anthropic', 'deepseek', 'qwen', 'zhipu', 'other']

const loading = ref(false)
const actionLoading = ref(false)
const activeTab = ref('models')

const models = ref<ModelRecord[]>([])
const keys = ref<ModelKeyRecord[]>([])
const tiers = ref<TierPolicy[]>([])

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
  fallback_model_id: '',
  priority: 0,
  base_url: '',
})

const keyModalVisible = ref(false)
const keyForm = ref({
  provider: 'openai',
  key_alias: '',
  key_value: '',
  tenant_quota: '0.0000',
  model_id: '',
  effective_at: '',
  expires_at: '',
})
const keyDateRange = ref<(number | undefined)[]>([])

const tierModalVisible = ref(false)
const editingTierCode = ref('')
const tierForm = ref({
  tier_code: '',
  allowed_models: [] as string[],
  default_model: '',
})

const loadAll = async () => {
  loading.value = true
  try {
    const [modelResult, keyResult, tierResult] = await Promise.all([
      listModels({ current_page: 1, page_size: 50 }),
      listModelKeys({ current_page: 1, page_size: 50 }),
      listTierPolicies(),
    ]) as [{ data?: { list?: ModelRecord[] } }, { data?: { list?: ModelKeyRecord[] } }, { data?: { list?: TierPolicy[] } }]
    models.value = modelResult.data?.list || []
    keys.value = keyResult.data?.list || []
    tiers.value = tierResult.data?.list || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.loadFailed')))
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
    max_tokens: 131072,
    fallback_model_id: '',
    priority: 0,
    base_url: '',
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
    fallback_model_id: model.fallback_model_id || '',
    priority: model.priority ?? 0,
    base_url: model.base_url || '',
  }
  modelModalVisible.value = true
}

const submitModel = async () => {
  actionLoading.value = true
  try {
    if (modelEditMode.value) {
      await updateModel(editingModelId.value, { ...modelForm.value })
      Message.success(t('admin.models.messages.modelUpdated'))
    } else {
      await createModel({ ...modelForm.value })
      Message.success(t('admin.models.messages.modelCreated'))
    }
    modelModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.saveModelFailed')))
  } finally {
    actionLoading.value = false
  }
}

const toggleModel = async (model: ModelRecord, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setModelStatus(model.id, enabled)
    Message.success(enabled ? t('admin.models.messages.modelEnabled') : t('admin.models.messages.modelDisabled'))
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.updateModelStatusFailed')))
  } finally {
    actionLoading.value = false
  }
}

const removeModel = async (model: ModelRecord) => {
  actionLoading.value = true
  try {
    await deleteModel(model.id)
    Message.success(t('admin.models.messages.modelDeleted'))
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.deleteModelFailed')))
  } finally {
    actionLoading.value = false
  }
}

const openCreateKey = () => {
  keyForm.value = { provider: 'openai', key_alias: '', key_value: '', tenant_quota: '0.0000', model_id: '', effective_at: '', expires_at: '' }
  keyDateRange.value = []
  keyModalVisible.value = true
}

const submitKey = async () => {
  actionLoading.value = true
  try {
    const payload = { ...keyForm.value }
    if (keyDateRange.value.length === 2) {
      payload.effective_at = keyDateRange.value[0] ? String(Math.floor(keyDateRange.value[0] / 1000)) : ''
      payload.expires_at = keyDateRange.value[1] ? String(Math.floor(keyDateRange.value[1] / 1000)) : ''
    }
    await createModelKey(payload)
    Message.success(t('admin.models.messages.keyCreated'))
    keyModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.createKeyFailed')))
  } finally {
    actionLoading.value = false
  }
}

const toggleKey = async (key: ModelKeyRecord, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setModelKeyStatus(key.id, enabled)
    Message.success(enabled ? t('admin.models.messages.keyEnabled') : t('admin.models.messages.keyDisabled'))
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.updateKeyStatusFailed')))
  } finally {
    actionLoading.value = false
  }
}

const removeKey = async (key: ModelKeyRecord) => {
  actionLoading.value = true
  try {
    await deleteModelKey(key.id)
    Message.success(t('admin.models.messages.keyDeleted'))
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.deleteKeyFailed')))
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
    Message.success(t('admin.models.messages.tierUpdated'))
    tierModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.updateTierFailed')))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.models.title') }}</h1>
      <p class="mt-1 text-sm text-gray-500">{{ t('admin.models.description') }}</p>
    </header>

    <div class="grid gap-4 md:grid-cols-4">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.models.stats.modelTotal') }}</p>
        <strong class="text-xl">{{ stats.modelTotal }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.models.stats.modelEnabled') }}</p>
        <strong class="text-xl">{{ stats.modelEnabled }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.models.stats.keyTotal') }}</p>
        <strong class="text-xl">{{ stats.keyTotal }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.models.stats.tierTotal') }}</p>
        <strong class="text-xl">{{ stats.tierTotal }}</strong>
      </article>
    </div>

    <a-tabs v-model:active-key="activeTab" type="rounded">
      <a-tab-pane key="models" :title="t('admin.models.tabs.modelConfig')">
        <div class="mb-3 flex justify-end">
          <a-button type="primary" @click="openCreateModel">{{ t('admin.models.actions.createModel') }}</a-button>
        </div>
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">{{ t('admin.models.columns.provider') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.modelName') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.displayName') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.tier') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.capabilities') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.pricePer1k') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.maxTokens') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.status') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.actions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!models.length">
                  <td class="p-6 text-center text-gray-400" colspan="9">{{ t('admin.models.empty.models') }}</td>
                </tr>
                <tr v-for="model in models" :key="model.id" class="border-t">
                  <td class="p-3">{{ model.provider }}</td>
                  <td class="p-3">{{ model.model_name }}</td>
                  <td class="p-3">{{ model.display_name || '-' }}</td>
                  <td class="p-3">{{ MODEL_TIER_LABELS[model.tier] || model.tier }}</td>
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
                      <a-button size="mini" @click="openEditModel(model)">{{ t('admin.models.actions.edit') }}</a-button>
                      <a-button size="mini" status="danger" @click="removeModel(model)">{{ t('admin.models.actions.delete') }}</a-button>
                    </a-space>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="keys" :title="t('admin.models.tabs.apiKeys')">
        <div class="mb-3 flex justify-end">
          <a-button type="primary" @click="openCreateKey">{{ t('admin.models.actions.createKey') }}</a-button>
        </div>
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">{{ t('admin.models.columns.provider') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.alias') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.keyMask') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.tenantQuota') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.failureCount') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.status') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.actions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!keys.length">
                  <td class="p-6 text-center text-gray-400" colspan="7">{{ t('admin.models.empty.keys') }}</td>
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
                    <a-button size="mini" status="danger" @click="removeKey(key)">{{ t('admin.models.actions.delete') }}</a-button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="tiers" :title="t('admin.models.tabs.modelTiers')">
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">{{ t('admin.models.columns.tierCode') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.allowedModels') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.defaultModel') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.actions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!tiers.length">
                  <td class="p-6 text-center text-gray-400" colspan="4">{{ t('admin.models.empty.tiers') }}</td>
                </tr>
                <tr v-for="tier in tiers" :key="tier.id" class="border-t">
                  <td class="p-3">{{ MODEL_TIER_LABELS[tier.tier_code] || tier.tier_code }}</td>
                  <td class="p-3">
                    <a-tag v-for="m in tier.allowed_models" :key="m" size="small">{{ m }}</a-tag>
                    <span v-if="!tier.allowed_models?.length" class="text-gray-400">-</span>
                  </td>
                  <td class="p-3">{{ tier.default_model || '-' }}</td>
                  <td class="p-3">
                    <a-button size="mini" @click="openEditTier(tier)">{{ t('admin.models.actions.edit') }}</a-button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="cost" :title="t('admin.models.tabs.costPolicies')">
        <a-alert type="info" :show-icon="true">
          <template #title>{{ t('admin.models.costMovedNotice.title') }}</template>
          {{ t('admin.models.costMovedNotice.desc') }}
          <template #action>
            <router-link to="/admin/cost-strategy" class="font-medium text-blue-600 hover:underline">
              {{ t('admin.models.costMovedNotice.link') }}
            </router-link>
          </template>
        </a-alert>
      </a-tab-pane>
    </a-tabs>

    <a-modal
      v-model:visible="modelModalVisible"
      :title="modelEditMode ? t('admin.models.modelModal.editTitle') : t('admin.models.actions.createModel')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitModel"
    >
      <a-form :model="modelForm" layout="vertical">
        <a-form-item :label="t('admin.models.columns.provider')" field="provider">
          <a-select v-model="modelForm.provider">
            <a-option v-for="p in PROVIDERS" :key="p" :value="p">{{ p }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.modelName')" field="model_name">
          <a-input v-model="modelForm.model_name" :placeholder="t('admin.models.modelModal.placeholders.modelName')" />
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.displayName')" field="display_name">
          <a-input v-model="modelForm.display_name" :placeholder="t('admin.models.modelModal.placeholders.displayName')" />
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.tier')" field="tier">
          <a-select v-model="modelForm.tier">
            <a-option v-for="tier in MODEL_TIERS" :key="tier" :value="tier">{{ MODEL_TIER_LABELS[tier] }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.capabilities')" field="capabilities">
          <a-input-tag v-model="modelForm.capabilities" :placeholder="t('admin.models.modelModal.placeholders.capabilities')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.models.fields.pricePer1k')" field="price_per_1k_tokens">
          <a-input v-model="modelForm.price_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.price')" />
        </a-form-item>
        <a-form-item :label="t('admin.models.fields.maxTokens')" field="max_tokens">
          <a-select v-model="modelForm.max_tokens" allow-search>
            <a-option :value="4096" label="4K (4,096)" />
            <a-option :value="8192" label="8K (8,192)" />
            <a-option :value="16384" label="16K (16,384)" />
            <a-option :value="32768" label="32K (32,768)" />
            <a-option :value="65536" label="64K (65,536)" />
            <a-option :value="131072" label="128K (131,072)" />
            <a-option :value="200000" label="200K (200,000)" />
            <a-option :value="524288" label="512K (524,288)" />
            <a-option :value="1048576" label="1M (1,048,576)" />
            <a-option :value="1572864" label="1.5M (1,572,864)" />
            <a-option :value="2000000" label="2M (2,000,000)" />
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.models.fields.fallbackModelId')" field="fallback_model_id">
          <a-input v-model="modelForm.fallback_model_id" :placeholder="t('admin.models.modelModal.placeholders.fallbackModelId')" />
        </a-form-item>
        <a-form-item :label="t('admin.models.fields.baseUrl')" field="base_url">
          <a-input v-model="modelForm.base_url" :placeholder="t('admin.models.modelModal.placeholders.baseUrl')" />
        </a-form-item>
        <a-form-item :label="t('admin.models.fields.priority')" field="priority">
          <a-input-number v-model="modelForm.priority" :min="0" :step="1" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:visible="keyModalVisible"
      :title="t('admin.models.actions.createKey')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitKey"
    >
      <a-form :model="keyForm" layout="vertical">
        <a-form-item :label="t('admin.models.columns.provider')" field="provider">
          <a-select v-model="keyForm.provider">
            <a-option v-for="p in PROVIDERS" :key="p" :value="p">{{ p }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.alias')" field="key_alias">
          <a-input v-model="keyForm.key_alias" :placeholder="t('admin.models.keyModal.placeholders.alias')" />
        </a-form-item>
        <a-form-item :label="t('admin.models.fields.keyValue')" field="key_value">
          <a-input v-model="keyForm.key_value" :placeholder="t('admin.models.keyModal.placeholders.keyValue')" />
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.tenantQuota')" field="tenant_quota">
          <a-input v-model="keyForm.tenant_quota" :placeholder="t('admin.models.keyModal.placeholders.tenantQuota')" />
          <template #extra>消费上限（元），Key 累计消费达到此金额后自动停用。0 表示不限制</template>
        </a-form-item>
        <a-form-item label="绑定模型" field="model_id">
          <a-select v-model="keyForm.model_id" allow-search allow-clear :placeholder="t('admin.models.keyModal.placeholders.modelId')">
            <a-option value="" label="不限模型（自动匹配同供应商可用 Key）" />
            <a-option v-for="m in models" :key="m.id" :value="m.id" :label="`${m.display_name || m.model_name} (${m.provider})`" />
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.models.fields.effectiveRange')" field="date_range">
          <a-range-picker
            v-model="keyDateRange"
            show-time
            value-format="timestamp"
            :placeholder="[t('admin.models.keyModal.placeholders.effectiveStart'), t('admin.models.keyModal.placeholders.effectiveEnd')]"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:visible="tierModalVisible"
      :title="t('admin.models.tierModal.title')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitTier"
    >
      <a-form :model="tierForm" layout="vertical">
        <a-form-item :label="t('admin.models.columns.tierCode')" field="tier_code">
          <a-input v-model="tierForm.tier_code" disabled />
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.allowedModels')" field="allowed_models">
          <a-input-tag v-model="tierForm.allowed_models" :placeholder="t('admin.models.tierModal.placeholders.allowedModels')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.defaultModel')" field="default_model">
          <a-input v-model="tierForm.default_model" :placeholder="t('admin.models.tierModal.placeholders.defaultModel')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
