import { QueueEvent } from '@/config'
import type { BillingUsageEvent } from '@/models/billing-metering'
import type { RoutingDecision } from '@/models/orchestration'
import type { ToolConfirmationPrompt } from '@/models/tool-confirmation'
export type { ToolConfirmationPrompt }
import {
  buildChatOutputParts,
  extractInlineImageUrls,
  mergeChatArtifacts,
} from './chat-output'

type StreamEventData = {
  id?: string
  message_id?: string
  task_id?: string
  conversation_id?: string
  event?: string
  thought?: string
  answer?: string
  observation?: string
  tool?: string
  tool_input?: unknown
  latency?: number
  total_token_count?: number
  aggregate_latency?: number
  aggregate_total_token_count?: number
  reason?: string
  message?: string
  estimated_steps?: number
  risk_level?: string
  spent_credits?: number
  target_system?: string
  target_environment?: string
  impact_scope?: string
  rollback_strategy?: string
  audit_hint?: string
  confirmation_id?: string
  confirmation_status?: string
  execution_summary?: string
  candidate_id?: string
  content?: string
  confidence?: number
  occurrences?: number
  status?: string
  // 多智能体子任务规划（subtask_started 事件）
  execution_mode?: string
  aggregation_strategy?: string
  task_count?: number
  items?: SubtaskPlanItem[]
  // 子任务完成（subtask_completed 事件）
  agent_id?: string
  answer_preview?: string
  errors?: string[]
  // 结果合成元数据（agent_message 事件附加）
  summary?: string
  visible_sources?: unknown[]
  user_warnings?: string[]
}

export type StreamEventResponse = {
  event?: string
  data?: StreamEventData
}

export type ChatThought = {
  id: string
  position: number
  event: string
  thought: string
  observation: string
  tool: string
  tool_input: Record<string, unknown>
  latency: number
  created_at: number
}

// 多智能体子任务规划项（subtask_started 事件 items 数组元素）
export type SubtaskPlanItem = {
  task_id: string
  title: string
  description: string
  depends_on: string[]
  execution_order: number
  agent_id: string
  tools: string[]
  risk_level: string
  timeout_seconds?: number
}

// 子任务执行进度跟踪（subtask_started 初始化，subtask_completed 更新）
export type SubtaskProgress = {
  task_id: string
  title: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  agent_id: string
  answer_preview?: string
  confidence?: number
  errors?: string[]
  timeout_seconds?: number
  last_activity_at?: number
  stall_warning?: boolean
  timed_out?: boolean
}

// 多智能体结果合成元数据（agent_message 事件附加字段）
export type SynthesisMeta = {
  summary: string
  confidence: number
  visible_sources: unknown[]
  user_warnings: string[]
}

export type StreamMessage = {
  id: string
  conversation_id: string
  answer: string
  answer_parts: unknown[]
  artifacts: unknown[]
  latency: number
  total_token_count: number
  agent_thoughts: ChatThought[]
}

export type RenderableStreamMessage = StreamMessage & {
  render_id: string
}

export type StreamState = {
  position: number
  message_id: string
  task_id: string
  conversation_id: string
  billingEvents: BillingUsageEvent[]
  deepThinkingProposal?: DeepThinkingProposal | null
  routingDecision?: RoutingDecision | null
  orchestratorReject?: { reason: string; message: string } | null
  toolConfirmationPrompt?: ToolConfirmationPrompt | null
  // 多智能体子任务进度（subtask_started 初始化，subtask_completed 更新）
  subtasks?: SubtaskProgress[] | null
  // 任务规划元数据（subtask_started 事件携带）
  taskPlan?: {
    execution_mode: string
    aggregation_strategy: string
    reason: string
    task_count: number
  } | null
  // 结果合成元数据（agent_message 事件附加）
  synthesisMeta?: SynthesisMeta | null
}

export type DeepThinkingProposal = {
  reason: string
  estimated_steps: number
}

export type StreamApplyResult = {
  state: StreamState
  didUpdate: boolean
}

let streamRenderIdSequence = 0

export const createChatRenderId = (scope: string = 'chat') => {
  streamRenderIdSequence += 1
  return `${scope}-${streamRenderIdSequence}`
}

export const withChatRenderId = <T extends { id?: string; render_id?: string }>(
  message: T,
  scope: string = 'chat',
): T & { render_id: string } => {
  const renderId = String(message.render_id ?? '').trim() || String(message.id ?? '').trim() || createChatRenderId(scope)
  return {
    ...message,
    render_id: renderId,
  }
}

export const withChatRenderIds = <T extends { id?: string; render_id?: string }>(
  messages: T[],
  scope: string = 'chat',
): Array<T & { render_id: string }> => {
  return messages.map((message) => withChatRenderId(message, scope))
}

export const mergeChatHistoryMessages = <T extends { id?: string; render_id?: string }>(
  messages: T[],
  scope: string = 'chat',
): Array<T & { render_id: string }> => {
  const merged: Array<T & { render_id: string }> = []
  const seenKeys = new Set<string>()

  for (const message of messages) {
    const normalizedId = String(message.id ?? '').trim()
    const normalizedRenderId = String(message.render_id ?? '').trim()
    const identityKey = normalizedId || normalizedRenderId
    if (identityKey && seenKeys.has(identityKey)) {
      continue
    }

    if (identityKey) {
      seenKeys.add(identityKey)
    }

    merged.push({
      ...message,
      render_id: normalizedRenderId || normalizedId || createChatRenderId(scope),
    })
  }

  return merged
}

const toPositiveNumber = (value: unknown) => {
  const normalized = Number(value)
  return Number.isFinite(normalized) && normalized > 0 ? normalized : 0
}

const toNonNegativeNumber = (value: unknown) => {
  const normalized = Number(value)
  return Number.isFinite(normalized) && normalized >= 0 ? normalized : 0
}

const normalizeToolInput = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {}
  }
  return value as Record<string, unknown>
}

const extractConfirmationId = (text: unknown): string => {
  const match = String(text ?? '').match(/确认ID:\s*([0-9a-fA-F-]{36})/)
  return match?.[1] ?? ''
}

const buildThought = (data: StreamEventData, position: number): ChatThought => {
  return {
    id: String(data.id ?? ''),
    position,
    event: String(data.event ?? ''),
    thought: String(data.thought ?? ''),
    observation: String(data.observation ?? ''),
    tool: String(data.tool ?? ''),
    tool_input: normalizeToolInput(data.tool_input),
    latency: toPositiveNumber(data.latency),
    created_at: 0,
  }
}

const upsertThought = (
  thoughts: ChatThought[],
  data: StreamEventData,
  nextState: StreamState,
  options: { appendThought: boolean },
) => {
  const { appendThought } = options
  const eventId = String(data.id ?? '')
  const event = String(data.event ?? '')

  // 修复 ID 覆盖：如果 id 为空，直接 push 新 thought，避免 findIndex 匹配到空 id 的条目导致覆盖
  if (!eventId) {
    nextState.position += 1
    thoughts.push(buildThought(data, nextState.position))
    return
  }

  const thoughtIdx = thoughts.findIndex((item) => item.id === eventId && item.event === event)

  if (thoughtIdx === -1) {
    nextState.position += 1
    thoughts.push(buildThought(data, nextState.position))
    return
  }

  const previous = thoughts[thoughtIdx]
  thoughts[thoughtIdx] = {
    ...previous,
    ...buildThought(data, previous.position),
    thought: appendThought
      ? `${previous.thought}${String(data.thought ?? '')}`
      : String(data.thought ?? previous.thought ?? ''),
    observation: String(data.observation ?? previous.observation ?? ''),
    tool: String(data.tool ?? previous.tool ?? ''),
    tool_input: normalizeToolInput(data.tool_input ?? previous.tool_input),
    latency: toPositiveNumber(data.latency) || previous.latency,
  }
}

export const applyChatStreamEvent = (
  message: StreamMessage,
  eventResponse: StreamEventResponse,
  currentState: StreamState,
): StreamApplyResult => {
  const event = String(eventResponse?.event ?? '')
  const data = eventResponse?.data ?? {}
  const nextState: StreamState = { ...currentState }

  if (nextState.message_id === '' && data.message_id) {
    nextState.task_id = String(data.task_id ?? '')
    nextState.message_id = String(data.message_id)
    nextState.conversation_id = String(data.conversation_id ?? '')
    message.id = nextState.message_id
    message.conversation_id = nextState.conversation_id
  }

  if (event === '' || event === QueueEvent.ping) {
    return { state: nextState, didUpdate: false }
  }

  const thoughts = message.agent_thoughts
  let shouldRefreshOutputParts = false

  if (event === QueueEvent.agentMessage) {
    // 只有当 payload 携带 thought 内容时才创建/更新 thought 条目
    // 真流式 token 事件只有 answer 字段，没有 thought，不应创建空 thought
    if (data.thought) {
      upsertThought(thoughts, data, nextState, { appendThought: true })
    }
    // 后端 AGENT_MESSAGE 事件 payload 使用 'answer' 字段（新契约，所有执行器遵循）
    // 旧测试 / 历史数据可能使用 'thought' 字段，两者兼容：优先 answer，回退 thought
    const answerChunk = String(data.answer ?? data.thought ?? '')
    message.answer += answerChunk
    // 多智能体合成元数据：summary / confidence / visible_sources / user_warnings
    // 仅 MultiAgentExecutor 在多结果合成时会附加这些字段
    const hasSynthesisMeta = Boolean(
      data.summary || data.user_warnings?.length || data.visible_sources?.length,
    )
    if (hasSynthesisMeta) {
      nextState.synthesisMeta = {
        summary: String(data.summary ?? ''),
        confidence: Number(data.confidence ?? 0) || 0,
        visible_sources: Array.isArray(data.visible_sources) ? data.visible_sources : [],
        user_warnings: Array.isArray(data.user_warnings) ? data.user_warnings : [],
      }
    }
    shouldRefreshOutputParts = true
  } else if (event === QueueEvent.agentAction) {
    upsertThought(thoughts, data, nextState, { appendThought: false })
    if (nextState.toolConfirmationPrompt && data.tool === 'run_os_task' && data.observation) {
      nextState.toolConfirmationPrompt.execution_summary = String(data.observation)
    }
    const observation = String(data.observation ?? '')
    const existingUrls = mergeChatArtifacts([], message.artifacts)
      .map(artifact => String(artifact.url || '').trim())
    const inlineImageUrls = extractInlineImageUrls(observation, existingUrls)
    if (inlineImageUrls.length > 0) {
      const extractedArtifacts = inlineImageUrls.map((url, index) => ({
        name: inlineImageUrls.length === 1 ? '生成图片' : `生成图片 ${index + 1}`,
        url,
      }))
      message.artifacts = mergeChatArtifacts(message.artifacts, extractedArtifacts)
      shouldRefreshOutputParts = true
    }
  } else if (event === QueueEvent.deepThinking) {
    upsertThought(thoughts, data, nextState, { appendThought: true })
  } else if (
    event === QueueEvent.deepStep ||
    event === QueueEvent.deepComplete
  ) {
    upsertThought(thoughts, data, nextState, { appendThought: false })
  } else if (event === QueueEvent.deepArtifactCreated) {
    upsertThought(thoughts, data, nextState, { appendThought: false })
    const toolInput = (data.tool_input && typeof data.tool_input === 'object')
      ? data.tool_input as Record<string, unknown>
      : {}
    message.artifacts = mergeChatArtifacts(message.artifacts, [toolInput.artifact || null])
    shouldRefreshOutputParts = true
  } else if (event === QueueEvent.agentEnd) {
    return { state: nextState, didUpdate: false }
  } else if (event === QueueEvent.agentThought) {
    upsertThought(thoughts, data, nextState, { appendThought: false })
  } else if (event === QueueEvent.deepThinkingProposal) {
    nextState.deepThinkingProposal = {
      reason: String(data.reason ?? ''),
      estimated_steps: Number(data.estimated_steps ?? 0) || 0,
    }
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.error) {
    message.answer = String(data.observation ?? '')
    shouldRefreshOutputParts = true
  } else if (event === QueueEvent.timeout) {
    message.answer = '当前Agent执行已超时，无法得到答案，请重试'
    shouldRefreshOutputParts = true
  } else if (
    event === QueueEvent.billingStarted ||
    event === QueueEvent.billingDelta ||
    event === QueueEvent.billingCancelled ||
    event === QueueEvent.billingFinal ||
    event === QueueEvent.billingSummary
  ) {
    nextState.billingEvents = [...nextState.billingEvents, data as unknown as BillingUsageEvent]
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.orchestratorRouting) {
    nextState.routingDecision = data as unknown as RoutingDecision
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.orchestratorReject) {
    nextState.orchestratorReject = {
      reason: String(data?.reason ?? ''),
      message: String(data?.message ?? ''),
    }
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.subtaskStarted) {
    // 多智能体任务分解：subtask_started 事件携带完整任务规划
    // 初始化 subtasks 数组，每个子任务初始状态为 pending
    const items = Array.isArray(data.items) ? data.items : []
    const subtasks: SubtaskProgress[] = items.map((item) => ({
      task_id: String(item?.task_id ?? ''),
      title: String(item?.title ?? ''),
      status: 'pending' as const,
      agent_id: String(item?.agent_id ?? ''),
      timeout_seconds: Number(item?.timeout_seconds ?? 0) || 0,
    }))
    nextState.subtasks = subtasks
    nextState.taskPlan = {
      execution_mode: String(data.execution_mode ?? ''),
      aggregation_strategy: String(data.aggregation_strategy ?? ''),
      reason: String(data.reason ?? ''),
      task_count: Number(data.task_count ?? 0) || 0,
    }
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.subtaskRunning) {
    // 单个子任务开始执行：更新对应 task 状态为 running
    const taskId = String(data.task_id ?? '')
    const currentSubtasks = nextState.subtasks ?? []
    nextState.subtasks = currentSubtasks.map((subtask) => {
      if (subtask.task_id !== taskId) {
        return subtask
      }
      return {
        ...subtask,
        status: 'running' as const,
      }
    })
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.subtaskCompleted) {
    // 单个子任务完成：更新对应 task 状态
    const taskId = String(data.task_id ?? '')
    const status: SubtaskProgress['status'] = data.status === 'failed' ? 'failed' : 'completed'
    const errors = Array.isArray(data.errors) ? data.errors.map(String) : []
    const currentSubtasks = nextState.subtasks ?? []
    nextState.subtasks = currentSubtasks.map((subtask) => {
      if (subtask.task_id !== taskId) {
        return subtask
      }
      return {
        ...subtask,
        status,
        answer_preview: String(data.answer_preview ?? ''),
        confidence: Number(data.confidence ?? 0) || 0,
        errors,
      }
    })
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.toolConfirmationRequired) {
    nextState.toolConfirmationPrompt = {
      id: String(data.confirmation_id ?? extractConfirmationId(data.observation) ?? ''),
      tool_name: String(data.tool ?? ''),
      risk_level: (String(data.risk_level ?? 'high') as ToolConfirmationPrompt['risk_level']),
      spent_credits: Number(data.spent_credits ?? 0),
      tool_input: normalizeToolInput(data.tool_input),
      status: (String(data.confirmation_status ?? 'pending') as ToolConfirmationPrompt['status']),
      execution_summary: String(data.execution_summary ?? ''),
      target_system: String(data.target_system ?? ''),
      target_environment: String(data.target_environment ?? ''),
      impact_scope: String(data.impact_scope ?? ''),
      rollback_strategy: String(data.rollback_strategy ?? ''),
      audit_hint: String(data.audit_hint ?? ''),
    } as ToolConfirmationPrompt
    return { state: nextState, didUpdate: true }
  } else {
    nextState.position += 1
    thoughts.push(buildThought(data, nextState.position))
  }

  const normalizedLatency = toPositiveNumber(
    data.aggregate_latency ?? data.latency,
  )
  if (normalizedLatency > 0) {
    message.latency = normalizedLatency
  }

  const normalizedTokenCount = Math.floor(toNonNegativeNumber(
    data.aggregate_total_token_count ?? data.total_token_count,
  ))
  if (normalizedTokenCount > 0) {
    message.total_token_count = normalizedTokenCount
  }

  message.agent_thoughts = thoughts
  if (shouldRefreshOutputParts) {
    message.answer_parts = buildChatOutputParts(message.answer, message.artifacts)
  }
  return { state: nextState, didUpdate: true }
}
