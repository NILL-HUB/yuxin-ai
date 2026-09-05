import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BillingView from '@/views/admin/BillingView.vue'
import { useAdminStore } from '@/stores/admin'

const mocks = vi.hoisted(() => ({
  listPlans: vi.fn(),
  setPlanStatus: vi.fn(),
  generateRedeemCodes: vi.fn(),
  listRedeemCodeBatches: vi.fn(),
  listRedeemCodes: vi.fn(),
  disableRedeemCode: vi.fn(),
  disableRedeemCodeBatch: vi.fn(),
  getRedeemCodePlain: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-billing', () => ({
  listPlans: mocks.listPlans,
  setPlanStatus: mocks.setPlanStatus,
  generateRedeemCodes: mocks.generateRedeemCodes,
  listRedeemCodeBatches: mocks.listRedeemCodeBatches,
  listRedeemCodes: mocks.listRedeemCodes,
  disableRedeemCode: mocks.disableRedeemCode,
  disableRedeemCodeBatch: mocks.disableRedeemCodeBatch,
  getRedeemCodePlain: mocks.getRedeemCodePlain,
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

const textareaStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<textarea :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const selectStub = {
  props: ['modelValue', 'placeholder', 'options'],
  emits: ['update:modelValue'],
  template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="o in (options || [])" :key="o.value" :value="o.value">{{ o.label }}</option></select>',
}

const buttonStub = {
  props: ['loading', 'size', 'type', 'status'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

const switchStub = {
  props: ['modelValue', 'checkedText', 'uncheckedText'],
  emits: ['change'],
  template: '<button type="button" @click="$emit(\'change\')"><span>{{ modelValue ? checkedText : uncheckedText }}</span></button>',
}

const tagStub = {
  props: ['color', 'size'],
  template: '<span><slot /></span>',
}

const modalStub = {
  props: ['visible'],
  template: '<div v-if="visible"><slot /></div>',
}

const plan = {
  id: 'plan-1',
  code: 'pro',
  name: 'Pro',
  description: 'Pro plan',
  plan_type: 'membership' as const,
  duration_days: 30,
  grant_token_credits: 100000,
  auto_renew_threshold_percent: 5,
  auto_renew_threshold_days: 1,
  purchase_limit: 0,
  purchase_limit_period: 'none' as const,
  quota_refresh_period: 'cycle' as const,
  auto_renew_default: false,
  price: '99.00',
  status: 'active' as const,
  sort_order: 10,
  created_at: 1893456000,
  updated_at: 1893456000,
}

const batch = {
  id: 'batch-1',
  name: 'Batch',
  description: '拉新渠道',
  plan_id: 'plan-1',
  plan_name: 'Pro',
  quantity: 2,
  status: 'active',
  expires_at: null,
  disabled_at: null,
  created_by: 'admin-1',
  created_at: 1893456000,
}

const code = {
  id: 'code-1',
  batch_id: 'batch-1',
  plan_id: 'plan-1',
  plan_name: 'Pro',
  code_mask: 'OAAB****C',
  status: 'unused' as const,
  redeemed_by: null,
  redeemed_at: null,
  expires_at: null,
  disabled_at: null,
  created_at: 1893456000,
}

const renderView = async (permissions = ['plan:read', 'plan:update', 'redeem_code:read', 'redeem_code:update']) => {
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
    permissions,
  })
  mocks.listPlans.mockResolvedValue({ list: [plan], paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 50 } })
  mocks.listRedeemCodeBatches.mockResolvedValue({ list: [batch], paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 50 } })
  mocks.listRedeemCodes.mockResolvedValue({ list: [code], paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 } })
  const wrapper = mount(BillingView, {
    global: {
      plugins: [pinia],
      stubs: {
        'a-input': inputStub,
        'a-textarea': textareaStub,
        'a-input-number': inputStub,
        'a-select': selectStub,
        'a-button': buttonStub,
        'a-switch': switchStub,
        'a-tag': tagStub,
        'a-modal': modalStub,
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

describe('BillingView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads plans, redeem code batches, and masked codes', async () => {
    const wrapper = await renderView()

    expect(mocks.listPlans).toHaveBeenCalledWith({ keyword: '', status: '', current_page: 1, page_size: 10 })
    expect(mocks.listRedeemCodeBatches).toHaveBeenCalledWith({ keyword: '', current_page: 1, page_size: 10 })
    expect(mocks.listRedeemCodes).toHaveBeenCalledWith({ batch_id: '', status: '', code_keyword: '', current_page: 1, page_size: 20 })
    expect(wrapper.text()).toContain('套餐卡密')
    expect(wrapper.text()).toContain('Pro')
    expect(wrapper.text()).toContain('Batch')
    expect(wrapper.text()).toContain('OAAB****C')
    expect(wrapper.text()).toContain('拉新渠道')
  })

  it('generates redeem codes for the selected plan and shows export actions', async () => {
    mocks.generateRedeemCodes.mockResolvedValue({
      batch: { id: 'batch-2', name: 'New Batch', description: '', plan_id: 'plan-1', plan_name: 'Pro', quantity: 2 },
      codes: [{ plain_code: 'OA-ABC', code_mask: 'OAAB****C' }],
    })
    const wrapper = await renderView()

    await wrapper.findAll('select')[0].setValue('plan-1')
    await wrapper.find('input[placeholder="例如：101期-拉新渠道"]').setValue('New Batch')
    await buttonByText(wrapper, '生成卡密').trigger('click')
    await flushPromises()

    expect(mocks.generateRedeemCodes).toHaveBeenCalledWith(expect.objectContaining({ name: 'New Batch', plan_id: 'plan-1', quantity: 10 }))
    expect(wrapper.text()).toContain('OA-ABC')
    expect(wrapper.text()).toContain('复制全部')
    expect(wrapper.text()).toContain('下载 TXT')
    expect(wrapper.text()).toContain('下载 CSV')
  })

  it('validates plan selection and batch name before generating', async () => {
    const wrapper = await renderView()
    await buttonByText(wrapper, '生成卡密').trigger('click')
    await flushPromises()

    expect(mocks.generateRedeemCodes).not.toHaveBeenCalled()
  })

  it('copies all generated plain codes', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    mocks.generateRedeemCodes.mockResolvedValue({
      batch: { id: 'batch-2', name: 'New Batch', description: '', plan_id: 'plan-1', plan_name: 'Pro', quantity: 2 },
      codes: [{ plain_code: 'OA-ABC', code_mask: 'OAAB****C' }, { plain_code: 'OA-DEF', code_mask: 'OADE****F' }],
    })
    const wrapper = await renderView()

    await wrapper.findAll('select')[0].setValue('plan-1')
    await wrapper.find('input[placeholder="例如：101期-拉新渠道"]').setValue('New Batch')
    await buttonByText(wrapper, '生成卡密').trigger('click')
    await flushPromises()
    await buttonByText(wrapper, '复制全部').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith('OA-ABC\nOA-DEF')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('卡密已复制')
  })

  it('filters codes by batch and status dropdowns and keyword', async () => {
    mocks.listRedeemCodes
      .mockResolvedValueOnce({ list: [code], paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 } })
      .mockResolvedValueOnce({
        list: [{ ...code, id: 'code-2', code_mask: 'OA12****7890', status: 'used', redeemed_by: 'user-1', redeemed_at: 1893456000 }],
        paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
      })
    const wrapper = await renderView()

    await wrapper.findAll('select')[2].setValue('used')
    await wrapper.find('input[placeholder="卡密掩码关键词"]').setValue('7890')
    await buttonByText(wrapper, '查询').trigger('click')
    await flushPromises()

    expect(mocks.listRedeemCodes).toHaveBeenLastCalledWith({ batch_id: '', status: 'used', code_keyword: '7890', current_page: 1, page_size: 20 })
    expect(wrapper.text()).toContain('OA12****7890')
    expect(wrapper.text()).toContain('user-1')
  })

  it('views plaintext of an unused code', async () => {
    mocks.getRedeemCodePlain.mockResolvedValue({ id: 'code-1', code_mask: 'OAAB****C', plain_code: 'OA-FULLCODE123' })
    const wrapper = await renderView()

    await buttonByText(wrapper, '查看明文').trigger('click')
    await flushPromises()

    expect(mocks.getRedeemCodePlain).toHaveBeenCalledWith('code-1')
    expect(wrapper.text()).toContain('OA-FULLCODE123')
  })

  it('disables redeem code batch and reloads billing data', async () => {
    mocks.disableRedeemCodeBatch.mockResolvedValue({ id: 'batch-1', status: 'disabled' })
    const wrapper = await renderView()

    await buttonByText(wrapper, '禁用批次').trigger('click')
    await flushPromises()

    expect(mocks.disableRedeemCodeBatch).toHaveBeenCalledWith('batch-1')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('批次已禁用')
    expect(mocks.listRedeemCodeBatches).toHaveBeenCalledTimes(2)
  })

  it('disables redeem code and reloads code list', async () => {
    mocks.disableRedeemCode.mockResolvedValue({ id: 'code-1', status: 'disabled' })
    const wrapper = await renderView()

    await buttonByText(wrapper, '禁用卡密').trigger('click')
    await flushPromises()

    expect(mocks.disableRedeemCode).toHaveBeenCalledWith('code-1')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('卡密已禁用')
    expect(mocks.listRedeemCodes).toHaveBeenCalledTimes(2)
  })

  it('toggles plan availability through switch', async () => {
    mocks.setPlanStatus.mockResolvedValue({ ...plan, status: 'disabled' })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((node) => node.text() === '已上架')?.trigger('click')
    await flushPromises()

    expect(mocks.setPlanStatus).toHaveBeenCalledWith('plan-1', 'disabled')
    expect(mocks.messageSuccess).toHaveBeenCalled()
  })

  it('hides redeem code mutation actions when permission is missing', async () => {
    const wrapper = await renderView(['plan:read', 'plan:update', 'redeem_code:read'])

    const buttonTexts = wrapper.findAll('button').map((node) => node.text())
    expect(buttonTexts.some((text) => text.includes('生成卡密'))).toBe(false)
    expect(buttonTexts.some((text) => text.includes('禁用卡密'))).toBe(false)
    expect(buttonTexts.some((text) => text.includes('查看明文'))).toBe(false)
  })
})