import type { McpCliTemplate } from './types'

const BAILIAN_PACKAGE = 'bailian-cli@2.0.1'
const ARK_PACKAGE = '@volcengine/ark-cli@1.0.36'

export const MCP_CLI_TEMPLATES: McpCliTemplate[] = [
  {
    key: 'bailian_model_search',
    vendor: 'bailian',
    transport: 'cli',
    command: 'npx',
    args: [
      '-y',
      BAILIAN_PACKAGE,
      'model',
      'search',
      '--keyword',
      '{keyword}',
      '--limit',
      '{limit}',
      '--output',
      'json',
    ],
    env: { NO_COLOR: '1' },
    requiresSecret: false,
    secretKeyName: '',
    versionedPackage: BAILIAN_PACKAGE,
    toolSchema: {
      search_bailian_models: {
        description: '按关键词搜索阿里云百炼模型目录',
        parameters: {
          type: 'object',
          properties: {
            keyword: { type: 'string', description: '搜索关键词，例如 qwen' },
            limit: { type: 'integer', description: '返回条数上限' },
          },
          required: ['keyword'],
        },
      },
    },
  },
  {
    key: 'bailian_text_chat',
    vendor: 'bailian',
    transport: 'cli',
    command: 'npx',
    args: [
      '-y',
      BAILIAN_PACKAGE,
      'text',
      'chat',
      '--model',
      '{model}',
      '--message',
      '{message}',
      '--output',
      'json',
    ],
    env: { NO_COLOR: '1' },
    requiresSecret: true,
    secretKeyName: 'DASHSCOPE_API_KEY',
    versionedPackage: BAILIAN_PACKAGE,
    toolSchema: {
      bailian_text_chat: {
        description: '调用阿里云百炼文本大模型进行对话与推理',
        parameters: {
          type: 'object',
          properties: {
            model: { type: 'string', description: '模型 ID，例如 qwen3.8-max' },
            message: { type: 'string', description: '用户消息内容' },
          },
          required: ['message'],
        },
      },
    },
  },
  {
    key: 'ark_text_chat',
    vendor: 'ark',
    transport: 'cli',
    command: 'npx',
    args: [
      '-y',
      ARK_PACKAGE,
      '+chat',
      '{prompt}',
      '--model',
      '{model}',
      '--text-format',
      'json',
    ],
    env: { NO_COLOR: '1' },
    requiresSecret: true,
    secretKeyName: 'ARK_API_KEY',
    versionedPackage: ARK_PACKAGE,
    toolSchema: {
      ark_text_chat: {
        description: '调用火山方舟文本模型进行对话与推理',
        parameters: {
          type: 'object',
          properties: {
            prompt: { type: 'string', description: '提示词内容' },
            model: { type: 'string', description: '模型名或接入点 ID' },
          },
          required: ['prompt'],
        },
      },
    },
  },
  {
    key: 'ark_model_search',
    vendor: 'ark',
    transport: 'cli',
    command: 'npx',
    args: ['-y', ARK_PACKAGE, 'models', 'search', '--keyword', '{keyword}'],
    env: { NO_COLOR: '1' },
    requiresSecret: true,
    secretKeyName: 'ARK_API_KEY',
    versionedPackage: ARK_PACKAGE,
    toolSchema: {
      search_ark_models: {
        description: '按关键词搜索火山方舟模型目录',
        parameters: {
          type: 'object',
          properties: {
            keyword: { type: 'string', description: '搜索关键词，例如 seedream' },
          },
          required: ['keyword'],
        },
      },
    },
  },
]

export const findMcpCliTemplate = (key: string): McpCliTemplate | undefined =>
  MCP_CLI_TEMPLATES.find((template) => template.key === key)

export const bumpTemplateToLatest = (template: McpCliTemplate): string[] =>
  template.args.map((arg) => (arg === template.versionedPackage ? latestPackageName(template.versionedPackage) : arg))

export const latestPackageName = (versionedPackage: string): string => {
  const atIndex = versionedPackage.lastIndexOf('@')
  if (atIndex <= 0) return versionedPackage
  return `${versionedPackage.slice(0, atIndex)}@latest`
}
