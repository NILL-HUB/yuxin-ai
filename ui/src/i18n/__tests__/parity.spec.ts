import { describe, expect, it } from 'vitest'

import enUS from '@/i18n/messages/en-US'
import zhCN from '@/i18n/messages/zh-CN'

type UnknownRecord = Record<string, unknown>

const isPlainObject = (value: unknown): value is UnknownRecord =>
  !!value && typeof value === 'object' && !Array.isArray(value)

const collectLeafPaths = (obj: unknown, prefix: string, out: string[]): void => {
  if (!isPlainObject(obj)) {
    out.push(prefix)
    return
  }
  for (const [key, value] of Object.entries(obj)) {
    const full = prefix ? `${prefix}.${key}` : key
    collectLeafPaths(value, full, out)
  }
}

const toPathSet = (obj: unknown): Set<string> => {
  const paths: string[] = []
  collectLeafPaths(obj, '', paths)
  return new Set(paths)
}

const leafValue = (obj: unknown, path: string): unknown =>
  path.split('.').reduce<unknown>((acc, seg) => {
    if (acc && typeof acc === 'object' && seg in (acc as UnknownRecord)) {
      return (acc as UnknownRecord)[seg]
    }
    return undefined
  }, obj)

describe('i18n message parity', () => {
  const zhPaths = toPathSet(zhCN)
  const enPaths = toPathSet(enUS)

  it('keeps zh-CN and en-US leaf key sets identical', () => {
    const onlyInZh = [...zhPaths].filter((p) => !enPaths.has(p))
    const onlyInEn = [...enPaths].filter((p) => !zhPaths.has(p))
    expect(onlyInZh).toEqual([])
    expect(onlyInEn).toEqual([])
  })

  it('mirrors top-level structure between zh-CN and en-US', () => {
    expect(Object.keys(zhCN).sort()).toEqual(Object.keys(enUS).sort())
  })

  it('resolves every leaf path to a value in both locales', () => {
    for (const path of zhPaths) {
      expect(leafValue(zhCN, path), `zh-CN "${path}"`).toBeDefined()
      expect(leafValue(enUS, path), `en-US "${path}"`).toBeDefined()
    }
  })
})
