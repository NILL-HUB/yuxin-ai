const { test } = require('node:test')
const assert = require('node:assert')
const http = require('http')
const { createBridge } = require('../bridge')

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve(server.address().port))
  })
}

async function request(port, path, token) {
  const response = await fetch(`http://127.0.0.1:${port}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: '{}',
  })
  return { status: response.status, body: await response.json() }
}

test('bridge rejects unknown path', async () => {
  const server = createBridge({ token: 't' })
  const port = await listen(server)
  try {
    const result = await request(port, '/unknown', 't')
    assert.equal(result.status, 404)
    assert.equal(result.body.error, 'not_found')
  } finally {
    server.close()
  }
})

test('bridge rejects missing or wrong token', async () => {
  const server = createBridge({ token: 'secret' })
  const port = await listen(server)
  try {
    assert.equal((await request(port, '/recycle')).status, 401)
    assert.equal((await request(port, '/recycle', 'bad')).status, 401)
  } finally {
    server.close()
  }
})

test('bridge returns 502 when worker unavailable', async () => {
  const server = createBridge({
    token: 'secret',
    recyclePort: 1,
    recycleToken: 'worker-token',
  })
  const port = await listen(server)
  try {
    const result = await request(port, '/recycle', 'secret')
    assert.equal(result.status, 502)
    assert.match(result.body.error, /不可用/)
  } finally {
    server.close()
  }
})

async function stubWorker(body, handler) {
  const server = http.createServer((req, res) => {
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf-8')
      handler({
        path: req.url,
        authorization: req.headers.authorization || '',
        body: raw ? JSON.parse(raw) : {},
      })
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify({ ok: true, echo: { path: req.url, body: raw } }))
    })
  })
  const port = await listen(server)
  return { server, port }
}

test('bridge forwards /file to os worker /file with worker token', async () => {
  let seen = null
  const { server, port } = await stubWorker('{}', (call) => {
    seen = call
  })
  const bridge = createBridge({
    token: 'secret',
    filePort: port,
    fileToken: 'os-token',
  })
  const bridgePort = await listen(bridge)
  try {
    const result = await request(bridgePort, '/file', 'secret')
    assert.equal(result.status, 200)
    assert.ok(seen, '请求应被转发到 worker')
    assert.equal(seen.path, '/file')
    assert.equal(seen.authorization, 'Bearer os-token')
    assert.deepEqual(seen.body, {})
  } finally {
    bridge.close()
    server.close()
  }
})

test('bridge forwards /snapshot to os worker /snapshot with worker token', async () => {
  let seen = null
  const { server, port } = await stubWorker('{}', (call) => {
    seen = call
  })
  const bridge = createBridge({
    token: 'secret',
    snapshotPort: port,
    snapshotToken: 'os-token',
  })
  const bridgePort = await listen(bridge)
  try {
    const result = await request(bridgePort, '/snapshot', 'secret')
    assert.equal(result.status, 200)
    assert.ok(seen, '请求应被转发到 worker')
    assert.equal(seen.path, '/snapshot')
    assert.equal(seen.authorization, 'Bearer os-token')
    assert.deepEqual(seen.body, {})
  } finally {
    bridge.close()
    server.close()
  }
})

test('bridge forwards /render to render worker with worker token', async () => {
  let seen = null
  const { server, port } = await stubWorker('{}', (call) => {
    seen = call
  })
  const bridge = createBridge({
    token: 'secret',
    renderPort: port,
    renderToken: 'render-token',
  })
  const bridgePort = await listen(bridge)
  try {
    const result = await request(bridgePort, '/render', 'secret')
    assert.equal(result.status, 200)
    assert.ok(seen, '请求应被转发到 render worker')
    assert.equal(seen.path, '/render')
    assert.equal(seen.authorization, 'Bearer render-token')
  } finally {
    bridge.close()
    server.close()
  }
})

test('bridge forwards /artifact to render worker with worker token', async () => {
  let seen = null
  const { server, port } = await stubWorker('{}', (call) => {
    seen = call
  })
  const bridge = createBridge({
    token: 'secret',
    renderPort: port,
    renderToken: 'render-token',
  })
  const bridgePort = await listen(bridge)
  try {
    const result = await request(bridgePort, '/artifact', 'secret')
    assert.equal(result.status, 200)
    assert.ok(seen, '请求应被转发到 render worker')
    assert.equal(seen.path, '/artifact')
    assert.equal(seen.authorization, 'Bearer render-token')
  } finally {
    bridge.close()
    server.close()
  }
})
