export type ToolConfirmationPrompt = {
  id: string
  tool_name: string
  risk_level: 'medium' | 'high'
  spent_credits: number
  tool_input: Record<string, unknown>
}
