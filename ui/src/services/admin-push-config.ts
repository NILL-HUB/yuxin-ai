import { get, post, put } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

export type PushProvider = 'getui' | 'umeng'

export interface GetuiConfigPayload {
  app_id: string
  app_key: string
  app_secret: string
  master_secret: string
}

export interface UmengConfigPayload {
  app_key: string
  app_master_secret: string
  production_mode: boolean
}

export interface PushConfigPayload {
  enabled: boolean
  primary_provider: PushProvider
  fallback_enabled: boolean
  getui: GetuiConfigPayload
  umeng: UmengConfigPayload
}

export interface PushTestResult {
  ok: boolean
  detail?: string
}

// 读取系统推送配置（密钥字段返回掩码 ******）
export const getPushConfig = async (): Promise<PushConfigPayload> => {
  const response = await get<BaseResponse<{ configs: PushConfigPayload }>>('/admin/push-config')
  return response.data.configs
}

// 保存系统推送配置（密钥字段留空或传掩码表示不修改）
export const savePushConfig = async (configs: PushConfigPayload): Promise<PushConfigPayload> => {
  const response = await put<BaseResponse<{ configs: PushConfigPayload }>>('/admin/push-config', {
    body: { configs },
  })
  return response.data.configs
}

// 联调：向指定令牌发一条测试推送
export const testPushSend = async (
  provider: PushProvider,
  deviceToken: string,
): Promise<PushTestResult> => {
  const response = await post<BaseResponse<PushTestResult>>('/admin/push-config/test', {
    body: { provider, device_token: deviceToken },
  })
  return response.data
}
