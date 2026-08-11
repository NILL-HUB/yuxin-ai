import { get, post } from '@/utils/request'
import { type BasePaginatorRequest, type BaseResponse } from '@/models/base'
import {
  type CreateApiKeyRequest,
  type CreateApiKeyResponse,
  type GetApiKeysWithPageResponse,
  type UpdateApiKeyRequest,
} from '@/models/api-key'

const prefix = (admin: boolean) => (admin ? '/admin' : '')

// 创建API秘钥请求
export const createApiKey = (req: CreateApiKeyRequest, admin = false) => {
  return post<BaseResponse<CreateApiKeyResponse>>(`${prefix(admin)}/openapi/api-keys`, { body: req })
}

// 删除API秘钥请求
export const deleteApiKey = (api_key_id: string, admin = false) => {
  return post<BaseResponse<Record<string, unknown>>>(`${prefix(admin)}/openapi/api-keys/${api_key_id}/delete`)
}

// 修改API秘钥请求
export const updateApiKey = (api_key_id: string, req: UpdateApiKeyRequest, admin = false) => {
  return post<BaseResponse<Record<string, unknown>>>(`${prefix(admin)}/openapi/api-keys/${api_key_id}`, { body: req })
}

// 修改API秘钥激活请求
export const updateApiKeyIsActive = (api_key_id: string, is_active: boolean, admin = false) => {
  return post<BaseResponse<Record<string, unknown>>>(`${prefix(admin)}/openapi/api-keys/${api_key_id}/is-active`, {
    body: { is_active },
  })
}

// 获取API秘钥分页列表数据
export const getApiKeysWithPage = (req: BasePaginatorRequest, admin = false) => {
  return get<GetApiKeysWithPageResponse>(`${prefix(admin)}/openapi/api-keys`, { params: req })
}
