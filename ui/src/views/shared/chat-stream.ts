import { QueueEvent } from '@/config'
import type { BillingUsageEvent } from '@/models/billing-metering'
import type { MemoryCandidatePrompt } from '@/models/memory'
import type { ToolConfirmationPrompt } from '@/models/tool-confirmation'
export type { ToolConfirmationPrompt }
export type { MemoryCandidatePrompt }
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
  candidate_id?: string
  content?: string
  confidence?: number
  occurrences?: number
  status?: string
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
  routingDecision?: Record<string, unknown> | null
  orchestratorReject?: { reason: string; message: string } | null
  toolConfirmationPrompt?: ToolConfirmationPrompt | null
  memoryCandidatePrompt?: MemoryCandidatePrompt | null
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
    upsertThought(thoughts, data, nextState, { appendThought: true })
    message.answer += String(data.thought ?? '')
    shouldRefreshOutputParts = true
  } else if (event === QueueEvent.agentAction) {
    upsertThought(thoughts, data, nextState, { appendThought: false })
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
    nextState.routingDecision = data as Record<string, unknown>
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.orchestratorReject) {
    nextState.orchestratorReject = {
      reason: String(data?.reason ?? ''),
      message: String(data?.message ?? ''),
    }
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.toolConfirmationRequired) {
    nextState.toolConfirmationPrompt = {
      id: String(data.id ?? ''),
      tool_name: String(data.tool ?? ''),
      risk_level: (String(data.risk_level ?? 'high') as ToolConfirmationPrompt['risk_level']),
      spent_credits: Number(data.spent_credits ?? 0),
      tool_input: normalizeToolInput(data.tool_input),
      target_system: String(data.target_system ?? ''),
      target_environment: String(data.target_environment ?? ''),
      impact_scope: String(data.impact_scope ?? ''),
      rollback_strategy: String(data.rollback_strategy ?? ''),
      audit_hint: String(data.audit_hint ?? ''),
    } as ToolConfirmationPrompt
    return { state: nextState, didUpdate: true }
  } else if (event === QueueEvent.memoryCandidatePrompt) {
    nextState.memoryCandidatePrompt = {
      id: String(data.candidate_id ?? ''),
      content: String(data.content ?? ''),
      confidence: Number(data.confidence ?? 0) || 0,
      occurrences: Number(data.occurrences ?? 1) || 1,
      status: String(data.status ?? 'pending'),
    } as MemoryCandidatePrompt
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
