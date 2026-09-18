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
  const win32 = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-w32-'))
  try {
    const napi = path.join(src, 'node_modules', 'onnxruntime-node', 'bin', 'napi-v3')
    for (const p of ['win32', 'linux', 'darwin']) {
      fs.mkdirSync(path.join(napi, p, 'x64'), { recursive: true })
      fs.writeFileSync(path.join(napi, p, 'x64', 'onnxruntime_binding.node'), 'x')
    }
    // 加一个必须被保留的普通包，验证没有误删
    fs.mkdirSync(path.join(src, 'node_modules', 'hyperframes'), { recursive: true })
    fs.writeFileSync(path.join(src, 'node_modules', 'hyperframes', 'keep.txt'), 'k')
    // 容器来源的 linux 原生包（应被裁掉）
    fs.mkdirSync(path.join(src, 'node_modules', '@esbuild', 'linux-x64'), { recursive: true })
    // Windows 侧原生包（overlay 源）
    fs.mkdirSync(path.join(win32, '@esbuild', 'win32-x64'), { recursive: true })
    fs.writeFileSync(path.join(win32, '@esbuild', 'win32-x64', 'esbuild.exe'), 'e')
    fs.mkdirSync(path.join(win32, '@img', 'sharp-win32-x64'), { recursive: true })
    fs.writeFileSync(path.join(win32, '@img', 'sharp-win32-x64', 'sharp.node'), 's')

    execFileSync(process.execPath, [SCRIPT], {
      env: {
        ...process.env,
        RENDER_RUNTIME_SOURCE_DIR: src,
        STAGE_TARGET_DIR: dst,
        RENDER_RUNTIME_WIN32_MODULES_DIR: win32,
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
    // 容器来源的 linux 原生包必须被裁掉，win32 必须存在
    assert.ok(
      !fs.existsSync(path.join(dst, 'node_modules', '@esbuild', 'linux-x64')),
      'linux 原生包应被裁掉',
    )
    assert.ok(
      fs.existsSync(path.join(dst, 'node_modules', '@esbuild', 'win32-x64', 'esbuild.exe')),
      'win32 esbuild 必须存在，否则 Windows 上 esbuild 不可用',
    )
  } finally {
    fs.rmSync(src, { recursive: true, force: true })
    fs.rmSync(dst, { recursive: true, force: true })
    fs.rmSync(win32, { recursive: true, force: true })
  }
})

test('stage script overlays win32 sharp so the CLI can start', () => {
  // 回归本方案实测到的硬崩：容器只有 @img/sharp-linux-x64，
  // 而 hyperframes 启动阶段即 import sharp，缺 win32 构建时连 --version 都崩。
  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-src-'))
  const dst = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-dst-'))
  const win32 = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-w32-'))
  try {
    const nm = path.join(src, 'node_modules')
    fs.mkdirSync(path.join(nm, 'hyperframes'), { recursive: true })
    for (const p of ['linux-x64']) {
      fs.mkdirSync(path.join(nm, '@img', `sharp-${p}`), { recursive: true })
      fs.writeFileSync(path.join(nm, '@img', `sharp-${p}`, 'x.node'), 'x')
    }
    // 跨平台包（无平台分段）不能被误删
    fs.mkdirSync(path.join(nm, '@img', 'colour'), { recursive: true })
    fs.writeFileSync(path.join(nm, '@img', 'colour', 'index.js'), 'c')
    // 中间带平台分段的包也必须被裁掉（曾漏判）
    fs.mkdirSync(path.join(nm, '@img', 'sharp-libvips-linux-x64'), { recursive: true })
    fs.mkdirSync(path.join(nm, '@esbuild', 'linux-x64'), { recursive: true })

    fs.mkdirSync(path.join(win32, '@esbuild', 'win32-x64'), { recursive: true })
    fs.writeFileSync(path.join(win32, '@esbuild', 'win32-x64', 'esbuild.exe'), 'e')
    fs.mkdirSync(path.join(win32, '@img', 'sharp-win32-x64'), { recursive: true })
    fs.writeFileSync(
      path.join(win32, '@img', 'sharp-win32-x64', 'sharp-win32-x64-0.35.4.node'),
      's',
    )

    execFileSync(process.execPath, [SCRIPT], {
      env: {
        ...process.env,
        RENDER_RUNTIME_SOURCE_DIR: src,
        STAGE_TARGET_DIR: dst,
        RENDER_RUNTIME_WIN32_MODULES_DIR: win32,
      },
      encoding: 'utf-8',
    })

    const out = path.join(dst, 'node_modules')
    assert.ok(
      fs.existsSync(path.join(out, '@img', 'sharp-win32-x64', 'sharp-win32-x64-0.35.4.node')),
      'win32 sharp 必须被 overlay 进来，否则 CLI 启动即崩',
    )
    assert.ok(
      !fs.existsSync(path.join(out, '@img', 'sharp-linux-x64')),
      'linux sharp 应被裁掉',
    )
    assert.ok(
      !fs.existsSync(path.join(out, '@img', 'sharp-libvips-linux-x64')),
      '中间带平台分段的包也应被裁掉',
    )
    assert.ok(
      fs.existsSync(path.join(out, '@img', 'colour', 'index.js')),
      '无平台分段的跨平台包不应被误删',
    )
  } finally {
    fs.rmSync(src, { recursive: true, force: true })
    fs.rmSync(dst, { recursive: true, force: true })
    fs.rmSync(win32, { recursive: true, force: true })
  }
})

test('stage script fails loudly when win32 native packages are missing', () => {
  // 只有 linux 原生包时必须报错退出，而不是静默产出一个渲染必崩的安装包
  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-src-'))
  const dst = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-dst-'))
  try {
    const nm = path.join(src, 'node_modules')
    fs.mkdirSync(path.join(nm, 'hyperframes'), { recursive: true })
    fs.mkdirSync(path.join(nm, '@img', 'sharp-linux-x64'), { recursive: true })

    const res = spawnSync(process.execPath, [SCRIPT], {
      env: {
        ...process.env,
        RENDER_RUNTIME_SOURCE_DIR: src,
        STAGE_TARGET_DIR: dst,
      },
      encoding: 'utf-8',
    })
    assert.notStrictEqual(res.status, 0, '缺少 win32 原生包时必须失败')
    assert.match(res.stderr + res.stdout, /win32|Windows|sharp/i)
  } finally {
    fs.rmSync(src, { recursive: true, force: true })
    fs.rmSync(dst, { recursive: true, force: true })
  }
})
