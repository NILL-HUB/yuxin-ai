const { test, afterEach } = require('node:test')
const assert = require('node:assert')
const {
  configureUpdater,
  normalizeReleaseNotes,
  fetchUpdateManifest,
} = require('../updater')

const originalFetch = globalThis.fetch

function stubFetch(handler) {
  globalThis.fetch = async (url, options) => handler(url, options)
}

afterEach(() => {
  globalThis.fetch = originalFetch
  configureUpdater({ getApiBase: null })
})

test('normalizeReleaseNotes keeps strings and trims them', () => {
  assert.equal(normalizeReleaseNotes('  a\nb  '), 'a\nb')
})

test('normalizeReleaseNotes joins version notes into lines', () => {
  assert.equal(
    normalizeReleaseNotes([
      { version: '0.1.1', note: 'A' },
      { version: '0.1.0', note: 'B' },
    ]),
    'A\nB',
  )
})

test('normalizeReleaseNotes returns empty for null and undefined', () => {
  assert.equal(normalizeReleaseNotes(null), '')
  assert.equal(normalizeReleaseNotes(undefined), '')
})

test('fetchUpdateManifest returns null without an api base resolver', async () => {
  configureUpdater({})
  assert.equal(await fetchUpdateManifest(), null)
})

test('fetchUpdateManifest reads the gate manifest and trims the feed url', async () => {
  configureUpdater({ getApiBase: () => 'https://openllm.cloud/api' })
  let requested = ''
  stubFetch((url) => {
    requested = url
    return {
      ok: true,
      json: async () => ({
        code: 'success',
        data: { enabled: true, feed_url: 'https://openllm.cloud/desktop-updates/' },
      }),
    }
  })

  const manifest = await fetchUpdateManifest()

  assert.equal(requested, 'https://openllm.cloud/api/desktop/update-manifest')
  assert.deepEqual(manifest, {
    enabled: true,
    feed_url: 'https://openllm.cloud/desktop-updates',
  })
})

test('fetchUpdateManifest reports disabled when the admin turns pushing off', async () => {
  configureUpdater({ getApiBase: () => 'https://openllm.cloud/api' })
  stubFetch(() => ({
    ok: true,
    json: async () => ({ code: 'success', data: { enabled: false, feed_url: '' } }),
  }))

  assert.deepEqual(await fetchUpdateManifest(), { enabled: false, feed_url: '' })
})

test('fetchUpdateManifest falls back to null when the endpoint is unreachable', async () => {
  configureUpdater({ getApiBase: () => 'https://openllm.cloud/api' })
  stubFetch(() => {
    throw new Error('network down')
  })

  assert.equal(await fetchUpdateManifest(), null)
})

test('fetchUpdateManifest falls back to null on a non-ok response', async () => {
  configureUpdater({ getApiBase: () => 'https://openllm.cloud/api' })
  stubFetch(() => ({ ok: false, status: 503, json: async () => ({}) }))

  assert.equal(await fetchUpdateManifest(), null)
})
