import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getAdminDashboardSummary } from '@/services/admin-dashboard'

const mocks = vi.hoisted(() => ({
  listAdminWorkflows: vi.fn(),
  listAdminApps: vi.fn(),
  listCustomerUsers: vi.fn(),
  listModels: vi.fn(),
  getAgentPoolStats: vi.fn(),
  listAdminMcpProviders: vi.fn(),
  listAdminApiTools: vi.fn(),
  listAdminSkills: vi.fn(),
  getStorageOverview: vi.fn(),
  listAdminRoutingLogs: vi.fn(),
  listAuditLogs: vi.fn(),
  listRecycleBin: vi.fn(),
  getCostStatsOverview: vi.fn(),
}))

vi.mock('@/services/admin-workflows', () => ({
  listAdminWorkflows: mocks.listAdminWorkflows,
}))
vi.mock('@/services/admin-apps', () => ({
  listAdminApps: mocks.listAdminApps,
}))
vi.mock('@/services/admin-customer-users', () => ({
  listCustomerUsers: mocks.listCustomerUsers,
}))
vi.mock('@/services/admin-model-pool', () => ({
  listModels: mocks.listModels,
}))
vi.mock('@/services/admin-agent-pool', () => ({
  getAgentPoolStats: mocks.getAgentPoolStats,
}))
vi.mock('@/services/admin-mcp', () => ({
  listAdminMcpProviders: mocks.listAdminMcpProviders,
}))
vi.mock('@/services/admin-tools', () => ({
  listAdminApiTools: mocks.listAdminApiTools,
}))
vi.mock('@/services/admin-skills', () => ({
  listAdminSkills: mocks.listAdminSkills,
}))
vi.mock('@/services/admin-storage', () => ({
  getStorageOverview: mocks.getStorageOverview,
}))
vi.mock('@/services/admin-routing-logs', () => ({
  listAdminRoutingLogs: mocks.listAdminRoutingLogs,
}))
vi.mock('@/services/admin-audit-logs', () => ({
  listAuditLogs: mocks.listAuditLogs,
}))
vi.mock('@/services/admin-recycle-bin', () => ({
  listRecycleBin: mocks.listRecycleBin,
}))
vi.mock('@/services/admin-cost-stats', () => ({
  getCostStatsOverview: mocks.getCostStatsOverview,
}))

const paginator = (totalRecord: number) => ({
  paginator: {
    total_record: totalRecord,
    total_page: 1,
    current_page: 1,
    page_size: 1,
  },
})

const envelope = <T>(data: T) => ({
  code: 'success',
  message: 'ok',
  data,
})

const ALL_PERMISSIONS = [
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
]

describe('admin dashboard service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('aggregates counts and recent activity from existing admin endpoints', async () => {
    mocks.listAdminWorkflows
      .mockResolvedValueOnce({ ...paginator(12), list: [] })
      .mockResolvedValueOnce({ ...paginator(5), list: [] })
      .mockResolvedValueOnce({ ...paginator(4), list: [] })
    mocks.listAdminApps
      .mockResolvedValueOnce({ ...paginator(9), list: [] })
      .mockResolvedValueOnce({ ...paginator(3), list: [] })
    mocks.listCustomerUsers
      .mockResolvedValueOnce({ ...paginator(20), list: [] })
      .mockResolvedValueOnce({ ...paginator(15), list: [] })
    mocks.listModels
      .mockResolvedValueOnce(envelope({ ...paginator(30), list: [] }))
      .mockResolvedValueOnce(envelope({ ...paginator(22), list: [] }))
    mocks.getAgentPoolStats.mockResolvedValueOnce(
      envelope({ list: [{ total: 8, enabled: 6, healthy: 5 }] }),
    )
    mocks.listAdminMcpProviders.mockResolvedValueOnce({
      ...paginator(7),
      list: [
        { id: 'mcp-1', is_public: true },
        { id: 'mcp-2', is_public: true },
        { id: 'mcp-3', is_public: false },
      ],
    })
    mocks.listAdminApiTools.mockResolvedValueOnce({ ...paginator(11), list: [] })
    mocks.listAdminSkills.mockResolvedValueOnce({
      ...paginator(6),
      list: [
        { id: 'skill-1', enabled: true },
        { id: 'skill-2', enabled: true },
        { id: 'skill-3', enabled: false },
      ],
    })
    mocks.getStorageOverview.mockResolvedValueOnce(
      envelope({
        active_backend: 's3',
        backend_items: [],
        stats: {
          local: { count: 4, size: 1024 },
          s3: { count: 2, size: 2048 },
        },
      }),
    )
    mocks.listAdminRoutingLogs.mockResolvedValueOnce(
      {
        list: [
          {
            id: 'route-1',
            user_query: 'hello',
            status: 'success',
            created_at: 1893456000,
            routing_decision: { execution_mode: 'auto' },
          },
        ],
        paginator: {},
        summary: {
          total_count: 42,
          success_count: 38,
          fallback_count: 2,
          total_credits: 120,
          avg_latency_ms: 850,
          agent_pool_hit_rate: 0.9,
          tool_pool_hit_rate: 0.8,
        },
      },
    )
    mocks.listAuditLogs.mockResolvedValueOnce(
      envelope({
        list: [
          {
            id: 'audit-1',
            action: 'create',
            resource_type: 'workflow',
            admin_user_name: 'admin',
            created_at: 1893456000,
          },
        ],
        paginator: { total_record: 5 },
      }),
    )
    mocks.listRecycleBin.mockResolvedValueOnce({
      items: [],
      total: 3,
      page: 1,
      page_size: 1,
      total_pages: 3,
      total_record: 3,
    })
    mocks.getCostStatsOverview.mockResolvedValueOnce({
      total_credits: 500,
      total_requests: 100,
      avg_cost_per_request: 5,
      total_input_tokens: 10,
      total_output_tokens: 20,
    })

    const result = await getAdminDashboardSummary(ALL_PERMISSIONS)

    expect(result.workflows).toEqual({ total: 12, published: 5, draft: 4 })
    expect(result.apps).toEqual({ total: 9, published: 3 })
    expect(result.users).toEqual({ total: 20, active: 15 })
    expect(result.models).toEqual({ total: 30, active: 22 })
    expect(result.agentPool).toEqual({ total: 8, enabled: 6, healthy: 5 })
    expect(result.mcp).toEqual({ total: 7, published: 2 })
    expect(result.tools).toEqual({ total: 11 })
    expect(result.skills).toEqual({ total: 6, enabled: 2 })
    expect(result.storage).toEqual({
      active_backend: 's3',
      files: 6,
      size: 3072,
    })
    expect(result.routing.total_count).toBe(42)
    expect(result.recentRoutingLogs).toHaveLength(1)
    expect(result.audits).toHaveLength(1)
    expect(result.recycleBin).toBe(3)
    expect(result.costs).toEqual({
      total_credits: 500,
      total_requests: 100,
      avg_cost_per_request: 5,
    })
  })

  it('skips domains the admin has no permission to read', async () => {
    const result = await getAdminDashboardSummary(['admin:access'])

    expect(mocks.listAdminWorkflows).not.toHaveBeenCalled()
    expect(mocks.listAdminApps).not.toHaveBeenCalled()
    expect(mocks.listCustomerUsers).not.toHaveBeenCalled()
    expect(mocks.listModels).not.toHaveBeenCalled()
    expect(mocks.getAgentPoolStats).not.toHaveBeenCalled()
    expect(result).toMatchObject({
      workflows: { total: 0, published: 0, draft: 0 },
      apps: { total: 0, published: 0 },
      users: { total: 0, active: 0 },
      models: { total: 0, active: 0 },
      agentPool: { total: 0, enabled: 0, healthy: 0 },
      mcp: { total: 0, published: 0 },
      tools: { total: 0 },
      skills: { total: 0, enabled: 0 },
    })
  })
})
