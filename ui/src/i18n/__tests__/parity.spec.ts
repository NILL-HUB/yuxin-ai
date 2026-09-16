import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
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

// ---------------------------------------------------------------------------
// 源码引用键扫描（守卫：防止「代码引用了字典里不存在的键」导致页面显示原始 key）
// 背景：desktopClientConfig 字典曾多包一层命名空间，实际路径变成
// admin.desktopClientConfig.desktopClient.title，与组件引用的
// admin.desktopClientConfig.title 不匹配，整块文案退化成裸 key。
// 旧的 parity 测试只比对 zh/en 键集合是否镜像，两侧同时错也发现不了。
// ---------------------------------------------------------------------------

// vitest 的 root 即 ui/ 目录（见 vitest.config.ts），源码在 ui/src
const SRC_DIR = join(process.cwd(), 'src')

const collectSourceFiles = (dir: string, out: string[] = []): string[] => {
  for (const entry of readdirSync(dir)) {
    const full = `${dir}${sep}${entry}`
    if (statSync(full).isDirectory()) {
      if (entry === '__tests__' || entry === 'node_modules') continue
      collectSourceFiles(full, out)
    } else if (/\.(ts|vue)$/.test(entry)) {
      out.push(full)
    }
  }
  return out
}

// 匹配 t('a.b')、$t('a.b')、i18n.global.t('a.b') 等字面量调用；动态键（变量/模板串）天然不匹配
const REFERENCED_KEY_RE = /(?:\bt|\$t)\(\s*(['"])([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)\1/g

const collectReferencedKeys = (): Map<string, string> => {
  const files = collectSourceFiles(SRC_DIR)
  const referenced = new Map<string, string>()
  for (const file of files) {
    const normalized = relative(SRC_DIR, file).split(sep).join('/')
    // 字典本身是「定义键」而非「引用键」，跳过以免自引用
    if (normalized.includes('/i18n/messages/')) continue
    const content = readFileSync(file, 'utf8')
    let match: RegExpExecArray | null
    while ((match = REFERENCED_KEY_RE.exec(content)) !== null) {
      const key = match[2]
      if (!referenced.has(key)) {
        referenced.set(key, `src/${normalized}`)
      }
    }
  }
  return referenced
}

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

describe('i18n referenced-key guard', () => {
  const zhPaths = toPathSet(zhCN)

  it('resolves every literal t() key referenced in src against the dictionary', () => {
    const referenced = collectReferencedKeys()
    const unresolved: string[] = []
    for (const [key, file] of referenced) {
      if (!zhPaths.has(key)) {
        unresolved.push(`${key}  (引用位置: ${file})`)
      }
    }
    expect(unresolved.sort()).toEqual([])
  })

  it('actually finds referenced keys (guards against a silently broken scanner)', () => {
    const referenced = collectReferencedKeys()
    // 扫描器至少要能识别出大量键，否则说明正则/路径失效，守卫形同虚设
    expect(referenced.size).toBeGreaterThan(500)
  })
})
