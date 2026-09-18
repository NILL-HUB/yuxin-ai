const { test } = require('node:test')
const assert = require('node:assert')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
  resolveRuntimePaths,
  ensureCliShim,
  _shimFileName,
} = require('../render-runtime')

test('shim file name is platform specific', () => {
  const name = _shimFileName()
  if (process.platform === 'win32') {
    assert.match(name, /\.cmd$/)
  } else {
    assert.match(name, /hyperframes$/)
  }
})

test('ensureCliShim writes a shim that runs electron as node', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shim-test-'))
  try {
    const shimPath = ensureCliShim({
      electronPath: 'C:/app/electron.exe',
      cliJsPath: 'C:/app/resources/render-runtime/cli.js',
      targetDir: dir,
    })
    assert.ok(fs.existsSync(shimPath), 'shim 未生成')
    const content = fs.readFileSync(shimPath, 'utf-8')
    assert.match(content, /ELECTRON_RUN_AS_NODE/)
    assert.match(content, /render-runtime/)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('resolveRuntimePaths points at bundled runtime dir', () => {
  const paths = resolveRuntimePaths({
    env: {},
    resourcesDir: '/res',
  })
  assert.equal(paths.runtimeDir, path.join('/res', 'render-runtime'))
  assert.match(paths.cliJsPath, /render-runtime.*hyperframes.*cli\.js$/)
  assert.match(paths.browserPath, /render-runtime/)
  assert.match(paths.ffmpegPath, /render-runtime/)
  assert.match(paths.ffprobePath, /render-runtime/)
})

test('resolveRuntimePaths lets explicit env override bundled defaults', () => {
  const paths = resolveRuntimePaths({
    env: {
      HYPERFRAMES_BROWSER_PATH: '/custom/chrome',
      HYPERFRAMES_FFMPEG_PATH: '/custom/ffmpeg',
      HYPERFRAMES_FFPROBE_PATH: '/custom/ffprobe',
    },
    resourcesDir: '/res',
  })
  assert.equal(paths.browserPath, '/custom/chrome')
  assert.equal(paths.ffmpegPath, '/custom/ffmpeg')
  assert.equal(paths.ffprobePath, '/custom/ffprobe')
})
