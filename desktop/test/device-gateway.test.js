const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')

const {
  GATEWAY_NAMESPACE,
  computeReconnectDelay,
  createDeviceGateway,
} = require('../device-gateway')

class FakeSocket extends EventEmitter {
  constructor() {
    super()
    this.connected = false
    this.sent = []
    this.disconnectCalls = 0
  }

  emit(event, ...args) {
    if (this.listenerCount(event) > 0) {
      return super.emit(event, ...args)
    }
    this.sent.push([event, ...args])
    return true
  }

  connect() {
    this.connected = true
    super.emit('connect')
  }

  serverPush(event, payload) {
    super.emit(event, payload)
  }

  disconnect() {
    this.disconnectCalls += 1
    this.connected = false
    super.emit('disconnect')
  }
}

function buildEnv(overrides = {}) {
  const socket = new FakeSocket()
  const ioCalls = []
  const fetchCalls = []
  const timers = []

  const fetchImpl = async (url, init) => {
    fetchCalls.push({ url, init })
    return {
      ok: true,
      status: 200,
      json: async () => ({ ok: true, content: 'hello' }),
    }
  }

  const gateway = createDeviceGateway({
    socketUrl: 'https://cloud.example.com',
    socketPath: '/api/socket.io',
    apiBase: 'https://cloud.example.com/api',
    deviceId: 'dev-1',
    bridgeToken: 'bridge-token',
    bridgePort: 9876,
    ioFactory: (url, opts) => {
      ioCalls.push({ url, opts })
      return socket
    },
    fetchImpl,
    setTimeoutImpl: (fn, delay) => {
      timers.push({ fn, delay })
      return { id: timers.length }
    },
    clearTimeoutImpl: () => {},
    logger: { log() {}, warn() {} },
    ...overrides,
  })
  return { gateway, socket, ioCalls, fetchCalls, timers }
}

test('computeReconnectDelay grows exponentially and caps at 60s', () => {
  assert.equal(computeReconnectDelay(1), 1000)
  assert.equal(computeReconnectDelay(2), 2000)
  assert.equal(computeReconnectDelay(3), 4000)
  assert.equal(computeReconnectDelay(7), 60000)
  assert.equal(computeReconnectDelay(99), 60000)
})

test('start connects to /device namespace with device credentials', () => {
  const { gateway, ioCalls } = buildEnv()

  gateway.start()

  assert.equal(ioCalls.length, 1)
  assert.equal(ioCalls[0].url, `https://cloud.example.com${GATEWAY_NAMESPACE}`)
  assert.equal(ioCalls[0].opts.path, '/api/socket.io')
  assert.deepEqual(ioCalls[0].opts.auth, { device_id: 'dev-1', bridge_token: 'bridge-token' })
  assert.equal(ioCalls[0].opts.reconnection, false)
})

test('dispatch executes on local bridge then posts result to cloud', async () => {
  const { gateway, socket, fetchCalls } = buildEnv()
  gateway.start()
  socket.connect()

  await gateway.handleDispatch({ request_id: 'r1', purpose: '/file', payload: { op: 'read' } })

  assert.equal(fetchCalls.length, 2)
  assert.equal(fetchCalls[0].url, 'http://127.0.0.1:9876/file')
  assert.equal(fetchCalls[0].init.headers.Authorization, 'Bearer bridge-token')
  assert.deepEqual(JSON.parse(fetchCalls[0].init.body), { op: 'read' })

  assert.equal(fetchCalls[1].url, 'https://cloud.example.com/api/desktop/gateway/result')
  const report = JSON.parse(fetchCalls[1].init.body)
  assert.equal(report.device_id, 'dev-1')
  assert.equal(report.request_id, 'r1')
  assert.equal(report.ok, true)
  assert.deepEqual(report.result, { ok: true, content: 'hello' })
})

test('dispatch rejects non-whitelisted purpose without touching local bridge', async () => {
  const { gateway, socket, fetchCalls } = buildEnv()
  gateway.start()
  socket.connect()

  await gateway.handleDispatch({ request_id: 'r2', purpose: '/evil', payload: {} })

  assert.equal(fetchCalls.length, 1)
  assert.equal(fetchCalls[0].url, 'https://cloud.example.com/api/desktop/gateway/result')
  const report = JSON.parse(fetchCalls[0].init.body)
  assert.equal(report.ok, false)
  assert.match(report.error, /不支持的指令类型/)
})

test('dispatch reports failure when local bridge errors', async () => {
  const { gateway, socket, fetchCalls } = buildEnv({
    fetchImpl: async (url, init) => {
      fetchCalls.push({ url, init })
      if (url.startsWith('http://127.0.0.1')) {
        return { ok: false, status: 502, json: async () => ({ error: 'worker down' }) }
      }
      return { ok: true, status: 200, json: async () => ({}) }
    },
  })
  gateway.start()
  socket.connect()

  await gateway.handleDispatch({ request_id: 'r3', purpose: '/control', payload: {} })

  const report = JSON.parse(fetchCalls[fetchCalls.length - 1].init.body)
  assert.equal(report.ok, false)
  assert.match(report.error, /HTTP 502/)
})

test('dispatch reports failure when local bridge is unreachable', async () => {
  const fetchCalls = []
  const { gateway, socket } = buildEnv({
    fetchImpl: async (url, init) => {
      fetchCalls.push({ url, init })
      if (url.startsWith('http://127.0.0.1')) {
        throw new Error('connect ECONNREFUSED')
      }
      return { ok: true, status: 200, json: async () => ({}) }
    },
  })
  gateway.start()
  socket.connect()

  await gateway.handleDispatch({ request_id: 'r4', purpose: '/snapshot', payload: {} })

  const report = JSON.parse(fetchCalls[fetchCalls.length - 1].init.body)
  assert.equal(report.ok, false)
  assert.match(report.error, /ECONNREFUSED/)
})

test('disconnect schedules reconnect with backoff and stop cancels it', () => {
  const { gateway, socket, timers } = buildEnv()
  gateway.start()
  socket.connect()

  socket.disconnect()
  const reconnectTimers = timers.filter((item) => item.delay === 1000)
  assert.equal(reconnectTimers.length, 1)

  gateway.stop()
  const before = timers.length
  socket.disconnect()
  assert.equal(timers.length, before)
})

test('refreshCredentials restarts the connection when bridge token rotates', () => {
  const { gateway, ioCalls, socket } = buildEnv()
  gateway.start()
  assert.equal(ioCalls.length, 1)

  gateway.refreshCredentials({ bridgeToken: 'rotated-token' })

  assert.equal(ioCalls.length, 2)
  assert.equal(ioCalls[1].opts.auth.bridge_token, 'rotated-token')
  assert.equal(socket.disconnectCalls, 1)
})

test('ping timer emits device_ping while connected', () => {
  const { gateway, socket, timers } = buildEnv()
  gateway.start()
  socket.connect()

  const pingTimer = timers.find((item) => item.delay === 30000)
  assert.ok(pingTimer)
  pingTimer.fn()

  assert.ok(socket.sent.some((entry) => entry[0] === 'device_ping'))
})
