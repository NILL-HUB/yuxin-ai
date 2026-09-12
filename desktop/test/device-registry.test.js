const { test } = require('node:test')
const assert = require('node:assert')
const path = require('node:path')
const os = require('node:os')
const fs = require('node:fs')
const {
  loadOrCreateDeviceId,
  resolveBridgePublicOrigin,
  resolveDeviceName,
  registerDevice,
  revokeDevice,
} = require('../device-registry')

test('loadOrCreateDeviceId persists and is stable across calls', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'devid-'))
  const filePath = path.join(dir, 'nested', 'device-id')

  const first = loadOrCreateDeviceId({ filePath })
  const second = loadOrCreateDeviceId({ filePath })

  assert.ok(first)
  assert.equal(first, second)
  assert.ok(fs.existsSync(filePath))
})

test('loadOrCreateDeviceId returns empty without filePath', () => {
  assert.equal(loadOrCreateDeviceId({}), '')
})

test('resolveBridgePublicOrigin defaults to host.docker.internal with bridge port', () => {
  assert.equal(
    resolveBridgePublicOrigin({ env: {}, bridgePort: 9876 }),
    'http://host.docker.internal:9876',
  )
  assert.equal(
    resolveBridgePublicOrigin({ env: {}, bridgePort: 9999 }),
    'http://host.docker.internal:9999',
  )
})

test('resolveBridgePublicOrigin honors explicit override', () => {
  assert.equal(
    resolveBridgePublicOrigin({
      env: { DESKTOP_BRIDGE_PUBLIC_ORIGIN: 'http://127.0.0.1:9876/' },
      bridgePort: 9876,
    }),
    'http://127.0.0.1:9876',
  )
})

test('resolveDeviceName prefers configured name', () => {
  assert.equal(resolveDeviceName({ env: { DESKTOP_DEVICE_NAME: '我的电脑' } }), '我的电脑')
  assert.ok(resolveDeviceName({ env: {} }) !== undefined)
})

test('registerDevice posts payload with bearer token', async () => {
  const captured = {}
  const result = await registerDevice({
    apiBase: 'https://cloud.example.com/api/',
    accessToken: 'jwt-token',
    deviceId: 'dev-1',
    bridgeOrigin: 'http://host.docker.internal:9876',
    bridgeToken: 'bridge-token',
    name: '我的电脑',
    platform: 'win32',
    fetchImpl: async (url, options) => {
      captured.url = url
      captured.options = options
      return { ok: true, json: async () => ({ code: 'success', data: { device_id: 'dev-1' } }) }
    },
  })

  assert.equal(result.ok, true)
  assert.equal(captured.url, 'https://cloud.example.com/api/desktop/devices/register')
  assert.equal(captured.options.method, 'POST')
  assert.equal(captured.options.headers.Authorization, 'Bearer jwt-token')
  const body = JSON.parse(captured.options.body)
  assert.equal(body.device_id, 'dev-1')
  assert.equal(body.bridge_origin, 'http://host.docker.internal:9876')
  assert.equal(body.bridge_token, 'bridge-token')
})

test('registerDevice returns invalid_params when required fields missing', async () => {
  const result = await registerDevice({ apiBase: 'https://x/api', accessToken: '' })
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'invalid_params')
})

test('registerDevice returns http status reason on failure', async () => {
  const result = await registerDevice({
    apiBase: 'https://x/api',
    accessToken: 't',
    deviceId: 'd',
    bridgeOrigin: 'http://h:1',
    bridgeToken: 'bt',
    fetchImpl: async () => ({ ok: false, status: 401 }),
  })
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'http_401')
})

test('registerDevice returns network_error when fetch throws', async () => {
  const result = await registerDevice({
    apiBase: 'https://x/api',
    accessToken: 't',
    deviceId: 'd',
    bridgeOrigin: 'http://h:1',
    bridgeToken: 'bt',
    fetchImpl: async () => {
      throw new Error('boom')
    },
  })
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'network_error')
})

test('revokeDevice posts to device revoke endpoint', async () => {
  const captured = {}
  const result = await revokeDevice({
    apiBase: 'https://cloud.example.com/api/',
    accessToken: 'jwt-token',
    deviceId: 'dev-1',
    fetchImpl: async (url, options) => {
      captured.url = url
      captured.options = options
      return { ok: true }
    },
  })

  assert.equal(result.ok, true)
  assert.equal(captured.url, 'https://cloud.example.com/api/desktop/devices/dev-1/revoke')
  assert.equal(captured.options.method, 'POST')
  assert.equal(captured.options.headers.Authorization, 'Bearer jwt-token')
})

test('revokeDevice returns invalid_params when deviceId missing', async () => {
  const result = await revokeDevice({ apiBase: 'https://x/api', accessToken: 't' })
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'invalid_params')
})

test('revokeDevice returns http status reason on failure', async () => {
  const result = await revokeDevice({
    apiBase: 'https://x/api',
    accessToken: 't',
    deviceId: 'd',
    fetchImpl: async () => ({ ok: false, status: 404 }),
  })
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'http_404')
})
