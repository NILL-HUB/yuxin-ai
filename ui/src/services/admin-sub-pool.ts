import { get, post, del, request } from '@/utils/request'

const patch = (url: string, body?: Record<string, unknown>) =>
  request(url, { method: 'PATCH', body })

const put = (url: string, body?: Record<string, unknown>) =>
  request(url, { method: 'PUT', body })

export const listSubPoolDefinitions = (params?: Record<string, unknown>) =>
  get('/admin/sub-pool-definitions', { params })

export const createSubPoolDefinition = (data: Record<string, unknown>) =>
  post('/admin/sub-pool-definitions', { body: data })

export const getSubPoolDefinition = (id: string) =>
  get(`/admin/sub-pool-definitions/${id}`)

export const updateSubPoolDefinition = (id: string, data: Record<string, unknown>) =>
  patch(`/admin/sub-pool-definitions/${id}`, data)

export const deleteSubPoolDefinition = (id: string) =>
  del(`/admin/sub-pool-definitions/${id}`)

export const setSubPoolStatus = (id: string, enabled: boolean) =>
  post(`/admin/sub-pool-definitions/${id}/status`, { body: { enabled: enabled ? 'true' : 'false' } })
