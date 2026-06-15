import { type BaseResponse } from '@/models/base'
import {
  type ConfirmMemoryCandidateRequest,
  type IgnoreMemoryCandidateRequest,
  type MemoryCandidate,
  type UserMemory,
} from '@/models/memory'
import { post } from '@/utils/request'

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
