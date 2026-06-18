import { type BaseResponse } from '@/models/base'
import {
  type ConfirmMemoryCandidateRequest,
  type IgnoreMemoryCandidateRequest,
  type MemoryCandidate,
  type UserMemory,
} from '@/models/memory'
import { get, post, request } from '@/utils/request'

export const confirmMemoryCandidate = (
  candidateId: string,
  req: ConfirmMemoryCandidateRequest,
) => {
  return post<BaseResponse<UserMemory>>(`/memory-candidates/${candidateId}/confirm`, {
    body: req,
  })
}

export const ignoreMemoryCandidate = (
  candidateId: string,
  req: IgnoreMemoryCandidateRequest,
) => {
  return post<BaseResponse<MemoryCandidate>>(`/memory-candidates/${candidateId}/ignore`, {
    body: req,
  })
}

export type CreateUserMemoryRequest = {
  content: string
  memory_type: string
}

export type UpdateUserMemoryRequest = {
  content: string
  memory_type: string
  enabled: boolean
}

export const getUserMemories = () => {
  return get<BaseResponse<Array<UserMemory>>>(`/user/memory`)
}

export const createUserMemory = (req: CreateUserMemoryRequest) => {
  return post<BaseResponse<UserMemory>>(`/user/memory`, { body: req })
}

export const getUserMemory = (id: string) => {
  return get<BaseResponse<UserMemory>>(`/user/memory/${id}`)
}

export const updateUserMemory = (id: string, req: UpdateUserMemoryRequest) => {
  return post<BaseResponse<UserMemory>>(`/user/memory/${id}`, { body: req })
}

export const deleteUserMemory = (id: string) => {
  return request<BaseResponse<null>>(`/user/memory/${id}`, { method: 'DELETE' })
}
