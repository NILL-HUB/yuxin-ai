import { del, get, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  GetRecycleBinRequest,
  RecycleBinPageData,
  RecycleBinPageResponse,
} from '@/models/recycle-bin'

/**
 * 获取当前账号回收站条目列表（用户删除 + agent 代删，按身份隔离）。
 */
export const listUserRecycleBin = async (
  req: GetRecycleBinRequest,
): Promise<RecycleBinPageData> => {
  const response = await get<RecycleBinPageResponse>('/space/recycle-bin', { params: req })
  return response.data
}

/**
 * 恢复当前账号回收站条目（agent 代删内容同样可恢复）。
 *
 * @param body 可选：
 *  - `target_path`：自选路径恢复时指定目标目录/文件路径
 *  - `confirm_device_mismatch`：跨设备恢复（非本地删除）确认后置为 true
 */
export const restoreUserRecycleBinItem = async (
  id: number,
  body?: { target_path?: string; confirm_device_mismatch?: boolean },
): Promise<void> => {
  await post<BaseResponse<unknown>>(`/space/recycle-bin/${id}/restore`, { body })
}

/**
 * 一键清理当前账号已销毁（expired）的回收站记录，终止无限堆积。
 */
export const cleanupExpiredUserRecycleBin = async (): Promise<number> => {
  const response = await del<BaseResponse<{ cleaned: number }>>('/space/recycle-bin/expired')
  return response.data?.cleaned ?? 0
}
