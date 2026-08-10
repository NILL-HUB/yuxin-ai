import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import MembershipView from '@/views/membership/MembershipView.vue'

vi.mock('@/services/billing', () => ({
  getMembershipSummary: vi.fn().mockResolvedValue({
    credit_account: { balance: 100, total_granted: 500, total_consumed: 400 },
    membership: { plan: { name: '标准版' }, expires_at: 1789000000 },
    recent_transactions: [],
  }),
  getRedeemRecords: vi.fn().mockResolvedValue({ list: [] }),
  redeemCode: vi.fn().mockResolvedValue({}),
}))

vi.mock('@/utils/error', () => ({
  getErrorMessage: (e: unknown, fallback: string) => fallback,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: { error: vi.fn(), success: vi.fn() },
  Input: { template: '<input />' },
  Button: { template: '<button><slot /></button>' },
}))

describe('MembershipView', () => {
  it('renders membership page content', async () => {
    const wrapper = mount(MembershipView, {
      global: { stubs: { 'a-input': true, 'a-button': true } },
    })
    await new Promise((r) => setTimeout(r, 50))
    expect(wrapper.text()).toContain('我的会员')
    expect(wrapper.text()).toContain('当前算力值')
  })
})
