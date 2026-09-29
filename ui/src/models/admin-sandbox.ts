import type { BaseResponse } from '@/models/base'

/** 沙箱能力域 */
export type SandboxCapability = 'code_interpreter' | 'skill_exec' | 'workflow_code'

/** 可切换的后端选项 */
export type SandboxBackendOption = {
  backend: string
  label: string
  is_active: boolean
}

/** 某能力域的运行时概览 */
export type SandboxCapabilityOverview = {
  capability: string
  active_backend: string
  enabled: boolean
  reason: string
  configs: Record<string, unknown>
  /** 凭证掩码（键=env 名；值已脱敏，绝不回明文） */
  credentials: Record<string, string>
  /** 该后端可配置的凭证键清单（供渲染表单） */
  credential_keys: string[]
  backends: SandboxBackendOption[]
}

export type SandboxOverviewResponse = BaseResponse<{ items: SandboxCapabilityOverview[] }>

/** 单条（能力域 × 后端）配置 */
export type SandboxConfigItem = {
  capability: string
  backend: string
  label: string
  configs: Record<string, unknown>
  is_active: boolean
  /** 凭证掩码（键=env 名；值已脱敏，绝不回明文） */
  credentials: Record<string, string>
  /** 该后端可配置的凭证键清单（供渲染表单） */
  credential_keys: string[]
}

export type SandboxConfigListResponse = BaseResponse<{ items: SandboxConfigItem[] }>
export type SandboxConfigItemResponse = BaseResponse<{ item: SandboxConfigItem }>

/** 连通性探测结果 */
export type SandboxProbeResult = {
  capability: string
  backend: string
  ok: boolean
  reason: string
}

export type SandboxProbeResponse = BaseResponse<SandboxProbeResult>
