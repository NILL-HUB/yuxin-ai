import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminDashboardView from '@/views/admin/AdminDashboardView.vue'

const mocks = vi.hoisted(() => ({
  getAdminDashboardSummary: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-dashboard', () => ({
  getAdminDashboardSummary: mocks.getAdminDashboardSummary,
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: {
      error: mocks.messageError,
    },
  }
})

describe('AdminDashboardView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders workflow summary cards and quick entries', async () => {
    mocks.getAdminDashboardSummary.mockResolvedValue({
      workflow_total: 12,
      workflow_published: 5,
      workflow_draft: 4,
    })

    const wrapper = mount(AdminDashboardView, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a :href="String(to)"><slot /></a>' },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('管理总览')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.text()).toContain('进入工作流管理')
    expect(wrapper.html()).toContain('/admin/workflows')
  })

  it('shows error message when summary loading fails', async () => {
    mocks.getAdminDashboardSummary.mockRejectedValue(new Error('boom'))

    mount(AdminDashboardView, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a :href="String(to)"><slot /></a>' },
        },
      },
    })

    await flushPromises()

    expect(mocks.messageError).toHaveBeenCalled()
  })
})
