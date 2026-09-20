import { get } from '@/utils/request'
import { type GetStorageUsageResponse } from '@/models/storage-usage'

// 获取用户端存储用量概览（供知识库详情页用量面板）
export const getStorageUsage = (): Promise<GetStorageUsageResponse> => {
  return get<GetStorageUsageResponse>('/space/storage/usage')
}

// 扩容入口：跳转会员中心
export const resolveUpgradeUrl = (): string => '/membership'