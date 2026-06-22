import { get, post, del, request } from '@/utils/request'

const patch = (url: string, body?: Record<string, unknown>) =>
  request(url, { method: 'PATCH', body })

export const listToolPolicies = (params?: Record<string, unknown>) =>
  get('/admin/tool-governance', { params })
export const createToolPolicy = (data: Record<string, unknown>) =>
  post('/admin/tool-governance', { body: data })
export const getToolPolicy = (id: string) => get(`/admin/tool-governance/${id}`)
export const updateToolPolicy = (id: string, data: Record<string, unknown>) =>
  patch(`/admin/tool-governance/${id}`, data)
export const deleteToolPolicy = (id: string) => del(`/admin/tool-governance/${id}`)
export const setToolPolicyStatus = (id: string, enabled: boolean) =>
  post(`/admin/tool-governance/${id}/status`, { body: { enabled } })
export const batchUpdateRisk = (ids: string[], riskLevel: string) =>
  post('/admin/tool-governance/batch-risk', { body: { policy_ids: ids, risk_level: riskLevel } })
export const listToolAuditLogs = (params?: Record<string, unknown>) =>
  get('/admin/tool-governance/audit', { params })
export const getToolGovernanceStats = () => get('/admin/tool-governance/stats')
