import { get, post, del, request } from '@/utils/request'

const patch = (url: string, body?: Record<string, unknown>) =>
  request(url, { method: 'PATCH', body })
const put = (url: string, body?: Record<string, unknown>) =>
  request(url, { method: 'PUT', body })

export const listModels = (params?: Record<string, unknown>) =>
  get('/admin/models', { params })
export const createModel = (data: Record<string, unknown>) =>
  post('/admin/models', { body: data })
export const getModel = (id: string) => get(`/admin/models/${id}`)
export const updateModel = (id: string, data: Record<string, unknown>) =>
  patch(`/admin/models/${id}`, data)
export const deleteModel = (id: string) => del(`/admin/models/${id}`)
export const setModelStatus = (id: string, enabled: boolean) =>
  post(`/admin/models/${id}/status`, { body: { status: enabled ? 'active' : 'disabled' } })

export const listModelKeys = (params?: Record<string, unknown>) =>
  get('/admin/model-keys', { params })
export const createModelKey = (data: Record<string, unknown>) =>
  post('/admin/model-keys', { body: data })
export const updateModelKey = (id: string, data: Record<string, unknown>) =>
  patch(`/admin/model-keys/${id}`, data)
export const deleteModelKey = (id: string) => del(`/admin/model-keys/${id}`)
export const setModelKeyStatus = (id: string, enabled: boolean) =>
  post(`/admin/model-keys/${id}/status`, { body: { status: enabled ? 'active' : 'disabled' } })

export const listTierPolicies = () => get('/admin/model-tiers')
export const updateTierPolicy = (tierCode: string, data: Record<string, unknown>) =>
  put(`/admin/model-tiers/${tierCode}`, data)

export const listCostPolicies = () => get('/admin/cost-policies')
export const updateCostPolicy = (id: string, data: Record<string, unknown>) =>
  put(`/admin/cost-policies/${id}`, data)
