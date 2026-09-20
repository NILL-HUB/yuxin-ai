import { type BaseResponse } from '@/models/base'

// 用户端存储用量概览（供详情页用量面板）
export type StorageUsage = {
  total_bytes: number
  used_bytes: number
  remaining_bytes: number
  usage_percent: number
}

// 接口响应：返回完整信封，调用方需按 resp.data 取值
export type GetStorageUsageResponse = BaseResponse<StorageUsage>