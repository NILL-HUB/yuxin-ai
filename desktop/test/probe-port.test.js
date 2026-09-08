const { test } = require('node:test')
const assert = require('node:assert')
const net = require('node:net')

// probePort 从 main.js 提取逻辑的独立测试：优先 preferred，被占用则顺延。
// main.js 直接 require 会触发 electron，这里用一个最小实现验证算法本身，
// 并在集成层（冒烟）验证 main.js 行为。

function probePort(preferred, maxAttempts = 50, exclude = new Set()) {
  return new Promise((resolve) => {
    const tryPort = (offset) => {
      if (offset >= maxAttempts) return resolve(preferred)
      const candidate = preferred + offset
      if (exclude.has(candidate)) return tryPort(offset + 1)
      const server = net.createServer()
      server.once('error', () => {
        server.close()
        tryPort(offset + 1)
      })
      server.listen(candidate, '127.0.0.1', () => {
        server.close(() => resolve(candidate))
      })
    }
    tryPort(0)
  })
}

const occupyPort = (port) =>
  new Promise((resolve) => {
    const server = net.createServer()
    server.listen(port, '127.0.0.1', () => resolve(server))
  })

test('probePort returns preferred port when free', async () => {
  const free = 19001
  const result = await probePort(free)
  assert.equal(result, free)
})

test('probePort bumps to next free port when preferred is occupied', async () => {
  const occupied = 19010
  const blocker = await occupyPort(occupied)
  try {
    const result = await probePort(occupied)
    assert.notEqual(result, occupied)
    assert.ok(result > occupied)
  } finally {
    blocker.close()
  }
})

test('probePort skips excluded ports and finds a distinct free one', async () => {
  const base = 19020
  const blockerA = await occupyPort(base)
  const blockerB = await occupyPort(base + 1)
  try {
    // 串行分配：A 拿到 base+2，B 必须排除 base+2 且绕过 base/base+1 占用
    const first = await probePort(base) // 占用 base/base+1 → 顺延到 base+2
    const second = await probePort(base, 50, new Set([first]))
    assert.notEqual(second, first)
    assert.notEqual(second, base)
    assert.notEqual(second, base + 1)
  } finally {
    blockerA.close()
    blockerB.close()
  }
})
