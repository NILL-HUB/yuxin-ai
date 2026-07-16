import { get, post, del, request } from '@/utils/request'

const patch = (url: string, body?: Record<string, unknown>) =>
  request(url, { method: 'PATCH', body })

export const listModelProviders = (params?: Record<string, unknown>) =>
  get('/admin/model-providers', { params })
export const getModelProvider = (id: string) => get(`/admin/model-providers/${id}`)
export const createModelProvider = (data: Record<string, unknown>) =>
  post('/admin/model-providers', { body: data })
export const updateModelProvider = (id: string, data: Record<string, unknown>) =>
  patch(`/admin/model-providers/${id}`, data)
export const deleteModelProvider = (id: string) => del(`/admin/model-providers/${id}`)
export const setModelProviderStatus = (id: string, status: string) =>
  post(`/admin/model-providers/${id}/status`, { body: { status } })
export const listProviderOptions = () => get('/admin/model-providers/options')
