const { test } = require('node:test')
const assert = require('node:assert')
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
