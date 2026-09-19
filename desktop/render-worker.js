'use strict'

const path = require('node:path')

const { resolveRuntimePaths, ensureCliShim } = require('./render-runtime')

// 本机 render worker 的启动配置组装。
//
// 为什么要独立成模块：main.js 顶层 `require('electron')` 会拉起 Electron，
// 无法在 `node --test` 中直接加载，导致「worker 托管」这段接线长期无自动化测试
// （而它恰恰是「装了包却跑不起来」的高发断链点）。故把不依赖 Electron 的
// 纯组装逻辑抽到这里，main.js 只负责把 app/process 上的运行时值传进来。
//
// 消费方契约（与 api/scripts/render_worker.py 的 _load_settings / main 对齐）：
//   RENDER_WORKER_TOKEN      必填，缺失则 worker 拒绝启动（SystemExit 1）
//   RENDER_WORKER_PORT       HTTP 监听端口（默认 8768）
//   HYPERFRAMES_CLI_BIN      CLI 可执行入口（**必须是 shim 路径**，不是 cli.js）
//   HYPERFRAMES_BROWSER_PATH 浏览器可执行文件
//   HYPERFRAMES_FFMPEG_PATH  ffmpeg
//   HYPERFRAMES_FFPROBE_PATH ffprobe
const RENDER_WORKER_ENV_KEYS = [
  'RENDER_WORKER_TOKEN',
  'RENDER_WORKER_PORT',
  'HYPERFRAMES_CLI_BIN',
  'HYPERFRAMES_BROWSER_PATH',
  'HYPERFRAMES_FFMPEG_PATH',
  'HYPERFRAMES_FFPROBE_PATH',
]

const DEFAULT_RENDER_WORKER_PORT = 8768

// shim 目录名（位于 Electron userData 下，随 app.getPath('userData') 解析）
const SHIM_DIR_NAME = 'render-runtime-bin'

/**
 * 解析 render worker 的偏好端口（环境变量优先，其次默认 8768）。
 *
 * 与 os/browser/computer 三个 worker 同口径：这里只给「偏好值」，
 * 实际可用端口由 main.js 的 probePort 串行顺延确定（互相排除已分配端口）。
 */
function resolveRenderWorkerPort(env = process.env) {
  const raw = Number((env && env.RENDER_WORKER_PORT) || DEFAULT_RENDER_WORKER_PORT)
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_RENDER_WORKER_PORT
}

/**
 * 组装 render worker 的启动环境变量。
 *
 * @param {object} args
 * @param {string} args.renderToken  本进程随机生成的 worker token
 * @param {number} args.renderPort   实际可用端口（由 probePort 决定）
 * @param {object} args.runtime      resolveRuntimePaths 的返回值
 * @param {string} args.cliShim      ensureCliShim 生成的 shim 路径
 * @returns {Record<string,string>}
 */
function buildRenderWorkerEnv({ renderToken, renderPort, runtime, cliShim }) {
  if (!renderToken) {
    throw new Error('render worker 缺少 token：RENDER_WORKER_TOKEN 缺失会让 worker 拒绝启动')
  }
  if (!cliShim) {
    throw new Error('render worker 缺少 CLI shim（HYPERFRAMES_CLI_BIN 必须是 shim 路径）')
  }
  return {
    RENDER_WORKER_TOKEN: String(renderToken),
    RENDER_WORKER_PORT: String(renderPort),
    HYPERFRAMES_CLI_BIN: String(cliShim),
    HYPERFRAMES_BROWSER_PATH: String(runtime.browserPath || ''),
    HYPERFRAMES_FFMPEG_PATH: String(runtime.ffmpegPath || ''),
    HYPERFRAMES_FFPROBE_PATH: String(runtime.ffprobePath || ''),
  }
}

/**
 * 准备渲染运行时：解析随包分发的路径 + 生成 CLI shim。
 *
 * @param {object} args
 * @param {string} args.resourcesDir  process.resourcesPath（打包后为 .../resources）
 * @param {object} args.env           进程环境（用于 HYPERFRAMES_* 显式覆盖）
 * @param {string} args.execPath      process.execPath（Electron 可执行文件，**必须原地引用**）
 * @param {string} args.userDataDir   app.getPath('userData')
 * @returns {{ runtime: object, cliShim: string, shimDir: string }}
 */
function prepareRenderWorker({ resourcesDir, env, execPath, userDataDir }) {
  const runtime = resolveRuntimePaths({ env, resourcesDir })
  const shimDir = path.join(userDataDir, SHIM_DIR_NAME)
  // electronPath 必须原地引用：把 electron.exe 拷成单文件会缺 DLL（0xC0000135）
  const cliShim = ensureCliShim({
    electronPath: execPath,
    cliJsPath: runtime.cliJsPath,
    targetDir: shimDir,
  })
  return { runtime, cliShim, shimDir }
}

module.exports = {
  buildRenderWorkerEnv,
  prepareRenderWorker,
  resolveRenderWorkerPort,
  RENDER_WORKER_ENV_KEYS,
  DEFAULT_RENDER_WORKER_PORT,
  SHIM_DIR_NAME,
}
