export type ToolConfirmationPrompt = {
  id: string
  tool_name: string
  risk_level: 'medium' | 'high' | 'sensitive'
  spent_credits: number
  tool_input: Record<string, unknown>
  target_system?: string
  target_environment?: string
  impact_scope?: string
  rollback_strategy?: string
  audit_hint?: string
}

export type ToolConfirmation = {
  id: string
  tool_name: string
  risk_level: 'medium' | 'high' | 'sensitive'
  tool_input: Record<string, unknown>
  status: 'pending' | 'confirmed' | 'cancelled'
  spent_credits: number
  reason: string
  created_at: string
  updated_at: string
}
