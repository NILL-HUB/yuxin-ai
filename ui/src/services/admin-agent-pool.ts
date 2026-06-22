import { get, post, del, request } from '@/utils/request'

const patch = (url: string, body?: Record<string, unknown>) =>
  request(url, { method: 'PATCH', body })

export const listAgentPoolConfigs = (params?: Record<string, unknown>) =>
  get('/admin/agent-pool', { params })
export const createAgentPoolConfig = (data: Record<string, unknown>) =>
  post('/admin/agent-pool', { body: data })
export const getAgentPoolConfig = (id: string) => get(`/admin/agent-pool/${id}`)
export const updateAgentPoolConfig = (id: string, data: Record<string, unknown>) =>
  patch(`/admin/agent-pool/${id}`, data)
export const deleteAgentPoolConfig = (id: string) => del(`/admin/agent-pool/${id}`)
export const setAgentPoolStatus = (id: string, enabled: boolean) =>
  post(`/admin/agent-pool/${id}/status`, { body: { enabled: enabled ? 'true' : 'false' } })
export const checkAgentHealth = (id: string) =>
  post(`/admin/agent-pool/${id}/health`, { body: {} })
export const getAgentPoolStats = () => get('/admin/agent-pool/stats')
