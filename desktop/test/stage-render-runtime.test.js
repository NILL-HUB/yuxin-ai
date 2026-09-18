const { test } = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { execFileSync, spawnSync } = require('node:child_process')

const SCRIPT = path.join(__dirname, '..', 'scripts', 'stage-render-runtime.js')
const {
  checkFfmpegCapabilities,
  _isForeignPlatformDir,
  _resolveBrowserDir,
} = require(SCRIPT)

function mkTmp(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix))
}

// 造一个「源目录」：node_modules + Chromium 整目录 + ffmpeg/ffprobe
function makeSource({ withBrowser = true, withFfmpeg = true } = {}) {
  const src = mkTmp('stage-src-')
  const nm = path.join(src, 'node_modules')
  fs.mkdirSync(nm, { recursive: true })

  // 容器来源的 linux 原生包（应被裁掉）
  fs.mkdirSync(path.join(nm, '@esbuild', 'linux-x64'), { recursive: true })
  fs.mkdirSync(path.join(nm, '@img', 'sharp-linux-x64'), { recursive: true })
  fs.mkdirSync(path.join(nm, '@img', 'sharp-libvips-linux-x64'), { recursive: true })
  // 跨平台包（无平台分段）不该被误删
  fs.mkdirSync(path.join(nm, '@img', 'colour'), { recursive: true })
  fs.writeFileSync(path.join(nm, '@img', 'colour', 'index.js'), 'c')

  const browser = path.join(src, 'browser')
  if (withBrowser) {
    fs.mkdirSync(path.join(browser, 'locales'), { recursive: true })
    fs.writeFileSync(path.join(browser, 'chrome-headless-shell.exe'), 'exe')
    fs.writeFileSync(path.join(browser, 'icudtl.dat'), 'icu')
    fs.writeFileSync(path.join(browser, 'libEGL.dll'), 'dll')
    fs.writeFileSync(path.join(browser, 'headless_lib_data.pak'), 'pak')
  }

  if (withFfmpeg) {
    fs.writeFileSync(path.join(src, 'ffmpeg.exe'), 'ff')
    fs.writeFileSync(path.join(src, 'ffprobe.exe'), 'fp')
  }
  return { src, browser }
}

function makeWin32Modules() {
  const w = mkTmp('stage-w32-')
  fs.mkdirSync(path.join(w, '@esbuild', 'win32-x64'), { recursive: true })
  fs.writeFileSync(path.join(w, '@esbuild', 'win32-x64', 'esbuild.exe'), 'e')
  fs.mkdirSync(path.join(w, '@img', 'sharp-win32-x64'), { recursive: true })
  fs.writeFileSync(path.join(w, '@img', 'sharp-win32-x64', 'sharp.node'), 's')
  return w
}

function runScript(env) {
  return execFileSync(process.execPath, [SCRIPT], {
    env: {
      ...process.env,
      // 假 exe 无法真正探测能力，测试中跳过（能力探测由单测覆盖）
      RENDER_RUNTIME_SKIP_BINARY_PROBE: '1',
      ...env,
    },
    encoding: 'utf-8',
  })
}

test('stage script exists and is runnable', () => {
  assert.ok(fs.existsSync(SCRIPT), 'stage-render-runtime.js 不存在')
})

test('stage script skips gracefully when source is absent', () => {
  // 源缺失时应打印提示并以 0 退出（不阻断打包），与 stage-cua-driver.js 一致
  const dir = mkTmp('stage-rr-')
  try {
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
  // 断言：onnxruntime 仅保留 win32；linux 原生包被裁；win32 原生包被 overlay
  const { src, browser } = makeSource()
  const dst = mkTmp('stage-dst-')
  const win32 = makeWin32Modules()
  try {
    const napi = path.join(src, 'node_modules', 'onnxruntime-node', 'bin', 'napi-v3')
    for (const p of ['win32', 'linux', 'darwin']) {
      fs.mkdirSync(path.join(napi, p, 'x64'), { recursive: true })
      fs.writeFileSync(path.join(napi, p, 'x64', 'onnxruntime_binding.node'), 'x')
    }

    runScript({
      RENDER_RUNTIME_SOURCE_DIR: src,
      STAGE_TARGET_DIR: dst,
      RENDER_RUNTIME_WIN32_MODULES_DIR: win32,
      RENDER_RUNTIME_BROWSER_DIR: browser,
      RENDER_RUNTIME_FFMPEG_PATH: path.join(src, 'ffmpeg.exe'),
      RENDER_RUNTIME_FFPROBE_PATH: path.join(src, 'ffprobe.exe'),
      ORT_PLATFORMS: 'win32',
    })

    const outNapi = path.join(dst, 'node_modules', 'onnxruntime-node', 'bin', 'napi-v3')
    assert.ok(fs.existsSync(path.join(outNapi, 'win32')), 'win32 应保留')
    assert.ok(!fs.existsSync(path.join(outNapi, 'linux')), 'linux 应被裁剪')
    assert.ok(!fs.existsSync(path.join(outNapi, 'darwin')), 'darwin 应被裁剪')

    const outNm = path.join(dst, 'node_modules')
    assert.ok(!fs.existsSync(path.join(outNm, '@esbuild', 'linux-x64')), 'linux esbuild 应被裁掉')
    assert.ok(
      fs.existsSync(path.join(outNm, '@img', 'colour', 'index.js')),
      '无平台分段的跨平台包不应被误删',
    )
    assert.ok(
      fs.existsSync(path.join(outNm, '@esbuild', 'win32-x64', 'esbuild.exe')),
      'win32 esbuild 必须存在',
    )
  } finally {
    for (const d of [src, dst, win32]) fs.rmSync(d, { recursive: true, force: true })
  }
})

test('stage script copies Chromium as a whole directory (not just the exe)', () => {
  // 回归实测崩溃：只拷 chrome-headless-shell.exe 会因缺 icudtl.dat/*.dll/*.pak
  // 在启动时直接崩（退出码 0x80000003），故必须整目录复制
  const { src, browser } = makeSource()
  const dst = mkTmp('stage-dst-')
  const win32 = makeWin32Modules()
  try {
    runScript({
      RENDER_RUNTIME_SOURCE_DIR: src,
      STAGE_TARGET_DIR: dst,
      RENDER_RUNTIME_WIN32_MODULES_DIR: win32,
      RENDER_RUNTIME_BROWSER_DIR: browser,
      RENDER_RUNTIME_FFMPEG_PATH: path.join(src, 'ffmpeg.exe'),
      RENDER_RUNTIME_FFPROBE_PATH: path.join(src, 'ffprobe.exe'),
    })

    for (const name of [
      'chrome-headless-shell.exe',
      'icudtl.dat',
      'libEGL.dll',
      'headless_lib_data.pak',
    ]) {
      assert.ok(fs.existsSync(path.join(dst, name)), `Chromium 旁挂文件必须一并暂存：${name}`)
    }
  } finally {
    for (const d of [src, dst, win32]) fs.rmSync(d, { recursive: true, force: true })
  }
})

test('stage script accepts the browser exe path and uses its directory', () => {
  assert.equal(_resolveBrowserDir('/a/b/chrome-headless-shell.exe'), '/a/b')
  assert.equal(_resolveBrowserDir('C:\\x\\y\\chrome-headless-shell.exe'), 'C:\\x\\y')
  assert.equal(_resolveBrowserDir('/a/b'), '/a/b')
})

test('stage script stages ffmpeg/ffprobe under fixed names', () => {
  const { src, browser } = makeSource()
  const dst = mkTmp('stage-dst-')
  const win32 = makeWin32Modules()
  try {
    runScript({
      RENDER_RUNTIME_SOURCE_DIR: src,
      STAGE_TARGET_DIR: dst,
      RENDER_RUNTIME_WIN32_MODULES_DIR: win32,
      RENDER_RUNTIME_BROWSER_DIR: browser,
      RENDER_RUNTIME_FFMPEG_PATH: path.join(src, 'ffmpeg.exe'),
      RENDER_RUNTIME_FFPROBE_PATH: path.join(src, 'ffprobe.exe'),
    })
    // render-runtime.js 按固定名解析，故目标名必须是 ffmpeg.exe / ffprobe.exe
    assert.ok(fs.existsSync(path.join(dst, 'ffmpeg.exe')), 'ffmpeg.exe 必须存在')
    assert.ok(fs.existsSync(path.join(dst, 'ffprobe.exe')), 'ffprobe.exe 必须存在')
    assert.ok(fs.existsSync(path.join(dst, 'MANIFEST.json')), '应写入 MANIFEST.json')
  } finally {
    for (const d of [src, dst, win32]) fs.rmSync(d, { recursive: true, force: true })
  }
})

test('stage script fails loudly when win32 native packages are missing', () => {
  // 只有 linux 原生包时必须报错退出，而不是静默产出一个渲染必崩的安装包
  const { src, browser } = makeSource()
  const dst = mkTmp('stage-dst-')
  try {
    const res = spawnSync(process.execPath, [SCRIPT], {
      env: {
        ...process.env,
        RENDER_RUNTIME_SOURCE_DIR: src,
        STAGE_TARGET_DIR: dst,
        RENDER_RUNTIME_BROWSER_DIR: browser,
        RENDER_RUNTIME_FFMPEG_PATH: path.join(src, 'ffmpeg.exe'),
        RENDER_RUNTIME_FFPROBE_PATH: path.join(src, 'ffprobe.exe'),
        RENDER_RUNTIME_SKIP_BINARY_PROBE: '1',
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

test('stage script fails loudly when Chromium directory is missing', () => {
  const { src } = makeSource({ withBrowser: false })
  const dst = mkTmp('stage-dst-')
  const win32 = makeWin32Modules()
  try {
    const res = spawnSync(process.execPath, [SCRIPT], {
      env: {
        ...process.env,
        RENDER_RUNTIME_SOURCE_DIR: src,
        STAGE_TARGET_DIR: dst,
        RENDER_RUNTIME_WIN32_MODULES_DIR: win32,
        RENDER_RUNTIME_FFMPEG_PATH: path.join(src, 'ffmpeg.exe'),
        RENDER_RUNTIME_FFPROBE_PATH: path.join(src, 'ffprobe.exe'),
        RENDER_RUNTIME_SKIP_BINARY_PROBE: '1',
      },
      encoding: 'utf-8',
    })
    assert.notStrictEqual(res.status, 0, '缺少 Chromium 目录时必须失败')
    assert.match(res.stderr + res.stdout, /浏览器|Chromium|browser/i)
  } finally {
    fs.rmSync(src, { recursive: true, force: true })
    fs.rmSync(dst, { recursive: true, force: true })
    fs.rmSync(win32, { recursive: true, force: true })
  }
})

test('checkFfmpegCapabilities reports missing image2pipe / libx264', () => {
  // 实测根因：Trae 构建缺 image2pipe → `Unknown input format: 'image2pipe'`；
  // playwright 构建缺 libx264 无法编码。二者都必须被拦下。
  const noImage2pipe = (args) => {
    const key = args[args.length - 1]
    if (key === '-demuxers') return ' D  image2  image2 sequence'
    if (key === '-decoders') return ' V..... mjpeg'
    if (key === '-encoders') return ' V....D libx264264'
    return ''
  }
  const missing = checkFfmpegCapabilities('/fake/ffmpeg', { run: noImage2pipe })
  assert.strictEqual(missing.length, 1)
  assert.match(missing[0], /image2pipe/)

  const noLibx264 = (args) => {
    const key = args[args.length - 1]
    if (key === '-demuxers') return ' D  image2pipe'
    if (key === '-decoders') return ' V..... mjpeg'
    if (key === '-encoders') return ' V....D h264'
    return ''
  }
  const m2 = checkFfmpegCapabilities('/fake/ffmpeg', { run: noLibx264 })
  assert.strictEqual(m2.length, 1)
  assert.match(m2[0], /libx264/)
})

test('checkFfmpegCapabilities passes for a full build', () => {
  const full = (args) => {
    const key = args[args.length - 1]
    if (key === '-demuxers') return ' D  image2pipe'
    if (key === '-decoders') return ' V..... mjpeg'
    if (key === '-encoders') return ' V....D libx264'
    return ''
  }
  assert.deepStrictEqual(checkFfmpegCapabilities('/fake/ffmpeg', { run: full }), [])
})

test('_isForeignPlatformDir keeps target platform and platform-free packages', () => {
  assert.equal(_isForeignPlatformDir('linux-x64'), true)
  assert.equal(_isForeignPlatformDir('sharp-linux-x64'), true)
  assert.equal(_isForeignPlatformDir('sharp-libvips-linux-x64'), true)
  assert.equal(_isForeignPlatformDir('sharp-win32-x64'), false)
  assert.equal(_isForeignPlatformDir('colour'), false)
})
