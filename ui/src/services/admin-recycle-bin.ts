import { get, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  GetRecycleBinRequest,
  RecycleBinDetailResponse,
  RecycleBinPageData,
  RecycleBinPageResponse,
} from '@/models/admin-recycle-bin'

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
