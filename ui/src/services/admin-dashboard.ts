import { listAdminWorkflows } from '@/services/admin-workflows'
import { listAdminApps } from '@/services/admin-apps'
import { listCustomerUsers } from '@/services/admin-customer-users'
import { listModels } from '@/services/admin-model-pool'
import { getAgentPoolStats } from '@/services/admin-agent-pool'
import { listAdminMcpProviders } from '@/services/admin-mcp'
import { listAdminApiTools } from '@/services/admin-tools'
import { listAdminSkills } from '@/services/admin-skills'
import { getStorageOverview } from '@/services/admin-storage'
import { listAdminRoutingLogs } from '@/services/admin-routing-logs'
import { listAuditLogs, type AuditLog, type AuditLogListData } from '@/services/admin-audit-logs'
import { listRecycleBin } from '@/services/admin-recycle-bin'
import { getCostStatsOverview } from '@/services/admin-cost-stats'
import type { AdminRoutingLogRecord, AdminRoutingLogSummary } from '@/models/admin-routing-log'
import type { StorageOverviewData } from '@/models/admin-storage'

export type AdminDashboardSummary = {
  workflows: { total: number; published: number; draft: number }
  apps: { total: number; published: number }
  users: { total: number; active: number }
  models: { total: number; active: number }
  agentPool: { total: number; enabled: number; healthy: number }
  mcp: { total: number; published: number }
  tools: { total: number }
  skills: { total: number; enabled: number }
  storage: { active_backend: string; files: number; size: number }
  routing: AdminRoutingLogSummary
  recentRoutingLogs: AdminRoutingLogRecord[]
  audits: AuditLog[]
  recycleBin: number
  costs: { total_credits: number; total_requests: number; avg_cost_per_request: number }
}

type PaginatorData = { paginator?: { total_record?: number } }

const pageTotal = (data: PaginatorData | undefined) => {
  return Number(data?.paginator?.total_record ?? 0)
}

const readEnvelopeData = <T>(response: unknown): T | undefined => {
  return (response as { data?: T } | undefined)?.data
}

const createEmptySummary = (): AdminDashboardSummary => ({
  workflows: { total: 0, published: 0, draft: 0 },
  apps: { total: 0, published: 0 },
  users: { total: 0, active: 0 },
  models: { total: 0, active: 0 },
  agentPool: { total: 0, enabled: 0, healthy: 0 },
  mcp: { total: 0, published: 0 },
  tools: { total: 0 },
  skills: { total: 0, enabled: 0 },
  storage: { active_backend: '', files: 0, size: 0 },
  routing: {
    total_count: 0,
    success_count: 0,
    fallback_count: 0,
    total_credits: 0,
    avg_latency_ms: 0,
    agent_pool_hit_rate: 0,
    tool_pool_hit_rate: 0,
  },
  recentRoutingLogs: [],
  audits: [],
  recycleBin: 0,
  costs: { total_credits: 0, total_requests: 0, avg_cost_per_request: 0 },
})

/**
 * 聚合后台各管理域已有接口，生成管理总览数据。
 * 单个域接口失败时不会拖垮整页，未授权或未配置的域保持空值。
 */
export const getAdminDashboardSummary = async (
  permissions: string[] = [],
): Promise<AdminDashboardSummary> => {
  const hasPermission = (permission: string) => permissions.includes(permission)

  const guarded = async <T>(
    permission: string,
    loader: () => Promise<T>,
  ): Promise<T | undefined> => {
    if (!hasPermission(permission)) return undefined
    try {
      return await loader()
    } catch {
      return undefined
    }
  }

  const now = Math.floor(Date.now() / 1000)
  const sevenDaysAgo = now - 7 * 24 * 60 * 60

  const [
    workflows,
    workflowsPublished,
    workflowsDraft,
    apps,
    appsPublished,
    users,
    usersActive,
    models,
    modelsActive,
    agentPoolStats,
    mcp,
    tools,
    skills,
    storage,
    routingResponse,
    auditResponse,
    recycleBin,
    costs,
  ] = await Promise.all([
    guarded('workflow:read', () =>
      listAdminWorkflows({ search: '', status: 'all', current_page: 1, page_size: 1 }),
    ),
    guarded('workflow:read', () =>
      listAdminWorkflows({ search: '', status: 'published', current_page: 1, page_size: 1 }),
    ),
    guarded('workflow:read', () =>
      listAdminWorkflows({ search: '', status: 'draft', current_page: 1, page_size: 1 }),
    ),
    guarded('app:read', () => listAdminApps({ current_page: 1, page_size: 1, status: 'all' })),
    guarded('app:read', () =>
      listAdminApps({ current_page: 1, page_size: 1, status: 'published' }),
    ),
    guarded('user:read', () => listCustomerUsers({ current_page: 1, page_size: 1 })),
    guarded('user:read', () =>
      listCustomerUsers({ current_page: 1, page_size: 1, status: 'active' }),
    ),
    guarded('model_pool:read', () => listModels({ current_page: 1, page_size: 1 })),
    guarded('model_pool:read', () =>
      listModels({ current_page: 1, page_size: 1, status: 'active' }),
    ),
    guarded('agent_pool:read', () => getAgentPoolStats()),
    guarded('mcp:read', () => listAdminMcpProviders({ current_page: 1, page_size: 100 })),
    guarded('tool:read', () => listAdminApiTools({ current_page: 1, page_size: 1 })),
    guarded('skill:read', () => listAdminSkills({ current_page: 1, page_size: 100 })),
    guarded('storage:read', () => getStorageOverview()),
    guarded('routing_log:read', () => listAdminRoutingLogs({ current_page: 1, page_size: 6 })),
    guarded('audit_log:read', () => listAuditLogs({ current_page: 1, page_size: 6 })),
    guarded('recycle_bin:read', () => listRecycleBin({ page: 1, page_size: 1 })),
    guarded('cost_stats:read', () =>
      getCostStatsOverview({
        start_at: String(sevenDaysAgo),
        end_at: String(now),
      }),
    ),
  ])

  const modelTotal = pageTotal(readEnvelopeData<PaginatorData>(models))
  const modelActiveTotal = pageTotal(readEnvelopeData<PaginatorData>(modelsActive))
  const agentPoolItem = readEnvelopeData<{
    list?: Array<{ total?: number; enabled?: number; healthy?: number }>
  }>(agentPoolStats)?.list?.[0]
  const storageData = readEnvelopeData<StorageOverviewData>(storage)
  const storageValues = Object.values(storageData?.stats ?? {}) as Array<{
    count?: number
    size?: number
  }>
  const routingData = routingResponse
  const auditData = readEnvelopeData<AuditLogListData>(auditResponse)

  const summary = createEmptySummary()
  summary.workflows = {
    total: pageTotal(workflows),
    published: pageTotal(workflowsPublished),
    draft: pageTotal(workflowsDraft),
  }
  summary.apps = {
    total: pageTotal(apps),
    published: pageTotal(appsPublished),
  }
  summary.users = {
    total: pageTotal(users),
    active: pageTotal(usersActive),
  }
  summary.models = {
    total: modelTotal,
    active: modelActiveTotal,
  }
  summary.agentPool = {
    total: Number(agentPoolItem?.total ?? 0),
    enabled: Number(agentPoolItem?.enabled ?? 0),
    healthy: Number(agentPoolItem?.healthy ?? 0),
  }
  summary.mcp = {
    total: pageTotal(mcp),
    published: (mcp?.list ?? []).filter((item) => item.is_public).length,
  }
  summary.tools = {
    total: pageTotal(tools),
  }
  summary.skills = {
    total: pageTotal(skills),
    enabled: (skills?.list ?? []).filter((item) => item.enabled).length,
  }
  summary.storage = {
    active_backend: storageData?.active_backend || '',
    files: storageValues.reduce((total, item) => total + Number(item.count ?? 0), 0),
    size: storageValues.reduce((total, item) => total + Number(item.size ?? 0), 0),
  }
  summary.routing = routingData?.summary ?? summary.routing
  summary.recentRoutingLogs = routingData?.list ?? []
  summary.audits = auditData?.list ?? []
  summary.recycleBin = recycleBin?.total_record ?? recycleBin?.total ?? 0
  summary.costs = {
    total_credits: costs?.total_credits ?? 0,
    total_requests: costs?.total_requests ?? 0,
    avg_cost_per_request: costs?.avg_cost_per_request ?? 0,
  }

  return summary
}
