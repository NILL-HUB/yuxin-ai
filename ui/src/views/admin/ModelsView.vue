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
import { suggestSellPrices } from '@/services/admin-pricing-suggest'
import { getErrorMessage } from '@/utils/error'
import { perKToPerM, perMToPerK } from '@/utils/pricing-unit'

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
  [key: string]: unknown
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
  // 价格字段统一为 number：供 a-input-number 双向绑定，后端字符串在 openEditModel 回填时经 Number() 归一
  price_per_1k_tokens: 0,
  input_price_per_1k_tokens: 0,
  output_price_per_1k_tokens: 0,
  input_cost_per_1k_tokens: 0,
  output_cost_per_1k_tokens: 0,
  peak_valley_enabled: false,
  cache_pricing_enabled: false,
  peak_windows: '[]',
  input_cached_price_per_1k_tokens: 0,
  input_cached_cost_per_1k_tokens: 0,
  peak_input_price_per_1k_tokens: 0,
  peak_input_cost_per_1k_tokens: 0,
  peak_output_price_per_1k_tokens: 0,
  peak_output_cost_per_1k_tokens: 0,
  peak_input_cached_price_per_1k_tokens: 0,
  peak_input_cached_cost_per_1k_tokens: 0,
  valley_input_price_per_1k_tokens: 0,
  valley_input_cost_per_1k_tokens: 0,
  valley_output_price_per_1k_tokens: 0,
  valley_output_cost_per_1k_tokens: 0,
  valley_input_cached_price_per_1k_tokens: 0,
  valley_input_cached_cost_per_1k_tokens: 0,
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

// 表单字段口径为 /M tokens（显示层），售价与成本同为「元/M」，毛利预览无需任何汇率折算
const PRICING_INPUT_DIM_KEYS = ['input', 'output'] as const
type PricingInputDim = typeof PRICING_INPUT_DIM_KEYS[number]
// 读取表单某维度的"当前档"售价/成本（/M 口径）：启用峰谷时取峰档（保守毛利），否则取 flat
const formPricingDimOf = (form: typeof modelForm.value, kind: 'price' | 'cost', dim: PricingInputDim): number => {
  const suffix = kind === 'price' ? 'price' : 'cost'
  if (form.peak_valley_enabled) {
    const peak = Number((form as unknown as Record<string, string>)[`peak_${dim}_${suffix}_per_1k_tokens`] || 0)
    const valley = Number((form as unknown as Record<string, string>)[`valley_${dim}_${suffix}_per_1k_tokens`] || 0)
    return peak > 0 ? peak : valley
  }
  return Number((form as unknown as Record<string, string>)[`${dim}_${suffix}_per_1k_tokens`] || 0)
}
const MARGIN_RATIO = 3
// 毛利预览：参考用量 3:1（3000 输入 + 1000 输出），售价与成本同为 /M 元，同单位直减（元）
const marginPreview = computed(() => {
  const f = modelForm.value
  const sellIn = formPricingDimOf(f, 'price', 'input')
  const sellOut = formPricingDimOf(f, 'price', 'output')
  const costIn = formPricingDimOf(f, 'cost', 'input')
  const costOut = formPricingDimOf(f, 'cost', 'output')
  if (!sellIn && !sellOut) return null
  const sell = sellIn * MARGIN_RATIO + sellOut
  const cost = costIn * MARGIN_RATIO + costOut
  return sell - cost
})
const marginPercent = computed(() => {
  const f = modelForm.value
  const costIn = formPricingDimOf(f, 'cost', 'input')
  const costOut = formPricingDimOf(f, 'cost', 'output')
  const cost = costIn * MARGIN_RATIO + costOut
  if (cost <= 0) return 0
  return ((marginPreview.value || 0) / cost) * 100
})
const formatSigned = (value: number) => {
  const n = Math.round(Number(value) || 0)
  return n > 0 ? `+${n}` : `${n}`
}
// 拆分售价是否已配置：任一档任一维度 >0 即认为拆售价生效，兜底单价不参与计费
const splitSellPriceActive = computed(() => {
  const f = modelForm.value
  const candidates = [
    f.input_price_per_1k_tokens,
    f.output_price_per_1k_tokens,
    f.peak_input_price_per_1k_tokens,
    f.peak_output_price_per_1k_tokens,
    f.valley_input_price_per_1k_tokens,
    f.valley_output_price_per_1k_tokens,
  ]
  return candidates.some((v) => Number(v || 0) > 0)
})

// 读取模型某维度的"当前档"售价/成本：启用峰谷时取峰档（保守毛利），否则取 flat
const pricingDimOf = (record: ModelRecord, kind: 'price' | 'cost', dim: 'input' | 'output' | 'inputCached') => {
  const pv = toBool(record.peak_valley_enabled)
  const cache = toBool(record.cache_pricing_enabled)
  const suffix = kind === 'price' ? 'price_per_1k_tokens' : 'cost_per_1k_tokens'
  if (pv) {
    const peak = Number((record as unknown as Record<string, string>)[`peak_${dim === 'inputCached' ? 'input_cached' : dim}_${suffix}`] || 0)
    const valley = Number((record as unknown as Record<string, string>)[`valley_${dim === 'inputCached' ? 'input_cached' : dim}_${suffix}`] || 0)
    return { peak, valley }
  }
  const flat = Number((record as unknown as Record<string, string>)[`${dim === 'inputCached' ? 'input_cached' : dim}_${suffix}`] || 0)
  return { peak: flat, valley: flat }
}

const marginOf = (record: ModelRecord) => {
  const { peak: costIn } = pricingDimOf(record, 'cost', 'input')
  const { peak: costOut } = pricingDimOf(record, 'cost', 'output')
  const { peak: sellIn } = pricingDimOf(record, 'price', 'input')
  const { peak: sellOut } = pricingDimOf(record, 'price', 'output')
  // 参考用量 3:1（3000 输入 + 1000 输出），售价与成本同为元/1k，同单位直减即为该 4k 用量的毛利（元）
  // 已按 perKToPerM ×1000 折算为「元/M」数量级展示（元/M 毛利 = (sellIn*3+sellOut - costIn*3-costOut) × 250）
  const sell = sellIn * 3 + sellOut
  const cost = costIn * 3 + costOut
  return (sell - cost) * 250
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
// 常规 flat 4 个价格字段（含兜底单价），与峰谷/缓存字段一同做 /M→/1k 换算后提交
const FLAT_PRICE_FIELD_KEYS = [
  'price_per_1k_tokens',
  'input_price_per_1k_tokens',
  'output_price_per_1k_tokens',
  'input_cost_per_1k_tokens',
  'output_cost_per_1k_tokens',
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

// 峰谷窗口编辑器行
type PeakWindowRow = {
  days: number[]
  start: string
  end: string
}
// 星期选项：0=周日 ~ 6=周六，value 与后端 days 字段的 0-6 序号一致
const WEEKDAY_OPTIONS = [
  { value: 0, label: '周日' },
  { value: 1, label: '周一' },
  { value: 2, label: '周二' },
  { value: 3, label: '周三' },
  { value: 4, label: '周四' },
  { value: 5, label: '周五' },
  { value: 6, label: '周六' },
]
const WEEKDAY_DAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const windowsParseError = ref(false)
const peakWindowsDirty = ref(false)

const parseDays = (days?: unknown): number[] => {
  if (typeof days === 'number') return [days]
  if (typeof days !== 'string' || !days.trim()) return []
  const daysStr = days.trim()
  if (/^\d(-\d)?$/.test(daysStr)) {
    const [from, to] = daysStr.split('-').map(Number)
    if (to === undefined) return [from]
    const out: number[] = []
    for (let i = from; i <= to; i += 1) out.push(i % 7)
    return out
  }
  return daysStr.split(',').map(Number).filter((n) => !Number.isNaN(n) && n >= 0 && n <= 6)
}

// modelForm.peak_windows 为 JSON 字符串，此处解析为编辑器行；解析失败回退空数组并提示
const peakWindowRows = computed<PeakWindowRow[]>({
  get() {
    const raw = modelForm.value.peak_windows
    if (typeof raw !== 'string' || !raw.trim()) return []
    try {
      const arr = JSON.parse(raw)
      if (!Array.isArray(arr)) return []
      return arr.map((item: Record<string, unknown>) => ({
        days: parseDays(item?.days),
        start: String(item?.start ?? ''),
        end: String(item?.end ?? ''),
      }))
    } catch {
      return []
    }
  },
  set(rows: PeakWindowRow[]) {
    modelForm.value.peak_windows = JSON.stringify(rows.map((row) => ({ days: row.days.join(','), start: row.start, end: row.end })))
  },
})
const setPeakWindows = (rows: PeakWindowRow[]) => {
  windowsParseError.value = false
  peakWindowRows.value = rows
  peakWindowsDirty.value = true
}
const addPeakWindow = () => {
  setPeakWindows([...peakWindowRows.value, { days: [1, 2, 3, 4, 5], start: '09:00', end: '12:00' }])
}
const removePeakWindow = (index: number) => {
  const rows = peakWindowRows.value.filter((_, i) => i !== index)
  setPeakWindows(rows)
}

// 仅当未配置任何窗口时才按供应商默认填充，绝不覆盖用户已配置的窗口
const applyProviderDefaultWindows = () => {
  if (peakWindowRows.value.length > 0) return
  const provider = String(modelForm.value.provider || '').toLowerCase()
  if (provider === 'siliconflow') {
    // 低谷 02:00-08:00 → 峰窗口为每日两段
    setPeakWindows([
      { days: [0, 1, 2, 3, 4, 5, 6], start: '00:00', end: '02:00' },
      { days: [0, 1, 2, 3, 4, 5, 6], start: '08:00', end: '24:00' },
    ])
  } else {
    setPeakWindows([
      { days: [0, 1, 2, 3, 4], start: '09:00', end: '12:00' },
      { days: [0, 1, 2, 3, 4], start: '14:00', end: '18:00' },
    ])
  }
}
const handlePeakValleyEnabled = () => {
  // 校验非法 JSON：一旦打开谷峰开关且表单里遗留非法 JSON，提示并按空处理
  const raw = modelForm.value.peak_windows
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed)) {
        windowsParseError.value = true
        peakWindowRows.value = []
        return
      }
    } catch {
      windowsParseError.value = true
      modelForm.value.peak_windows = '[]'
      peakWindowRows.value = []
      return
    }
  }
  if (peakWindowRows.value.length === 0) {
    applyProviderDefaultWindows()
  }
}
// 值变化时按需初始化窗口（幂等：仅在从常规切到峰谷的一次转变时触发，绝不覆盖已有窗口）
watch(() => modelForm.value.peak_valley_enabled, (enabled) => {
  if (enabled) {
    handlePeakValleyEnabled()
  }
})
const validatePeakWindows = (): boolean => {
  if (!modelForm.value.peak_valley_enabled) return true
  const rows = peakWindowRows.value
  if (rows.length === 0) return true
  const timeRe = /^([01]\d|2[0-3]):[0-5]\d$/
  const midNightRe = /^24:00$/
  const weekdays = new Set([0, 1, 2, 3, 4, 5, 6])
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i]
    const rowWeekdays = Array.isArray(row.days) ? row.days : []
    if (rowWeekdays.length === 0) {
      Message.warning(t('admin.models.pricingMode.windowsRowError', { index: i + 1, reason: t('admin.models.pricingMode.windowsReasonDays') }))
      return false
    }
    if (rowWeekdays.some((d) => !weekdays.has(Number(d)))) {
      Message.warning(t('admin.models.pricingMode.windowsRowError', { index: i + 1, reason: t('admin.models.pricingMode.windowsReasonDays') }))
      return false
    }
    const endIsMidnight = midNightRe.test(row.end)
    const startValid = typeof row.start === 'string' && timeRe.test(row.start)
    const endValid = typeof row.end === 'string' && (endIsMidnight || timeRe.test(row.end))
    if (!startValid) {
      Message.warning(t('admin.models.pricingMode.windowsRowError', { index: i + 1, reason: t('admin.models.pricingMode.windowsReasonStart') }))
      return false
    }
    if (!endValid) {
      Message.warning(t('admin.models.pricingMode.windowsRowError', { index: i + 1, reason: t('admin.models.pricingMode.windowsReasonEnd') }))
      return false
    }
    if (!endIsMidnight && row.end <= row.start) {
      Message.warning(t('admin.models.pricingMode.windowsRowError', { index: i + 1, reason: t('admin.models.pricingMode.windowsReasonOrder') }))
      return false
    }
  }
  return true
}
const parsePeakWindowsWarnings = (): string[] => {
  const raw = modelForm.value.peak_windows
  if (typeof raw !== 'string' || !raw.trim()) return []
  try {
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return ['unparseable']
    const timeRe = /^([01]\d|2[0-3]):[0-5]\d$/
    return arr.some((item: Record<string, unknown>) => {
      const days = parseDays(item?.days)
      const start = String(item?.start ?? '')
      const end = String(item?.end ?? '')
      const startValid = timeRe.test(start)
      const endValid = /^24:00$/.test(end) || timeRe.test(end)
      return !startValid || !endValid || days.length === 0
    })
      ? ['invalid-row']
      : []
  } catch {
    return ['unparseable']
  }
}
const peakWindowsWarnings = computed<string[]>(() => {
  if (!modelForm.value.peak_valley_enabled) return []
  if (windowsParseError.value) return ['unparseable']
  if (peakWindowsDirty.value) return []
  return parsePeakWindowsWarnings()
})

// 自动定价建议预览
type SuggestRow = {
  key: string
  label: string
  current: string
  suggested: string
}
const priceKeyDefs: { key: string; item: string; dimension: string; cache: boolean }[] = [
  { key: 'peak_input_price_per_1k_tokens', item: 'peak', dimension: 'input', cache: false },
  { key: 'peak_output_price_per_1k_tokens', item: 'peak', dimension: 'output', cache: false },
  { key: 'peak_input_cached_price_per_1k_tokens', item: 'peak', dimension: 'input', cache: true },
  { key: 'valley_input_price_per_1k_tokens', item: 'valley', dimension: 'input', cache: false },
  { key: 'valley_output_price_per_1k_tokens', item: 'valley', dimension: 'output', cache: false },
  { key: 'valley_input_cached_price_per_1k_tokens', item: 'valley', dimension: 'input', cache: true },
  { key: 'input_cached_price_per_1k_tokens', item: 'regular', dimension: 'input', cache: true },
  { key: 'input_price_per_1k_tokens', item: 'regular', dimension: 'input', cache: false },
  { key: 'output_price_per_1k_tokens', item: 'regular', dimension: 'output', cache: false },
]
const peakTag = computed(() => t('admin.models.pricingMode.tag.peak'))
const valleyTag = computed(() => t('admin.models.pricingMode.tag.valley'))
const cacheTag = computed(() => t('admin.models.pricingMode.tag.cache'))
const labelForPriceKey = (key: string): string => {
  const def = priceKeyDefs.find((d) => d.key === key)
  if (!def) return key
  const tag = def.item === 'peak' ? peakTag.value : def.item === 'valley' ? valleyTag.value : ''
  const dim = def.cache
    ? t('admin.models.pricingMode.dim.inputCached')
    : def.dimension === 'input'
      ? t('admin.models.pricingMode.dim.input')
      : t('admin.models.pricingMode.dim.output')
  return tag ? `${tag} · ${dim}` : dim
}
const formatSuggestPrice = (value: unknown): string => {
  const n = Number(value ?? '')
  if (value === null || value === undefined || value === '' || Number.isNaN(n)) return '—'
  return perKToPerM(n)
}
const currentPriceOf = (key: string): string => {
  const modelValue = (modelForm.value as Record<string, unknown>)[key]
  const n = Number(modelValue ?? '')
  return !Number.isNaN(n) && n > 0 ? String(n) : '—'
}
const suggestRows = ref<SuggestRow[]>([])
const suggestWarnings = ref<string[]>([])
const pricingPreviewVisible = ref(false)
const pricingPreviewLoading = ref(false)
const fallbackSuggestRecord = ref<Record<string, string>>({})

const buildSuggestPreview = (key: string, value: unknown) => {
  const def = priceKeyDefs.find((d) => d.key === key)
  if (!def) return
  suggestRows.value.push({
    key,
    label: labelForPriceKey(key),
    current: currentPriceOf(key),
    suggested: formatSuggestPrice(value),
  })
}
const openPricingSuggest = async () => {
  pricingPreviewLoading.value = true
  try {
    // 表单为 /M 口径，后端建议引擎按 /1k 计算：先换算回 /1k 提交
    const perKForm = { ...modelForm.value } as Record<string, unknown>
    ;[...PRICING_FIELD_KEYS, ...FLAT_PRICE_FIELD_KEYS].forEach((key) => {
      perKForm[key] = perMToPerK(perKForm[key])
    })
    const resp = await suggestSellPrices(
      {
        ...perKForm,
        peak_valley_enabled: modelForm.value.peak_valley_enabled,
        cache_pricing_enabled: modelForm.value.cache_pricing_enabled,
      },
      0.3,
    )
    if (resp) {
      suggestWarnings.value = Array.isArray(resp.warnings) ? resp.warnings.map((w) => String(w)) : []
      // 新结构优先取 resp.suggestions；为空则回退到顶层展开的旧结构
      const inner = resp.suggestions && typeof resp.suggestions === 'object' && !Array.isArray(resp.suggestions)
        ? (resp.suggestions as Record<string, unknown>)
        : {}
      const source = Object.keys(inner).length > 0
        ? inner
        : Object.fromEntries(Object.entries(resp).filter(([key]) => key !== 'suggestions' && key !== 'applied' && key !== 'warnings'))
      // 后端建议为 /1k 口径：预览按 /M 展示，应用时以 /M 写入表单
      fallbackSuggestRecord.value = Object.fromEntries(
        Object.keys(source)
          .filter((key) => (key in modelForm.value))
          .map((key) => [key, perKToPerM(source[key])]),
      )
      suggestRows.value = []
      Object.entries(source).forEach(([key, value]) => buildSuggestPreview(key, value))
      pricingPreviewVisible.value = true
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.models.messages.getPricingSuggestFailed')))
  } finally {
    pricingPreviewLoading.value = false
  }
}
const cancelPricingSuggest = () => {
  pricingPreviewVisible.value = false
  suggestRows.value = []
  suggestWarnings.value = []
}
const applyPricingSuggest = () => {
  const formRecord = modelForm.value as Record<string, unknown>
  Object.entries(fallbackSuggestRecord.value).forEach(([key, value]) => {
    if (key in formRecord) {
      // 建议值为 /M 数字字符串，写入前转为 number 以兼容 a-input-number
      formRecord[key] = Number(value) || 0
    }
  })
  pricingPreviewVisible.value = false
  Message.success(t('admin.models.messages.pricingSuggestApplied'))
}
// 列表「定价」列展示结构：峰谷 / 普通两态，均含售价+成本，缓存单独行（/M 口径）
type PricingLine = { label: string; sell: string; cost: string; tone: 'peak' | 'valley' | 'flat' }
const num = (v?: string): number => Number(v || 0)
const fmtM = (v?: string): string => perKToPerM(v)
const pricingBlockOf = (model: ModelRecord): { lines: PricingLine[]; cached: { sell: string; cost: string } | null } => {
  const lines: PricingLine[] = []
  let cached: { sell: string; cost: string } | null = null
  const cacheOn = toBool(model.cache_pricing_enabled)
  if (toBool(model.peak_valley_enabled)) {
    const peakSell = fmtM(model.peak_input_price_per_1k_tokens) + '/' + fmtM(model.peak_output_price_per_1k_tokens)
    const peakCost = fmtM(model.peak_input_cost_per_1k_tokens) + '/' + fmtM(model.peak_output_cost_per_1k_tokens)
    const valleySell = fmtM(model.valley_input_price_per_1k_tokens) + '/' + fmtM(model.valley_output_price_per_1k_tokens)
    const valleyCost = fmtM(model.valley_input_cost_per_1k_tokens) + '/' + fmtM(model.valley_output_cost_per_1k_tokens)
    if (peakSell !== '0/0' || peakCost !== '0/0') lines.push({ label: '峰', sell: peakSell, cost: peakCost, tone: 'peak' })
    if (valleySell !== '0/0' || valleyCost !== '0/0') lines.push({ label: '谷', sell: valleySell, cost: valleyCost, tone: 'valley' })
    if (cacheOn) {
      cached = {
        sell: fmtM(model.peak_input_cached_price_per_1k_tokens) + '/' + fmtM(model.valley_input_cached_price_per_1k_tokens),
        cost: fmtM(model.peak_input_cached_cost_per_1k_tokens) + '/' + fmtM(model.valley_input_cached_cost_per_1k_tokens),
      }
    }
    return { lines, cached }
  }
  // 普通模式
  const sell = fmtM(model.input_price_per_1k_tokens) + '/' + fmtM(model.output_price_per_1k_tokens)
  const cost = fmtM(model.input_cost_per_1k_tokens) + '/' + fmtM(model.output_cost_per_1k_tokens)
  if (num(model.input_price_per_1k_tokens) || num(model.output_price_per_1k_tokens) || num(model.input_cost_per_1k_tokens) || num(model.output_cost_per_1k_tokens)) {
    lines.push({ label: '常规', sell, cost, tone: 'flat' })
  }
  if (cacheOn) {
    cached = { sell: fmtM(model.input_cached_price_per_1k_tokens), cost: fmtM(model.input_cached_cost_per_1k_tokens) }
  }
  return { lines, cached }
}
// 列表毛利标签：售价与成本同为元/1k，同单位直减后折算为 /M（marginOf 返回元/M）
const peakValleySummaryOf = (model: ModelRecord): { peak: string; valley: string } | null => {
  const { lines } = pricingBlockOf(model)
  if (!toBool(model.peak_valley_enabled)) return null
  const peak = lines.find((l) => l.tone === 'peak')?.sell || ''
  const valley = lines.find((l) => l.tone === 'valley')?.sell || ''
  if (!peak && !valley) return null
  return { peak, valley }
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
    price_per_1k_tokens: 0,
    input_price_per_1k_tokens: 0,
    output_price_per_1k_tokens: 0,
    input_cost_per_1k_tokens: 0,
    output_cost_per_1k_tokens: 0,
    peak_valley_enabled: false,
    cache_pricing_enabled: false,
    peak_windows: '[]',
    input_cached_price_per_1k_tokens: 0,
    input_cached_cost_per_1k_tokens: 0,
    peak_input_price_per_1k_tokens: 0,
    peak_input_cost_per_1k_tokens: 0,
    peak_output_price_per_1k_tokens: 0,
    peak_output_cost_per_1k_tokens: 0,
    peak_input_cached_price_per_1k_tokens: 0,
    peak_input_cached_cost_per_1k_tokens: 0,
    valley_input_price_per_1k_tokens: 0,
    valley_input_cost_per_1k_tokens: 0,
    valley_output_price_per_1k_tokens: 0,
    valley_output_cost_per_1k_tokens: 0,
    valley_input_cached_price_per_1k_tokens: 0,
    valley_input_cached_cost_per_1k_tokens: 0,
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
    // 后端 /1k 字符串 → 界面 /M number：perKToPerM 返回紧凑字符串，Number() 归一后再绑 a-input-number
    price_per_1k_tokens: Number(perKToPerM(model.price_per_1k_tokens)) || 0,
    input_price_per_1k_tokens: Number(perKToPerM(model.input_price_per_1k_tokens)) || 0,
    output_price_per_1k_tokens: Number(perKToPerM(model.output_price_per_1k_tokens)) || 0,
    input_cost_per_1k_tokens: Number(perKToPerM(model.input_cost_per_1k_tokens)) || 0,
    output_cost_per_1k_tokens: Number(perKToPerM(model.output_cost_per_1k_tokens)) || 0,
    peak_valley_enabled: toBool(model.peak_valley_enabled),
    cache_pricing_enabled: toBool(model.cache_pricing_enabled),
    peak_windows: model.peak_windows || '[]',
    input_cached_price_per_1k_tokens: Number(perKToPerM(model.input_cached_price_per_1k_tokens)) || 0,
    input_cached_cost_per_1k_tokens: Number(perKToPerM(model.input_cached_cost_per_1k_tokens)) || 0,
    peak_input_price_per_1k_tokens: Number(perKToPerM(model.peak_input_price_per_1k_tokens)) || 0,
    peak_input_cost_per_1k_tokens: Number(perKToPerM(model.peak_input_cost_per_1k_tokens)) || 0,
    peak_output_price_per_1k_tokens: Number(perKToPerM(model.peak_output_price_per_1k_tokens)) || 0,
    peak_output_cost_per_1k_tokens: Number(perKToPerM(model.peak_output_cost_per_1k_tokens)) || 0,
    peak_input_cached_price_per_1k_tokens: Number(perKToPerM(model.peak_input_cached_price_per_1k_tokens)) || 0,
    peak_input_cached_cost_per_1k_tokens: Number(perKToPerM(model.peak_input_cached_cost_per_1k_tokens)) || 0,
    valley_input_price_per_1k_tokens: Number(perKToPerM(model.valley_input_price_per_1k_tokens)) || 0,
    valley_input_cost_per_1k_tokens: Number(perKToPerM(model.valley_input_cost_per_1k_tokens)) || 0,
    valley_output_price_per_1k_tokens: Number(perKToPerM(model.valley_output_price_per_1k_tokens)) || 0,
    valley_output_cost_per_1k_tokens: Number(perKToPerM(model.valley_output_cost_per_1k_tokens)) || 0,
    valley_input_cached_price_per_1k_tokens: Number(perKToPerM(model.valley_input_cached_price_per_1k_tokens)) || 0,
    valley_input_cached_cost_per_1k_tokens: Number(perKToPerM(model.valley_input_cached_cost_per_1k_tokens)) || 0,
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
  if (!validatePeakWindows()) return
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
    // 表单内价格口径为 /M tokens：提交前统一 ÷1000 换算回 /1k，再转为字符串数字；开关转 'true'/'false'
    ;[...PRICING_FIELD_KEYS, ...FLAT_PRICE_FIELD_KEYS].forEach((key) => {
      payload[key] = stringifyPriceField(perMToPerK(payload[key]))
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
          <div class="overflow-x-auto rounded-lg border bg-white">
            <table class="w-full min-w-[1280px] text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">{{ t('admin.models.columns.provider') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.modelName') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.displayName') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.description') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.tier') }}</th>
                  <th class="p-3">
                    <a-tooltip :content="t('admin.models.columns.priceUnitHint')" position="bottom" mini>
                      <span class="cursor-help">{{ t('admin.models.columns.pricing') }}</span>
                    </a-tooltip>
                  </th>
                  <th class="p-3">{{ t('admin.models.columns.margin') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.capabilities') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.maxInputTokens') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.maxOutputTokens') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.status') }}</th>
                  <th class="p-3">{{ t('admin.models.columns.actions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!filteredModels.length">
                  <td class="p-6 text-center text-gray-400" colspan="12">{{ t('admin.models.empty.models') }}</td>
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
                    <div class="flex flex-col gap-1 text-xs">
                      <template v-if="pricingBlockOf(model).lines.length || pricingBlockOf(model).cached">
                        <div
                          v-for="line in pricingBlockOf(model).lines"
                          :key="line.label"
                          class="flex items-center gap-1 whitespace-nowrap"
                        >
                          <a-tag
                            size="small"
                            :color="line.tone === 'peak' ? 'purple' : line.tone === 'valley' ? 'gray' : 'arcoblue'"
                          >{{ line.label }}</a-tag>
                          <span class="text-gray-400">{{ t('admin.models.columns.sellAbbr') }}</span>
                          <code class="font-mono text-gray-700">{{ line.sell }}</code>
                          <span class="text-gray-400">{{ t('admin.models.columns.costAbbr') }}</span>
                          <code class="font-mono text-amber-600">{{ line.cost }}</code>
                        </div>
                        <div v-if="pricingBlockOf(model).cached" class="flex items-center gap-1 whitespace-nowrap">
                          <a-tag size="small" color="cyan">{{ t('admin.models.columns.cacheHit') }}</a-tag>
                          <span class="text-gray-400">{{ t('admin.models.columns.sellAbbr') }}</span>
                          <code class="font-mono text-gray-700">{{ pricingBlockOf(model).cached!.sell }}</code>
                          <span class="text-gray-400">{{ t('admin.models.columns.costAbbr') }}</span>
                          <code class="font-mono text-amber-600">{{ pricingBlockOf(model).cached!.cost }}</code>
                        </div>
                      </template>
                      <span v-else class="text-gray-400">-</span>
                    </div>
                  </td>
                  <td class="p-3 text-right">
                    <a-tooltip :content="t('admin.models.columns.marginHint')" position="left">
                      <a-tag :color="marginOf(model) >= 0 ? 'green' : 'red'">{{ marginOf(model) >= 0 ? '+' : '' }}{{ marginOf(model).toFixed(0) }}</a-tag>
                    </a-tooltip>
                  </td>
                  <td class="p-3">
                    <a-tag v-for="cap in model.capabilities" :key="cap" size="small" color="arcoblue">{{ cap }}</a-tag>
                    <span v-if="!model.capabilities?.length" class="text-gray-400">-</span>
                  </td>
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
        <div v-if="!modelForm.peak_valley_enabled" class="form-group">
          <h4 class="form-group-title">{{ t('admin.models.groups.sellPrice') }}</h4>
          <p class="form-group-desc">{{ t('admin.models.groups.sellPriceDesc') }}</p>
          <div class="pricing-grid">
            <div class="pricing-cell">
              <div class="pricing-cell-label">{{ t('admin.models.fields.inputPrice') }}</div>
              <a-input-number v-model="modelForm.input_price_per_1k_tokens" name="input_price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.modelModal.placeholders.inputPrice')" class="w-full" />
            </div>
            <div class="pricing-cell">
              <div class="pricing-cell-label">{{ t('admin.models.fields.inputCost') }}</div>
              <a-input-number v-model="modelForm.input_cost_per_1k_tokens" name="input_cost_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.modelModal.placeholders.inputCost')" class="w-full" />
            </div>
            <div class="pricing-cell">
              <div class="pricing-cell-label">{{ t('admin.models.fields.outputPrice') }}</div>
              <a-input-number v-model="modelForm.output_price_per_1k_tokens" name="output_price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.modelModal.placeholders.outputPrice')" class="w-full" />
            </div>
            <div class="pricing-cell">
              <div class="pricing-cell-label">{{ t('admin.models.fields.outputCost') }}</div>
              <a-input-number v-model="modelForm.output_cost_per_1k_tokens" name="output_cost_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.modelModal.placeholders.outputCost')" class="w-full" />
            </div>
          </div>
          <template v-if="modelForm.cache_pricing_enabled">
            <div class="pricing-grid">
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.pricingMode.cachedInputPriceLabel') }}</div>
                <a-input-number v-model="modelForm.input_cached_price_per_1k_tokens" name="input_cached_price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.cachedInputPricePlaceholder')" class="w-full" />
              </div>
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.pricingMode.cachedInputCostLabel') }}</div>
                <a-input-number v-model="modelForm.input_cached_cost_per_1k_tokens" name="input_cached_cost_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.cachedInputCostPlaceholder')" class="w-full" />
              </div>
            </div>
          </template>
        </div>
        <a-alert v-if="modelForm.peak_valley_enabled" type="info" show-icon class="mb-2">
          {{ t('admin.models.groups.peakValleyInlineHint') }}
        </a-alert>
        <a-alert v-if="marginPreview !== null" :type="marginPreview >= 0 ? 'success' : 'warning'" show-icon>
          <a-tooltip :content="t('admin.models.groups.marginTooltip')">
            <span>{{ t('admin.models.groups.marginPreview', { margin: formatSigned(marginPreview), percent: formatSigned(marginPercent) }) }}</span>
          </a-tooltip>
        </a-alert>
        <div class="form-group">
          <h4 class="form-group-title">{{ t('admin.models.pricingMode.title') }}</h4>
          <p class="form-group-desc">{{ t('admin.models.pricingMode.desc') }}</p>
          <a-form-item :label="t('admin.models.pricingMode.radioLabel')" field="peak_valley_enabled">
            <a-radio-group v-model="modelForm.peak_valley_enabled">
              <a-radio :value="false">{{ t('admin.models.pricingMode.radio.regular') }}</a-radio>
              <a-radio :value="true">{{ t('admin.models.pricingMode.radio.peakValley') }}</a-radio>
            </a-radio-group>
          </a-form-item>
          <a-form-item :label="t('admin.models.pricingMode.cacheSplit')" :tooltip="t('admin.models.pricingMode.cacheSplitTooltip')" field="cache_pricing_enabled">
            <a-switch v-model="modelForm.cache_pricing_enabled" class="cache-split-switch" />
          </a-form-item>

          <template v-if="modelForm.peak_valley_enabled">
            <a-alert v-if="peakWindowsWarnings.length" type="warning" show-icon class="mb-3">
              {{ t('admin.models.pricingMode.windowsParseError') }}
            </a-alert>
            <a-form-item :label="t('admin.models.pricingMode.windowsLabel')" field="peak_windows">
              <div class="w-full rounded border border-dashed border-gray-300 p-3">
                <p class="mb-2 text-xs text-gray-500">{{ t('admin.models.pricingMode.peakWindowsTip') }}</p>
                <div v-if="peakWindowRows.length === 0" class="py-3 text-center text-xs text-gray-400">
                  {{ t('admin.models.pricingMode.emptyWindows') }}
                </div>
                <div v-else class="space-y-2">
                  <div v-for="(row, index) in peakWindowRows" :key="index" class="window-row flex flex-wrap items-center gap-2">
                    <span class="w-16 shrink-0 text-xs text-gray-500">{{ t('admin.models.pricingMode.daysLabel') }}</span>
                    <div class="w-48">
                      <a-select
                        v-model="row.days"
                        multiple
                        :placeholder="t('admin.models.pricingMode.daysPlaceholder')"
                        size="small"
                        class="w-full"
                      >
                        <a-option v-for="day in WEEKDAY_OPTIONS" :key="day.value" :value="day.value">{{ t(`admin.models.pricingMode.weekdays.${day.value}`) }}</a-option>
                      </a-select>
                    </div>
                    <span class="text-xs text-gray-500">{{ t('admin.models.pricingMode.startLabel') }}</span>
                    <div class="w-28">
                      <a-time-picker v-model="row.start" format="HH:mm" size="small" class="w-full" />
                    </div>
                    <span class="text-xs text-gray-500">{{ t('admin.models.pricingMode.endLabel') }}</span>
                    <div class="w-28">
                      <a-time-picker v-model="row.end" format="HH:mm" size="small" class="w-full" />
                    </div>
                    <a-button type="text" size="small" status="danger" @click="removePeakWindow(index)">
                      {{ t('admin.models.pricingMode.removeWindow') }}
                    </a-button>
                  </div>
                </div>
                <div class="mt-2">
                  <a-button size="small" type="outline" @click="addPeakWindow">
                    {{ t('admin.models.pricingMode.addWindow') }}
                  </a-button>
                  <a-button size="small" class="ml-2" @click="applyProviderDefaultWindows">
                    {{ t('admin.models.pricingMode.providerDefaults') }}
                  </a-button>
                </div>
              </div>
            </a-form-item>
            <h5 class="form-subgroup-title">{{ t('admin.models.pricingMode.peakTitle') }}</h5>
            <div class="pricing-grid">
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.fields.inputPrice') }}</div>
                <a-input-number v-model="modelForm.peak_input_price_per_1k_tokens" name="peak_input_price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.peakInputPricePlaceholder')" class="w-full" />
              </div>
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.fields.inputCost') }}</div>
                <a-input-number v-model="modelForm.peak_input_cost_per_1k_tokens" name="peak_input_cost_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.peakInputCostPlaceholder')" class="w-full" />
              </div>
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.fields.outputPrice') }}</div>
                <a-input-number v-model="modelForm.peak_output_price_per_1k_tokens" name="peak_output_price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.peakOutputPricePlaceholder')" class="w-full" />
              </div>
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.fields.outputCost') }}</div>
                <a-input-number v-model="modelForm.peak_output_cost_per_1k_tokens" name="peak_output_cost_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.peakOutputCostPlaceholder')" class="w-full" />
              </div>
            </div>
            <div v-if="modelForm.cache_pricing_enabled" class="pricing-grid-2">
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.pricingMode.cachedInputPriceLabel') }}</div>
                <a-input-number v-model="modelForm.peak_input_cached_price_per_1k_tokens" name="peak_input_cached_price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.peakCachedPricePlaceholder')" class="w-full" />
              </div>
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.pricingMode.cachedInputCostLabel') }}</div>
                <a-input-number v-model="modelForm.peak_input_cached_cost_per_1k_tokens" name="peak_input_cached_cost_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.peakCachedCostPlaceholder')" class="w-full" />
              </div>
            </div>
            <h5 class="form-subgroup-title">{{ t('admin.models.pricingMode.valleyTitle') }}</h5>
            <div class="pricing-grid">
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.fields.inputPrice') }}</div>
                <a-input-number v-model="modelForm.valley_input_price_per_1k_tokens" name="valley_input_price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.valleyInputPricePlaceholder')" class="w-full" />
              </div>
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.fields.inputCost') }}</div>
                <a-input-number v-model="modelForm.valley_input_cost_per_1k_tokens" name="valley_input_cost_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.valleyInputCostPlaceholder')" class="w-full" />
              </div>
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.fields.outputPrice') }}</div>
                <a-input-number v-model="modelForm.valley_output_price_per_1k_tokens" name="valley_output_price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.valleyOutputPricePlaceholder')" class="w-full" />
              </div>
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.fields.outputCost') }}</div>
                <a-input-number v-model="modelForm.valley_output_cost_per_1k_tokens" name="valley_output_cost_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.valleyOutputCostPlaceholder')" class="w-full" />
              </div>
            </div>
            <div v-if="modelForm.cache_pricing_enabled" class="pricing-grid-2">
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.pricingMode.cachedInputPriceLabel') }}</div>
                <a-input-number v-model="modelForm.valley_input_cached_price_per_1k_tokens" name="valley_input_cached_price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.valleyCachedPricePlaceholder')" class="w-full" />
              </div>
              <div class="pricing-cell">
                <div class="pricing-cell-label">{{ t('admin.models.pricingMode.cachedInputCostLabel') }}</div>
                <a-input-number v-model="modelForm.valley_input_cached_cost_per_1k_tokens" name="valley_input_cached_cost_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.pricingMode.valleyCachedCostPlaceholder')" class="w-full" />
              </div>
            </div>
          </template>
          <a-button type="outline" class="mt-2" :loading="pricingPreviewLoading" @click="openPricingSuggest">{{ t('admin.models.pricingMode.applySuggest') }}</a-button>
        </div>
        <div v-if="!modelForm.peak_valley_enabled" class="form-group">
          <h4 class="form-group-title">{{ t('admin.models.groups.fallback') }}</h4>
          <p class="form-group-desc">{{ t('admin.models.groups.fallbackDesc') }}</p>
          <a-alert v-if="splitSellPriceActive" type="info" show-icon class="mb-2">{{ t('admin.models.groups.fallbackInactiveAlert') }}</a-alert>
          <a-form-item :label="t('admin.models.fields.pricePer1k')" field="price_per_1k_tokens">
            <a-input-number v-model="modelForm.price_per_1k_tokens" name="price_per_1k_tokens" :min="0" :precision="6" :placeholder="t('admin.models.modelModal.placeholders.price')" class="w-full" />
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
      v-model:visible="pricingPreviewVisible"
      :title="t('admin.models.pricingMode.previewTitle')"
      :ok-loading="pricingPreviewLoading"
      :mask-closable="false"
      hide-cancel
    >
      <a-alert v-if="suggestWarnings.length" type="warning" show-icon class="mb-3">
        <div class="space-y-1">
          <p v-for="(warning, index) in suggestWarnings" :key="index" class="text-xs">{{ warning }}</p>
        </div>
      </a-alert>
      <a-spin :loading="pricingPreviewLoading" class="block">
        <div class="overflow-hidden rounded border">
          <table class="w-full text-left text-sm">
            <thead class="bg-gray-50 text-gray-500">
              <tr>
                <th class="p-2">{{ t('admin.models.pricingMode.suggestItem') }}</th>
                <th class="p-2">{{ t('admin.models.pricingMode.suggestCurrent') }}</th>
                <th class="p-2">{{ t('admin.models.pricingMode.suggestSuggested') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in suggestRows" :key="row.key" class="border-t">
                <td class="p-2 text-xs">{{ row.label }}</td>
                <td class="p-2 font-mono text-xs text-gray-400">{{ row.current }}</td>
                <td class="p-2 font-mono text-xs font-medium text-green-600">{{ row.suggested }}</td>
              </tr>
              <tr v-if="!suggestRows.length">
                <td class="p-3 text-center text-xs text-gray-400" colspan="3">{{ t('admin.models.pricingMode.suggestEmpty') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </a-spin>
      <template #footer>
        <div class="flex justify-end gap-2">
          <a-button :disabled="pricingPreviewLoading" @click="cancelPricingSuggest">{{ t('admin.models.pricingMode.cancelBtn') }}</a-button>
          <a-button type="primary" :loading="pricingPreviewLoading" @click="applyPricingSuggest">{{ t('admin.models.pricingMode.applyBtn') }}</a-button>
        </div>
      </template>
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

.pricing-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px 12px;
  margin-bottom: 8px;
}

.pricing-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
  margin-bottom: 8px;
}

.pricing-grid:last-child {
  margin-bottom: 0;
}

.pricing-cell {
  min-width: 0;
}

.pricing-cell-label {
  margin-bottom: 2px;
  font-size: 12px;
  line-height: 18px;
  color: #86909c;
  overflow-wrap: break-word;
  word-break: break-all;
}

@media (max-width: 768px) {
  .pricing-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
