/**
 * 技能包同步状态的展示语义（单一事实源）。
 *
 * 背景：后端 `skill_package.sync_status` / `skill_package_version.sync_status` 的取值
 * 由 `api/internal/service/skill_service.py` 写入。历史上前端只映射了
 * `ready|synced|pending|warming|failed|error`，漏掉 `skipped`，
 * 导致"无需同步"的技能在前端退化成裸英文码；更严重的是后端曾把
 * "远端未配置"错写成 `pending`，前端渲染为"同步中"且永无终态。
 *
 * 因此这里集中定义「全部合法取值 → 展示语义」的映射，并用 `SKILL_SYNC_STATUSES`
 * 暴露完整取值集合，供测试断言"没有漏映射的状态"。
 */
import type { BaseResponse } from '@/models/base'

export type SkillSyncTone = 'green' | 'orange' | 'red' | 'gray'

export type SkillSyncDescriptor = {
  /** 归一化后的语义键（与后端取值一一对应） */
  key: string
  color: SkillSyncTone
  /** i18n 键，由调用方用 t() 解析 */
  labelKey: string
  /** 原始取值，用于排查（不直接作为文案展示） */
  raw: string
}

/**
 * 后端 `sync_status` 的全部合法取值（与 skill_service.py 同步维护）：
 * - pending        已创建/已变更，尚未成功同步
 * - synced         已成功同步到远端 SCF
 * - failed         同步尝试失败
 * - skipped        无需远端同步（非 scf 类型，或 scf 但无工具定义）
 * - not_configured 远端 SCF 未配置（未发起同步）
 *
 * 注意：`SyncSkillStatus` 之外，前端历史数据里还有 `ready` / `warming` / `error`
 * 等兼容值，映射函数一并兼容。
 */
export const SKILL_SYNC_STATUSES = [
  'pending',
  'synced',
  'failed',
  'skipped',
  'not_configured',
] as const

export type SkillSyncStatus = (typeof SKILL_SYNC_STATUSES)[number]

export const resolveSkillSyncDescriptor = (status?: string): SkillSyncDescriptor => {
  const raw = String(status ?? '').trim()
  switch (raw) {
    case 'ready':
    case 'synced':
      return {
        key: 'synced',
        color: 'green',
        labelKey: 'admin.skillsAdmin.syncReady',
        raw,
      }
    case 'pending':
    case 'warming':
      return {
        key: 'pending',
        color: 'orange',
        labelKey: 'admin.skillsAdmin.syncPending',
        raw,
      }
    case 'not_configured':
      return {
        key: 'not_configured',
        color: 'orange',
        labelKey: 'admin.skillsAdmin.syncNotConfigured',
        raw,
      }
    case 'skipped':
      return {
        key: 'skipped',
        color: 'gray',
        labelKey: 'admin.skillsAdmin.syncSkipped',
        raw,
      }
    case 'failed':
    case 'error':
      return {
        key: 'failed',
        color: 'red',
        labelKey: 'admin.skillsAdmin.syncFailed',
        raw,
      }
    default:
      // 未知取值不把原始英文码当文案展示，避免"看起来像文案的裸键"
      return {
        key: 'unknown',
        color: 'gray',
        labelKey: 'admin.skillsAdmin.syncUnknown',
        raw,
      }
  }
}

export type SkillSyncNoticeLevel = 'success' | 'warning' | 'info' | 'error'

export type SkillSyncNotice = {
  level: SkillSyncNoticeLevel
  /** i18n 键；含 {reason} 占位的文案由调用方传入 reason */
  messageKey: string
}

/**
 * 同步接口返回后的提示语义。
 *
 * 关键：**不能用"接口成功"等同"已同步"**。远端未配置时接口照样 200，
 * 但实际什么都没同步——必须按返回的 sync_status 如实提示。
 */
export const resolveSkillSyncNotice = (status?: string): SkillSyncNotice => {
  switch (String(status ?? '').trim()) {
    case 'ready':
    case 'synced':
      return { level: 'success', messageKey: 'admin.skillsAdmin.syncSucceeded' }
    case 'not_configured':
      return { level: 'warning', messageKey: 'admin.skillsAdmin.syncNotConfiguredNotice' }
    case 'skipped':
      return { level: 'info', messageKey: 'admin.skillsAdmin.syncSkippedNotice' }
    case 'failed':
    case 'error':
      return { level: 'error', messageKey: 'admin.skillsAdmin.syncFailedNotice' }
    default:
      return { level: 'info', messageKey: 'admin.skillsAdmin.syncUnknownNotice' }
  }
}

/** 技能包同步接口返回体 */
export type SkillSyncResult = {
  sync_status: string
  sync_error: string
}

export type SkillSyncResponse = BaseResponse<SkillSyncResult>
