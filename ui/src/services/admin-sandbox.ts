import { get, post } from '@/utils/request'
import type {
  SandboxConfigItemResponse,
  SandboxConfigListResponse,
  SandboxOverviewResponse,
  SandboxProbeResponse,
} from '@/models/admin-sandbox'

/**
 * 获取沙箱概览：各能力域的激活后端、可用性、原因与可切换后端。
 */
export const getSandboxOverview = async (): Promise<SandboxOverviewResponse> => {
  return get<SandboxOverviewResponse>('/admin/sandbox/overview')
}

/**
 * 获取沙箱配置列表（全部能力域 × 后端）。
 */
export const listSandboxConfigs = async (): Promise<SandboxConfigListResponse> => {
  return get<SandboxConfigListResponse>('/admin/sandbox/configs')
}

/**
 * 更新某（能力域, 后端）的配置。
 *
 * - `configs`：白名单配置键；
 * - `credentials`：白名单**凭证键**（键=env 名），值加密入库、空值表示清除；不传则保持既有凭证不变。
 */
export const updateSandboxConfig = async (
  capability: string,
  backend: string,
  configs: Record<string, unknown>,
  credentials?: Record<string, string>,
): Promise<SandboxConfigItemResponse> => {
  return post<SandboxConfigItemResponse>(
    `/admin/sandbox/configs/${capability}/${backend}`,
    { body: JSON.stringify({ configs, credentials: credentials ?? {} }) },
  )
}

/**
 * 激活某能力域的后端（热切换：仅影响新会话）。
 */
export const activateSandboxBackend = async (
  capability: string,
  backend: string,
): Promise<SandboxConfigItemResponse> => {
  return post<SandboxConfigItemResponse>('/admin/sandbox/activate', {
    body: JSON.stringify({ capability, backend }),
  })
}

/**
 * 探测某能力域当前后端是否可用（含不可用原因）。
 */
export const probeSandbox = async (capability: string): Promise<SandboxProbeResponse> => {
  return post<SandboxProbeResponse>('/admin/sandbox/probe', {
    body: JSON.stringify({ capability }),
  })
}
