import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ModelsView from '@/views/admin/ModelsView.vue'
import { createModel } from '@/services/admin-model-pool'

const mocks = vi.hoisted(() => ({
  listModels: vi.fn(),
  listModelKeys: vi.fn(),
  listTierPolicies: vi.fn(),
  listProviderOptions: vi.fn(),
  getBillingConfig: vi.fn(),
  suggestSellPrices: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('@/services/admin-model-pool', () => ({
  listModels: mocks.listModels,
  listModelKeys: mocks.listModelKeys,
  listTierPolicies: mocks.listTierPolicies,
  createModel: vi.fn(),
  updateModel: vi.fn(),
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
      this.$emit('update:modelValue', v)
      this.$emit('change', v)
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

const tagStub = {
  props: ['color', 'size'],
  template: '<span class="arco-tag" :data-color="color"><slot /></span>',
}

const modalStub = {
  props: ['visible', 'title', 'okLoading', 'maskClosable'],
  emits: ['ok', 'cancel', 'update:visible'],
  template: '<div v-if="visible" class="a-modal"><slot /><button class="modal-ok" type="button" @click="$emit(\'ok\')">OK</button></div>',
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

const renderView = async (models = modelRecords, providerOptions = defaultProviderOptions) => {
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

    const priceInputs = wrapper.findAll('input').filter((node) => node.attributes('placeholder') === '0.000000（留 0 则使用单价）')
    const costInputs = wrapper.findAll('input').filter((node) => node.attributes('placeholder') === '0.000000（元/1k）')
    expect(priceInputs).toHaveLength(2)
    expect(costInputs).toHaveLength(2)

    await priceInputs[0].setValue('1.2')
    await priceInputs[1].setValue('4.8')
    await costInputs[0].setValue('0.009')
    await costInputs[1].setValue('0.036')
    await nextTick()

    // sell = 1.2*3 + 4.8 = 8.4; cost = (0.009*3 + 0.036) * 100 = 6.3; margin ≈ +2.1
    expect(wrapper.text()).toContain('参考毛利：+2 算力（+33%）')
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

    const costInputs = wrapper.findAll('input').filter((node) => node.attributes('placeholder') === '0.000000（元/1k）')
    expect(costInputs).toHaveLength(2)
    expect((costInputs[0].element as HTMLInputElement).value).toBe('0.009000')
    expect((costInputs[1].element as HTMLInputElement).value).toBe('0.036000')
  })

  it('toggling peak-valley shows peak/valley price groups and hides them when off', async () => {
    const wrapper = await renderView()

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()

    expect(wrapper.find('input[name="peak_input_price_per_1k_tokens"]').exists()).toBe(false)
    expect(wrapper.find('input[name="valley_input_price_per_1k_tokens"]').exists()).toBe(false)
    expect(wrapper.find('textarea[name="peak_windows"]').exists()).toBe(false)

    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    expect(wrapper.find('textarea[name="peak_windows"]').exists()).toBe(true)
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

  it('fills provider default peak windows for siliconflow with two daily windows', async () => {
    const siliconflowOptions = [
      { id: 'sf', name: 'SiliconFlow', label: 'SiliconFlow', description: '', default_base_url: '', supported_model_types: ['chat'] },
    ]
    const wrapper = await renderView(modelRecords, siliconflowOptions)

    await buttonByText(wrapper, '新建模型').trigger('click')
    await nextTick()
    await wrapper.find('.price-mode-switch input').setValue(true)
    await nextTick()

    const windows = JSON.parse((wrapper.find('textarea[name="peak_windows"]').element as HTMLTextAreaElement).value)
    expect(windows).toHaveLength(2)
    expect(windows[0]).toEqual({ days: '0-6', start: '00:00', end: '02:00' })
    expect(windows[1]).toEqual({ days: '0-6', start: '08:00', end: '24:00' })
  })

  it('applies pricing suggestions from the auto pricing assistant', async () => {
    mocks.suggestSellPrices.mockResolvedValue({
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
    expect((wrapper.find('input[name="peak_input_price_per_1k_tokens"]').element as HTMLInputElement).value).toBe('1.250000')
    expect(mocks.messageSuccess).toHaveBeenCalled()
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
})