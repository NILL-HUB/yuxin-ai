import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MembershipView from '@/views/membership/MembershipView.vue'

/**
 * 会员中心 — 真实接口版测试
 * mock 各服务接口返回典型数据，断言页面渲染真实数据。
 */
const mocks = vi.hoisted(() => ({
  getMembershipSummary: vi.fn(),
  getRedeemRecords: vi.fn(),
  getBalanceProfile: vi.fn(),
  listWithdrawals: vi.fn(),
  listOrders: vi.fn(),
  listAutoRenewals: vi.fn(),
  getMyDistribution: vi.fn(),
  listPlans: vi.fn(),
  listSubordinates: vi.fn(),
  listMyCommissions: vi.fn(),
  getDistributionQrcode: vi.fn(),
}))

vi.mock('@/services/billing', () => ({
  getMembershipSummary: mocks.getMembershipSummary,
  getRedeemRecords: mocks.getRedeemRecords,
  redeemCode: vi.fn(),
}))

vi.mock('@/services/balance', () => ({
  getBalanceProfile: mocks.getBalanceProfile,
  listWithdrawals: mocks.listWithdrawals,
  createWithdrawal: vi.fn(),
}))

vi.mock('@/services/commerce', () => ({
  cancelOrder: vi.fn(),
  createAutoRenewal: vi.fn(),
  createOrder: vi.fn(),
  createRefund: vi.fn(),
  listAutoRenewals: mocks.listAutoRenewals,
  listOrders: mocks.listOrders,
  listPlans: mocks.listPlans,
  setAutoRenewalStatus: vi.fn(),
}))

vi.mock('@/services/distribution', () => ({
  getDistributionQrcode: mocks.getDistributionQrcode,
  getMyDistribution: mocks.getMyDistribution,
  listMyCommissions: mocks.listMyCommissions,
  listSubordinates: mocks.listSubordinates,
  updateReferralCode: vi.fn(),
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  Modal: {},
}))

const summary = {
  membership: {
    status: 'active',
    expires_at: 1789000000,
    plan: { id: 'p1', code: 'pro', name: '高级会员 Pro', duration_days: 30, grant_token_credits: 1000 },
  },
  credit_account: { balance: 151970, total_granted: 152000, total_consumed: 30 },
  recent_transactions: [
    { id: 't1', amount: -5, description: '模型调用消耗算力值：4200 token，扣减 5（1000 token=1 算力）', transaction_type: 'consume', created_at: 1789000000 },
    { id: 't2', amount: 150000, description: '卡密兑换赠送算力值', transaction_type: 'redeem_grant', created_at: 1789000000 },
  ],
  recent_tasks: [
    { id: 't1', amount: -5, transaction_type: 'consume', source: 'message', source_id: 'm1', message: '帮我写一份会员营销方案', created_at: 1789000000 },
  ],
}

const renderView = async () => {
  mocks.getMembershipSummary.mockResolvedValue(summary)
  mocks.getRedeemRecords.mockResolvedValue({ list: [] })
  mocks.getBalanceProfile.mockResolvedValue({
    balance: 128, recharge_balance: 500, commission_balance: 86.4,
    total_withdrawn: 300, total_purchased: 1256.8,
    high_rate_locked: true, quota_credit: 2000, permanent_credit: 480,
  })
  mocks.listWithdrawals.mockResolvedValue({ list: [] })
  mocks.listOrders.mockResolvedValue({ list: [] })
  mocks.listAutoRenewals.mockResolvedValue({ list: [] })
  mocks.getMyDistribution.mockResolvedValue({
    referral_code: 'YXINV-8888', share_url: 'https://ai.yuxin.cn/i/YXINV-8888',
    superior: null, subordinate_count: 8, high_rate_locked: true, commission_rate: '30',
  })
  mocks.listPlans.mockResolvedValue({ list: [], paginator: { total_record: 0 } })
  mocks.listSubordinates.mockResolvedValue({ list: [], paginator: { total_record: 0 } })
  mocks.listMyCommissions.mockResolvedValue({ list: [], paginator: { total_record: 0 } })
  mocks.getDistributionQrcode.mockResolvedValue({ share_url: '', qrcode_url: null })
  const wrapper = mount(MembershipView, {
    global: { stubs: { 'a-modal': { template: '<div><slot /></div>' } } },
  })
  await flushPromises()
  return wrapper
}

describe('MembershipView (真实接口)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('加载会员概览并渲染真实算力值', async () => {
    const wrapper = await renderView()
    expect(wrapper.text()).toContain('我的会员')
    expect(wrapper.text()).toContain('151,970')
    expect(wrapper.text()).toContain('余额中心')
  })

  it('渲染余额中心五项真实指标', async () => {
    const wrapper = await renderView()
    const text = wrapper.text()
    expect(text).toContain('¥128.00')
    expect(text).toContain('¥500.00')
    expect(text).toContain('¥86.40')
    expect(text).toContain('累计提现')
    expect(text).toContain('累计消费')
  })

  it('渲染算力值/账户与真实配额', async () => {
    const wrapper = await renderView()
    const text = wrapper.text()
    expect(text).toContain('算力值')
    expect(text).toContain('2,000')
    expect(text).toContain('480')
    expect(text).toContain('累计获得')
    expect(text).toContain('累计消耗')
  })

  it('渲染当前套餐真实信息', async () => {
    const wrapper = await renderView()
    expect(wrapper.text()).toContain('当前套餐')
    expect(wrapper.text()).toContain('高级会员 Pro')
  })

  it('最近任务消耗展示用户问题+消耗算力，且不暴露 token 算式', async () => {
    const wrapper = await renderView()
    const text = wrapper.text()
    expect(text).toContain('帮我写一份会员营销方案')
    expect(text).toContain('-5')
    expect(text).not.toContain('token')
    expect(text).not.toContain('1000 token=1 算力')
  })

  it('渲染分销中心真实推荐码', async () => {
    const wrapper = await renderView()
    expect(wrapper.html()).toContain('YXINV-8888')
    expect(wrapper.text()).toContain('30%')
  })
})
