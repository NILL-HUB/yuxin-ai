// ui/src/services/admin-agents.ts
// 管理端 Agent（Agent 治理）API 封装。
// 端点契约见 docs/api/admin-agents-api.md 与 api/app/http/admin_routes_7.py。
import { get, post, patch, del, ssePost } from '@/utils/request'

type Envelope<T = unknown> = { code: string; message: string; data: T }

export type AutomationLevel = 'supervised' | 'autonomous' | 'blocked'

export interface AdminAgent {
  id: string
  name: string
  description: string
  prompt_key: string | null
  granted_permissions: string[]
  automation_policy: Record<string, AutomationLevel>
  budget_config: Record<string, number>
  enabled: boolean
  created_at: number
  updated_at: number
}

export interface AdminAgentCreatePayload {
  name: string
  description?: string
  prompt_key?: string | null
  granted_permissions?: string[]
  automation_policy?: Record<string, AutomationLevel>
  budget_config?: Record<string, number>
}

export interface AdminAgentUpdatePayload extends AdminAgentCreatePayload {
  enabled?: boolean
}

export interface BoardAction {
  board: string
  action: string
  kind: string
  permission_code: string
  description: string
}

export interface BoardCatalog {
  boards: string[]
  actions: BoardAction[]
}

export interface BudgetUsage {
  budget_config: Record<string, number>
  usage: {
    daily_executions: number
    monthly_executions: number
    daily_tokens: number
    monthly_tokens: number
  }
}

export interface ScheduleTask {
  id: string
  name: string
  cron_expression: string
  prompt: string
  task_type: string
  owner_type: string
  status: string
  input_params?: Record<string, unknown>
  next_run_at?: number
  last_run_at?: number
}

export interface ConversationItem {
  id: string
  admin_agent_id: string
  title: string
  created_at: number
  updated_at: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  tool_calls?: Record<string, unknown>[]
  created_at: number
}

export interface MemoryStats {
  total_nodes: number
  episodes: number
  skills: number
  recent_memories: {
    id: string
    content: string
    created_at: number | null
  }[]
}

export interface MemoryItem {
  id: string
  title: string
  content: string
  updated_at: number | null
}

export interface ChatFrame {
  event: string
  data: Record<string, unknown>
}

// ---------- Agent CRUD ----------

export async function listAgents(): Promise<AdminAgent[]> {
  const res = await get<Envelope<{ items: AdminAgent[] }>>('/admin/agents')
  return res.data.items || []
}

export async function createAgent(payload: AdminAgentCreatePayload): Promise<AdminAgent> {
  const res = await post<Envelope<AdminAgent>>('/admin/agents', { body: payload as unknown as Record<string, unknown> })
  return res.data
}

export async function updateAgent(id: string, payload: AdminAgentUpdatePayload): Promise<AdminAgent> {
  const res = await patch<Envelope<AdminAgent>>(`/admin/agents/${id}`, { body: payload as unknown as Record<string, unknown> })
  return res.data
}

export async function deleteAgent(id: string): Promise<void> {
  await del(`/admin/agents/${id}`)
}

// ---------- 治理元数据 ----------

export async function listAssignablePermissions(): Promise<string[]> {
  const res = await get<Envelope<{ codes: string[] }>>('/admin/agents/assignable-permissions')
  return res.data.codes || []
}

export async function listBoards(): Promise<BoardCatalog> {
  const res = await get<Envelope<BoardCatalog>>('/admin/agents/boards')
  return res.data
}

// ---------- 预算 ----------

export async function getBudgetUsage(id: string): Promise<BudgetUsage> {
  const res = await get<Envelope<BudgetUsage>>(`/admin/agents/${id}/budget/usage`)
  return res.data
}

// ---------- 定时任务 ----------

export async function listSchedules(id: string, params?: Record<string, unknown>): Promise<{ items: ScheduleTask[]; total: number }> {
  const res = await get<Envelope<{ items: ScheduleTask[]; total: number }>>(`/admin/agents/${id}/schedules`, { params })
  return res.data
}

export async function createSchedule(
  id: string,
  payload: { name: string; prompt?: string; cron_expression: string; board: string; action: string; payload?: Record<string, unknown> },
): Promise<ScheduleTask> {
  const res = await post<Envelope<ScheduleTask>>(`/admin/agents/${id}/schedules`, { body: payload })
  return res.data
}

export async function deleteSchedule(id: string, taskId: string): Promise<void> {
  await del(`/admin/agents/${id}/schedules/${taskId}`)
}

// ---------- 对话（SSE） ----------

export async function chatAgent(
  id: string,
  body: { query: string; conversation_id?: string | null },
  onData: (frame: ChatFrame) => void,
): Promise<Envelope | void> {
  return ssePost<Record<string, unknown>, Envelope>(
    `/admin/agents/${id}/chat`,
    { body: body as unknown as Record<string, unknown> },
    (payload) => onData(payload as ChatFrame),
  )
}

export async function listConversations(id: string): Promise<ConversationItem[]> {
  const res = await get<Envelope<{ items: ConversationItem[] }>>(`/admin/agents/${id}/conversations`)
  return res.data.items || []
}

export async function listMessages(conversationId: string): Promise<ChatMessage[]> {
  const res = await get<Envelope<{ items: ChatMessage[] }>>(`/admin/agents/conversations/${conversationId}/messages`)
  return res.data.items || []
}

// ---------- 记忆 ----------

export async function getMemoryStats(id: string): Promise<MemoryStats> {
  const res = await get<Envelope<MemoryStats>>(`/admin/agents/${id}/memory/stats`)
  return res.data
}

export async function listMemories(
  id: string,
  params?: { page?: number; page_size?: number },
): Promise<{ items: MemoryItem[]; total: number }> {
  const res = await get<Envelope<{ items: MemoryItem[]; total: number }>>(`/admin/agents/${id}/memory/list`, { params })
  return res.data
}

export async function gdprDeleteMemory(payload: {
  subject_type: 'user' | 'admin' | 'agent'
  subject_id: string
  agent_id?: string
}): Promise<{ owner_key: string; stats: Record<string, unknown> }> {
  const res = await post<Envelope<{ owner_key: string; stats: Record<string, unknown> }>>('/admin/memory/gdpr-delete', { body: payload })
  return res.data
}
