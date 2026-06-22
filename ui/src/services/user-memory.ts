import { type BaseResponse } from '@/models/base'
import { get, post, del } from '@/utils/request'

export interface UserMemory {
  id: string
  memory_type: string
  content: string
  confidence: number
  status: string
  scope: string
  created_from: string
  created_at: number
  updated_at: number
}

export interface MemoryCandidate {
  id: string
  memory_type: string
  content: string
  confidence: number
  occurrences: number
  status: string
  extracted_at?: number
}

export const listUserMemories = () =>
  get<BaseResponse<{ items: UserMemory[]; total: number }>>('/user/memory').then((res) => res.data.items)

export const createUserMemory = (data: {
  memory_type: string
  content: string
  confidence?: number
}) => post<BaseResponse<UserMemory>>('/user/memory', { body: data }).then((res) => res.data)

export const getUserMemory = (id: string) =>
  get<BaseResponse<UserMemory>>(`/user/memory/${id}`).then((res) => res.data)

export const updateUserMemory = (
  id: string,
  data: { content?: string; memory_type?: string; enabled?: boolean },
) => post<BaseResponse<UserMemory>>(`/user/memory/${id}`, { body: data }).then((res) => res.data)

export const deleteUserMemory = (id: string) =>
  del<BaseResponse<{ id: string }>>(`/user/memory/${id}`).then((res) => res.data)

export const listMemoryCandidates = () =>
  get<BaseResponse<MemoryCandidate[]>>('/memory-candidates').then((res) => res.data)

export const confirmMemoryCandidate = (
  id: string,
  policy: 'manual_confirm' | 'auto_save' = 'manual_confirm',
) =>
  post<BaseResponse<UserMemory>>(`/memory-candidates/${id}/confirm`, { body: { policy } }).then(
    (res) => res.data,
  )

export const ignoreMemoryCandidate = (id: string, never_remind: boolean = false) =>
  post<BaseResponse<MemoryCandidate>>(`/memory-candidates/${id}/ignore`, {
    body: { never_remind },
  }).then((res) => res.data)
