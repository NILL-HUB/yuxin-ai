import { get, put } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

/** 模型运行时降级配置 */
export interface RuntimeFallbackConfig {
  enabled: boolean
  retry_attempts: number
}

/** 外部素材获取配置 */
export interface MediaFetchConfig {
  enabled: boolean
  /** 体积上限（字节） */
  max_bytes_fallback: number
}

/** 会话 Checkpoint 配置 */
export interface AgentCheckpointConfig {
  enabled: boolean
}

/** 技能目录同步配置 */
export interface SkillCatalogSyncConfig {
  enabled: boolean
}

/** 图像请求策略配置 */
export interface ImageRequestPolicyConfig {
  policy: 'strict' | 'auto_upgrade'
}

/** 视觉兜底模型配置 */
export interface VisionFallbackConfig {
  provider: string
  model: string
}

/** 模型 Key 池熔断配置 */
export interface ModelKeyPoolConfig {
  failure_threshold: number
  cooldown_seconds: number
}

export interface GlobalControlConfigs {
  runtime_fallback: RuntimeFallbackConfig
  media_fetch: MediaFetchConfig
  agent_checkpoint: AgentCheckpointConfig
  skill_catalog_sync: SkillCatalogSyncConfig
  image_request_policy: ImageRequestPolicyConfig
  vision_fallback: VisionFallbackConfig
  model_key_pool: ModelKeyPoolConfig
}

export const getGlobalControlConfigs = async (): Promise<GlobalControlConfigs> => {
  const response = await get<BaseResponse<{ configs: GlobalControlConfigs }>>('/admin/global-control-config')
  return response.data.configs
}

export const saveGlobalControlSection = async <T extends Record<string, unknown>>(
  section: string,
  configs: T,
): Promise<T> => {
  const response = await put<BaseResponse<{ section: string; configs: T }>>('/admin/global-control-config', {
    body: { section, configs },
  })
  return response.data.configs
}
