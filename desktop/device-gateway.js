/**
 * 设备网关客户端（Socket.IO `/device` 命名空间）：云端 → 设备 的常驻下行通道。
 *
 * 背景（spec §4.3 / P1 计划）：bridge 在 NAT 后面、公网不可达，服务端无法直连；
 * 因此桌面端主动外连云端，服务端经网关下发 `device_dispatch`，设备在本地调用
 * bridge（127.0.0.1）执行，再经 HTTP `POST /desktop/gateway/result` 回传结果
 * （上行方向无 NAT 问题）。服务端按 request_id 关联回发起进程完成同步等待。
 *
 * 鉴权：`device_id + bridge_token`（复用注册凭证；每次启动 token 重新生成并注册，
 * 凭证变化时调用 refreshCredentials 触发重连）。
 */

const GATEWAY_NAMESPACE = '/device'
const PING_INTERVAL_MS = 30_000
const RECONNECT_MAX_DELAY_MS = 60_000
const BRIDGE_LOCAL_HOST = '127.0.0.1'

// 允许经网关下发的 bridge 路由（白名单：与 desktop/bridge.js 的路由表一致）
const ALLOWED_DISPATCH_PURPOSES = new Set([
  '/file',
  '/recycle',
  '/snapshot',
  '/exec',
  '/browser',
  '/control',
  '/render',
  '/artifact',
])

/** 指数退避：1s → 2s → 4s …，封顶 60s。 */
function computeReconnectDelay(attempt) {
  const normalized = Math.max(1, Number(attempt) || 1)
  return Math.min(RECONNECT_MAX_DELAY_MS, 1000 * Math.pow(2, normalized - 1))
}

/** 懒加载 socket.io-client：缺少依赖时仅网关不可用，不拖垮桌面端主流程。 */
function loadDefaultIoFactory() {
  const { io } = require('socket.io-client')
  return io
}

function trimTrailingSlash(value) {
  return String(value || '').replace(/\/+$/, '')
}

function createDeviceGateway(options = {}) {
  let config = {
    socketUrl: trimTrailingSlash(options.socketUrl),
    socketPath: options.socketPath || '/socket.io',
    apiBase: trimTrailingSlash(options.apiBase),
    deviceId: String(options.deviceId || ''),
    bridgeToken: String(options.bridgeToken || ''),
    bridgePort: Number(options.bridgePort || 9876),
  }
  const ioFactoryOption = options.ioFactory || null
  let ioFactory = ioFactoryOption
  const fetchImpl = options.fetchImpl || (typeof fetch === 'function' ? fetch : null)
  const setTimeoutImpl = options.setTimeoutImpl || setTimeout
  const clearTimeoutImpl = options.clearTimeoutImpl || clearTimeout
  const logger = options.logger || console

  function resolveIoFactory() {
    if (!ioFactory) {
      ioFactory = loadDefaultIoFactory()
    }
    return ioFactory
  }

  let socket = null
  let pingTimer = null
  let reconnectTimer = null
  let reconnectAttempt = 0
  let running = false

  function log(...args) {
    if (logger && typeof logger.log === 'function') logger.log(...args)
  }

  function warn(...args) {
    if (logger && typeof logger.warn === 'function') logger.warn(...args)
  }

  function clearPing() {
    if (pingTimer) {
      clearTimeoutImpl(pingTimer)
      pingTimer = null
    }
  }

  function clearReconnect() {
    if (reconnectTimer) {
      clearTimeoutImpl(reconnectTimer)
      reconnectTimer = null
    }
  }

  function schedulePing() {
    clearPing()
    pingTimer = setTimeoutImpl(() => {
      if (socket && socket.connected) {
        socket.emit('device_ping', {})
      }
      if (running) schedulePing()
    }, PING_INTERVAL_MS)
  }

  function scheduleReconnect() {
    if (!running || reconnectTimer) return
    reconnectAttempt += 1
    const delay = computeReconnectDelay(reconnectAttempt)
    warn(`[device-gw] 连接中断，${delay}ms 后重连（第 ${reconnectAttempt} 次）`)
    reconnectTimer = setTimeoutImpl(() => {
      reconnectTimer = null
      openSocket()
    }, delay)
  }

  async function reportResult({ requestId, ok, result, error }) {
    if (!fetchImpl || !config.apiBase) return
    try {
      await fetchImpl(`${config.apiBase}/desktop/gateway/result`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          Authorization: `Bearer ${config.bridgeToken}`,
        },
        body: JSON.stringify({
          device_id: config.deviceId,
          request_id: requestId,
          ok: Boolean(ok),
          ...(ok ? { result } : { error: String(error || '设备执行失败') }),
        }),
      })
    } catch (err) {
      warn(`[device-gw] 结果回传失败 request=${requestId}: ${err && err.message ? err.message : err}`)
    }
  }

  async function handleDispatch(message) {
    const payload = message || {}
    const requestId = String(payload.request_id || '').trim()
    const purpose = String(payload.purpose || '').trim()
    if (!requestId) {
      warn('[device-gw] 收到缺少 request_id 的下发指令，忽略')
      return
    }
    if (!ALLOWED_DISPATCH_PURPOSES.has(purpose)) {
      await reportResult({ requestId, ok: false, error: `不支持的指令类型: ${purpose}` })
      return
    }
    if (!fetchImpl) {
      await reportResult({ requestId, ok: false, error: '本机网络组件不可用' })
      return
    }
    try {
      const response = await fetchImpl(`http://${BRIDGE_LOCAL_HOST}:${config.bridgePort}${purpose}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          Authorization: `Bearer ${config.bridgeToken}`,
        },
        body: JSON.stringify(payload.payload || {}),
      })
      let result = null
      try {
        result = await response.json()
      } catch (err) {
        result = null
      }
      if (response.ok && result) {
        await reportResult({ requestId, ok: true, result })
      } else {
        await reportResult({
          requestId,
          ok: false,
          error: `本机能力桥执行失败（HTTP ${response.status}）`,
        })
      }
    } catch (err) {
      await reportResult({
        requestId,
        ok: false,
        error: `本机能力桥不可达：${err && err.message ? err.message : err}`,
      })
    }
  }

  function openSocket() {
    if (!running) return
    if (!config.socketUrl || !config.deviceId || !config.bridgeToken) {
      warn('[device-gw] 缺少连接参数，跳过连接')
      return
    }
    let factory = null
    try {
      factory = resolveIoFactory()
    } catch (err) {
      warn(`[device-gw] socket.io-client 未安装，网关不可用: ${err && err.message ? err.message : err}`)
      return
    }
    const url = `${config.socketUrl}${GATEWAY_NAMESPACE}`
    socket = factory(url, {
      path: config.socketPath,
      transports: ['websocket'],
      reconnection: false, // 自管指数退避（便于与凭证刷新联动）
      auth: { device_id: config.deviceId, bridge_token: config.bridgeToken },
    })
    socket.on('connect', () => {
      reconnectAttempt = 0
      clearReconnect()
      log('[device-gw] 已连接')
      schedulePing()
    })
    socket.on('disconnect', () => {
      clearPing()
      scheduleReconnect()
    })
    socket.on('connect_error', (err) => {
      warn(`[device-gw] 连接失败: ${err && err.message ? err.message : err}`)
      scheduleReconnect()
    })
    socket.on('device_dispatch', (message) => {
      void handleDispatch(message)
    })
  }

  function start() {
    if (running) return
    running = true
    reconnectAttempt = 0
    openSocket()
  }

  function stop() {
    running = false
    clearPing()
    clearReconnect()
    if (socket) {
      try {
        socket.disconnect()
      } catch (err) {
        /* 忽略断开异常 */
      }
      socket = null
    }
  }

  /** 凭证/地址变化（重新注册后 token 变更、admin 切换服务器地址）时刷新并重连。 */
  function refreshCredentials(overrides = {}) {
    const next = {
      ...config,
      ...('socketUrl' in overrides ? { socketUrl: trimTrailingSlash(overrides.socketUrl) } : {}),
      ...('apiBase' in overrides ? { apiBase: trimTrailingSlash(overrides.apiBase) } : {}),
      ...('socketPath' in overrides && overrides.socketPath ? { socketPath: overrides.socketPath } : {}),
      ...('deviceId' in overrides && overrides.deviceId ? { deviceId: String(overrides.deviceId) } : {}),
      ...('bridgeToken' in overrides && overrides.bridgeToken
        ? { bridgeToken: String(overrides.bridgeToken) }
        : {}),
    }
    const changed =
      next.socketUrl !== config.socketUrl ||
      next.socketPath !== config.socketPath ||
      next.apiBase !== config.apiBase ||
      next.deviceId !== config.deviceId ||
      next.bridgeToken !== config.bridgeToken
    config = next
    if (!changed) return
    const wasRunning = running
    stop()
    if (wasRunning) start()
  }

  return {
    start,
    stop,
    refreshCredentials,
    isConnected: () => Boolean(socket && socket.connected),
    // 供单测直接驱动指令处理（生产路径由 socket.on('device_dispatch') 触发）
    handleDispatch,
  }
}

module.exports = {
  GATEWAY_NAMESPACE,
  ALLOWED_DISPATCH_PURPOSES,
  PING_INTERVAL_MS,
  RECONNECT_MAX_DELAY_MS,
  computeReconnectDelay,
  createDeviceGateway,
}
