const fs = require('node:fs')
const path = require('node:path')

const DEFAULT_ENTRY_ORIGIN = 'https://openllm.cloud'

async function loadServerConfig({ entryOrigin = DEFAULT_ENTRY_ORIGIN, cachePath, fetchImpl } = {}) {
  const fetchFn = fetchImpl || globalThis.fetch
  try {
    const resp = await fetchFn(`${entryOrigin}/api/desktop-config`)
    if (resp.ok) {
      const json = await resp.json()
      const data = json?.data
      if (data?.api_origin) {
        const cfg = {
          api_origin: String(data.api_origin).replace(/\/+$/, ''),
          api_prefix: data.api_prefix || '/api',
          app_name: data.app_name || '钰心AI',
        }
        if (cachePath) {
          fs.mkdirSync(path.dirname(cachePath), { recursive: true })
          fs.writeFileSync(cachePath, JSON.stringify(cfg), 'utf-8')
        }
        return cfg
      }
    }
  } catch {
    // 网络失败走缓存/默认
  }
  if (cachePath && fs.existsSync(cachePath)) {
    try {
      return JSON.parse(fs.readFileSync(cachePath, 'utf-8'))
    } catch {
      // 缓存损坏忽略
    }
  }
  return { api_origin: entryOrigin, api_prefix: '/api', app_name: '钰心AI' }
}

module.exports = { loadServerConfig, DEFAULT_ENTRY_ORIGIN }
