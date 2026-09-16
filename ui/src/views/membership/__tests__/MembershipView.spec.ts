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
  getCreditTransactions: vi.fn(),
  getBalanceProfile: vi.fn(),
  listWithdrawals: vi.fn(),
  listOrders: vi.fn(),
  listAutoRenewals: vi.fn(),
  getMyDistribution: vi.fn(),
  listPlans: vi.fn(),
  listPaymentMethods: vi.fn(),
  listSubordinates: vi.fn(),
  listMyCommissions: vi.fn(),
  getDistributionQrcode: vi.fn(),
}))

vi.mock('@/services/billing', () => ({
  getMembershipSummary: mocks.getMembershipSummary,
  getRedeemRecords: mocks.getRedeemRecords,
  getCreditTransactions: mocks.getCreditTransactions,
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
  listPaymentMethods: mocks.listPaymentMethods,
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

const renderView = async (
  paymentMethods: Array<{ provider: string; name: string; online: boolean }> = [
    { provider: 'balance', name: '余额', online: false },
  ],
) => {
  mocks.getMembershipSummary.mockResolvedValue(summary)
  mocks.getRedeemRecords.mockResolvedValue({ list: [] })
  mocks.getCreditTransactions.mockResolvedValue({
    list: [
      { id: 't1', amount: -35, description: '请帮我介绍一下杭州这座城市的特色和文化', transaction_type: 'consume', created_at: 1789000000, tx_count: 10, task_message: '请帮我介绍一下杭州这座城市的特色和文化' },
      { id: 't2', amount: 150000, description: '卡密兑换赠送算力值', transaction_type: 'redeem_grant', created_at: 1789000000 },
    ],
    total: 12,
    total_consumed: 5,
    page: 1,
    page_size: 10,
  })
  mocks.getBalanceProfile.mockResolvedValue({
    balance: 128, recharge_balance: 500, commission_balance: 86.4,
    total_withdrawn: 300, total_purchased: 1256.8,
    high_rate_locked: true, quota_credit: 2000, permanent_credit: 480,
  })
  mocks.listWithdrawals.mockResolvedValue({ list: [] })
  mocks.listOrders.mockResolvedValue({ list: [] })
  mocks.listAutoRenewals.mockResolvedValue({ list: [] })
  mocks.getMyDistribution.mockResolvedValue({
    referral_code: 'YXINV-8888', share_url: 'https://ai.yujianwo.cn/i/YXINV-8888',
    superior: null, subordinate_count: 8, high_rate_locked: true, commission_rate: '30',
  })
  mocks.listPlans.mockResolvedValue({ list: [], paginator: { total_record: 0 } })
  mocks.listPaymentMethods.mockResolvedValue({ list: paymentMethods })
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

  it('算力流水卡片展示累计消耗角标与分页明细', async () => {
    const wrapper = await renderView()
    const text = wrapper.text()
    expect(text).toContain('算力流水')
    expect(text).toContain('累计消耗 5 算力')
    expect(text).toContain('卡密兑换赠送算力值')
    expect(text).toContain('1 / 2 · 共 12 条')
  })

  it('消费流水按任务聚合：展示用户消息、聚合笔数与任务合计', async () => {
    const wrapper = await renderView()
    const text = wrapper.text()
    // 用户消息原文作为任务内容
    expect(text).toContain('请帮我介绍一下杭州这座城市的特色和文化')
    // 聚合笔数 meta
    expect(text).toContain('10 次模型调用')
    // 任务级合计 -35（不再逐笔展示 -1/-2 碎片）
    expect(text).toContain('-35')
    expect(text).not.toContain('扣减 5（1000 token')
  })

  it('算力流水翻页触发下一页请求', async () => {
    mocks.getCreditTransactions.mockResolvedValueOnce({
      list: [
        { id: 't2', amount: 150000, description: '卡密兑换赠送算力值', transaction_type: 'redeem_grant', created_at: 1789000000 },
      ],
      total: 12,
      total_consumed: 2058,
      page: 1,
      page_size: 10,
    })
    mocks.getCreditTransactions.mockResolvedValueOnce({
      list: [
        { id: 't10', amount: -3, description: '模型对话算力消耗', transaction_type: 'consume', created_at: 1789000100, tx_count: 1 },
      ],
      total: 12,
      total_consumed: 2058,
      page: 2,
      page_size: 10,
    })
    const wrapper = await renderView()
    expect(wrapper.text()).toContain('累计消耗 2,058 算力')
    const nextBtn = wrapper.find('.pager-btn:last-of-type')
    expect(nextBtn.exists()).toBe(true)
    await nextBtn.trigger('click')
    await flushPromises()
    expect(mocks.getCreditTransactions).toHaveBeenCalledWith({ page: 2, page_size: 10 })
    expect(wrapper.text()).toContain('模型对话算力消耗')
  })

  it('在线渠道全部停用时，充值区不显示微信/支付宝并给出提示', async () => {
    mocks.listPaymentMethods.mockResolvedValue({
      list: [{ provider: 'balance', name: '余额', online: false }],
    })
    const wrapper = await renderView()
    // 展开“余额充值”面板
    const summaries = wrapper.findAll('summary')
    const topupSummary = summaries.find((s) => s.text().includes('余额充值'))
    expect(topupSummary).toBeTruthy()
    await topupSummary!.trigger('click')
    await flushPromises()
    const text = wrapper.text()
    expect(text).not.toContain('微信支付')
    expect(text).not.toContain('支付宝')
    expect(text).toContain('在线支付渠道暂未开通')
  })

  it('仅启用微信时充值区只显示微信，不显示支付宝', async () => {
    const wrapper = await renderView([
      { provider: 'balance', name: '余额', online: false },
      { provider: 'wechat', name: '微信支付', online: true },
    ])
    const summaries = wrapper.findAll('summary')
    const topupSummary = summaries.find((s) => s.text().includes('余额充值'))
    await topupSummary!.trigger('click')
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('微信支付')
    expect(html).not.toContain('支付宝')
  })

  it('购买方式按开关动态渲染：仅余额时只出现余额', async () => {
    const wrapper = await renderView()
    const summaries = wrapper.findAll('summary')
    const planSummary = summaries.find((s) => s.text().includes('套餐购买'))
    await planSummary!.trigger('click')
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('购买方式')
    expect(html).toContain('value="balance"')
    expect(html).not.toContain('value="wechat"')
    expect(html).not.toContain('value="alipay"')
  })
})
