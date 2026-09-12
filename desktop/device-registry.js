const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const crypto = require('node:crypto')

// 桌面端 bridge 的默认对外地址：服务端（Docker 容器）经 host.docker.internal
// 可达宿主机回环。非容器部署可用 DESKTOP_BRIDGE_PUBLIC_ORIGIN 覆盖为 127.0.0.1。
const DEFAULT_BRIDGE_PUBLIC_ORIGIN = 'http://host.docker.internal:9876'
const REGISTER_TIMEOUT_MS = 8000

function loadOrCreateDeviceId({ filePath } = {}) {
  if (!filePath) return ''
  try {
    if (fs.existsSync(filePath)) {
      const raw = fs.readFileSync(filePath, 'utf-8').trim()
      if (raw) return raw
    }
  } catch {
    // 读取失败按缺失处理，重新生成
  }
  const deviceId = crypto.randomUUID()
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    fs.writeFileSync(filePath, deviceId, 'utf-8')
  } catch {
    // 落盘失败仍返回内存值：本次会话可用，下次重新生成
  }
  return deviceId
}

function resolveBridgePublicOrigin({ env = process.env, bridgePort } = {}) {
  const configured = String(env.DESKTOP_BRIDGE_PUBLIC_ORIGIN || '').trim()
  if (configured) return configured.replace(/\/+$/, '')
  const port = Number(bridgePort || env.DESKTOP_BRIDGE_PORT || 9876)
  return `${DEFAULT_BRIDGE_PUBLIC_ORIGIN.replace(/:\d+$/, '')}:${port}`
}

function resolveDeviceName({ env = process.env } = {}) {
  const configured = String(env.DESKTOP_DEVICE_NAME || '').trim()
  if (configured) return configured
  try {
    return os.hostname() || ''
  } catch {
    return ''
  }
}

async function registerDevice({
  apiBase,
  accessToken,
  deviceId,
  bridgeOrigin,
  bridgeToken,
  name = '',
  platform = '',
  fetchImpl,
  timeoutMs = REGISTER_TIMEOUT_MS,
} = {}) {
  const fetchFn = fetchImpl || globalThis.fetch
  const base = String(apiBase || '').replace(/\/+$/, '')
  if (!base || !accessToken || !deviceId || !bridgeOrigin || !bridgeToken) {
    return { ok: false, reason: 'invalid_params' }
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const resp = await fetchFn(`${base}/desktop/devices/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({
        device_id: deviceId,
        bridge_origin: bridgeOrigin,
        bridge_token: bridgeToken,
        name,
        platform,
      }),
      signal: controller.signal,
    })
    if (!resp.ok) {
      return { ok: false, reason: `http_${resp.status}` }
    }
    const json = await resp.json().catch(() => ({}))
    if (json && json.code && json.code !== 'success') {
      return { ok: false, reason: json.code }
    }
    return { ok: true, data: (json && json.data) || null }
  } catch (err) {
    return { ok: false, reason: err && err.name === 'AbortError' ? 'timeout' : 'network_error' }
  } finally {
    clearTimeout(timer)
  }
}

async function revokeDevice({
  apiBase,
  accessToken,
  deviceId,
  fetchImpl,
  timeoutMs = REGISTER_TIMEOUT_MS,
} = {}) {
  const fetchFn = fetchImpl || globalThis.fetch
  const base = String(apiBase || '').replace(/\/+$/, '')
  if (!base || !accessToken || !deviceId) {
    return { ok: false, reason: 'invalid_params' }
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const resp = await fetchFn(
      `${base}/desktop/devices/${encodeURIComponent(deviceId)}/revoke`,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${accessToken}` },
        signal: controller.signal,
      },
    )
    if (!resp.ok) return { ok: false, reason: `http_${resp.status}` }
    return { ok: true }
  } catch (err) {
    return { ok: false, reason: err && err.name === 'AbortError' ? 'timeout' : 'network_error' }
  } finally {
    clearTimeout(timer)
  }
}

module.exports = {
  DEFAULT_BRIDGE_PUBLIC_ORIGIN,
  loadOrCreateDeviceId,
  resolveBridgePublicOrigin,
  resolveDeviceName,
  registerDevice,
  revokeDevice,
}
