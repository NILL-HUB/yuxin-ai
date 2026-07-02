import { get } from '@/utils/request'
import type { GetSkillsWithPageRequest, GetSkillsWithPageResponse } from '@/models/skill'

/**
 * 获取后台 Skills 分页列表，并解包接口返回的 data 字段。
 */
export const listAdminSkills = async (
  params: GetSkillsWithPageRequest,
): Promise<GetSkillsWithPageResponse['data']> => {
  const response = await get<GetSkillsWithPageResponse>('/admin/skills', { params })
  return response.data
}
