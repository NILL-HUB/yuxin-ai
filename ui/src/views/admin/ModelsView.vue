<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  createModel,
  createModelKey,
  createTierPolicy,
  deleteModel,
  deleteModelKey,
  deleteTierPolicy,
  listModelKeys,
  listModels,
  listTierPolicies,
  setModelKeyStatus,
  setModelStatus,
  updateModel,
  updateTierPolicy,
} from '@/services/admin-model-pool'
import { listProviderOptions } from '@/services/admin-model-providers'
import { getBillingConfig } from '@/services/admin-billing'
import { suggestSellPrices } from '@/services/admin-pricing-suggest'
import { getErrorMessage } from '@/utils/error'

type ModelRecord = {
  id: string
  provider: string
  model_name: string
  display_name: string
  description?: string
  tier: string
  capabilities: string[]
  price_per_1k_tokens: string
  input_price_per_1k_tokens?: string
  output_price_per_1k_tokens?: string
  input_cost_per_1k_tokens?: string
  output_cost_per_1k_tokens?: string
  max_tokens: number
  max_input_tokens: number
  max_output_tokens: number
  status: string
  fallback_model_id?: string
  priority?: number
  model_type?: string
  compatible_api?: string
  embedding_dimension?: number
  peak_valley_enabled?: boolean
  cache_pricing_enabled?: boolean
  peak_windows?: string
  input_cached_price_per_1k_tokens?: string
  input_cached_cost_per_1k_tokens?: string
  peak_input_price_per_1k_tokens?: string
  peak_input_cost_per_1k_tokens?: string
  peak_output_price_per_1k_tokens?: string
  peak_output_cost_per_1k_tokens?: string
  peak_input_cached_price_per_1k_tokens?: string
  peak_input_cached_cost_per_1k_tokens?: string
  valley_input_price_per_1k_tokens?: string
  valley_input_cost_per_1k_tokens?: string
  valley_output_price_per_1k_tokens?: string
  valley_output_cost_per_1k_tokens?: string
  valley_input_cached_price_per_1k_tokens?: string
  valley_input_cached_cost_per_1k_tokens?: string
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
  tier_name: string
  sort_order: number
  allowed_models: string[]
  default_model: string
  routing_rules: Record<string, unknown>
  created_at?: number
  updated_at?: number
}

const { t } = useI18n()

const ALL_MODEL_TYPES = [
  'chat', 'embedding', 'multimodal',
  'image_generation', 'video_generation', 'ocr', 'tts', 'asr', 'rerank',
]
const COMPATIBLE_APIS = ['openai', 'claude']
// 无上下文概念的模型类型：不展示也不校验 max_tokens
const CONTEXT_LESS_MODEL_TYPES = [
  'image_generation', 'video_generation', 'tts', 'asr', 'ocr',
]
// 上下文长度预设值，点击即填入；同时支持手动输入自定义值
const MAX_TOKENS_PRESETS = [
  { value: 4096, label: '4K' },
  { value: 8192, label: '8K' },
  { value: 16384, label: '16K' },
  { value: 32768, label: '32K' },
  { value: 65536, label: '64K' },
  { value: 131072, label: '128K' },
  { value: 200000, label: '200K' },
  { value: 393216, label: '384K' },
  { value: 524288, label: '512K' },
  { value: 1048576, label: '1M' },
  { value: 1572864, label: '1.5M' },
  { value: 2000000, label: '2M' },
]
// 最大输出长度预设值（通常远小于输入窗口）
const OUTPUT_TOKENS_PRESETS = [
  { value: 512, label: '512' },
  { value: 1024, label: '1K' },
  { value: 2048, label: '2K' },
  { value: 4096, label: '4K' },
  { value: 8192, label: '8K' },
  { value: 16384, label: '16K' },
  { value: 32768, label: '32K' },
  { value: 65536, label: '64K' },
]
// embedding 模型维度由后端自动探测（调用 API 探测实际维度），前端无需配置

type ProviderOption = {
  id: string
  name: string
  label: string
  description?: string
  default_base_url: string
  supported_model_types: string[]
}
const providerOptions = ref<ProviderOption[]>([])

const loading = ref(false)
const actionLoading = ref(false)
const activeTab = ref('models')

const models = ref<ModelRecord[]>([])
const keys = ref<ModelKeyRecord[]>([])
const tiers = ref<TierPolicy[]>([])

// 模型列表档位筛选：空字符串表示"全部档位"
const filterTier = ref('')

const getTierLabel = (tierCode: string) => {
  const tier = tiers.value.find((t) => t.tier_code === tierCode)
  return tier ? `${tier.tier_code} - ${tier.tier_name}` : tierCode
}

// 按档位筛选后的模型列表
const filteredModels = computed(() => {
  if (!filterTier.value) return models.value
  return models.value.filter((m) => m.tier === filterTier.value)
})

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
  provider: '',
  model_name: '',
  display_name: '',
  description: '',
  tier: '2',
  capabilities: [] as string[],
  price_per_1k_tokens: '0.000000',
  input_price_per_1k_tokens: '0.000000',
  output_price_per_1k_tokens: '0.000000',
  input_cost_per_1k_tokens: '0.000000',
  output_cost_per_1k_tokens: '0.000000',
  peak_valley_enabled: false,
  cache_pricing_enabled: false,
  peak_windows: '[]',
  input_cached_price_per_1k_tokens: '0.000000',
  input_cached_cost_per_1k_tokens: '0.000000',
  peak_input_price_per_1k_tokens: '0.000000',
  peak_input_cost_per_1k_tokens: '0.000000',
  peak_output_price_per_1k_tokens: '0.000000',
  peak_output_cost_per_1k_tokens: '0.000000',
  peak_input_cached_price_per_1k_tokens: '0.000000',
  peak_input_cached_cost_per_1k_tokens: '0.000000',
  valley_input_price_per_1k_tokens: '0.000000',
  valley_input_cost_per_1k_tokens: '0.000000',
  valley_output_price_per_1k_tokens: '0.000000',
  valley_output_cost_per_1k_tokens: '0.000000',
  valley_input_cached_price_per_1k_tokens: '0.000000',
  valley_input_cached_cost_per_1k_tokens: '0.000000',
  max_tokens: 0,
  max_input_tokens: 0,
  max_output_tokens: 0,
  fallback_model_id: '',
  priority: 0,
  model_type: 'chat',
  compatible_api: 'openai',
  embedding_dimension: 0,
})

const selectedProvider = computed(() =>
  providerOptions.value.find((p) => p.name === modelForm.value.provider),
)
const selectedProviderBaseUrl = computed(() => selectedProvider.value?.default_base_url || '')
const filteredModelTypeOptions = computed(() => {
  const supported = selectedProvider.value?.supported_model_types
  return supported && supported.length > 0 ? supported : ALL_MODEL_TYPES
})

// 汇率锚（成本→算力折算），用于毛利预览与表格参考毛利
const billingPerYuan = ref(100)
const loadBillingPerYuan = async () => {
  try {
    const config = await getBillingConfig('credits_per_yuan')
    billingPerYuan.value = config?.value_numeric ?? 100
  } catch {
    billingPerYuan.value = 100
  }
}

// 毛利预览：按 3:1 输入/输出比估算，仅编辑辅助，不落库
const marginPreview = computed(() => {
  const sellIn = Number(modelForm.value.input_price_per_1k_tokens || 0)
  const sellOut = Number(modelForm.value.output_price_per_1k_tokens || 0)
  const costIn = Number(modelForm.value.input_cost_per_1k_tokens || 0)
  const costOut = Number(modelForm.value.output_cost_per_1k_tokens || 0)
  if (!sellIn && !sellOut) return null
  const sell = sellIn * 3 + sellOut
  const cost = (costIn * 3 + costOut) * (billingPerYuan.value || 100)
  return sell - cost
})
const marginPercent = computed(() => {
  const cost = (Number(modelForm.value.input_cost_per_1k_tokens || 0) * 3 + Number(modelForm.value.output_cost_per_1k_tokens || 0)) * (billingPerYuan.value || 100)
  if (cost <= 0) return 0
  return ((marginPreview.value || 0) / cost) * 100
})
const formatSigned = (value: number) => {
  const n = Math.round(Number(value) || 0)
  return n > 0 ? `+${n}` : `${n}`
}

const formatPrice = (value?: string) => (Number(value || 0)).toFixed(6)
const marginOf = (record: ModelRecord) => {
  const perYuan = billingPerYuan.value || 100
  const cost = (Number(record.input_cost_per_1k_tokens || 0) * 3 + Number(record.output_cost_per_1k_tokens || 0)) * perYuan
  const sell = Number(record.input_price_per_1k_tokens || 0) * 3 + Number(record.output_price_per_1k_tokens || 0)
  return sell - cost
}
// 谷峰/缓存拆分定价字段（提交时统一转为字符串）
const PRICING_FIELD_KEYS = [
  'input_cached_price_per_1k_tokens',
  'input_cached_cost_per_1k_tokens',
  'peak_input_price_per_1k_tokens',
  'peak_input_cost_per_1k_tokens',
  'peak_output_price_per_1k_tokens',
  'peak_output_cost_per_1k_tokens',
  'peak_input_cached_price_per_1k_tokens',
  'peak_input_cached_cost_per_1k_tokens',
  'valley_input_price_per_1k_tokens',
  'valley_input_cost_per_1k_tokens',
  'valley_output_price_per_1k_tokens',
  'valley_output_cost_per_1k_tokens',
  'valley_input_cached_price_per_1k_tokens',
  'valley_input_cached_cost_per_1k_tokens',
] as const

// 后端开关以字符串（'true'/'false'）返回，需做宽松布尔解析
const toBool = (value: unknown): boolean => {
  if (typeof value === 'boolean') return value
  return ['true', '1', 'yes', 'on'].includes(String(value ?? '').toLowerCase())
}
const stringifyPriceField = (value: unknown): string =>
  value === null || value === undefined || value === '' ? '0.000000' : String(value)

const pricingSuggestLoading = ref(false)
const pricingErrors = ref<string[]>([])

const onPricingModeChange = () => {
  if (modelForm.value.peak_valley_enabled) {
    applyProviderDefaultWindows()
  }
}
const applyProviderDefaultWindows = () => {
  const provider = String(modelForm.value.provider || '').toLowerCase()
  if (provider === 'siliconflow') {
    // 低谷 02:00-08:00 → 峰窗口为每日两段
    modelForm.value.peak_windows = JSON.stringify([
      { days: '0-6', start: '00:00', end: '02:00' },
      { days: '0-6', start: '08:00', end: '24:00' },
    ])
  } else {
    modelForm.value.peak_windows = JSON.stringify([
      { days: '0-4', start: '09:00', end: '12:00' },
      { days: '0-4', start: '14:00', end: '18:00' },
    ])
  }
}
const openPricingSuggest = async () => {
  pricingSuggestLoading.value = true
  try {
    const resp = await suggestSellPrices(
      {
        ...modelForm.value,
        peak_valley_enabled: modelForm.value.peak_valley_enabled,
        cache_pricing_enabled: modelForm.value.cache_pricing_enabled,
      },
      0.3,
    )
    if (resp?.data) {
      const formRecord = modelForm.value as Record<string, unknown>
      Object.entries(resp.data).forEach(([key, value]) => {
        if (key in formRecord) {
          formRecord[key] = value
        }
      })
      Message.success('自动定价建议已应用')
    }
  } catch (error) {
    Message.error(getErrorMessage(error, '获取定价建议失败'))
  } finally {
    pricingSuggestLoading.value = false
  }
}
// 当前模型类型是否需要上下文长度配置
const hasContextField = computed(() => !CONTEXT_LESS_MODEL_TYPES.includes(modelForm.value.model_type))
// 切换模型类型时，自动调整 token 上限：切到无上下文类型时清零，切到有上下文类型且当前为 0 时恢复默认
watch(
  () => modelForm.value.model_type,
  (newType, oldType) => {
    if (newType === oldType) return
    if (CONTEXT_LESS_MODEL_TYPES.includes(newType)) {
      modelForm.value.max_input_tokens = 0
      modelForm.value.max_output_tokens = 0
      modelForm.value.max_tokens = 0
    } else if (CONTEXT_LESS_MODEL_TYPES.includes(oldType) && modelForm.value.max_input_tokens === 0) {
      modelForm.value.max_input_tokens = 131072
      if (modelForm.value.max_output_tokens === 0) {
        modelForm.value.max_output_tokens = 4096
      }
    }
  },
)

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
const keyDateRange = ref<number[]>([])

const tierModalVisible = ref(false)
const tierEditMode = ref(false)
const editingTierCode = ref('')
const tierForm = ref({
  tier_code: '',
  tier_name: '',
  sort_order: 0,
  allowed_models: [] as string[],
  default_model: '',
})

const loadAll = async () => {
  loading.value = true
  try {
    const [modelResult, keyResult, tierResult, optionsResult] = await Promise.all([
      listModels({ current_page: 1, page_size: 50 }),
      listModelKeys({ current_page: 1, page_size: 50 }),
      listTierPolicies(),
      listProviderOptions(),
    ]) as [
      { data?: { list?: ModelRecord[] } },
      { data?: { list?: ModelKeyRecord[] } },
      { data?: { list?: TierPolicy[] } },
      { data?: { options?: ProviderOption[] } },
    ]
    models.value = modelResult.data?.list || []
    keys.value = keyResult.data?.list || []
    tiers.value = tierResult.data?.list || []
    providerOptions.value = optionsResult.data?.options || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.loadFailed')))
  } finally {
    loading.value = false
  }
}

const openCreateModel = () => {
  modelEditMode.value = false
  editingModelId.value = ''
  pricingErrors.value = []
  modelForm.value = {
    provider: providerOptions.value[0]?.name || '',
    model_name: '',
    display_name: '',
    description: '',
    // 默认选第一个档位（已创建的档位才可选），无档位时为空
    tier: tiers.value[0]?.tier_code || '',
    capabilities: [],
    price_per_1k_tokens: '0.000000',
    input_price_per_1k_tokens: '0.000000',
    output_price_per_1k_tokens: '0.000000',
    input_cost_per_1k_tokens: '0.000000',
    output_cost_per_1k_tokens: '0.000000',
    peak_valley_enabled: false,
    cache_pricing_enabled: false,
    peak_windows: '[]',
    input_cached_price_per_1k_tokens: '0.000000',
    input_cached_cost_per_1k_tokens: '0.000000',
    peak_input_price_per_1k_tokens: '0.000000',
    peak_input_cost_per_1k_tokens: '0.000000',
    peak_output_price_per_1k_tokens: '0.000000',
    peak_output_cost_per_1k_tokens: '0.000000',
    peak_input_cached_price_per_1k_tokens: '0.000000',
    peak_input_cached_cost_per_1k_tokens: '0.000000',
    valley_input_price_per_1k_tokens: '0.000000',
    valley_input_cost_per_1k_tokens: '0.000000',
    valley_output_price_per_1k_tokens: '0.000000',
    valley_output_cost_per_1k_tokens: '0.000000',
    valley_input_cached_price_per_1k_tokens: '0.000000',
    valley_input_cached_cost_per_1k_tokens: '0.000000',
    max_tokens: 131072,
    max_input_tokens: 131072,
    max_output_tokens: 4096,
    fallback_model_id: '',
    priority: 0,
    model_type: 'chat',
    compatible_api: 'openai',
    embedding_dimension: 0,
  }
  modelModalVisible.value = true
}

const openEditModel = (model: ModelRecord) => {
  modelEditMode.value = true
  editingModelId.value = model.id
  pricingErrors.value = []
  modelForm.value = {
    provider: model.provider,
    model_name: model.model_name,
    display_name: model.display_name,
    description: model.description || '',
    tier: model.tier,
    capabilities: [...(model.capabilities || [])],
    price_per_1k_tokens: model.price_per_1k_tokens,
    input_price_per_1k_tokens: model.input_price_per_1k_tokens || '0.000000',
    output_price_per_1k_tokens: model.output_price_per_1k_tokens || '0.000000',
    input_cost_per_1k_tokens: model.input_cost_per_1k_tokens || '0.000000',
    output_cost_per_1k_tokens: model.output_cost_per_1k_tokens || '0.000000',
    peak_valley_enabled: toBool(model.peak_valley_enabled),
    cache_pricing_enabled: toBool(model.cache_pricing_enabled),
    peak_windows: model.peak_windows || '[]',
    input_cached_price_per_1k_tokens: model.input_cached_price_per_1k_tokens || '0.000000',
    input_cached_cost_per_1k_tokens: model.input_cached_cost_per_1k_tokens || '0.000000',
    peak_input_price_per_1k_tokens: model.peak_input_price_per_1k_tokens || '0.000000',
    peak_input_cost_per_1k_tokens: model.peak_input_cost_per_1k_tokens || '0.000000',
    peak_output_price_per_1k_tokens: model.peak_output_price_per_1k_tokens || '0.000000',
    peak_output_cost_per_1k_tokens: model.peak_output_cost_per_1k_tokens || '0.000000',
    peak_input_cached_price_per_1k_tokens: model.peak_input_cached_price_per_1k_tokens || '0.000000',
    peak_input_cached_cost_per_1k_tokens: model.peak_input_cached_cost_per_1k_tokens || '0.000000',
    valley_input_price_per_1k_tokens: model.valley_input_price_per_1k_tokens || '0.000000',
    valley_input_cost_per_1k_tokens: model.valley_input_cost_per_1k_tokens || '0.000000',
    valley_output_price_per_1k_tokens: model.valley_output_price_per_1k_tokens || '0.000000',
    valley_output_cost_per_1k_tokens: model.valley_output_cost_per_1k_tokens || '0.000000',
    valley_input_cached_price_per_1k_tokens: model.valley_input_cached_price_per_1k_tokens || '0.000000',
    valley_input_cached_cost_per_1k_tokens: model.valley_input_cached_cost_per_1k_tokens || '0.000000',
    max_tokens: model.max_tokens,
    max_input_tokens: model.max_input_tokens,
    max_output_tokens: model.max_output_tokens,
    fallback_model_id: model.fallback_model_id || '',
    priority: model.priority ?? 0,
    model_type: model.model_type || 'chat',
    compatible_api: model.compatible_api || 'openai',
    embedding_dimension: Number(model.embedding_dimension || 0),
  }
  modelModalVisible.value = true
}

const submitModel = async () => {
  actionLoading.value = true
  pricingErrors.value = []
  try {
    const payload = { ...modelForm.value } as Record<string, unknown>
    // embedding_dimension 由后端自动探测，前端不传该字段
    delete payload.embedding_dimension
    // max_tokens（总窗口）由后端按输入+输出派生，前端不直接提交
    delete payload.max_tokens
    // 无上下文概念的模型类型，强制 token 上限为 0，避免残留值干扰
    if (!hasContextField.value) {
      payload.max_input_tokens = 0
      payload.max_output_tokens = 0
    }
    // 谷峰/缓存定价字段统一转为字符串数字；开关转 'true'/'false'
    PRICING_FIELD_KEYS.forEach((key) => {
      payload[key] = stringifyPriceField(payload[key])
    })
    payload.peak_valley_enabled = modelForm.value.peak_valley_enabled ? 'true' : 'false'
    payload.cache_pricing_enabled = modelForm.value.cache_pricing_enabled ? 'true' : 'false'
    if (modelEditMode.value) {
      await updateModel(editingModelId.value, payload)
      Message.success(t('admin.models.messages.modelUpdated'))
    } else {
      await createModel(payload)
      Message.success(t('admin.models.messages.modelCreated'))
    }
    modelModalVisible.value = false
    await loadAll()
  } catch (error) {
    const message = getErrorMessage(error, t('admin.models.messages.saveModelFailed'))
    Message.error(message)
    // 双界校验（不亏损 / 不高于官方）失败时，把含「亏损/官方」的错误行展示到表单顶部 a-alert
    const pricingLines = message.split(/[\n；]+/).filter((line) => /亏损|官方/.test(line))
    if (pricingLines.length > 0) {
      pricingErrors.value = pricingLines
    }
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
  keyForm.value = { provider: providerOptions.value[0]?.name || '', key_alias: '', key_value: '', tenant_quota: '0.0000', model_id: '', effective_at: '', expires_at: '' }
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

const openCreateTier = () => {
  tierEditMode.value = false
  editingTierCode.value = ''
  tierForm.value = {
    tier_code: '',
    tier_name: '',
    sort_order: 0,
    allowed_models: [],
    default_model: '',
  }
  tierModalVisible.value = true
}

const openEditTier = (tier: TierPolicy) => {
  tierEditMode.value = true
  editingTierCode.value = tier.tier_code
  tierForm.value = {
    tier_code: tier.tier_code,
    tier_name: tier.tier_name,
    sort_order: tier.sort_order,
    allowed_models: [...(tier.allowed_models || [])],
    default_model: tier.default_model,
  }
  tierModalVisible.value = true
}

const submitTier = async () => {
  actionLoading.value = true
  try {
    if (tierEditMode.value) {
      await updateTierPolicy(editingTierCode.value, {
        tier_name: tierForm.value.tier_name,
        sort_order: tierForm.value.sort_order,
        allowed_models: tierForm.value.allowed_models,
        default_model: tierForm.value.default_model,
      })
      Message.success(t('admin.models.messages.tierUpdated'))
    } else {
      await createTierPolicy({
        tier_code: tierForm.value.tier_code,
        tier_name: tierForm.value.tier_name,
        sort_order: tierForm.value.sort_order,
        allowed_models: tierForm.value.allowed_models,
        default_model: tierForm.value.default_model,
      })
      Message.success('档位创建成功')
    }
    tierModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.updateTierFailed')))
  } finally {
    actionLoading.value = false
  }
}

const removeTier = async (tier: TierPolicy) => {
  actionLoading.value = true
  try {
    await deleteTierPolicy(tier.tier_code)
    Message.success('档位删除成功')
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '删除档位失败'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(() => {
  loadAll()
  loadBillingPerYuan()
})
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
        <div class="mb-3 flex items-center justify-between gap-3">
          <a-select
            v-model="filterTier"
            allow-clear
            allow-search
            :placeholder="t('admin.models.filterTierPlaceholder')"
            style="width: 240px"
          >
            <a-option value="">{{ t('admin.models.filterTierAll') }}</a-option>
            <a-option v-for="tier in tiers" :key="tier.tier_code" :value="tier.tier_code">
              {{ tier.tier_code }} - {{ tier.tier_name }}
            </a-option>
          </a-select>
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
                  <th class="p-3">{{ t('admin.models.columns.description') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.tier') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.pricing') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.margin') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.capabilities') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.pricePer1k') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.maxInputTokens') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.maxOutputTokens') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.status') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.actions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!filteredModels.length">
                  <td class="p-6 text-center text-gray-400" colspan="13">{{ t('admin.models.empty.models') }}</td>
                </tr>
                <tr v-for="model in filteredModels" :key="model.id" class="border-t">
                  <td class="p-3">{{ model.provider }}</td>
                  <td class="p-3">{{ model.model_name }}</td>
                  <td class="p-3">{{ model.display_name || '-' }}</td>
                  <td class="p-3 max-w-[200px]">
                    <a-tooltip v-if="model.description" :content="model.description" position="tl" mini>
                      <span class="inline-block max-w-[180px] truncate align-bottom text-gray-600">{{ model.description }}</span>
                    </a-tooltip>
                    <span v-else class="text-gray-400">-</span>
                  </td>
                  <td class="p-3">{{ getTierLabel(model.tier) }}</td>
                  <td class="p-3">
                    <div class="flex flex-col gap-0.5 text-xs">
                      <span class="text-gray-400">{{ t('admin.models.columns.sellLabel') }}</span>
                      <code class="font-mono text-gray-700">{{ formatPrice(model.input_price_per_1k_tokens) }} / {{ formatPrice(model.output_price_per_1k_tokens) }}</code>
                      <a-tag v-if="toBool(model.peak_valley_enabled)" size="small" color="purple">峰谷</a-tag>
                      <span class="text-gray-400">{{ t('admin.models.columns.costLabel') }}</span>
                      <code class="font-mono text-amber-600">{{ formatPrice(model.input_cost_per_1k_tokens) }} / {{ formatPrice(model.output_cost_per_1k_tokens) }}</code>
                    </div>
                  </td>
                  <td class="p-3 text-right">
                    <a-tag :color="marginOf(model) >= 0 ? 'green' : 'red'">{{ marginOf(model) >= 0 ? '+' : '' }}{{ marginOf(model).toFixed(1) }}</a-tag>
                  </td>
                  <td class="p-3">
                    <a-tag v-for="cap in model.capabilities" :key="cap" size="small" color="arcoblue">{{ cap }}</a-tag>
                    <span v-if="!model.capabilities?.length" class="text-gray-400">-</span>
                  </td>
                  <td class="p-3">{{ model.price_per_1k_tokens }}</td>
                  <td class="p-3">{{ CONTEXT_LESS_MODEL_TYPES.includes(model.model_type || '') ? '-' : model.max_input_tokens }}</td>
                  <td class="p-3">{{ CONTEXT_LESS_MODEL_TYPES.includes(model.model_type || '') ? '-' : model.max_output_tokens }}</td>
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
        <div class="mb-3 flex justify-end">
          <a-button type="primary" @click="openCreateTier">创建档位</a-button>
        </div>
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">档位标识</th>
                  <th class="p-3">档位名称</th>
                  <th class="p-3">排序</th>
                  <th class="p-3">允许的模型</th>
                  <th class="p-3">默认模型</th>
                  <th class="p-3">{{ t('admin.models.columns.actions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!tiers.length">
                  <td class="p-6 text-center text-gray-400" colspan="6">{{ t('admin.models.empty.tiers') }}</td>
                </tr>
                <tr v-for="tier in tiers" :key="tier.id" class="border-t">
                  <td class="p-3">{{ tier.tier_code }}</td>
                  <td class="p-3">{{ tier.tier_name || '-' }}</td>
                  <td class="p-3">{{ tier.sort_order ?? 0 }}</td>
                  <td class="p-3">
                    <a-tag v-for="mId in tier.allowed_models" :key="mId" size="small">
                      {{ models.find(m => m.id === mId)?.display_name || models.find(m => m.id === mId)?.model_name || mId }}
                    </a-tag>
                    <span v-if="!tier.allowed_models?.length" class="text-gray-400">-</span>
                  </td>
                  <td class="p-3">
                    {{ models.find(m => m.id === tier.default_model)?.display_name || models.find(m => m.id === tier.default_model)?.model_name || tier.default_model || '-' }}
                  </td>
                  <td class="p-3">
                    <a-space>
                      <a-button size="mini" @click="openEditTier(tier)">{{ t('admin.models.actions.edit') }}</a-button>
                      <a-button size="mini" status="danger" @click="removeTier(tier)">{{ t('admin.models.actions.delete') }}</a-button>
                    </a-space>
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
      :title="modelEditMode ? t('admin.models.modelModal.editTitle') : t('admin.models.actions.createModel')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitModel"
    >
      <a-form :model="modelForm" layout="vertical">
        <a-alert v-for="err in pricingErrors" :key="err" type="error" show-icon class="mb-3">{{ err }}</a-alert>
        <a-form-item :label="t('admin.models.columns.provider')" field="provider">
          <a-select v-model="modelForm.provider" allow-search>
            <a-option v-for="p in providerOptions" :key="p.id" :value="p.name">
              <a-tooltip :content="p.description || t('admin.models.noDescription')" position="tr" mini>
                <div>{{ p.label || p.name }}</div>
              </a-tooltip>
            </a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.models.modelType')" field="model_type">
          <a-select v-model="modelForm.model_type">
            <a-option v-for="mt in filteredModelTypeOptions" :key="mt" :value="mt">{{ t(`admin.models.modelTypeOptions.${mt}`) }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.models.compatibleApi')" field="compatible_api">
          <a-select v-model="modelForm.compatible_api">
            <a-option v-for="api in COMPATIBLE_APIS" :key="api" :value="api">{{ t(`admin.models.compatibleApiOptions.${api}`) }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.models.baseUrlFromProvider')" field="base_url">
          <a-input :model-value="selectedProviderBaseUrl" disabled />
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.modelName')" field="model_name">
          <a-input v-model="modelForm.model_name" :placeholder="t('admin.models.modelModal.placeholders.modelName')" />
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.displayName')" field="display_name">
          <a-input v-model="modelForm.display_name" :placeholder="t('admin.models.modelModal.placeholders.displayName')" />
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.description')" field="description">
          <a-textarea v-model="modelForm.description" :auto-size="{ minRows: 2, maxRows: 4 }" :placeholder="t('admin.models.modelModal.placeholders.description')" :max-length="500" show-word-limit />
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.tier')" field="tier">
          <a-select v-model="modelForm.tier" allow-search>
            <a-option v-for="tier in tiers" :key="tier.tier_code" :value="tier.tier_code">
              {{ tier.tier_code }} - {{ tier.tier_name }}
            </a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.models.columns.capabilities')" field="capabilities">
          <a-input-tag v-model="modelForm.capabilities" :placeholder="t('admin.models.modelModal.placeholders.capabilities')" allow-clear />
        </a-form-item>
        <div class="form-group">
          <h4 class="form-group-title">{{ t('admin.models.groups.sellPrice') }}</h4>
          <p class="form-group-desc">{{ t('admin.models.groups.sellPriceDesc') }}</p>
          <div class="grid gap-4 md:grid-cols-2">
            <a-form-item :label="t('admin.models.fields.inputPrice')" field="input_price_per_1k_tokens">
              <a-input v-model="modelForm.input_price_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.inputPrice')" />
            </a-form-item>
            <a-form-item :label="t('admin.models.fields.outputPrice')" field="output_price_per_1k_tokens">
              <a-input v-model="modelForm.output_price_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.outputPrice')" />
            </a-form-item>
          </div>
        </div>
        <div class="form-group">
          <h4 class="form-group-title">{{ t('admin.models.groups.costBase') }}</h4>
          <p class="form-group-desc">{{ t('admin.models.groups.costBaseDesc') }}</p>
          <div class="grid gap-4 md:grid-cols-2">
            <a-form-item :label="t('admin.models.fields.inputCost')" field="input_cost_per_1k_tokens">
              <a-input v-model="modelForm.input_cost_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.inputCost')" />
            </a-form-item>
            <a-form-item :label="t('admin.models.fields.outputCost')" field="output_cost_per_1k_tokens">
              <a-input v-model="modelForm.output_cost_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.outputCost')" />
            </a-form-item>
          </div>
        </div>
        <a-alert v-if="marginPreview !== null" :type="marginPreview >= 0 ? 'success' : 'warning'" show-icon>
          <a-tooltip :content="t('admin.models.groups.marginTooltip')">
            <span>{{ t('admin.models.groups.marginPreview', { margin: formatSigned(marginPreview), percent: formatSigned(marginPercent) }) }}</span>
          </a-tooltip>
        </a-alert>
        <div class="form-group">
          <h4 class="form-group-title">定价模式</h4>
          <p class="form-group-desc">开启「谷峰定价」可按峰谷时段分别设置售价与成本；开启「缓存命中/未命中拆分」后可单独为缓存命中输入计价。</p>
          <a-form-item label="计价方式" field="peak_valley_enabled">
            <a-radio-group v-model="modelForm.peak_valley_enabled" @change="onPricingModeChange">
              <a-radio :value="false">常规（单档单价）</a-radio>
              <a-radio :value="true">谷峰定价（分时段）</a-radio>
            </a-radio-group>
          </a-form-item>
          <a-form-item label="缓存命中/未命中拆分" tooltip="开启后输入按缓存命中与未命中两档分别计价" field="cache_pricing_enabled">
            <a-switch v-model="modelForm.cache_pricing_enabled" class="cache-split-switch" />
          </a-form-item>

          <template v-if="modelForm.peak_valley_enabled">
            <a-form-item label="峰谷时段（北京时间，JSON）" field="peak_windows">
              <a-textarea
                v-model="modelForm.peak_windows"
                name="peak_windows"
                :rows="2"
                placeholder='[{"days":"0-6","start":"09:00","end":"18:00"}]'
              />
              <div class="mt-2">
                <a-button size="small" @click="applyProviderDefaultWindows()">按供应商默认时段填充</a-button>
              </div>
            </a-form-item>
            <div class="grid gap-4 md:grid-cols-2">
              <div>
                <h5 class="form-subgroup-title">峰档售价</h5>
                <a-form-item label="输入（未命中）" field="peak_input_price_per_1k_tokens">
                  <a-input-number v-model="modelForm.peak_input_price_per_1k_tokens" name="peak_input_price_per_1k_tokens" :min="0" :precision="6" placeholder="峰-输入售价" class="w-full" />
                </a-form-item>
                <a-form-item label="输出" field="peak_output_price_per_1k_tokens">
                  <a-input-number v-model="modelForm.peak_output_price_per_1k_tokens" name="peak_output_price_per_1k_tokens" :min="0" :precision="6" placeholder="峰-输出售价" class="w-full" />
                </a-form-item>
                <a-form-item v-if="modelForm.cache_pricing_enabled" label="输入（缓存命中）" field="peak_input_cached_price_per_1k_tokens">
                  <a-input-number v-model="modelForm.peak_input_cached_price_per_1k_tokens" name="peak_input_cached_price_per_1k_tokens" :min="0" :precision="6" placeholder="峰-缓存命中售价" class="w-full" />
                </a-form-item>
              </div>
              <div>
                <h5 class="form-subgroup-title">峰档成本</h5>
                <a-form-item label="输入（未命中）" field="peak_input_cost_per_1k_tokens">
                  <a-input-number v-model="modelForm.peak_input_cost_per_1k_tokens" name="peak_input_cost_per_1k_tokens" :min="0" :precision="6" placeholder="峰-输入成本" class="w-full" />
                </a-form-item>
                <a-form-item label="输出" field="peak_output_cost_per_1k_tokens">
                  <a-input-number v-model="modelForm.peak_output_cost_per_1k_tokens" name="peak_output_cost_per_1k_tokens" :min="0" :precision="6" placeholder="峰-输出成本" class="w-full" />
                </a-form-item>
                <a-form-item v-if="modelForm.cache_pricing_enabled" label="输入（缓存命中）" field="peak_input_cached_cost_per_1k_tokens">
                  <a-input-number v-model="modelForm.peak_input_cached_cost_per_1k_tokens" name="peak_input_cached_cost_per_1k_tokens" :min="0" :precision="6" placeholder="峰-缓存命中成本" class="w-full" />
                </a-form-item>
              </div>
            </div>
            <div class="grid gap-4 md:grid-cols-2">
              <div>
                <h5 class="form-subgroup-title">谷档售价</h5>
                <a-form-item label="输入（未命中）" field="valley_input_price_per_1k_tokens">
                  <a-input-number v-model="modelForm.valley_input_price_per_1k_tokens" name="valley_input_price_per_1k_tokens" :min="0" :precision="6" placeholder="谷-输入售价" class="w-full" />
                </a-form-item>
                <a-form-item label="输出" field="valley_output_price_per_1k_tokens">
                  <a-input-number v-model="modelForm.valley_output_price_per_1k_tokens" name="valley_output_price_per_1k_tokens" :min="0" :precision="6" placeholder="谷-输出售价" class="w-full" />
                </a-form-item>
                <a-form-item v-if="modelForm.cache_pricing_enabled" label="输入（缓存命中）" field="valley_input_cached_price_per_1k_tokens">
                  <a-input-number v-model="modelForm.valley_input_cached_price_per_1k_tokens" name="valley_input_cached_price_per_1k_tokens" :min="0" :precision="6" placeholder="谷-缓存命中售价" class="w-full" />
                </a-form-item>
              </div>
              <div>
                <h5 class="form-subgroup-title">谷档成本</h5>
                <a-form-item label="输入（未命中）" field="valley_input_cost_per_1k_tokens">
                  <a-input-number v-model="modelForm.valley_input_cost_per_1k_tokens" name="valley_input_cost_per_1k_tokens" :min="0" :precision="6" placeholder="谷-输入成本" class="w-full" />
                </a-form-item>
                <a-form-item label="输出" field="valley_output_cost_per_1k_tokens">
                  <a-input-number v-model="modelForm.valley_output_cost_per_1k_tokens" name="valley_output_cost_per_1k_tokens" :min="0" :precision="6" placeholder="谷-输出成本" class="w-full" />
                </a-form-item>
                <a-form-item v-if="modelForm.cache_pricing_enabled" label="输入（缓存命中）" field="valley_input_cached_cost_per_1k_tokens">
                  <a-input-number v-model="modelForm.valley_input_cached_cost_per_1k_tokens" name="valley_input_cached_cost_per_1k_tokens" :min="0" :precision="6" placeholder="谷-缓存命中成本" class="w-full" />
                </a-form-item>
              </div>
            </div>
          </template>

          <template v-if="!modelForm.peak_valley_enabled && modelForm.cache_pricing_enabled">
            <a-form-item label="输入售价（缓存命中）" field="input_cached_price_per_1k_tokens">
              <a-input-number v-model="modelForm.input_cached_price_per_1k_tokens" name="input_cached_price_per_1k_tokens" :min="0" :precision="6" placeholder="缓存命中-输入售价" class="w-full" />
            </a-form-item>
            <a-form-item label="输入成本（缓存命中）" field="input_cached_cost_per_1k_tokens">
              <a-input-number v-model="modelForm.input_cached_cost_per_1k_tokens" name="input_cached_cost_per_1k_tokens" :min="0" :precision="6" placeholder="缓存命中-输入成本" class="w-full" />
            </a-form-item>
          </template>

          <a-button type="outline" :loading="pricingSuggestLoading" @click="openPricingSuggest()">自动定价助手</a-button>
        </div>
        <div class="form-group">
          <h4 class="form-group-title">{{ t('admin.models.groups.fallback') }}</h4>
          <p class="form-group-desc">{{ t('admin.models.groups.fallbackDesc') }}</p>
          <a-form-item :label="t('admin.models.fields.pricePer1k')" field="price_per_1k_tokens">
            <a-input v-model="modelForm.price_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.price')" />
          </a-form-item>
        </div>
        <a-form-item
          v-if="hasContextField"
          :label="t('admin.models.fields.maxInputTokens')"
          field="max_input_tokens"
        >
          <a-input-number
            v-model="modelForm.max_input_tokens"
            :min="0"
            :step="1024"
            :placeholder="t('admin.models.modelModal.placeholders.maxInputTokens')"
            class="w-full"
          />
          <div class="mt-2 flex flex-wrap gap-1.5">
            <a-tag
              v-for="preset in MAX_TOKENS_PRESETS"
              :key="preset.value"
              :checkable="true"
              :checked="modelForm.max_input_tokens === preset.value"
              size="small"
              @click="modelForm.max_input_tokens = preset.value"
            >
              {{ preset.label }}
            </a-tag>
          </div>
        </a-form-item>
        <a-form-item
          v-if="hasContextField"
          :label="t('admin.models.fields.maxOutputTokens')"
          field="max_output_tokens"
        >
          <a-input-number
            v-model="modelForm.max_output_tokens"
            :min="0"
            :step="512"
            :placeholder="t('admin.models.modelModal.placeholders.maxOutputTokens')"
            class="w-full"
          />
          <div class="mt-2 flex flex-wrap gap-1.5">
            <a-tag
              v-for="preset in OUTPUT_TOKENS_PRESETS"
              :key="preset.value"
              :checkable="true"
              :checked="modelForm.max_output_tokens === preset.value"
              size="small"
              @click="modelForm.max_output_tokens = preset.value"
            >
              {{ preset.label }}
            </a-tag>
          </div>
        </a-form-item>
        <a-form-item
          v-if="modelForm.model_type === 'embedding'"
          :label="t('admin.models.fields.embeddingDimension')"
          field="embedding_dimension"
        >
          <a-input
            :model-value="modelForm.embedding_dimension > 0
              ? `${modelForm.embedding_dimension} ${t('admin.models.embeddingDimensionHints.probedSuffix')}`
              : t('admin.models.embeddingDimensionHints.probing')"
            readonly
          />
          <template #extra>{{ t('admin.models.embeddingDimensionHints.autoProbeHint') }}</template>
        </a-form-item>
        <a-form-item :label="t('admin.models.fields.fallbackModelId')" field="fallback_model_id">
          <a-input v-model="modelForm.fallback_model_id" :placeholder="t('admin.models.modelModal.placeholders.fallbackModelId')" />
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
          <a-select v-model="keyForm.provider" allow-search>
            <a-option v-for="p in providerOptions" :key="p.id" :value="p.name">
              <a-tooltip :content="p.description || t('admin.models.noDescription')" position="tr" mini>
                <div>{{ p.label || p.name }}</div>
              </a-tooltip>
            </a-option>
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
          <template #extra>{{ t('admin.models.keyModal.hints.tenantQuota') }}</template>
        </a-form-item>
        <a-form-item :label="t('admin.models.fields.boundModel')" field="model_id">
          <a-select v-model="keyForm.model_id" allow-search allow-clear :placeholder="t('admin.models.keyModal.placeholders.modelId')">
            <a-option value="" :label="t('admin.models.keyModal.options.unlimitedModel')" />
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
      :title="tierEditMode ? t('admin.models.tierModal.title') : '创建档位'"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitTier"
    >
      <a-form :model="tierForm" layout="vertical">
        <a-form-item label="档位标识" field="tier_code">
          <a-input v-model="tierForm.tier_code" :disabled="tierEditMode" placeholder="如 1, 2, 3" />
        </a-form-item>
        <a-form-item label="档位名称" field="tier_name">
          <a-input v-model="tierForm.tier_name" placeholder="如 经济型、标准型" />
        </a-form-item>
        <a-form-item label="排序序号" field="sort_order">
          <a-input-number v-model="tierForm.sort_order" :min="0" :step="1" />
        </a-form-item>
        <a-form-item label="允许的模型" field="allowed_models">
          <a-select
            v-model="tierForm.allowed_models"
            multiple
            allow-search
            allow-clear
            placeholder="选择允许的模型（留空则不限制）"
          >
            <a-option v-for="m in models" :key="m.id" :value="m.id">
              {{ m.display_name || m.model_name }} ({{ m.provider }})
            </a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="默认模型" field="default_model">
          <a-select
            v-model="tierForm.default_model"
            allow-search
            allow-clear
            placeholder="选择默认模型"
          >
            <a-option v-for="m in models" :key="m.id" :value="m.id">
              {{ m.display_name || m.model_name }} ({{ m.provider }})
            </a-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>

<style scoped>
.form-group {
  padding: 12px 0;
  border-top: 1px solid #f0f1f3;
}

.form-group-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #1d2129;
}

.form-group-desc {
  margin: 4px 0 12px;
  font-size: 12px;
  color: #86909c;
  line-height: 1.6;
}

.form-subgroup-title {
  margin: 8px 0;
  font-size: 13px;
  font-weight: 600;
  color: #4e5969;
}
</style>
