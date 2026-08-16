import { type BaseResponse } from '@/models/base'
import { get, post } from '@/utils/request'
import type {
  ClusterSubgraph,
  ConsolidationResp,
  DecayMemoryResp,
  DeleteMemoryResp,
  EditMemoryResp,
  MemoryDigestResp,
  MemoryDetail,
  MemoryGraphData,
  MemoryHealth,
  MemoryRetrieveReq,
  MemoryRetrieveResp,
  MemoryWriteReq,
  MemoryWriteResp,
  SkillListResponse,
} from '@/models/memory-graph'

// 写入记忆
export const writeMemory = (data: MemoryWriteReq) =>
  post<BaseResponse<MemoryWriteResp>>('/memory/write', { body: data }).then((res) => res.data)

// 检索记忆
export const retrieveMemory = (data: MemoryRetrieveReq) =>
  post<BaseResponse<MemoryRetrieveResp>>('/memory/retrieve', { body: data }).then((res) => res.data)

// 获取记忆 Digest
export const getMemoryDigest = (userId: string) =>
  get<BaseResponse<MemoryDigestResp>>(`/memory/digest/${userId}`).then((res) => res.data)

// 触发巩固（同步模式）
export const triggerConsolidation = (userId: string) =>
  post<BaseResponse<ConsolidationResp>>(`/memory/consolidate/${userId}`).then((res) => res.data)

// 获取记忆图谱聚类视图
export const getMemoryGraph = (userId: string) =>
  get<BaseResponse<MemoryGraphData>>(`/memory/graph/${userId}`).then((res) => res.data)

// 获取聚类子图
export const getClusterSubgraph = (userId: string, clusterType: string) =>
  get<BaseResponse<ClusterSubgraph>>(`/memory/graph/${userId}/cluster/${clusterType}`).then(
    (res) => res.data,
  )

// 获取单条记忆详情
export const getMemoryDetail = (memoryId: string) =>
  get<BaseResponse<MemoryDetail>>(`/memory/${memoryId}`).then((res) => res.data)

// 编辑记忆（创建新版本 + 旧版本失效）
export const editMemory = (memoryId: string, newContent: string) =>
  post<BaseResponse<EditMemoryResp>>(`/memory/${memoryId}/edit`, {
    body: { new_content: newContent },
  }).then((res) => res.data)

// 软删除记忆（进入回收站，可指定留存天数）
export const softDeleteMemory = (memoryId: string, retentionDays?: number) =>
  post<BaseResponse<DeleteMemoryResp>>(`/memory/${memoryId}/soft-delete`, {
    body: retentionDays ? { retention_days: retentionDays } : undefined,
  }).then((res) => res.data)

// 彻底删除记忆
export const hardDeleteMemory = (memoryId: string) =>
  post<BaseResponse<DeleteMemoryResp>>(`/memory/${memoryId}/hard-delete`).then((res) => res.data)

// 手动降权
export const decayMemory = (memoryId: string, decayFactor: number, reason?: string) =>
  post<BaseResponse<DecayMemoryResp>>(`/memory/${memoryId}/decay`, {
    body: { decay_factor: decayFactor, reason },
  }).then((res) => res.data)

// 获取技能列表
export const listSkills = (userId: string) =>
  get<BaseResponse<SkillListResponse>>(`/memory/skills/${userId}`).then((res) => res.data)

// 健康检查
export const getMemoryHealth = () =>
  get<BaseResponse<MemoryHealth>>('/memory/health').then((res) => res.data)
