export type MemoryCandidatePrompt = {
  id: string
  content: string
  confidence: number
  occurrences: number
  status?: string
  metadata?: Record<string, unknown>
}

export type ConfirmMemoryCandidateRequest = {
  policy: 'manual_confirm' | 'auto_save'
}

export type IgnoreMemoryCandidateRequest = {
  never_remind: boolean
}

export type UserMemory = {
  id: string
  memory_type: string
  content: string
  confidence: number
  status: string
  created_from: string
  metadata: Record<string, unknown>
}

export type MemoryCandidate = MemoryCandidatePrompt & {
  candidate_key?: string
}
