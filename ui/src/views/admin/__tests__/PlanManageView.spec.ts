import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import PlanManageView from '@/views/admin/PlanManageView.vue'
import { useAdminStore } from '@/stores/admin'

const mocks = vi.hoisted(() => ({
  listPlans: vi.fn(),
  getBillingConfig: vi.fn(),
  updateBillingConfig: vi.fn(),
  createPlan: vi.fn(),
  updatePlan: vi.fn(),
  deletePlan: vi.fn(),
  setPlanStatus: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('@/services/admin-billing', () => ({
  listPlans: mocks.listPlans,
  getBillingConfig: mocks.getBillingConfig,
  updateBillingConfig: mocks.updateBillingConfig,
  createPlan: mocks.createPlan,
  updatePlan: mocks.updatePlan,
  deletePlan: mocks.deletePlan,
  setPlanStatus: mocks.setPlanStatus,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
  },
}))

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const inputNumberStub = {
  props: ['modelValue', 'placeholder', 'disabled'],
  emits: ['update:modelValue'],
  template: '<input type="number" :value="modelValue" :placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:modelValue\', Number($event.target.value))" />',
}

const buttonStub = {
  props: ['loading', 'disabled', 'type', 'status', 'size'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading || disabled" @click="$emit(\'click\')"><slot /></button>',
}

const spanSlotStub = {
  template: '<span><slot /></span>',
}

const divSlotStub = {
  template: '<div><slot /></div>',
}

const selectStub = {
  props: ['modelValue', 'placeholder', 'options'],
  emits: ['update:modelValue'],
  template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="o in (options || [])" :key="o.value" :value="o.value">{{ o.label }}</option></select>',
}

const tableStub = {
  props: ['data', 'loading', 'pagination'],
  template: '<div class="a-table"><slot name="columns" /></div>',
}

const tableColumnStub = {
  template: '<div class="a-table-column" />',
}

const drawerStub = {
  props: ['visible', 'width', 'footer'],
  emits: ['cancel', 'update:visible'],
  template: '<div v-if="visible" class="a-drawer"><slot /></div>',
}

const switchStub = {
  props: ['modelValue', 'disabled'],
  emits: ['change', 'update:modelValue'],
  template: '<button type="button" :disabled="disabled" class="arco-switch" @click="$emit(\'change\', !modelValue)"><slot /></button>',
}

const renderView = async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAdminStore(pinia).update({
    id: 'admin-1',
    username: 'admin',
    email: 'admin@example.com',
    name: 'Admin',
    avatar: '',
    status: 'active',
    roles: ['operator'],
    permissions: ['plan:read', 'plan:update'],
  })
  mocks.listPlans.mockResolvedValue({ list: [], paginator: { total_record: 0, total_page: 0, current_page: 1, page_size: 20 } })
  mocks.getBillingConfig.mockImplementation(async (code?: string) =>
    code === 'credits_per_yuan' ? { code: 'credits_per_yuan', value_numeric: 100 } : { code: 'credits_per_1k_tokens', value_numeric: 1 },
  )
  mocks.updateBillingConfig.mockResolvedValue({ code: 'credits_per_yuan', value_numeric: 90 })
  const wrapper = mount(PlanManageView, {
    global: {
      plugins: [pinia],
      stubs: {
        'a-input': inputStub,
        'a-input-number': inputNumberStub,
        'a-button': buttonStub,
        'a-select': selectStub,
        'a-table': tableStub,
        'a-table-column': tableColumnStub,
        'a-tooltip': spanSlotStub,
        'a-tag': spanSlotStub,
        'a-drawer': drawerStub,
        'a-switch': switchStub,
        'a-empty': divSlotStub,
        'a-textarea': inputStub,
        'a-radio-group': divSlotStub,
        'a-radio': spanSlotStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('PlanManageView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders two billing config cards with independent values', async () => {
    const wrapper = await renderView()

    expect(mocks.getBillingConfig).toHaveBeenCalledWith()
    expect(mocks.getBillingConfig).toHaveBeenCalledWith('credits_per_yuan')

    const numberInputs = wrapper.findAll('input[type="number"]')
    expect(numberInputs).toHaveLength(2)
    expect((numberInputs[0].element as HTMLInputElement).value).toBe('1')
    expect((numberInputs[1].element as HTMLInputElement).value).toBe('100')

    expect(wrapper.text()).toContain('汇率锚')
    expect(wrapper.text()).toContain('兜底售价')
    expect(wrapper.text()).toContain('fallback')
    expect(wrapper.text()).toContain('anchor')
    expect(wrapper.text()).toContain('预计影响')
  })

  it('saves the exchange anchor card independently with code credits_per_yuan', async () => {
    const wrapper = await renderView()

    const numberInputs = wrapper.findAll('input[type="number"]')
    await numberInputs[1].setValue(90)
    await nextTick()

    expect(wrapper.text()).toContain('预计影响：+10%')

    const saveButtons = wrapper.findAll('button').filter((node) => node.text().trim() === '保存')
    expect(saveButtons).toHaveLength(2)
    await saveButtons[1].trigger('click')
    await flushPromises()

    expect(mocks.updateBillingConfig).toHaveBeenCalledTimes(1)
    expect(mocks.updateBillingConfig).toHaveBeenCalledWith({ code: 'credits_per_yuan', value_numeric: 90 })
    expect(mocks.messageSuccess).toHaveBeenCalled()
  })

  it('does not touch the fallback rate card when saving the anchor card', async () => {
    const wrapper = await renderView()

    const numberInputs = wrapper.findAll('input[type="number"]')
    await numberInputs[1].setValue(90)
    await nextTick()
    const saveButtons = wrapper.findAll('button').filter((node) => node.text().trim() === '保存')
    await saveButtons[1].trigger('click')
    await flushPromises()

    const fallbackRateCalls = mocks.updateBillingConfig.mock.calls.filter((call) => call[0]?.code === undefined)
    expect(fallbackRateCalls).toHaveLength(0)
    expect(mocks.updateBillingConfig.mock.calls[0][0]).toEqual({ code: 'credits_per_yuan', value_numeric: 90 })
  })
})