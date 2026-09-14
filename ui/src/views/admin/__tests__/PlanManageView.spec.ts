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

const clickButton = async (wrapper: ReturnType<typeof mount>, text: string) => {
  const button = wrapper.findAll('button').find((node) => node.text().trim() === text)
  if (!button) throw new Error(`button not found: ${text}`)
  await button.trigger('click')
}

const clickFormButton = async (wrapper: ReturnType<typeof mount>, text: string) => {
  const button = wrapper.find('.plan-form').findAll('button').find((node) => node.text().trim().replace(/^\+\s*/, '') === text)
  if (!button) throw new Error(`form button not found: ${text}`)
  await button.trigger('click')
}

const openCreate = async (wrapper: ReturnType<typeof mount>) => {
  await clickButton(wrapper, '+ 新建套餐')
  await nextTick()
}

const storageAddonPlan = {
  id: 'plan-1',
  code: 'STORAGE_50G',
  name: '存储扩容包',
  description: '',
  plan_type: 'storage_addon' as const,
  duration_days: 30,
  grant_token_credits: 0,
  auto_renew_threshold_percent: 5,
  auto_renew_threshold_days: 1,
  purchase_limit: 0,
  purchase_limit_period: 'none' as const,
  quota_refresh_period: 'none' as const,
  auto_renew_default: false,
  price: '9.90',
  status: 'active' as const,
  sort_order: 0,
  created_at: null,
  updated_at: null,
  entitlements: [{ feature_key: 'storage_quota_gb', feature_value: '100', value_type: 'number' as const }],
}

describe('PlanManageView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('offers the storage_addon plan type option', async () => {
    const wrapper = await renderView()

    await openCreate(wrapper)

    expect(wrapper.text()).toContain('存储扩容包')
  })

  it('starts a new plan with an empty entitlement list and shows the editor', async () => {
    const wrapper = await renderView()

    await openCreate(wrapper)

    const form = (wrapper.vm as unknown as { form: { entitlements: unknown[] } }).form
    expect(Array.isArray(form.entitlements)).toBe(true)
    expect(form.entitlements).toHaveLength(0)
    expect(wrapper.find('.entitlement-editor').exists()).toBe(true)
    expect(wrapper.findAll('.entitlement-row')).toHaveLength(0)
  })

  it('adds entitlement rows and sends them in the create payload', async () => {
    const wrapper = await renderView()

    await openCreate(wrapper)
    await clickFormButton(wrapper, '添加权益')
    await nextTick()

    expect(wrapper.findAll('.entitlement-row')).toHaveLength(1)

    const row = wrapper.find('.entitlement-row')
    const inputs = row.findAll('input')
    await inputs[0].setValue('max_single_file_gb')
    await inputs[1].setValue('2')
    await row.find('select').setValue('number')
    await nextTick()

    const form = (wrapper.vm as unknown as { form: Record<string, unknown> }).form
    form.code = 'STORAGE_2G'
    form.name = '大文件包'
    await clickFormButton(wrapper, '保存')
    await flushPromises()

    expect(mocks.createPlan).toHaveBeenCalledTimes(1)
    expect(mocks.createPlan.mock.calls[0][0].entitlements).toEqual([
      { feature_key: 'max_single_file_gb', feature_value: '2', value_type: 'number' },
    ])
  })

  it('removes an entitlement row', async () => {
    const wrapper = await renderView()

    await openCreate(wrapper)
    await clickFormButton(wrapper, '添加权益')
    await clickFormButton(wrapper, '添加权益')
    await nextTick()

    expect(wrapper.findAll('.entitlement-row')).toHaveLength(2)

    await wrapper.findAll('.entitlement-row')[1].find('button').trigger('click')
    await nextTick()

    expect(wrapper.findAll('.entitlement-row')).toHaveLength(1)
  })

  it('drops entitlement rows whose feature_key is blank', async () => {
    const wrapper = await renderView()

    await openCreate(wrapper)
    await clickFormButton(wrapper, '添加权益')
    await clickFormButton(wrapper, '添加权益')
    await nextTick()

    const rows = wrapper.findAll('.entitlement-row')
    expect(rows).toHaveLength(2)
    const filled = rows[1].findAll('input')
    await filled[0].setValue('storage_quota_gb')
    await filled[1].setValue('100')
    await nextTick()

    const form = (wrapper.vm as unknown as { form: Record<string, unknown> }).form
    form.code = 'STORAGE_100G'
    form.name = '容量包'
    await clickFormButton(wrapper, '保存')
    await flushPromises()

    expect(mocks.createPlan.mock.calls[0][0].entitlements).toEqual([
      { feature_key: 'storage_quota_gb', feature_value: '100', value_type: 'string' },
    ])
  })

  it('backfills existing entitlements when editing and saves them back', async () => {
    const wrapper = await renderView()

    const vm = wrapper.vm as unknown as { openEdit: (plan: unknown) => void; form: { entitlements: unknown[] } }
    vm.openEdit(storageAddonPlan)
    await nextTick()

    expect(vm.form.entitlements).toEqual([
      { feature_key: 'storage_quota_gb', feature_value: '100', value_type: 'number' },
    ])
    expect(wrapper.findAll('.entitlement-row')).toHaveLength(1)

    await clickFormButton(wrapper, '保存')
    await flushPromises()

    expect(mocks.updatePlan).toHaveBeenCalledWith('plan-1', expect.objectContaining({
      entitlements: [{ feature_key: 'storage_quota_gb', feature_value: '100', value_type: 'number' }],
    }))
  })

  it('shows the storage_addon hint when the plan type is storage_addon', async () => {
    const wrapper = await renderView()

    await openCreate(wrapper)
    const form = (wrapper.vm as unknown as { form: Record<string, unknown> }).form
    form.plan_type = 'storage_addon'
    await nextTick()

    expect(wrapper.text()).toContain('storage_quota_gb')
    expect(wrapper.text()).toContain('max_single_file_gb')
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