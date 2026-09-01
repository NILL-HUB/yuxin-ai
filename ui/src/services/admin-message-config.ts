import { get, post, put } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

export interface MailConfigPayload {
  smtp_host: string
  smtp_port: string
  use_tls: boolean
  use_ssl: boolean
  username: string
  password: string
  default_sender: string
  from_name: string
  timeout: string
}

export interface SmsConfigPayload {
  provider: '' | 'aliyun' | 'tencent'
  access_key: string
  access_secret: string
  sign_name: string
  region: string
  sdk_app_id: string
  verify_code_template: string
}

export interface TestSendResult {
  ok: boolean
  detail?: string
}

export const getMailConfig = async (): Promise<MailConfigPayload> => {
  const response = await get<BaseResponse<{ configs: MailConfigPayload }>>('/admin/mail-config')
  return response.data.configs
}

export const saveMailConfig = async (configs: MailConfigPayload): Promise<MailConfigPayload> => {
  const response = await put<BaseResponse<{ configs: MailConfigPayload }>>('/admin/mail-config', {
    body: { configs },
  })
  return response.data.configs
}

export const testMailSend = async (to: string): Promise<TestSendResult> => {
  const response = await post<BaseResponse<TestSendResult>>('/admin/mail-config/test', {
    body: { to },
  })
  return response.data
}

export const getSmsConfig = async (): Promise<SmsConfigPayload> => {
  const response = await get<BaseResponse<{ configs: SmsConfigPayload }>>('/admin/sms-config')
  return response.data.configs
}

export const saveSmsConfig = async (configs: SmsConfigPayload): Promise<SmsConfigPayload> => {
  const response = await put<BaseResponse<{ configs: SmsConfigPayload }>>('/admin/sms-config', {
    body: { configs },
  })
  return response.data.configs
}

export const testSmsSend = async (phone: string): Promise<TestSendResult> => {
  const response = await post<BaseResponse<TestSendResult>>('/admin/sms-config/test', {
    body: { phone, to: phone },
  })
  return response.data
}
