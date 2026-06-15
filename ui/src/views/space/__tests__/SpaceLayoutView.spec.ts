import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const readSource = () => {
  return readFileSync(resolve(process.cwd(), 'src/views/space/SpaceLayoutView.vue'), 'utf8')
}

const matchCount = (source: string, pattern: string) => {
  return source.split(pattern).length - 1
}

describe('SpaceLayoutView', () => {
  it('wraps routed content in a flex container so nested pages can scroll', () => {
    const source = readSource()

    expect(source).toContain('<div v-if="isLoggedIn" class="flex min-h-0 flex-1 overflow-hidden">')
    expect(source).toContain('<router-view />')
  })

  it('renders the configuration center title through i18n', () => {
    const source = readSource()

    expect(source).toContain("{{ $t('space.title') }}")
    expect(source).not.toContain('>配置中心<')
  })

  it('keeps a single i18n-backed MCP nav item and create button', () => {
    const source = readSource()

    expect(matchCount(source, "{{ $t('space.nav.mcp') }}")).toBe(1)
    expect(matchCount(source, "{{ $t('space.createMcp') }}")).toBe(1)
    expect(source).not.toContain('>MCP\n          </router-link>')
    expect(source).not.toContain('>\n          创建 MCP\n        </a-button>')
  })
})
