import { get } from '@/utils/request'
import type { GetLanguageModelResponse, GetLanguageModelsResponse } from '@/models/language-model'

const prefix = (admin: boolean) => (admin ? '/admin' : '')

// 获取所有语言模型列表信息
export const getLanguageModels = (admin = false) => {
  return get<GetLanguageModelsResponse>(`${prefix(admin)}/language-models`)
}

// 获取指定模型的详细信息
export const getLanguageModel = (provider_name: string, model_name: string, admin = false) => {
  return get<GetLanguageModelResponse>(`${prefix(admin)}/language-models/${provider_name}/${model_name}`)
}
