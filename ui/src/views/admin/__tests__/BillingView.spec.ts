import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BillingView from '@/views/admin/BillingView.vue'
import { useAdminStore } from '@/stores/admin'

const mocks = vi.hoisted(() => ({
  listPlans: vi.fn(),
  createPlan: vi.fn(),
  setPlanStatus: vi.fn(),
  generateRedeemCodes: vi.fn(),
  listRedeemCodeBatches: vi.fn(),
  listRedeemCodes: vi.fn(),
  disableRedeemCode: vi.fn(),
  disableRedeemCodeBatch: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-billing', () => ({
  listPlans: mocks.listPlans,
  createPlan: mocks.createPlan,
  setPlanStatus: mocks.setPlanStatus,
  generateRedeemCodes: mocks.generateRedeemCodes,
  listRedeemCodeBatches: mocks.listRedeemCodeBatches,
  listRedeemCodes: mocks.listRedeemCodes,
  disableRedeemCode: mocks.disableRedeemCode,
  disableRedeemCodeBatch: mocks.disableRedeemCodeBatch,
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

const buttonStub = {
  props: ['loading', 'size', 'type', 'status'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

const plan = {
  id: 'plan-1',
  code: 'pro',
  name: 'Pro',
  description: 'Pro plan',
  duration_days: 30,
  grant_token_credits: 100000,
  price: '99.00',
  status: 'active' as const,
  sort_order: 10,
  created_at: 1893456000,
  updated_at: 1893456000,
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
  mocks.listPlans.mockResolvedValue({ list: [plan], paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 } })
  mocks.listRedeemCodeBatches.mockResolvedValue({ list: [{ id: 'batch-1', name: 'Batch', plan_id: 'plan-1', quantity: 2, status: 'active', expires_at: null, disabled_at: null, created_by: 'admin-1', created_at: 1893456000 }], paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 } })
  mocks.listRedeemCodes.mockResolvedValue({ list: [{ id: 'code-1', batch_id: 'batch-1', plan_id: 'plan-1', code_mask: 'OAAB****C', status: 'unused', redeemed_by: null, redeemed_at: null, expires_at: null, disabled_at: null, created_at: 1893456000 }], paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 } })
  const wrapper = mount(BillingView, {
    global: {
      plugins: [pinia],
      stubs: {
        'a-input': inputStub,
        'a-button': buttonStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('BillingView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads plans, redeem code batches, and masked codes', async () => {
    const wrapper = await renderView()

    expect(mocks.listPlans).toHaveBeenCalledWith({ keyword: '', status: '', current_page: 1, page_size: 20 })
    expect(mocks.listRedeemCodeBatches).toHaveBeenCalledWith({ keyword: '', current_page: 1, page_size: 20 })
    expect(mocks.listRedeemCodes).toHaveBeenCalledWith({ batch_id: '', status: '', code_keyword: '', current_page: 1, page_size: 20 })
    expect(wrapper.text()).toContain('套餐卡密')
    expect(wrapper.text()).toContain('Pro')
    expect(wrapper.text()).toContain('Batch')
    expect(wrapper.text()).toContain('OAAB****C')
  })

  it('creates plan from quick form', async () => {
    mocks.createPlan.mockResolvedValue(plan)
    const wrapper = await renderView()

    await wrapper.find('input[placeholder="套餐代码"]').setValue('team')
    await wrapper.find('input[placeholder="套餐名称"]').setValue('Team')
    await wrapper.findAll('button').find((button) => button.text() === '创建套餐')?.trigger('click')
    await flushPromises()

    expect(mocks.createPlan).toHaveBeenCalledWith(expect.objectContaining({ code: 'team', name: 'Team' }))
    expect(mocks.messageSuccess).toHaveBeenCalledWith('套餐已创建')
  })

  it('generates redeem codes and displays one-time export actions', async () => {
    mocks.generateRedeemCodes.mockResolvedValue({ batch: { id: 'batch-2', name: 'New Batch' }, codes: [{ plain_code: 'OA-ABC', code_mask: 'OAAB****C' }] })
    const wrapper = await renderView()

    await wrapper.find('input[placeholder="卡密批次名称"]').setValue('New Batch')
    await wrapper.findAll('button').find((button) => button.text() === '生成卡密')?.trigger('click')
    await flushPromises()

    expect(mocks.generateRedeemCodes).toHaveBeenCalledWith(expect.objectContaining({ name: 'New Batch', plan_id: 'plan-1' }))
    expect(wrapper.text()).toContain('OA-ABC')
    expect(wrapper.text()).toContain('卡密明文只展示一次')
    expect(wrapper.text()).toContain('复制全部')
    expect(wrapper.text()).toContain('下载 TXT')
    expect(wrapper.text()).toContain('下载 CSV')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('卡密已生成，请立即复制或下载明文')
  })

  it('copies all generated plain codes', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    mocks.generateRedeemCodes.mockResolvedValue({ batch: { id: 'batch-2', name: 'New Batch' }, codes: [{ plain_code: 'OA-ABC', code_mask: 'OAAB****C' }, { plain_code: 'OA-DEF', code_mask: 'OADE****F' }] })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '生成卡密')?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '复制全部')?.trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith('OA-ABC\nOA-DEF')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('卡密已复制')
  })

  it('downloads generated plain codes as txt and csv', async () => {
    const createObjectURL = vi.fn(() => 'blob:redeem-codes')
    const revokeObjectURL = vi.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const click = vi.fn()
    const anchor = document.createElement('a')
    anchor.click = click
    mocks.generateRedeemCodes.mockResolvedValue({ batch: { id: 'batch-2', name: 'New Batch' }, codes: [{ plain_code: 'OA-ABC', code_mask: 'OAAB****C' }, { plain_code: 'OA-DEF', code_mask: 'OADE****F' }] })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '生成卡密')?.trigger('click')
    await flushPromises()
    const createElement = vi.spyOn(document, 'createElement').mockReturnValue(anchor)
    await wrapper.findAll('button').find((button) => button.text() === '下载 TXT')?.trigger('click')
    await wrapper.findAll('button').find((button) => button.text() === '下载 CSV')?.trigger('click')

    expect(createElement).toHaveBeenCalledWith('a')
    expect(click).toHaveBeenCalledTimes(2)
    expect(createObjectURL).toHaveBeenCalledTimes(2)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:redeem-codes')
    createElement.mockRestore()
  })

  it('filters redeem codes by keyword and status and displays redeem details', async () => {
    mocks.listRedeemCodes
      .mockResolvedValueOnce({ list: [{ id: 'code-1', batch_id: 'batch-1', plan_id: 'plan-1', code_mask: 'OAAB****C', status: 'unused', redeemed_by: null, redeemed_at: null, expires_at: null, disabled_at: null, created_at: 1893456000 }], paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 } })
      .mockResolvedValueOnce({
        list: [{ id: 'code-2', batch_id: 'batch-1', plan_id: 'plan-1', code_mask: 'OA12****7890', status: 'used', redeemed_by: 'user-1', redeemed_at: 1893456000, expires_at: 1896048000, disabled_at: null, created_at: 1893456000 }],
        paginator: { total_record: 1, total_page: 1, current_page: 1, page_size: 20 },
      })
    const wrapper = await renderView()

    await wrapper.find('input[placeholder="卡密掩码关键词"]').setValue('7890')
    await wrapper.find('input[placeholder="状态 unused/used/disabled/expired"]').setValue('used')
    await wrapper.findAll('button').find((button) => button.text() === '查询卡密')?.trigger('click')
    await flushPromises()

    expect(mocks.listRedeemCodes).toHaveBeenLastCalledWith({ batch_id: '', status: 'used', code_keyword: '7890', current_page: 1, page_size: 20 })
    expect(wrapper.text()).toContain('OA12****7890')
    expect(wrapper.text()).toContain('已兑换')
    expect(wrapper.text()).toContain('user-1')
    expect(wrapper.text()).toContain('2030-01-01')
  })

  it('disables redeem code batch and reloads billing data', async () => {
    mocks.disableRedeemCodeBatch.mockResolvedValue({ id: 'batch-1', status: 'disabled' })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '禁用批次')?.trigger('click')
    await flushPromises()

    expect(mocks.disableRedeemCodeBatch).toHaveBeenCalledWith('batch-1')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('批次已禁用')
    expect(mocks.listRedeemCodeBatches).toHaveBeenCalledTimes(2)
  })

  it('disables redeem code and reloads code list', async () => {
    mocks.disableRedeemCode.mockResolvedValue({ id: 'code-1', status: 'disabled' })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '禁用卡密')?.trigger('click')
    await flushPromises()

    expect(mocks.disableRedeemCode).toHaveBeenCalledWith('code-1')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('卡密已禁用')
    expect(mocks.listRedeemCodes).toHaveBeenCalledTimes(2)
  })

  it('hides plan mutation actions when plan update permission is missing', async () => {
    const wrapper = await renderView(['plan:read', 'redeem_code:read', 'redeem_code:update'])

    const buttonTexts = wrapper.findAll('button').map((button) => button.text())
    expect(buttonTexts).not.toContain('创建套餐')
    expect(buttonTexts).not.toContain('停用')
    expect(buttonTexts).toContain('生成卡密')
    expect(buttonTexts).toContain('禁用卡密')
  })

  it('hides redeem code mutation actions when redeem code update permission is missing', async () => {
    const wrapper = await renderView(['plan:read', 'plan:update', 'redeem_code:read'])

    const buttonTexts = wrapper.findAll('button').map((button) => button.text())
    expect(buttonTexts).toContain('创建套餐')
    expect(buttonTexts).toContain('停用')
    expect(buttonTexts).not.toContain('生成卡密')
    expect(buttonTexts).not.toContain('禁用卡密')
    expect(buttonTexts).not.toContain('禁用批次')
  })

  it('disables active plan', async () => {
    mocks.setPlanStatus.mockResolvedValue({ ...plan, status: 'disabled' })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '停用')?.trigger('click')
    await flushPromises()

    expect(mocks.setPlanStatus).toHaveBeenCalledWith('plan-1', 'disabled')
  })
})
