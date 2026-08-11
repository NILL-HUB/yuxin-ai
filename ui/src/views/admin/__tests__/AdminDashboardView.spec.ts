import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AdminDashboardView from '@/views/admin/AdminDashboardView.vue'
import { useAdminStore } from '@/stores/admin'

const mocks = vi.hoisted(() => ({
  getAdminDashboardSummary: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-dashboard', () => ({
  getAdminDashboardSummary: mocks.getAdminDashboardSummary,
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual =
    await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: {
      error: mocks.messageError,
    },
  }
})

const summary = {
  workflows: { total: 12, published: 5, draft: 4 },
  apps: { total: 9, published: 3 },
  users: { total: 20, active: 15 },
  models: { total: 30, active: 22 },
  agentPool: { total: 8, enabled: 6, healthy: 5 },
  mcp: { total: 7, published: 2 },
  tools: { total: 11 },
  skills: { total: 6, enabled: 2 },
  storage: { active_backend: 's3', files: 6, size: 3072 },
  routing: {
    total_count: 42,
    success_count: 38,
    fallback_count: 2,
    total_credits: 120,
    avg_latency_ms: 850,
    agent_pool_hit_rate: 0.9,
    tool_pool_hit_rate: 0.8,
  },
  recentRoutingLogs: [
    {
      id: 'route-1',
      user_query: 'hello',
      status: 'success',
      created_at: 1893456000,
      routing_decision: { execution_mode: 'auto' },
    },
  ],
  audits: [
    {
      id: 'audit-1',
      action: 'create',
      resource_type: 'workflow',
      admin_user_name: 'admin',
      created_at: 1893456000,
    },
  ],
  recycleBin: 3,
  costs: { total_credits: 500, total_requests: 100, avg_cost_per_request: 5 },
}

const mountDashboard = () => {
  return mount(AdminDashboardView, {
    global: {
      stubs: {
        RouterLink: { props: ['to'], template: '<a :href="String(to)"><slot /></a>' },
        'a-button': { template: '<button type="button"><slot /></button>' },
        'a-tag': { props: ['color'], template: '<span><slot /></span>' },
      },
    },
  })
}

describe('AdminDashboardView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    useAdminStore().update({
      id: 'admin-1',
      username: 'admin',
      email: '',
      name: 'Root',
      avatar: '',
      status: 'active',
      roles: ['super_admin'],
      permissions: [
        'workflow:read',
        'app:read',
        'user:read',
        'model_pool:read',
        'agent_pool:read',
        'mcp:read',
        'tool:read',
        'skill:read',
        'storage:read',
        'routing_log:read',
        'audit_log:read',
        'recycle_bin:read',
        'cost_stats:read',
      ],
    })
  })

  it('renders resource stats and recent activity from admin domains', async () => {
    mocks.getAdminDashboardSummary.mockResolvedValue(summary)

    const wrapper = mountDashboard()

    await flushPromises()

    expect(mocks.getAdminDashboardSummary).toHaveBeenCalledWith([
      'workflow:read',
      'app:read',
      'user:read',
      'model_pool:read',
      'agent_pool:read',
      'mcp:read',
      'tool:read',
      'skill:read',
      'storage:read',
      'routing_log:read',
      'audit_log:read',
      'recycle_bin:read',
      'cost_stats:read',
    ])
    expect(wrapper.text()).toContain('管理总览')
    expect(wrapper.text()).toContain('工作流')
    expect(wrapper.text()).toContain('AI 应用')
    expect(wrapper.text()).toContain('用户')
    expect(wrapper.text()).toContain('模型')
    expect(wrapper.text()).toContain('Agent 池')
    expect(wrapper.text()).toContain('MCP')
    expect(wrapper.text()).toContain('API 工具')
    expect(wrapper.text()).toContain('Skills')
    expect(wrapper.text()).toContain('hello')
    expect(wrapper.text()).toContain('创建')
    expect(wrapper.text()).toContain('workflow')
    expect(wrapper.html()).toContain('/admin/workflows')
    expect(wrapper.html()).toContain('/admin/cost-stats')
  })

  it('shows error message when summary loading fails', async () => {
    mocks.getAdminDashboardSummary.mockRejectedValue(new Error('boom'))

    mountDashboard()

    await flushPromises()

    expect(mocks.messageError).toHaveBeenCalled()
  })
})
