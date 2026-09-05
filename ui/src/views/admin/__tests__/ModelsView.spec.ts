import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ModelsView from '@/views/admin/ModelsView.vue'
import { createModel, updateModel } from '@/services/admin-model-pool'

const mocks = vi.hoisted(() => ({
  listModels: vi.fn(),
  listModelKeys: vi.fn(),
  listTierPolicies: vi.fn(),
  listProviderOptions: vi.fn(),
  getBillingConfig: vi.fn(),
  suggestSellPrices: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
  updateModel: vi.fn(),
}))

vi.mock('@/services/admin-model-pool', () => ({
  listModels: mocks.listModels,
  listModelKeys: mocks.listModelKeys,
  listTierPolicies: mocks.listTierPolicies,
  createModel: vi.fn(),
  updateModel: mocks.updateModel,
  deleteModel: vi.fn(),
  setModelStatus: vi.fn(),
  createModelKey: vi.fn(),
  deleteModelKey: vi.fn(),
  setModelKeyStatus: vi.fn(),
  createTierPolicy: vi.fn(),
  updateTierPolicy: vi.fn(),
  deleteTierPolicy: vi.fn(),
}))

vi.mock('@/services/admin-model-providers', () => ({
  listProviderOptions: mocks.listProviderOptions,
}))

vi.mock('@/services/admin-billing', () => ({
  getBillingConfig: mocks.getBillingConfig,
}))

vi.mock('@/services/admin-pricing-suggest', () => ({
  suggestSellPrices: mocks.suggestSellPrices,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
  },
}))

const inputStub = {
  props: ['modelValue', 'placeholder', 'disabled'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" :placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const inputNumberStub = {
  props: ['modelValue', 'placeholder', 'name'],
  emits: ['update:modelValue'],
  template: '<input type="number" :name="name" :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', Number($event.target.value))" />',
}

const textareaStub = {
  props: ['modelValue', 'placeholder', 'name'],
  emits: ['update:modelValue'],
  template: '<textarea :name="name" :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const buttonStub = {
  props: ['loading', 'disabled', 'type', 'status', 'size'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading || disabled" @click="$emit(\'click\')"><slot /></button>',
}

const radioGroupStub = {
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: `
    <div class="price-mode-switch">
      <input
        type="checkbox"
        :checked="Boolean(modelValue)"
        @change="onToggle"
        @input="onToggle"
      />
      <slot />
    </div>
  `,
  methods: {
    onToggle(e: Event) {
      const v = (e.target as HTMLInputElement).checked
      ;(this as unknown as { $emit: (n: string, v: boolean) => void }).$emit('update:modelValue', v)
      ;(this as unknown as { $emit: (n: string, v: boolean) => void }).$emit('change', v)
    },
  },
}

const radioStub = {
  props: ['value'],
  template: '<span class="arco-radio" :data-value="String(value)"><slot /></span>',
}

const spanSlotStub = {
  template: '<span><slot /></span>',
}

const divSlotStub = {
  template: '<div><slot /></div>',
}

const timePickerStub = {
  props: ['modelValue', 'format', 'size'],
  emits: ['update:modelValue'],
  template: '<input :name="`time:${modelValue}`" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const tagStub = {
  props: ['color', 'size'],
  template: '<span class="arco-tag" :data-color="color"><slot /></span>',
}

const modalStub = {
  props: ['visible', 'title', 'okLoading', 'maskClosable', 'hideCancel'],
  emits: ['ok', 'cancel', 'update:visible'],
  template: `
    <div v-if="visible" class="a-modal">
      <h3 v-if="title" class="modal-title">{{ title }}</h3>
      <slot />
      <slot name="footer">
        <button class="modal-ok" type="button" @click="$emit('ok')">OK</button>
      </slot>
    </div>
  `,
}

const modelRecords = [
  {
    id: 'model-1',
    provider: 'openai',
    model_name: 'gpt-test',
    display_name: 'GPT Test',
    description: '',
    tier: '1',
    capabilities: [],
    price_per_1k_tokens: '0.000000',
    input_price_per_1k_tokens: '1.200000',
    output_price_per_1k_tokens: '4.800000',
    input_cost_per_1k_tokens: '0.009000',
    output_cost_per_1k_tokens: '0.036000',
    max_tokens: 131072,
    max_input_tokens: 131072,
    max_output_tokens: 4096,
    status: 'active',
    model_type: 'chat',
  },
  {
    id: 'model-2',
    provider: 'openai',
    model_name: 'losing-model',
    display_name: 'Losing',
    description: '',
    tier: '2',
    capabilities: [],
    price_per_1k_tokens: '0.000000',
    input_price_per_1k_tokens: '0.010000',
    output_price_per_1k_tokens: '0.010000',
    input_cost_per_1k_tokens: '0.500000',
    output_cost_per_1k_tokens: '0.500000',
    max_tokens: 8192,
    max_input_tokens: 8192,
    max_output_tokens: 1024,
    status: 'active',
    model_type: 'chat',
  },
]

const defaultProviderOptions = [
  { id: 'p1', name: 'openai', label: 'OpenAI', description: '', default_base_url: '', supported_model_types: ['chat'] },
]

const renderView = async (models: Record<string, unknown>[] = modelRecords as Record<string, unknown>[], providerOptions = defaultProviderOptions) => {
  mocks.listModels.mockResolvedValue({ data: { list: models } })
  mocks.listModelKeys.mockResolvedValue({ data: { list: [] } })
  mocks.listTierPolicies.mockResolvedValue({ data: { list: [] } })
  mocks.listProviderOptions.mockResolvedValue({
    data: { options: providerOptions },
  })
  mocks.getBillingConfig.mockResolvedValue({ code: 'credits_per_yuan', value_numeric: 100 })
  const wrapper = mount(ModelsView, {
    global: {
      stubs: {
        'a-input': inputStub,
        'a-input-number': inputNumberStub,
        'a-input-tag': inputStub,
        'a-textarea': textareaStub,
        'a-button': buttonStub,
        'a-radio-group': radioGroupStub,
        'a-radio': radioStub,
        'a-select': divSlotStub,
        'a-option': spanSlotStub,
        'a-time-picker': timePickerStub,
        'a-tabs': divSlotStub,
        'a-tab-pane': divSlotStub,
        'a-spin': divSlotStub,
        'a-form': divSlotStub,
        'a-form-item': divSlotStub,
        'a-modal': modalStub,
        'a-tag': tagStub,
        'a-tooltip': spanSlotStub,
        'a-alert': divSlotStub,
        'a-space': divSlotStub,
        'a-range-picker': divSlotStub,
        'a-switch': inputStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

const buttonByText = (wrapper: Awaited<ReturnType<typeof renderView>>, text: string) => {
  const found = wrapper.findAll('button').find((node) => node.text().includes(text))
  if (!found) {
    throw new Error(`button not found: ${text}`)
  }
  return found
}

describe('ModelsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows real-time margin preview while editing sell price and cost base', async () => {
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()

    const priceInputs = wrapper.findAll('input').filter((node) => node.attributes('placeholder') === '0（留空则回退单价）')
    const costInputs = wrapper.findAll('input').filter((node) => node.attributes('placeholder') === '0（元/M）')
    expect(priceInputs).toHaveLength(2)
    expect(costInputs).toHaveLength(2)

    // 表单为 /M 口径：售价 1200/4800（元/M），成本 9/36（元/M）
    await priceInputs[0].setValue('1200')
    await priceInputs[1].setValue('4800')
    await costInputs[0].setValue('9')
    await costInputs[1].setValue('36')
    await nextTick()

    // 售价与成本同为 /M 元：sell = 1200*3 + 4800 = 8400；cost = 9*3 + 36 = 63；毛利 8337 元
    // 毛利率 = 8337 ÷ 8400 ≈ 99.25% → 显示 +99
    expect(wrapper.text()).toContain('参考毛利率：+99%')
  })

  it('renders positive margin as green tag and negative margin as red tag in the table', async () => {
    const wrapper = await renderView()

    const redTags = wrapper.findAll('[data-color="red"]')
    const greenTags = wrapper.findAll('[data-color="green"]')
    expect(redTags.length).toBeGreaterThan(0)
    expect(greenTags.length).toBeGreaterThan(0)
    expect(redTags[0]?.text()).toContain('-')
    expect(greenTags[0]?.text()).toContain('+')

    expect(wrapper.text()).toContain('售价')
    expect(wrapper.text()).toContain('成本')
  })

  it('backfills cost base fields when editing a model', async () => {
    const wrapper = await renderView()

    await buttonByText(wrapper, '编辑').trigger('click')
    await nextTick()

    const costInputs = wrapper.findAll('input').filter((node) => node.attributes('placeholder') === '0（元/M）')
    expect(costInputs).toHaveLength(2)
    // 回填值已从 /1k 换算为 /M：0.009 → 9，0.036 → 36
    expect((costInputs[0].element as HTMLInputElement).value).toBe('9')
    expect((costInputs[1].element as HTMLInputElement).value).toBe('36')
  })

  it('toggling peak-valley shows peak/valley price groups and hides them when off', async () => {
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()

    expect(wrapper.find('input[name="peak_input_price_per_1k_tokens"]').exists()).toBe(false)
    expect(wrapper.find('input[name="valley_input_price_per_1k_tokens"]').exists()).toBe(false)
    expect(wrapper.find('.window-row').exists()).toBe(false)

    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    expect(wrapper.find('.window-row').exists()).toBe(true)
    expect(wrapper.find('textarea[name="peak_windows"]').exists()).toBe(false)
    expect(wrapper.find('input[name="peak_input_price_per_1k_tokens"]').exists()).toBe(true)
    expect(wrapper.find('input[name="peak_output_price_per_1k_tokens"]').exists()).toBe(true)
    expect(wrapper.find('input[name="valley_input_price_per_1k_tokens"]').exists()).toBe(true)
    expect(wrapper.find('input[name="valley_output_price_per_1k_tokens"]').exists()).toBe(true)
  })

  it('shows cached price inputs only when cache split is enabled without peak-valley', async () => {
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()
    expect(wrapper.find('input[name="input_cached_price_per_1k_tokens"]').exists()).toBe(false)

    await wrapper.find('input.cache-split-switch').setValue(true)
    await nextTick()

    expect(wrapper.find('input[name="input_cached_price_per_1k_tokens"]').exists()).toBe(true)
    expect(wrapper.find('input[name="input_cached_cost_per_1k_tokens"]').exists()).toBe(true)
  })

  it('binds the cached-input cost box to the cost field (not the price field)', async () => {
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()
    await wrapper.find('input.cache-split-switch').setValue(true)
    await nextTick()

    const priceInput = wrapper.find('input[name="input_cached_price_per_1k_tokens"]')
    const costInput = wrapper.find('input[name="input_cached_cost_per_1k_tokens"]')
    expect(priceInput.exists()).toBe(true)
    expect(costInput.exists()).toBe(true)

    await costInput.setValue('0.321000')
    await nextTick()

    const state = (wrapper.vm as unknown as { modelForm: Record<string, unknown> }).modelForm
    expect(state.input_cached_cost_per_1k_tokens).toBe(0.321)
    expect(state.input_cached_price_per_1k_tokens).not.toBe(0.321)
  })

  it('fills provider default peak windows for siliconflow with two daily windows', async () => {
    const siliconflowOptions = [
      { id: 'sf', name: 'SiliconFlow', label: 'SiliconFlow', description: '', default_base_url: '', supported_model_types: ['chat'] },
    ]
    const wrapper = await renderView(modelRecords, siliconflowOptions)

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()
    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    const state = (wrapper.vm as unknown as { modelForm: { peak_windows: string } }).modelForm
    const windows = JSON.parse(state.peak_windows)
    expect(windows).toHaveLength(2)
    expect(windows[0]).toEqual({ days: '0,1,2,3,4,5,6', start: '00:00', end: '02:00' })
    expect(windows[1]).toEqual({ days: '0,1,2,3,4,5,6', start: '08:00', end: '24:00' })
  })

  it('does not overwrite existing peak windows when peak-valley is toggled on', async () => {
    const existing = [{ days: '0-2', start: '20:00', end: '23:00' }]
    const wrapper = await renderView([{ ...modelRecords[0], peak_valley_enabled: false, peak_windows: JSON.stringify(existing) }])

    await buttonByText(wrapper, '编辑').trigger('click')
    await nextTick()
    const state = (wrapper.vm as unknown as { modelForm: { peak_windows: string } }).modelForm
    expect(state.peak_windows).toBe(JSON.stringify(existing))

    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    expect(state.peak_windows).toBe(JSON.stringify(existing))
    expect(wrapper.findAll('.window-row')).toHaveLength(1)
  })

  it('adds and removes peak window rows which sync back to the peak_windows JSON', async () => {
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()
    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    const state = (wrapper.vm as unknown as { modelForm: { peak_windows: string } }).modelForm
    expect(JSON.parse(state.peak_windows)).toHaveLength(2)

    await buttonByText(wrapper, '添加时段').trigger('click')
    await nextTick()
    let windows = JSON.parse(state.peak_windows) as { days: string; start: string; end: string }[]
    expect(windows).toHaveLength(3)
    expect(windows[2]).toEqual({ days: '1,2,3,4,5', start: '09:00', end: '12:00' })

    await buttonByText(wrapper, '添加时段').trigger('click')
    await nextTick()
    windows = JSON.parse(state.peak_windows) as { days: string; start: string; end: string }[]
    expect(windows).toHaveLength(4)
    expect(windows[3]).toEqual({ days: '1,2,3,4,5', start: '09:00', end: '12:00' })

    const removeButtons = wrapper.findAll('button').filter((node) => node.text().includes('删除'))
    await removeButtons[removeButtons.length - 1].trigger('click')
    await nextTick()
    windows = JSON.parse(state.peak_windows) as { days: string; start: string; end: string }[]
    expect(windows).toHaveLength(3)
  })

  it('shows a parse warning and treats unparseable windows as empty', async () => {
    const wrapper = await renderView([{ ...modelRecords[0], peak_valley_enabled: false, peak_windows: '{broken' }])

    await buttonByText(wrapper, '编辑').trigger('click')
    await nextTick()
    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    expect(wrapper.text()).toContain('峰谷时段格式无法解析，已按空处理')
    const state = (wrapper.vm as unknown as { modelForm: { peak_windows: string } }).modelForm
    expect(JSON.parse(state.peak_windows)).toEqual([])
    // 空窗口时显示空态文案（无窗口行）
    expect(wrapper.findAll('.window-row')).toHaveLength(0)
  })

  it('previews suggestions first and only fills the form on confirm', async () => {
    mocks.suggestSellPrices.mockResolvedValue({
      suggestions: { peak_input_price_per_1k_tokens: '1.250000', valley_input_price_per_1k_tokens: '0.800000' },
      applied: false,
      warnings: ['峰值时段与低谷时段存在重叠，已自动按默认时段计算'],
      peak_input_price_per_1k_tokens: '1.250000',
      valley_input_price_per_1k_tokens: '0.800000',
    })
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()
    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    await buttonByText(wrapper, '自动定价助手').trigger('click')
    await flushPromises()

    expect(mocks.suggestSellPrices).toHaveBeenCalledWith(
      expect.objectContaining({ peak_valley_enabled: true, cache_pricing_enabled: false }),
      0.3,
    )
    expect(wrapper.text()).toContain('自动定价建议预览')
    // 后端建议为 /1k（1.25/0.8）→ 预览按 /M 展示（1250/800）
    expect(wrapper.text()).toContain('1250')
    expect(wrapper.text()).toContain('800')
    expect(wrapper.text()).toContain('重叠')

    // 未应用前，表单字段保持原值（新建默认 /M 口径 0）
    const state = (wrapper.vm as unknown as { modelForm: Record<string, number> }).modelForm
    expect(state.peak_input_price_per_1k_tokens).toBe(0)
    expect(state.valley_input_price_per_1k_tokens).toBe(0)

    await buttonByText(wrapper, '应用并填入表单').trigger('click')
    await nextTick()

    expect(state.peak_input_price_per_1k_tokens).toBe(1250)
    expect(state.valley_input_price_per_1k_tokens).toBe(800)
    expect(mocks.messageSuccess).toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('自动定价建议预览')
  })

  it('keeps the form unchanged when suggestion preview is cancelled', async () => {
    mocks.suggestSellPrices.mockResolvedValue({
      suggestions: { peak_input_price_per_1k_tokens: '9.900000' },
      applied: false,
      warnings: [],
      peak_input_price_per_1k_tokens: '9.900000',
    })
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()
    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    await buttonByText(wrapper, '自动定价助手').trigger('click')
    await flushPromises()

    const state = (wrapper.vm as unknown as { modelForm: Record<string, number> }).modelForm
    expect(state.peak_input_price_per_1k_tokens).toBe(0)

    await buttonByText(wrapper, '取消').trigger('click')
    await nextTick()

    expect(state.peak_input_price_per_1k_tokens).toBe(0)
    expect(wrapper.text()).not.toContain('自动定价建议预览')
    expect(mocks.messageSuccess).not.toHaveBeenCalled()
  })

  it('falls back to the legacy top-level suggestion keys when suggestions is empty', async () => {
    mocks.suggestSellPrices.mockResolvedValue({
      suggestions: {},
      applied: false,
      warnings: [],
      valley_input_price_per_1k_tokens: '0.660000',
    })
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()
    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    await buttonByText(wrapper, '自动定价助手').trigger('click')
    await flushPromises()

    // 后端 /1k 建议 0.66 → 预览 /M 显示 660
    expect(wrapper.text()).toContain('660')

    await buttonByText(wrapper, '应用并填入表单').trigger('click')
    await nextTick()

    const state = (wrapper.vm as unknown as { modelForm: Record<string, number> }).modelForm
    expect(state.valley_input_price_per_1k_tokens).toBe(660)
  })

  it('shows a peak/valley sell summary in the pricing column when peak-valley is enabled', async () => {
    const pvRecords = [
      {
        ...modelRecords[0],
        peak_valley_enabled: true,
        cache_pricing_enabled: true,
        peak_windows: JSON.stringify([{ days: '0-4', start: '09:00', end: '12:00' }]),
        peak_input_price_per_1k_tokens: '0.390000',
        peak_output_price_per_1k_tokens: '0.900000',
        valley_input_price_per_1k_tokens: '0.200000',
        valley_output_price_per_1k_tokens: '0.500000',
      },
    ]
    const wrapper = await renderView(pvRecords)

    const row = wrapper.find('tbody tr')
    expect(row.text()).toContain('峰')
    expect(row.text()).toContain('谷')
    // 列表 /M 口径展示：0.39/0.9/0.2/0.5（/1k） → 390/900/200/500
    expect(row.text()).toContain('390')
    expect(row.text()).toContain('900')
    expect(row.text()).toContain('200')
    expect(row.text()).toContain('500')
    expect(row.text()).toContain('缓存')
  })

  it('lists loss/official pricing bound errors in an alert when save is rejected', async () => {
    const saveError = new Error('save failed') as Error & { response?: unknown }
    saveError.response = {
      data: { message: '峰档售价低于成本，存在亏损风险；谷档售价高于官方定价' },
    }
    vi.mocked(createModel).mockRejectedValueOnce(saveError)
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()
    await wrapper.find('.modal-ok').trigger('click')
    await flushPromises()

    expect(mocks.messageError).toHaveBeenCalled()
    expect(wrapper.text()).toContain('亏损风险')
    expect(wrapper.text()).toContain('官方定价')
  })

  it('backfills pricing fields in /M as numbers when editing a model', async () => {
    const wrapper = await renderView()

    await buttonByText(wrapper, '编辑').trigger('click')
    await nextTick()

    const state = (wrapper.vm as unknown as { modelForm: Record<string, number> }).modelForm
    // record /1k 值 ×1000 回填为 /M，且为 number 语义（a-input-number 可显示）
    expect(state.input_price_per_1k_tokens).toBe(1200)
    expect(state.output_price_per_1k_tokens).toBe(4800)
    expect(state.input_cost_per_1k_tokens).toBe(9)
    expect(state.output_cost_per_1k_tokens).toBe(36)
    expect(state.price_per_1k_tokens).toBe(0)
    // 真实输入框能拿到 number 回显（value 为数字字符串而非空白）
    expect((wrapper.find('input[name="input_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('1200')
    expect((wrapper.find('input[name="output_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('4800')
    expect((wrapper.find('input[name="input_cost_per_1k_tokens"]').element as HTMLInputElement).value).toBe('9')
    expect((wrapper.find('input[name="output_cost_per_1k_tokens"]').element as HTMLInputElement).value).toBe('36')
    // 顶部不出现峰谷空框
    expect(wrapper.find('input[name="peak_input_price_per_1k_tokens"]').exists()).toBe(false)
  })

  it('divides /M inputs back to /1k in the submit payload', async () => {
    mocks.updateModel.mockResolvedValue({})
    const wrapper = await renderView()

    await buttonByText(wrapper, '编辑').trigger('click')
    await nextTick()

    const state = (wrapper.vm as unknown as { modelForm: Record<string, number> }).modelForm
    // 用户改售价为 1200（元/M）
    state.input_price_per_1k_tokens = 1200
    await nextTick()

    await wrapper.find('.modal-ok').trigger('click')
    await flushPromises()

    expect(mocks.updateModel).toHaveBeenCalledTimes(1)
    const payload = mocks.updateModel.mock.calls[0][1] as Record<string, unknown>
    // payload 内价格字段应 ÷1000 回 /1k 六位小数
    expect(payload.input_price_per_1k_tokens).toBe('1.200000')
    expect(payload.output_price_per_1k_tokens).toBe('4.800000')
    expect(payload.input_cost_per_1k_tokens).toBe('0.009000')
    expect(payload.output_cost_per_1k_tokens).toBe('0.036000')
    expect(payload.price_per_1k_tokens).toBe('0.000000')
  })

  it('applies pricing suggestions into the form in /M', async () => {
    mocks.suggestSellPrices.mockResolvedValue({
      suggestions: { peak_input_price_per_1k_tokens: '3.000000', peak_output_price_per_1k_tokens: '9.000000' },
      applied: false,
      warnings: [],
    })
    const wrapper = await renderView()

    await buttonByText(wrapper, '编辑').trigger('click')
    await nextTick()
    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    await buttonByText(wrapper, '自动定价助手').trigger('click')
    await flushPromises()
    await buttonByText(wrapper, '应用并填入表单').trigger('click')
    await nextTick()

    const state = (wrapper.vm as unknown as { modelForm: Record<string, number> }).modelForm
    // 后端 /1k 建议 ×1000 写入表单（/M），number 语义
    expect(state.peak_input_price_per_1k_tokens).toBe(3000)
    expect(state.peak_output_price_per_1k_tokens).toBe(9000)
    expect((wrapper.find('input[name="peak_input_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('3000')
  })

  it('shows peak/valley cost fields for a peak/valley-enabled model so cost base is not blank', async () => {
    const pvCostRecord = [
      {
        ...modelRecords[0],
        peak_valley_enabled: true,
        cache_pricing_enabled: false,
        peak_windows: JSON.stringify([{ days: '0-4', start: '09:00', end: '12:00' }]),
        peak_input_price_per_1k_tokens: '1.200000',
        peak_output_price_per_1k_tokens: '4.800000',
        peak_input_cost_per_1k_tokens: '0.500000',
        peak_output_cost_per_1k_tokens: '2.000000',
        valley_input_price_per_1k_tokens: '0.800000',
        valley_output_price_per_1k_tokens: '3.200000',
        valley_input_cost_per_1k_tokens: '0.400000',
        valley_output_cost_per_1k_tokens: '1.600000',
      },
    ]
    const wrapper = await renderView(pvCostRecord)

    await buttonByText(wrapper, '编辑').trigger('click')
    await nextTick()

    const state = (wrapper.vm as unknown as { modelForm: Record<string, number> }).modelForm
    // 峰/谷成本回填为 /M number（0.5/2.0 元/1k → 500/2000 元/M）
    expect(state.peak_input_cost_per_1k_tokens).toBe(500)
    expect(state.peak_output_cost_per_1k_tokens).toBe(2000)
    expect(state.valley_input_cost_per_1k_tokens).toBe(400)
    expect(state.valley_output_cost_per_1k_tokens).toBe(1600)
    // 峰档售价回填为 /M
    expect(state.peak_input_price_per_1k_tokens).toBe(1200)
    expect(state.peak_output_price_per_1k_tokens).toBe(4800)

    // 弹窗内渲染出峰/谷成本输入框与具体值（number 回显非空白），顶部无 flat 空框
    expect(wrapper.find('input[name="peak_input_price_per_1k_tokens"]').exists()).toBe(true)
    expect((wrapper.find('input[name="peak_input_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('1200')
    expect((wrapper.find('input[name="peak_output_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('4800')
    expect((wrapper.find('input[name="peak_input_cost_per_1k_tokens"]').element as HTMLInputElement).value).toBe('500')
    expect((wrapper.find('input[name="peak_output_cost_per_1k_tokens"]').element as HTMLInputElement).value).toBe('2000')
    expect((wrapper.find('input[name="valley_input_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('800')
    expect((wrapper.find('input[name="valley_output_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('3200')
    expect((wrapper.find('input[name="valley_input_cost_per_1k_tokens"]').element as HTMLInputElement).value).toBe('400')
    expect((wrapper.find('input[name="valley_output_cost_per_1k_tokens"]').element as HTMLInputElement).value).toBe('1600')

    // marginPreview 峰谷感知：不再因 flat 列为 0 而显示空白。
    // 峰档 /M：sell(1200*3+4800)=8400 元；cost(500*3+2000)=3500 元 → 毛利 4900 元
    // 毛利率 = 4900 ÷ 8400 ≈ 58.33% → 显示 +58
    expect(wrapper.text()).toContain('参考毛利率：+58%')

    // 峰谷模型下顶部 flat 售价/成本 group 隐藏（不再出现误导性空框），并展示谷峰提示
    const flatPriceInputs = wrapper.findAll('input[name="input_price_per_1k_tokens"]')
    expect(flatPriceInputs.length).toBe(0)
    expect(wrapper.text()).toContain('该模型已启用谷峰定价')
  })

  it('echoes peak/valley cached pricing inputs as numbers when editing a peak-valley + cache model', async () => {
    const pvCacheRecord = [
      {
        ...modelRecords[0],
        peak_valley_enabled: true,
        cache_pricing_enabled: true,
        peak_windows: JSON.stringify([{ days: '0-4', start: '09:00', end: '12:00' }]),
        peak_input_price_per_1k_tokens: '0.390000',
        peak_output_price_per_1k_tokens: '0.900000',
        peak_input_cached_price_per_1k_tokens: '0.195000',
        peak_input_cost_per_1k_tokens: '0.003000',
        valley_input_price_per_1k_tokens: '0.200000',
        valley_output_price_per_1k_tokens: '0.500000',
        valley_input_cached_price_per_1k_tokens: '0.100000',
        valley_input_cost_per_1k_tokens: '0.001500',
      },
    ]
    const wrapper = await renderView(pvCacheRecord)

    await buttonByText(wrapper, '编辑').trigger('click')
    await nextTick()

    // 峰谷模型：顶部无 flat 输入框
    expect(wrapper.find('input[name="input_price_per_1k_tokens"]').exists()).toBe(false)
    expect(wrapper.find('input[name="input_cost_per_1k_tokens"]').exists()).toBe(false)
    // 峰/谷 8 个输入框（含缓存）回显为数字字符串
    expect((wrapper.find('input[name="peak_input_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('390')
    expect((wrapper.find('input[name="peak_output_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('900')
    expect((wrapper.find('input[name="peak_input_cached_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('195')
    expect((wrapper.find('input[name="peak_input_cost_per_1k_tokens"]').element as HTMLInputElement).value).toBe('3')
    expect((wrapper.find('input[name="valley_input_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('200')
    expect((wrapper.find('input[name="valley_output_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('500')
    expect((wrapper.find('input[name="valley_input_cached_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('100')
    expect((wrapper.find('input[name="valley_input_cost_per_1k_tokens"]').element as HTMLInputElement).value).toBe('1.5')
    // 标签含单位标注
    expect(wrapper.text()).toContain('输入售价（元/M）')
    expect(wrapper.text()).toContain('输入成本（元/M）')
  })
})