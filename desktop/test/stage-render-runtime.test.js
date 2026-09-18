const { test } = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { execFileSync, spawnSync } = require('node:child_process')

const SCRIPT = path.join(__dirname, '..', 'scripts', 'stage-render-runtime.js')

test('stage script exists and is runnable', () => {
  assert.ok(fs.existsSync(SCRIPT), 'stage-render-runtime.js 不存在')
})

test('stage script skips gracefully when source is absent', () => {
  // 源缺失时应打印提示并以 0 退出（不阻断打包），与 stage-cua-driver.js 一致
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-rr-'))
  try {
    // 跳过提示经 console.warn 写入 stderr，故合并两条流后再断言
    const res = spawnSync(process.execPath, [SCRIPT], {
      env: { ...process.env, RENDER_RUNTIME_SOURCE_DIR: dir, STAGE_TARGET_DIR: dir },
      encoding: 'utf-8',
    })
    assert.strictEqual(res.status, 0, '源缺失时不应阻断打包')
    assert.match(res.stdout + res.stderr + '', /skip|跳过|未找到/i)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('stage script prunes non-target onnxruntime platforms', () => {
  // 构造假的 node_modules/onnxruntime-node/bin/napi-v3/{win32,linux,darwin}
  // 断言：暂存后仅保留 win32，其余被删（536MB → 68MB 的核心优化）
  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-src-'))
  const dst = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-dst-'))
  try {
    const napi = path.join(src, 'node_modules', 'onnxruntime-node', 'bin', 'napi-v3')
    for (const p of ['win32', 'linux', 'darwin']) {
      fs.mkdirSync(path.join(napi, p, 'x64'), { recursive: true })
      fs.writeFileSync(path.join(napi, p, 'x64', 'onnxruntime_binding.node'), 'x')
    }
    // 加一个必须被保留的普通包，验证没有误删
    fs.mkdirSync(path.join(src, 'node_modules', 'hyperframes'), { recursive: true })
    fs.writeFileSync(path.join(src, 'node_modules', 'hyperframes', 'keep.txt'), 'k')

    execFileSync(process.execPath, [SCRIPT], {
      env: {
        ...process.env,
        RENDER_RUNTIME_SOURCE_DIR: src,
        STAGE_TARGET_DIR: dst,
        ORT_PLATFORMS: 'win32',
      },
      encoding: 'utf-8',
    })

    const outNapi = path.join(dst, 'node_modules', 'onnxruntime-node', 'bin', 'napi-v3')
    assert.ok(fs.existsSync(path.join(outNapi, 'win32')), 'win32 应保留')
    assert.ok(!fs.existsSync(path.join(outNapi, 'linux')), 'linux 应被裁剪')
    assert.ok(!fs.existsSync(path.join(outNapi, 'darwin')), 'darwin 应被裁剪')
    assert.ok(
      fs.existsSync(path.join(dst, 'node_modules', 'hyperframes', 'keep.txt')),
      '其它包不应被误删',
    )
  } finally {
    fs.rmSync(src, { recursive: true, force: true })
    fs.rmSync(dst, { recursive: true, force: true })
  }
})
