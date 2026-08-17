import { get, post, ssePost } from '@/utils/request'
import type {
  CreateAppRequest,
  GetAppResponse,
  GetAppsWithPageRequest,
  GetAppsWithPageResponse,
  GetDebugConversationMessagesWithPageRequest,
  GetDebugConversationMessagesWithPageResponse,
  GetDraftAppConfigResponse,
  GetPublishedConfigResponse,
  GetPublishHistoriesWithPageResponse,
  GetVersionsResponse,
  PromptCompareChatRequest,
  RegenerateWebAppTokenResponse,
  UpdateAppRequest,
  UpdateDraftAppConfigRequest,
} from '@/models/app'
import type { BasePaginatorRequest, BaseResponse } from '@/models/base' // 获取应用基础信息

// 获取应用基础信息
export const getApp = (app_id: string) => {
  return get<GetAppResponse>(`/apps/${app_id}`)
}

// 在个人空间下新增应用
export const createApp = (req: CreateAppRequest) => {
  return post<BaseResponse<{ id: string }>>(`/apps`, { body: req })
}

// 修改指定应用
export const updateApp = (app_id: string, req: UpdateAppRequest) => {
  return post<BaseResponse<Record<string, unknown>>>(`/apps/${app_id}`, { body: req })
}

// 删除指定应用（进入回收站，可指定留存天数）
export const deleteApp = (app_id: string, retentionDays?: number) => {
  return post<BaseResponse<Record<string, unknown>>>(`/apps/${app_id}/delete`, {
    body: { retention_days: retentionDays },
  })
}

// 拷贝指定的应用
export const copyApp = (app_id: string) => {
  return post<BaseResponse<{ id: string }>>(`/apps/${app_id}/copy`)
}

// 获取应用分页列表数据
export const getAppsWithPage = (req: GetAppsWithPageRequest) => {
  return get<GetAppsWithPageResponse>(`/apps`, { params: req })
}

// 获取特定应用的草稿配置信息
export const getDraftAppConfig = (app_id: string) => {
  return get<GetDraftAppConfigResponse>(`/apps/${app_id}/draft-app-config`)
}

// 更新特定应用的草稿配置信息
export const updateDraftAppConfig = (app_id: string, req: UpdateDraftAppConfigRequest) => {
  return post<BaseResponse<Record<string, unknown>>>(`/apps/${app_id}/draft-app-config`, { body: req })
}

// 获取应用的调试长记忆（admin=true 时走 admin 域接口，以应用归属账号执行）
export const getDebugConversationSummary = (app_id: string, admin = false) => {
  const prefix = admin ? '/admin' : ''
  return get<BaseResponse<{ summary: string }>>(`${prefix}/apps/${app_id}/summary`)
}

// 更新应用的调试长记忆
export const updateDebugConversationSummary = (app_id: string, summary: string, admin = false) => {
  const prefix = admin ? '/admin' : ''
  return post<BaseResponse<Record<string, unknown>>>(`${prefix}/apps/${app_id}/summary`, { body: { summary } })
}

// 应用调试对话，该接口为流式事件输出
export const debugChat = (
  app_id: string,
  query: string,
  image_urls: string[],
  conversation_id: string = '',
  onData: (event_response: Record<string, unknown>) => void,
  confirm_deep_thinking: boolean = false,
  admin = false,
) => {
  const prefix = admin ? '/admin' : ''
  return ssePost(
    `${prefix}/apps/${app_id}/conversations`,
    { body: { query, image_urls, conversation_id, confirm_deep_thinking } },
    onData,
  )
}

// 提示词对比调试，该接口为流式事件输出
export const promptCompareChat = (
  app_id: string,
  req: PromptCompareChatRequest,
  onData: (event_response: Record<string, unknown>) => void,
) => {
  return ssePost(`/apps/${app_id}/prompt-compare/chat`, { body: req }, onData)
}

// 工作流应用调试，该接口为流式事件输出（SSE 推送节点级执行事件）
export const debugWorkflowApp = (
  app_id: string,
  inputs: Record<string, unknown>,
  onData: (event_response: { event: string; data: Record<string, unknown> }) => void,
  admin = false,
) => {
  const prefix = admin ? '/admin' : ''
  return ssePost(`${prefix}/apps/${app_id}/workflow/debug`, { body: inputs }, onData)
}

// 停止某次应用的调试会话
export const stopDebugChat = (app_id: string, task_id: string, admin = false) => {
  const prefix = admin ? '/admin' : ''
  return post<BaseResponse<Record<string, unknown>>>(`${prefix}/apps/${app_id}/conversations/tasks/${task_id}/stop`)
}

// 停止某次提示词对比调试会话
export const stopPromptCompareChat = (app_id: string, task_id: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/apps/${app_id}/prompt-compare/tasks/${task_id}/stop`)
}

// 获取应用的调试会话消息列表
export const getDebugConversationMessagesWithPage = (
  app_id: string,
  req?: GetDebugConversationMessagesWithPageRequest,
  admin = false,
) => {
  const prefix = admin ? '/admin' : ''
  return get<GetDebugConversationMessagesWithPageResponse>(
    `${prefix}/apps/${app_id}/conversations/messages`,
    { params: req },
  )
}

// 清空应用的调试会话记录
export const deleteDebugConversation = (app_id: string, admin = false) => {
  const prefix = admin ? '/admin' : ''
  return post<BaseResponse<Record<string, unknown>>>(`${prefix}/apps/${app_id}/conversations/delete-debug-conversation`)
}

// 更新/发布应用的配置信息
export const publish = (app_id: string, share_to_square: boolean = true) => {
  return post<BaseResponse<Record<string, unknown>>>(`/apps/${app_id}/publish?share_to_square=${share_to_square}`)
}

// 取消指定应用的发布
export const cancelPublish = (app_id: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/apps/${app_id}/cancel-publish`)
}

// 获取应用的发布历史列表信息
export const getPublishHistoriesWithPage = (app_id: string, req: BasePaginatorRequest) => {
  return get<GetPublishHistoriesWithPageResponse>(`/apps/${app_id}/publish-histories`, {
    params: req,
  })
}

// 获取应用版本对比数据（草稿 + 发布历史）
export const getVersions = (app_id: string) => {
  return get<GetVersionsResponse>(`/apps/${app_id}/versions`)
}

// 回退指定的历史配置到草稿
export const fallbackHistoryToDraft = (app_id: string, app_config_version_id: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/apps/${app_id}/fallback-history`, {
    body: { app_config_version_id },
  })
}

// 获取指定应用的发布配置信息
export const getPublishedConfig = (app_id: string) => {
  return get<GetPublishedConfigResponse>(`/apps/${app_id}/published-config`)
}

// 重新生成 WebApp 的凭证标识
export const regenerateWebAppToken = (app_id: string) => {
  return post<RegenerateWebAppTokenResponse>(
    `/apps/${app_id}/published-config/regenerate-web-app-token`,
  )
}

// 重新生成应用图标
export const regenerateIcon = (app_id: string) => {
  return post<BaseResponse<{ icon: string }>>(`/apps/${app_id}/regenerate-icon`)
}

// 生成图标预览（不保存到应用）
export const generateIconPreview = (name: string, description: string) => {
  return post<BaseResponse<{ icon: string }>>(`/apps/generate-icon-preview`, {
    body: { name, description },
  })
}

// 分享应用到广场
export const shareAppToSquare = (app_id: string, category: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/apps/${app_id}/share-to-square`, { body: { category } })
}

// 取消分享应用到广场
export const unshareAppFromSquare = (app_id: string) => {
  return post<BaseResponse<Record<string, unknown>>>(`/apps/${app_id}/unshare-from-square`)
}
