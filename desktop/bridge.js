const http = require('http')

function createBridge(options = {}) {
  const bridgeToken = options.token || process.env.DESKTOP_BRIDGE_TOKEN || ''
  const targets = options.targets || {
    '/recycle': {
      port: Number(options.recyclePort || process.env.OS_AUTOMATION_PORT || 8765),
      token: options.recycleToken || process.env.OS_AUTOMATION_TOKEN || '',
      path: '/recycle',
    },
    '/browser': {
      port: Number(options.browserPort || process.env.BROWSER_AUTOMATION_PORT || 8766),
      token: options.browserToken || process.env.BROWSER_AUTOMATION_TOKEN || '',
      path: '/browser',
    },
    '/control': {
      port: Number(options.computerPort || process.env.COMPUTER_CONTROL_PORT || 8767),
      token: options.computerToken || process.env.COMPUTER_CONTROL_TOKEN || '',
      path: '/control',
    },
  }

  return http.createServer((req, res) => {
    const target = targets[req.url && req.url.split('?')[0]]
    if (!target) {
      res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify({ ok: false, error: 'not_found' }))
      return
    }
    const auth = String(req.headers.authorization || '')
    const supplied = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : ''
    if (!bridgeToken || supplied !== bridgeToken) {
      res.writeHead(401, { 'Content-Type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify({ ok: false, error: 'unauthorized' }))
      return
    }
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => {
      const body = Buffer.concat(chunks)
      const upstream = http.request(
        {
          host: '127.0.0.1',
          port: target.port,
          path: target.path,
          method: 'POST',
          headers: {
            'Content-Type': req.headers['content-type'] || 'application/json; charset=utf-8',
            'Content-Length': body.length,
            Authorization: `Bearer ${target.token}`,
          },
        },
        (upstreamRes) => {
          res.writeHead(upstreamRes.statusCode || 500, {
            'Content-Type': 'application/json; charset=utf-8',
          })
          upstreamRes.pipe(res)
        },
      )
      upstream.on('error', (error) => {
        res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
        res.end(JSON.stringify({ ok: false, error: `本地 worker 不可用: ${error.message}` }))
      })
      upstream.end(body)
    })
  })
}

function startBridge(options = {}) {
  const server = createBridge(options)
  const port = Number(options.port || process.env.DESKTOP_BRIDGE_PORT || 9876)
  const host = options.host || process.env.DESKTOP_BRIDGE_HOST || '127.0.0.1'
  server.listen(port, host, () => {
    console.log(`[bridge] local capability bridge listening on ${host}:${port}`)
  })
  return server
}

module.exports = { createBridge, startBridge }

if (require.main === module) {
  startBridge()
}
