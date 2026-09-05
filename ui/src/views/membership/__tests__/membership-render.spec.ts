import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MembershipView from '@/views/membership/MembershipView.vue'

vi.mock('@/services/billing', () => ({
  getMembershipSummary: vi.fn().mockResolvedValue({
    membership: null,
    credit_account: { balance: 100, total_granted: 500, total_consumed: 400 },
    recent_transactions: [],
  }),
  getRedeemRecords: vi.fn().mockResolvedValue({ list: [] }),
  redeemCode: vi.fn(),
}))

vi.mock('@/services/balance', () => ({
  getBalanceProfile: vi.fn().mockResolvedValue({ balance: 0, commission_balance: 0 }),
  listWithdrawals: vi.fn().mockResolvedValue({ list: [] }),
  createWithdrawal: vi.fn(),
}))

vi.mock('@/services/commerce', () => ({
  listOrders: vi.fn().mockResolvedValue({ list: [] }),
  listAutoRenewals: vi.fn().mockResolvedValue({ list: [] }),
  listPlans: vi.fn().mockResolvedValue({ list: [] }),
  cancelOrder: vi.fn(),
  createOrder: vi.fn(),
  createRefund: vi.fn(),
  createAutoRenewal: vi.fn(),
  setAutoRenewalStatus: vi.fn(),
}))

vi.mock('@/services/distribution', () => ({
  getMyDistribution: vi.fn().mockResolvedValue({ commission_rate: '0', referral_code: '', share_url: '', superior: null, subordinate_count: 0, high_rate_locked: false }),
  listSubordinates: vi.fn().mockResolvedValue({ list: [] }),
  listMyCommissions: vi.fn().mockResolvedValue({ list: [] }),
  getDistributionQrcode: vi.fn().mockResolvedValue({ share_url: '', qrcode_url: null }),
  updateReferralCode: vi.fn(),
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  Modal: {},
}))

describe('MembershipView 渲染', () => {
  it('渲染会员中心页内容', () => {
    const wrapper = mount(MembershipView, {
      global: { stubs: { 'a-modal': { template: '<div><slot /></div>' } } },
    })
    expect(wrapper.text()).toContain('我的会员')
    expect(wrapper.text()).toContain('当前算力值')
    expect(wrapper.text()).toContain('余额中心')
    expect(wrapper.text()).toContain('分销中心')
  })
})
