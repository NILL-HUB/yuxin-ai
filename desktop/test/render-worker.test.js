const { test } = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
  buildRenderWorkerEnv,
  prepareRenderWorker,
  resolveRenderWorkerPort,
  RENDER_WORKER_ENV_KEYS,
  DEFAULT_RENDER_WORKER_PORT,
} = require('../render-worker')

// 这段接线此前长期无自动化测试（main.js 顶层 require('electron') 无法在
// node --test 中加载），而它恰是「装了包却跑不起来」的高发断链点。
// 故逻辑抽到 render-worker.js，这里直接覆盖生产代码。

function mkTmp(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix))
}

test('resolveRenderWorkerPort defaults to 8768 (matches render_worker.py)', () => {
  assert.equal(resolveRenderWorkerPort({}), DEFAULT_RENDER_WORKER_PORT)
  assert.equal(DEFAULT_RENDER_WORKER_PORT, 8768)
})

test('resolveRenderWorkerPort honors env override', () => {
  assert.equal(resolveRenderWorkerPort({ RENDER_WORKER_PORT: '9100' }), 9100)
})

test('resolveRenderWorkerPort ignores invalid/absent env', () => {
  // 非法值必须回落到默认端口，而不是让 worker 绑到 NaN 端口
  assert.equal(resolveRenderWorkerPort({ RENDER_WORKER_PORT: 'abc' }), DEFAULT_RENDER_WORKER_PORT)
  assert.equal(resolveRenderWorkerPort({ RENDER_WORKER_PORT: '0' }), DEFAULT_RENDER_WORKER_PORT)
  assert.equal(resolveRenderWorkerPort({ RENDER_WORKER_PORT: '-1' }), DEFAULT_RENDER_WORKER_PORT)
})

test('buildRenderWorkerEnv emits every env key the worker requires', () => {
  // 契约来源：api/scripts/render_worker.py 的 _load_settings / _REQUIRED_ENV_KEYS。
  // 少传任一个 → worker 端渲染在启动阶段失败（缺 HYPERFRAMES_* 直接报环境错误）。
  const env = buildRenderWorkerEnv({
    renderToken: 'tok',
    renderPort: 8768,
    runtime: {
      browserPath: '/r/chrome-headless-shell.exe',
      ffmpegPath: '/r/ffmpeg.exe',
      ffprobePath: '/r/ffprobe.exe',
    },
    cliShim: '/shim/hyperframes.cmd',
  })

  for (const key of RENDER_WORKER_ENV_KEYS) {
    assert.ok(key in env, `缺少必需环境变量：${key}`)
    assert.notStrictEqual(env[key], '', `${key} 不应为空`)
  }
  assert.equal(env.RENDER_WORKER_TOKEN, 'tok')
  assert.equal(env.RENDER_WORKER_PORT, '8768')
  // HYPERFRAMES_CLI_BIN 必须是 shim（而非 cli.js）——CLI 需两段式调用
  assert.equal(env.HYPERFRAMES_CLI_BIN, '/shim/hyperframes.cmd')
  assert.equal(env.HYPERFRAMES_BROWSER_PATH, '/r/chrome-headless-shell.exe')
  assert.equal(env.HYPERFRAMES_FFMPEG_PATH, '/r/ffmpeg.exe')
  assert.equal(env.HYPERFRAMES_FFPROBE_PATH, '/r/ffprobe.exe')
})

test('buildRenderWorkerEnv stringifies the port (spawn env must be strings)', () => {
  const env = buildRenderWorkerEnv({
    renderToken: 't',
    renderPort: 9123,
    runtime: { browserPath: 'b', ffmpegPath: 'f', ffprobePath: 'p' },
    cliShim: 's',
  })
  // Node 的 spawn env 只接受字符串，数字会被丢弃/报错
  assert.strictEqual(typeof env.RENDER_WORKER_PORT, 'string')
  assert.equal(env.RENDER_WORKER_PORT, '9123')
})

test('buildRenderWorkerEnv refuses to start without a token', () => {
  // RENDER_WORKER_TOKEN 缺失时 api/scripts/render_worker.py 会 SystemExit(1)，
  // 这里提前拦下并给出可读错误，而不是拉起一个必然自杀的进程。
  assert.throws(
    () =>
      buildRenderWorkerEnv({
        renderToken: '',
        renderPort: 8768,
        runtime: { browserPath: 'b', ffmpegPath: 'f', ffprobePath: 'p' },
        cliShim: 's',
      }),
    /token/i,
  )
})

test('buildRenderWorkerEnv refuses to start without a CLI shim', () => {
  assert.throws(
    () =>
      buildRenderWorkerEnv({
        renderToken: 't',
        renderPort: 8768,
        runtime: { browserPath: 'b', ffmpegPath: 'f', ffprobePath: 'p' },
        cliShim: '',
      }),
    /shim/i,
  )
})

test('prepareRenderWorker generates a shim under userData and points at bundled runtime', () => {
  const resourcesDir = mkTmp('rw-res')
  const userDataDir = mkTmp('rw-ud')
  try {
    const { runtime, cliShim, shimDir } = prepareRenderWorker({
      resourcesDir,
      env: {},
      execPath: 'C:/app/electron.exe',
      userDataDir,
    })

    // 运行时目录固定为 resources/render-runtime
    assert.equal(runtime.runtimeDir, path.join(resourcesDir, 'render-runtime'))
    assert.match(runtime.cliJsPath, /render-runtime.*hyperframes.*cli\.js$/)

    // shim 落在 userData 下，且内容为「electron 当 node 用」
    assert.equal(shimDir, path.join(userDataDir, 'render-runtime-bin'))
    assert.ok(fs.existsSync(cliShim), 'shim 未生成')
    const content = fs.readFileSync(cliShim, 'utf-8')
    assert.match(content, /ELECTRON_RUN_AS_NODE/)
    assert.match(content, /C:\/app\/electron\.exe|C:\\\\app\\\\electron\.exe/)
  } finally {
    fs.rmSync(resourcesDir, { recursive: true, force: true })
    fs.rmSync(userDataDir, { recursive: true, force: true })
  }
})

test('prepareRenderWorker lets explicit HYPERFRAMES_* env override bundled paths', () => {
  const resourcesDir = mkTmp('rw-res2')
  const userDataDir = mkTmp('rw-ud2')
  try {
    const { runtime } = prepareRenderWorker({
      resourcesDir,
      env: {
        HYPERFRAMES_BROWSER_PATH: '/custom/chrome',
        HYPERFRAMES_FFMPEG_PATH: '/custom/ffmpeg',
        HYPERFRAMES_FFPROBE_PATH: '/custom/ffprobe',
      },
      execPath: 'C:/app/electron.exe',
      userDataDir,
    })
    assert.equal(runtime.browserPath, '/custom/chrome')
    assert.equal(runtime.ffmpegPath, '/custom/ffmpeg')
    assert.equal(runtime.ffprobePath, '/custom/ffprobe')
  } finally {
    fs.rmSync(resourcesDir, { recursive: true, force: true })
    fs.rmSync(userDataDir, { recursive: true, force: true })
  }
})

test('main.js wires the render worker through render-worker.js', () => {
  // 回归「接线被绕过」：main.js 必须真的调用本模块，否则抽出来的逻辑等于没接。
  const mainSrc = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf-8')
  assert.match(mainSrc, /require\('\.\/render-worker'\)/, 'main.js 未引入 render-worker')
  assert.match(mainSrc, /prepareRenderWorker\(\{/, 'main.js 未调用 prepareRenderWorker')
  assert.match(mainSrc, /buildRenderWorkerEnv\(\{/, 'main.js 未调用 buildRenderWorkerEnv')
  assert.match(mainSrc, /startWorker\(\s*'render'/, 'main.js 未托管 render worker')
  // 必须原地引用 electron（拷单文件会缺 DLL）
  assert.match(mainSrc, /execPath:\s*process\.execPath/)
})

test('main.js passes renderPort/renderToken to the bridge', () => {
  // 缺这两个参数 → bridge 的 /render 会转发到错误端口或空 token（401）
  const mainSrc = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf-8')
  assert.match(mainSrc, /renderPort,/)
  assert.match(mainSrc, /renderToken:\s*tokens\.render/)
})

test('render-worker.js is registered in package.json build.files', () => {
  // build.files 是显式白名单：漏登记会导致「npm start 正常、安装版 Cannot find module」
  const pkg = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf-8'),
  )
  assert.ok(
    pkg.build.files.includes('render-worker.js'),
    'render-worker.js 未登记进 build.files（安装版会崩）',
  )
  assert.ok(pkg.build.files.includes('render-runtime.js'), 'render-runtime.js 未登记')
})

test('render worker env keys match the python worker contract', () => {
  // 契约对齐：python 侧 _load_settings 读取这些键
  const py = fs.readFileSync(
    path.join(__dirname, '..', '..', 'api', 'scripts', 'render_worker.py'),
    'utf-8',
  )
  for (const key of RENDER_WORKER_ENV_KEYS) {
    assert.ok(py.includes(key), `python render_worker.py 未读取 ${key}（契约漂移）`)
  }
})
