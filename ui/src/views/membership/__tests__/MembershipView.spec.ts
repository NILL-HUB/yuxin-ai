import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MembershipView from '@/views/membership/MembershipView.vue'

const mocks = vi.hoisted(() => ({
  getMembershipSummary: vi.fn(),
  getRedeemRecords: vi.fn(),
  redeemCode: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/billing', () => ({
  getMembershipSummary: mocks.getMembershipSummary,
  getRedeemRecords: mocks.getRedeemRecords,
  redeemCode: mocks.redeemCode,
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
  props: ['loading', 'type'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

const summary = {
  membership: {
    id: 'membership-1',
    status: 'active',
    started_at: 1893456000,
    expires_at: 1896048000,
    source: 'redeem_code',
    source_id: 'code-1',
    plan: { id: 'plan-1', code: 'pro', name: 'Pro', duration_days: 30, grant_token_credits: 100000 },
  },
  credit_account: { account_id: 'account-1', balance: 100000, total_granted: 120000, total_consumed: 20000 },
  recent_transactions: [{ id: 'tx-1', amount: 100000, balance_after: 100000, transaction_type: 'redeem_grant', source: 'redeem_code', source_id: 'code-1', description: '卡密兑换赠送算力值', created_at: 1893456000 }],
}

const redeemRecords = {
  list: [{ id: 'code-1', code_mask: 'OAAB****C', redeemed_at: 1893456000, plan: { id: 'plan-1', code: 'pro', name: 'Pro', duration_days: 30, grant_token_credits: 100000 }, grant_token_credits: 100000, membership_expires_at: 1896048000 }],
}

const renderView = async () => {
  mocks.getMembershipSummary.mockResolvedValue(summary)
  mocks.getRedeemRecords.mockResolvedValue(redeemRecords)
  const wrapper = mount(MembershipView, {
    global: {
      stubs: {
        'a-input': inputStub,
        'a-button': buttonStub,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('MembershipView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads membership summary and credit balance', async () => {
    const wrapper = await renderView()

    expect(mocks.getMembershipSummary).toHaveBeenCalled()
    expect(mocks.getRedeemRecords).toHaveBeenCalled()
    expect(wrapper.text()).toContain('我的会员')
    expect(wrapper.text()).toContain('Pro')
    expect(wrapper.text()).toContain('100000')
    expect(wrapper.text()).toContain('卡密兑换赠送算力值')
    expect(wrapper.text()).toContain('兑换记录')
    expect(wrapper.text()).toContain('OAAB****C')
    expect(wrapper.text()).toContain('会员有效期')
  })

  it('redeems code and reloads summary', async () => {
    mocks.redeemCode.mockResolvedValue({ credit_account: { balance: 200000 } })
    const wrapper = await renderView()

    await wrapper.find('input[placeholder="输入卡密"]').setValue('OA-ABC')
    await wrapper.findAll('button').find((button) => button.text() === '兑换')?.trigger('click')
    await flushPromises()

    expect(mocks.redeemCode).toHaveBeenCalledWith('OA-ABC')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('兑换成功')
    expect(mocks.getMembershipSummary).toHaveBeenCalledTimes(2)
  })

  it('shows clear redeem failure message from backend', async () => {
    mocks.redeemCode.mockRejectedValue(new Error('该卡密已被兑换'))
    const wrapper = await renderView()

    await wrapper.find('input[placeholder="输入卡密"]').setValue('OA-ABC')
    await wrapper.findAll('button').find((button) => button.text() === '兑换')?.trigger('click')
    await flushPromises()

    expect(mocks.messageError).toHaveBeenCalledWith('该卡密已被兑换')
  })
})
