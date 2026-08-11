import { get } from '@/utils/request'
import type {
  GetSkillResponse,
  GetSkillsCategoriesResponse,
  GetSkillsWithPageRequest,
  GetSkillsWithPageResponse,
} from '@/models/skill'

const storePrefix = (admin: boolean) => (admin ? '/admin/store' : '')

export const getSkillCategories = (admin = false) => {
  return get<GetSkillsCategoriesResponse>(`${storePrefix(admin)}/skills/categories`)
}

export const getSkillsWithPage = (params: GetSkillsWithPageRequest, admin = false) => {
  return get<GetSkillsWithPageResponse>(`${storePrefix(admin)}/skills`, { params })
}

export const getSkill = (skill_id: string, admin = false) => {
  return get<GetSkillResponse>(`${storePrefix(admin)}/skills/${skill_id}`)
}
