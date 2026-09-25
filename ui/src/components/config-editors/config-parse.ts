export type ConfigParseErrorCode = 'invalidJson' | 'arrayExpected' | 'objectExpected'

export class ConfigParseError extends Error {
  code: ConfigParseErrorCode

  constructor(code: ConfigParseErrorCode) {
    super(code)
    this.name = 'ConfigParseError'
    this.code = code
  }
}

const normalizeText = (text: unknown): string => String(text ?? '').trim()

export const isValidJsonArray = (text: unknown): boolean => {
  const normalized = normalizeText(text)
  if (!normalized) return true
  try {
    return Array.isArray(JSON.parse(normalized))
  } catch {
    return false
  }
}

export const isValidJsonObject = (text: unknown): boolean => {
  const normalized = normalizeText(text)
  if (!normalized) return true
  try {
    const parsed = JSON.parse(normalized)
    return Boolean(parsed) && typeof parsed === 'object' && !Array.isArray(parsed)
  } catch {
    return false
  }
}

export const parseJsonArray = <T = unknown>(text: unknown): T[] => {
  const normalized = normalizeText(text)
  if (!normalized) return []
  let parsed: unknown
  try {
    parsed = JSON.parse(normalized)
  } catch {
    throw new ConfigParseError('invalidJson')
  }
  if (!Array.isArray(parsed)) {
    throw new ConfigParseError('arrayExpected')
  }
  return parsed as T[]
}

export const parseJsonObject = (text: unknown): Record<string, unknown> => {
  const normalized = normalizeText(text)
  if (!normalized) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(normalized)
  } catch {
    throw new ConfigParseError('invalidJson')
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new ConfigParseError('objectExpected')
  }
  return parsed as Record<string, unknown>
}

export const formatJson = (value: unknown, fallback = ''): string => {
  if (value === undefined || value === null) return fallback
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return fallback
  }
}

export const splitCommaList = (text: unknown): string[] =>
  normalizeText(text)
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean)

export const joinCommaList = (values: unknown): string =>
  (Array.isArray(values) ? values : []).map((item) => String(item ?? '').trim()).filter(Boolean).join(', ')
