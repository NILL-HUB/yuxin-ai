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
