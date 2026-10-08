// 机密记忆读取确认（memory_confirmation_required）数据模型。
// 后端线协议由 MemoryRecallOutcome.confirmation_payload() 单点定义：
// { confirmation_id, memory_items: [{ memory_id, types, label, preview }], count }
// 注意用 memory_items：用户端流里的 items 属于子任务契约（SubtaskPlanItem[]），同名会发散。

export type MemoryConfirmationStatus = 'pending' | 'confirmed' | 'cancelled'

export type MemoryConfirmationItem = {
  memory_id: string
  /** 命中的敏感类型（email/phone/id_card/bank_card/password/otp/secret），展示走 i18n */
  types: string[]
  /** 后端下发的中文标签，仅作为未知类型的兜底展示 */
  label: string
  /** 已脱敏的预览（如「我的手机号是 [PHONE_REDACTED]」） */
  preview: string
}

/** 确认记录（HTTP 详情 / 决策接口返回） */
export type MemoryConfirmation = {
  confirmation_id: string
  status: MemoryConfirmationStatus
  items: MemoryConfirmationItem[]
  created_at?: string
}

/** 对话流内展示确认卡片所需的最小状态 */
export type MemoryConfirmationPrompt = {
  confirmation_id: string
  status: MemoryConfirmationStatus
  items: MemoryConfirmationItem[]
  count: number
}

/** 把 SSE / 管理端帧的原始 payload 归一为卡片状态（用户端与管理端共用同一形状）。 */
export const normalizeMemoryConfirmationPrompt = (
  payload: Record<string, unknown>,
  status: MemoryConfirmationStatus = 'pending',
): MemoryConfirmationPrompt => {
  const rawItems = Array.isArray(payload?.memory_items) ? payload.memory_items : []
  const items: MemoryConfirmationItem[] = rawItems.map((raw) => {
    const record = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
    return {
      memory_id: String(record.memory_id ?? ''),
      types: Array.isArray(record.types) ? record.types.map(String) : [],
      label: String(record.label ?? ''),
      preview: String(record.preview ?? ''),
    }
  })
  const rawCount = Number(payload?.count)
  return {
    confirmation_id: String(payload?.confirmation_id ?? ''),
    status,
    items,
    count: Number.isFinite(rawCount) && rawCount >= 0 ? rawCount : items.length,
  }
}
