import { del, get, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  GetRecycleBinRequest,
  RecycleBinPageData,
  RecycleBinPageResponse,
} from '@/models/recycle-bin'

/**
 * 获取回收站条目列表，并解包接口返回的 data 字段。
 */
export const listRecycleBin = async (
  req: GetRecycleBinRequest,
): Promise<RecycleBinPageData> => {
  const response = await get<RecycleBinPageResponse>('/admin/recycle-bin', { params: req })
  return response.data
}

/**
 * 恢复回收站条目（按删除时的快照重建原资源）。
 */
export const restoreRecycleBinItem = async (id: number): Promise<void> => {
  await post<BaseResponse<unknown>>(`/admin/recycle-bin/${id}/restore`)
}

/**
 * 一键清理所有已销毁（expired）的回收站记录，终止无限堆积。
 */
export const cleanupExpiredRecycleBin = async (): Promise<number> => {
  const response = await del<BaseResponse<{ cleaned: number }>>('/admin/recycle-bin/expired')
  return response.data?.cleaned ?? 0
}

export type RecycleBinOverviewData = {
  total: number
  pending_total: number
  by_status: Array<{ name: string; count: number }>
  by_resource_type: Array<{ name: string; count: number }>
  by_deleted_by_type: Array<{ name: string; count: number }>
}

export type GetRecycleBinOverviewRequest = {
  resource_type?: string
  status?: string
  search_word?: string
  deleted_by_type?: string
}

export const getRecycleBinOverview = async (
  req: GetRecycleBinOverviewRequest = {},
): Promise<RecycleBinOverviewData> => {
  const response = await get<BaseResponse<RecycleBinOverviewData>>('/admin/recycle-bin/overview', {
    params: req,
  })
  return response.data
}
