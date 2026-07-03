import { get, post } from '@/utils/request'
import type {
  GetSkillResponse,
  GetSkillsWithPageRequest,
  GetSkillsWithPageResponse,
  SkillPackage,
} from '@/models/skill'
import type { BaseResponse } from '@/models/base'

/**
 * 获取后台 Skills 分页列表，并解包接口返回的 data 字段。
 */
export const listAdminSkills = async (
  params: GetSkillsWithPageRequest,
): Promise<GetSkillsWithPageResponse['data']> => {
  const response = await get<GetSkillsWithPageResponse>('/admin/skills', { params })
  return response.data
}

/**
 * 获取后台 Skill 详情（管理员视角，含完整 readme 和 tools）。
 */
export const getAdminSkill = async (id: string): Promise<SkillPackage> => {
  const response = await get<GetSkillResponse>(`/admin/skills/${id}`)
  return response.data
}

export type SkillVersion = {
  id: string
  skill_package_id: string
  version: number
  checksum: string
  sync_status: string
  sync_error: string
  is_current_version: boolean
  summary: string
  tool_count: number
  created_at: number
  updated_at: number
}

/**
 * 获取后台 Skill 版本历史。
 */
export const getAdminSkillVersions = async (id: string): Promise<SkillVersion[]> => {
  const response = await get<BaseResponse<{ list: SkillVersion[] }>>(`/admin/skills/${id}/versions`)
  return response.data.list || []
}

/**
 * 启用技能包（管理员视角）。
 */
export const enableAdminSkill = (id: string) => {
  return post<BaseResponse<null>>(`/admin/skills/${id}/enable`)
}

/**
 * 停用技能包（管理员视角）。
 */
export const disableAdminSkill = (id: string) => {
  return post<BaseResponse<null>>(`/admin/skills/${id}/disable`)
}

/**
 * 强制同步技能包到 SCF（管理员视角）。
 */
export const syncAdminSkill = (id: string) => {
  return post<BaseResponse<null>>(`/admin/skills/${id}/sync`)
}

/**
 * 回滚技能包到指定版本（管理员视角）。
 */
export const rollbackAdminSkill = (id: string, version: number) => {
  return post<BaseResponse<null>>(`/admin/skills/${id}/rollback`, { body: { version } })
}

// ------------------------------------------------------------------ //
//  CRUD API                                                           //
// ------------------------------------------------------------------ //

export type SkillToolInput = {
  name: string
  type: string
  required: boolean
  description: string
}

export type SkillToolDefinition = {
  name: string
  label: string
  description: string
  entrypoint: string
  input_schema: {
    type?: string
    properties?: Record<string, Record<string, unknown>>
    required?: string[]
  }
}

export type CreateSkillPackagePayload = {
  source_key: string
  name?: string
  label?: string
  description?: string
  category?: string
  icon?: string
  executor_type: 'scf' | 'prompt'
  enabled?: boolean
  readme?: string
  skill_code?: string
  tools?: SkillToolDefinition[]
  tags?: string[]
  capabilities?: Record<string, boolean>
}

export type UpdateSkillPackagePayload = Omit<CreateSkillPackagePayload, 'source_key'> & {
  source_key?: never
}

/**
 * 创建技能包（管理员直接写入 DB）。
 */
export const createAdminSkill = async (
  payload: CreateSkillPackagePayload,
): Promise<SkillPackage> => {
  const response = await post<GetSkillResponse>('/admin/skills', { body: payload })
  return response.data
}

/**
 * 更新技能包（管理员视角）。
 */
export const updateAdminSkill = async (
  id: string,
  payload: UpdateSkillPackagePayload,
): Promise<SkillPackage> => {
  const response = await post<GetSkillResponse>(`/admin/skills/${id}`, { body: payload })
  return response.data
}

/**
 * 删除技能包（仅允许删除 DB 来源的包）。
 */
export const deleteAdminSkill = (id: string) => {
  return post<BaseResponse<null>>(`/admin/skills/${id}/delete`)
}

// ------------------------------------------------------------------ //
//  Catalog 导入 API                                                   //
// ------------------------------------------------------------------ //

export type CatalogPackage = {
  source_key: string
  name: string
  label: string
  description: string
  category: string
  executor_type: string
  version: number
  tool_count: number
  imported: boolean
}

/**
 * 列出磁盘 catalog 目录中所有可导入的技能包。
 */
export const listCatalogSkills = async (): Promise<CatalogPackage[]> => {
  const response = await get<BaseResponse<{ list: CatalogPackage[] }>>('/admin/skills/catalog-packages')
  return response.data.list || []
}

/**
 * 从磁盘 catalog 导入指定 source_key 的技能包到 DB。
 */
export const importCatalogSkill = async (sourceKey: string): Promise<SkillPackage> => {
  const response = await post<GetSkillResponse>('/admin/skills/import-catalog', {
    body: { source_key: sourceKey },
  })
  return response.data
}
