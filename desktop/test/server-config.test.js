const { test } = require('node:test')
const assert = require('node:assert')
const path = require('node:path')
const os = require('node:os')
const fs = require('node:fs')
const { loadServerConfig } = require('../server-config')

const ENTRY_ORIGIN = 'https://entry.example.com'

test('loads remote config and caches it', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scfg-ok-'))
  const cachePath = path.join(dir, 'server-config.json')
  const cfg = await loadServerConfig({
    entryOrigin: ENTRY_ORIGIN,
    cachePath,
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({
        code: 'success',
        data: { app_name: '钰心AI', api_origin: 'https://cloud.example.com', api_prefix: '/api' },
      }),
    }),
  })
  assert.equal(cfg.api_origin, 'https://cloud.example.com')
  assert.equal(cfg.api_prefix, '/api')
  assert.equal(cfg.app_name, '钰心AI')
  assert.ok(fs.existsSync(cachePath))
})

test('uses cache when fetch fails', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scfg-cache-'))
  const cachePath = path.join(dir, 'server-config.json')
  fs.writeFileSync(
    cachePath,
    JSON.stringify({ api_origin: 'https://cached.example.com', api_prefix: '/api', app_name: 'X' }),
  )
  const cfg = await loadServerConfig({
    entryOrigin: ENTRY_ORIGIN,
    cachePath,
    fetchImpl: async () => {
      throw new Error('offline')
    },
  })
  assert.equal(cfg.api_origin, 'https://cached.example.com')
})

test('falls back to entry origin when no cache and fetch fails', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scfg-fb-'))
  const cfg = await loadServerConfig({
    entryOrigin: ENTRY_ORIGIN,
    cachePath: path.join(dir, 'none.json'),
    fetchImpl: async () => {
      throw new Error('offline')
    },
  })
  assert.equal(cfg.api_origin, ENTRY_ORIGIN)
  assert.equal(cfg.api_prefix, '/api')
})
