import { get, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

export interface ShowcaseCase {
  id: string
  conversation_id: string
  title: string
  summary: string
  query: string
  answer: string
  tags: string[]
  rating: number
  status: string
  contributor?: string
  created_at: number
}

export const createShowcaseCase = (data: {
  conversation_id: string
  title: string
  summary?: string
  query: string
  answer: string
  tags?: string[]
  rating?: number
}) => post<BaseResponse<{ id: string }>>('/showcase/cases', { body: data })

export const listPublicShowcaseCases = (params?: {
  page?: number
  per_page?: number
  tag?: string
  keyword?: string
}) => get<BaseResponse<{ data: ShowcaseCase[]; total: number }>>('/showcase/cases', { params })

export const getShowcaseCase = (id: string) =>
  get<BaseResponse<ShowcaseCase>>(`/showcase/cases/${id}`)

export const adminListShowcaseCases = (params?: {
  page?: number
  per_page?: number
  status?: string
}) => get<BaseResponse<{ data: ShowcaseCase[]; total: number }>>('/admin/showcase/cases', { params })

export const approveShowcaseCase = (id: string) =>
  post<BaseResponse<{ ok: boolean }>>(`/admin/showcase/cases/${id}/approve`, { body: {} })

export const rejectShowcaseCase = (id: string, reason?: string) =>
  post<BaseResponse<{ ok: boolean }>>(`/admin/showcase/cases/${id}/reject`, { body: { reason } })

export const offlineShowcaseCase = (id: string) =>
  post<BaseResponse<{ ok: boolean }>>(`/admin/showcase/cases/${id}/offline`, { body: {} })
