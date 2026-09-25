export type KeyValueItem = {
  key: string
  value: string
}

export type ToolParameterType = 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object'

export type ToolParameterItem = {
  name: string
  type: ToolParameterType
  required: boolean
  description: string
}

export type ToolDefinitionItem = {
  name: string
  description: string
  parameters: ToolParameterItem[]
}

export type McpCliTemplate = {
  key: string
  vendor: 'bailian' | 'ark'
  transport: 'cli'
  command: string
  args: string[]
  env: Record<string, string>
  toolSchema: Record<string, unknown>
  requiresSecret: boolean
  secretKeyName: string
  versionedPackage: string
}

export const TOOL_PARAMETER_TYPES: ToolParameterType[] = [
  'string',
  'number',
  'integer',
  'boolean',
  'array',
  'object',
]
