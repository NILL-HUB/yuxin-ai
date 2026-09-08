# 桌面客户端（子项目 A）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 `desktop/` Electron 壳完善为面向普通用户的 Windows 桌面客户端：单一 NSIS 安装包（Electron 主程序 + 单一 worker exe），内嵌完整 Web UI、免装 Python、托盘/通知/自启/自动更新、safeStorage 凭证、服务器地址由后端下发。

**Architecture:** Electron 主进程作为唯一入口，托管一个 PyInstaller 打包的 worker exe（内含 os/browser/computer/wake 四个服务，super 入口按子命令分发）；renderer 加载完整 Web UI（自定义协议 `app://` 服务 dist），API base 由主进程经 preload 注入 `window.__DESKTOP_CONFIG__`（后端 `/api/desktop-config` 下发 + 本机缓存）；凭证经 safeStorage 加密持久化；托盘/通知/开机自启/自动更新在主进程实现。

**Tech Stack:** Electron 33、electron-builder(NSIS)、electron-updater、PyInstaller、Python 3.12（worker）、Vue3/Vite（既有 UI）、Node 内置 test runner

**设计依据：** `docs/superpowers/specs/2026-09-08-desktop-client-a-design.md`

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `api/scripts/worker_super.py`（新建） | 单一 worker exe 入口：argparse 子命令 os/browser/computer/wake → 调用各 worker `main()` |
| `api/scripts/pyinstaller/worker.spec`（新建） | PyInstaller 配置，产出 `yuxin-worker.exe` |
| `api/test/scripts/test_worker_super.py`（新建） | worker_super 子命令分发单测 |
| `api/app/http/apps_routes.py` 或新 `desktop_routes.py` | `GET /desktop-config` 公开接口 |
| `api/test/app/http/test_desktop_config.py`（新建） | desktop-config 接口测试 |
| `ui/src/config/index.ts` | 增加 `window.__DESKTOP_CONFIG__` 运行时覆盖 |
| `desktop/main.js` | 托盘/通知/自启/更新/凭证/worker-host 改造/自定义协议 |
| `desktop/preload.js` | 暴露 `desktopConfig`、新 IPC（worker 状态/设置项） |
| `desktop/server-config.js`（新建） | 内置入口 → desktop-config 拉取 + userData 缓存 |
| `desktop/credential-store.js`（新建） | safeStorage 加解密 access_token |
| `desktop/tray.js`（新建） | 托盘菜单与生命周期 |
| `desktop/updater.js`（新建） | electron-updater 封装 |
| `desktop/package.json` | electron-builder NSIS + extraResources worker exe + publish 占位 |
| `ui/src/router/index.ts` | 桌面环境（检测 `window.__DESKTOP_CONFIG__`）用 hash history |
| `ui/src/components/DesktopDevicePanel.vue` | 扩展：worker 版本/快照入口/设置（自启/更新） |
| `ui/src/views/pages/HomeView.vue` 等 | 原生化自绘标题栏（若采用），暴露窗口控制 IPC 的调用点 |

---

### Task 1: worker_super 统一入口

**Files:**
- Create: `api/scripts/worker_super.py`
- Test: `api/test/scripts/test_worker_super.py`

- [ ] **Step 1: 读现状**

读 `api/scripts/os_automation_worker.py` L1729-1754、`browser_automation_worker.py` L214-231、`computer_control_worker.py` L210-230、`wake_word_worker.py` L121-147，确认各自 `main()` 均为 argparse + `serve_forever`/`_listen` 且 `if __name__ == "__main__": main()`。

- [ ] **Step 2: 写失败测试**

创建 `api/test/scripts/test_worker_super.py`：

```python
"""worker_super：单一 worker exe 的子命令分发测试。"""
from scripts import worker_super


class TestDispatch:
    def test_parse_subcommand(self):
        args = worker_super.parse_args(["os", "--port", "8765"])
        assert args.service == "os"
        assert args.port == 8765

    def test_rejects_unknown_service(self):
        import pytest

        with pytest.raises(SystemExit):
            worker_super.parse_args(["unknown"])

    def test_imports_each_worker_module(self):
        # 各 worker 模块可被 import（PyInstaller 隐藏导入的验证依据）
        import importlib

        for mod in ("os_automation_worker", "browser_automation_worker",
                    "computer_control_worker", "wake_word_worker"):
            importlib.import_module(f"scripts.{mod}")
```

- [ ] **Step 3: 运行确认失败**

Run: `cd d:\DEMO\openagent-main\api && python -m pytest test/scripts/test_worker_super.py -q --no-cov`
Expected: FAIL（ModuleNotFoundError: scripts.worker_super）

- [ ] **Step 4: 实现 worker_super**

创建 `api/scripts/worker_super.py`：

```python
"""YuxinAI 桌面 worker 统一入口（单一 exe）。

PyInstaller 打包为 yuxin-worker.exe 后，Electron 主进程通过子命令启动
对应服务，避免为每个 worker 单独打包：

    yuxin-worker.exe os       --port 8765
    yuxin-worker.exe browser  --port 8766
    yuxin-worker.exe computer --port 8767
    yuxin-worker.exe wake

开发模式（无 exe）下等效于 python scripts/<worker>.py。
"""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="yuxin-worker", description="YuxinAI desktop worker")
    parser.add_argument(
        "service",
        choices=("os", "browser", "computer", "wake"),
        help="要启动的 worker 服务",
    )
    parser.add_argument("--host", default="", help="监听地址（默认取各 worker 环境变量/常量）")
    parser.add_argument("--port", type=int, default=0, help="监听端口（默认取各 worker 环境变量/常量）")
    return parser.parse_args(argv)


def _module_and_entry(service: str) -> tuple[str, str]:
    return {
        "os": ("scripts.os_automation_worker", "main"),
        "browser": ("scripts.browser_automation_worker", "main"),
        "computer": ("scripts.computer_control_worker", "main"),
        "wake": ("scripts.wake_word_worker", "main"),
    }[service]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    module_name, entry_name = _module_and_entry(args.service)
    # 各 worker 的 main() 自行 argparse --host/--port（取各自环境变量默认值）。
    # 这里注入 argv，让 worker 的 argparse 只看到自己的参数。
    module = importlib.import_module(module_name)
    entry = getattr(module, entry_name)

    worker_argv = []
    if args.host:
        worker_argv += ["--host", args.host]
    if args.port:
        worker_argv += ["--port", str(args.port)]
    # 替换 sys.argv 后调用 worker main，使 worker 内 argparse 解析到正确参数
    old_argv = sys.argv
    sys.argv = [sys.argv[0], *worker_argv]
    try:
        result = entry()
        return int(result or 0)
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 运行确认通过**

Run: `cd d:\DEMO\openagent-main\api && python -m pytest test/scripts/test_worker_super.py -q --no-cov`
Expected: PASS（3 passed）

- [ ] **Step 6: 冒烟（os 服务 2 秒后终止）**

Run: `cd d:\DEMO\openagent-main\api && $env:OS_AUTOMATION_TOKEN="t"; python -c "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'scripts/worker_super.py','os','--port','8899'],env={**__import__('os').environ,'OS_AUTOMATION_TOKEN':'t'}); time.sleep(2); p.terminate(); print('exit', p.wait())"`
Expected: 输出 "OS automation worker listening on ...8899" 后 exit 正常

- [ ] **Step 7: Commit**

```bash
git add api/scripts/worker_super.py api/test/scripts/test_worker_super.py
git commit -m "feat(worker): unified worker_super entry for single-exe packaging"
```

---

### Task 2: 后端 /desktop-config 接口

**Files:**
- Modify: `api/app/http/apps_routes.py`（或独立 `api/app/http/desktop_routes.py`——以现有路由组织为准，读 asgi_app.py 的 register 模式决定）
- Test: `api/test/app/http/test_desktop_config.py`

- [ ] **Step 1: 读路由注册模式**

读 `api/app/http/apps_routes.py` 头部与 register 方式，以及 `api/app/http/asgi_app.py` 里各模块 register_routes 的调用方式，确认新接口挂哪、怎么注册最一致。

- [ ] **Step 2: 写失败测试**

创建 `api/test/app/http/test_desktop_config.py`（先看 test_asgi_app.py 如何构造 test client）：

```python
"""GET /desktop-config：桌面客户端引导配置接口。"""


def test_desktop_config_returns_same_origin(api_client):
    resp = api_client.get("/desktop-config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["code"] == "success"
    body = data["data"]
    assert body["app_name"]
    assert body["api_origin"]
    assert body["api_prefix"] == "/api"
```

（`api_client` fixture 若不存在，参照 test_asgi_app.py 中既有 client 构造方式。）

- [ ] **Step 3: 运行确认失败**

Run: `cd d:\DEMO\openagent-main\api && python -m pytest test/app/http/test_desktop_config.py -q --no-cov`
Expected: FAIL（404）

- [ ] **Step 4: 实现接口**

在对应 routes 模块注册：

```python
@quart_app.get("/desktop-config")
async def async_desktop_config() -> Response:
    """桌面客户端引导配置：返回当前服务器同源信息（公开、无鉴权）。"""
    from quart import request as _req

    scheme = _req.headers.get("X-Forwarded-Proto", _req.scheme)
    host = _req.headers.get("X-Forwarded-Host", _req.host)
    origin = f"{scheme}://{host}"
    return _ok({
        "app_name": "钰心AI",
        "api_origin": origin,
        "api_prefix": "/api",
    })
```

（若该模块无 `request` 导入则按文件风格补充 import。）

- [ ] **Step 5: 运行确认通过**

Run: `cd d:\DEMO\openagent-main\api && python -m pytest test/app/http/test_desktop_config.py -q --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/http/<routes>.py api/test/app/http/test_desktop_config.py
git commit -m "feat(api): desktop-config endpoint for client bootstrap"
```

---

### Task 3: UI config 运行时覆盖（window.__DESKTOP_CONFIG__）

**Files:**
- Modify: `ui/src/config/index.ts`
- Test: 新增 `ui/src/config/__tests__/desktop-config.spec.ts`

- [ ] **Step 1: 写失败测试**

创建 `ui/src/config/__tests__/desktop-config.spec.ts`：

```typescript
import { describe, expect, it, vi, afterEach } from 'vitest'
import { resolveEndpointResolution } from '@/config'

describe('resolveEndpointResolution desktop override', () => {
  afterEach(() => {
    delete (window as unknown as Record<string, unknown>).__DESKTOP_CONFIG__
    vi.unstubAllEnvs()
  })

  it('prefers window.__DESKTOP_CONFIG__ apiBase over VITE_API_PREFIX and origin', () => {
    ;(window as unknown as Record<string, unknown>).__DESKTOP_CONFIG__ = {
      apiBase: 'https://cloud.example.com/api',
      socketPath: '/api/socket.io',
      socketUrl: 'https://cloud.example.com',
    }
    const res = resolveEndpointResolution({
      origin: 'https://fallback.example.com',
    } as Location)
    expect(res.apiBaseUrl).toBe('https://cloud.example.com/api')
  })

  it('falls back to location.origin /api when no desktop override', () => {
    const res = resolveEndpointResolution({
      origin: 'https://web.example.com',
    } as Location)
    expect(res.apiBaseUrl).toBe('https://web.example.com/api')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd d:\DEMO\openagent-main\ui && npx vitest run src/config/__tests__/desktop-config.spec.ts`
Expected: FAIL（无 desktop override 分支）

- [ ] **Step 3: 实现**

修改 `ui/src/config/index.ts`：

```typescript
type DesktopRuntimeConfig = {
  apiBase?: string
  socketUrl?: string
  socketPath?: string
}

const resolveDesktopOverride = (): DesktopRuntimeConfig | null => {
  if (typeof window === 'undefined') return null
  const cfg = (window as unknown as { __DESKTOP_CONFIG__?: DesktopRuntimeConfig }).__DESKTOP_CONFIG__
  if (!cfg?.apiBase) return null
  return cfg
}
```

在 `resolveEndpointResolution` 开头插入：

```typescript
export function resolveEndpointResolution(
  loc: RuntimeLocation = globalThis.location,
): EndpointResolution {
  const desktop = resolveDesktopOverride()
  if (desktop?.apiBase) {
    let apiUrl: URL
    try {
      apiUrl = new URL(desktop.apiBase)
    } catch {
      apiUrl = new URL(desktop.apiBase, 'https://invalid.invalid')
    }
    const socketPath = desktop.socketPath || '/api/socket.io'
    const socketUrl = desktop.socketUrl || apiUrl.origin
    return {
      apiBaseUrl: desktop.apiBase,
      socketEndpoint: { url: socketUrl, path: socketPath },
    }
  }

  const envPrefix = String(import.meta.env.VITE_API_PREFIX || '').trim()
  const resolvedConfiguredUrl = resolveConfiguredApiUrl(envPrefix, loc)
  if (resolvedConfiguredUrl) {
    return buildEndpointResolution(resolvedConfiguredUrl)
  }
  // ... 原逻辑不变
}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd d:\DEMO\openagent-main\ui && npx vitest run src/config/__tests__/desktop-config.spec.ts`
Expected: PASS（2 passed）

- [ ] **Step 5: 回归既有 config 测试**

Run: `cd d:\DEMO\openagent-main\ui && npx vitest run src/config`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add ui/src/config/index.ts ui/src/config/__tests__/desktop-config.spec.ts
git commit -m "feat(ui): support window.__DESKTOP_CONFIG__ apiBase override"
```

---

### Task 4: UI 桌面环境 hash history

**Files:**
- Modify: `ui/src/router/index.ts`

- [ ] **Step 1: 读现状**

读 `ui/src/router/index.ts` L1-12（createWebHistory 用法）确认。

- [ ] **Step 2: 实现**

改 L9-11：

```typescript
const isDesktop = typeof window !== 'undefined' && Boolean((window as unknown as { __DESKTOP_CONFIG__?: unknown }).__DESKTOP_CONFIG__)

const router = createRouter({
  history: isDesktop
    ? createWebHashHistory(import.meta.env.BASE_URL)
    : createWebHistory(import.meta.env.BASE_URL),
  routes,
})
```

并补 import `createWebHashHistory`。说明：桌面端用自定义协议 `app://bundle/` 服务静态文件时，hash history 保证刷新/深链不依赖服务器 rewrite；Web 端保持 history 不变。

- [ ] **Step 3: 验证**

Run: `cd d:\DEMO\openagent-main\ui && npx vue-tsc --noEmit`（仅检查本文件相关错误；工作区既有错误可忽略并记录）
Expected: 本文件无新增类型错误

- [ ] **Step 4: Commit**

```bash
git add ui/src/router/index.ts
git commit -m "feat(ui): use hash history under desktop runtime"
```

---

### Task 5: server-config 模块（desktop 主进程）

**Files:**
- Create: `desktop/server-config.js`
- Test: `desktop/test/server-config.test.js`

- [ ] **Step 1: 写失败测试**

创建 `desktop/test/server-config.test.js`：

```javascript
const { test } = require('node:test')
const assert = require('node:assert')
const path = require('node:path')
const os = require('node:os')
const fs = require('node:fs')

const ENTRY_ORIGIN = 'https://entry.example.com'

test('resolveConfig uses cache when fetch fails', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scfg-'))
  const cachePath = path.join(dir, 'server-config.json')
  fs.writeFileSync(cachePath, JSON.stringify({ api_origin: 'https://cached.example.com', api_prefix: '/api', app_name: 'X' }))
  const mod = require('../server-config')
  const cfg = await mod.loadServerConfig({ entryOrigin: ENTRY_ORIGIN, cachePath, fetchImpl: async () => { throw new Error('offline') } })
  assert.equal(cfg.api_origin, 'https://cached.example.com')
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd d:\DEMO\openagent-main\desktop && node --test test/server-config.test.js`
Expected: FAIL（无法 require ../server-config）

- [ ] **Step 3: 实现**

创建 `desktop/server-config.js`：

```javascript
const fs = require('node:fs')
const path = require('node:path')

const DEFAULT_ENTRY_ORIGIN = 'https://openllm.cloud'

async function loadServerConfig({ entryOrigin = DEFAULT_ENTRY_ORIGIN, cachePath, fetchImpl } = {}) {
  const fetchFn = fetchImpl || globalThis.fetch
  try {
    const resp = await fetchFn(`${entryOrigin}/api/desktop-config`)
    if (resp.ok) {
      const json = await resp.json()
      const data = json?.data
      if (data?.api_origin) {
        const cfg = {
          api_origin: String(data.api_origin).replace(/\/+$/, ''),
          api_prefix: data.api_prefix || '/api',
          app_name: data.app_name || '钰心AI',
        }
        if (cachePath) {
          fs.mkdirSync(path.dirname(cachePath), { recursive: true })
          fs.writeFileSync(cachePath, JSON.stringify(cfg), 'utf-8')
        }
        return cfg
      }
    }
  } catch {
    // 网络失败走缓存/默认
  }
  if (cachePath && fs.existsSync(cachePath)) {
    try {
      return JSON.parse(fs.readFileSync(cachePath, 'utf-8'))
    } catch {
      // 缓存损坏忽略
    }
  }
  return { api_origin: entryOrigin, api_prefix: '/api', app_name: '钰心AI' }
}

module.exports = { loadServerConfig, DEFAULT_ENTRY_ORIGIN }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd d:\DEMO\openagent-main\desktop && node --test test/server-config.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/server-config.js desktop/test/server-config.test.js
git commit -m "feat(desktop): server-config bootstrap with cache fallback"
```

---

### Task 6: credential-store（safeStorage）

**Files:**
- Create: `desktop/credential-store.js`
- Test: `desktop/test/credential-store.test.js`

- [ ] **Step 1: 写失败测试**

创建 `desktop/test/credential-store.test.js`（用可注入的 fake safeStorage）：

```javascript
const { test } = require('node:test')
const assert = require('node:assert')
const path = require('node:path')
const os = require('node:os')
const fs = require('node:fs')
const { createCredentialStore } = require('../credential-store')

const fakeSafeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: (s) => Buffer.from(`enc:${s}`, 'utf-8'),
  decryptString: (b) => String(b).replace(/^enc:/, ''),
}

test('save then load returns token', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cred-'))
  const store = createCredentialStore({ filePath: path.join(dir, 'cred.bin'), safeStorage: fakeSafeStorage })
  store.save('token-abc')
  assert.equal(store.load(), 'token-abc')
})

test('load with no file returns null', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cred2-'))
  const store = createCredentialStore({ filePath: path.join(dir, 'nope.bin'), safeStorage: fakeSafeStorage })
  assert.equal(store.load(), null)
})

test('clear removes file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cred3-'))
  const store = createCredentialStore({ filePath: path.join(dir, 'c.bin'), safeStorage: fakeSafeStorage })
  store.save('x')
  store.clear()
  assert.equal(store.load(), null)
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd d:\DEMO\openagent-main\desktop && node --test test/credential-store.test.js`
Expected: FAIL（cannot find module）

- [ ] **Step 3: 实现**

创建 `desktop/credential-store.js`：

```javascript
const fs = require('node:fs')
const path = require('node:path')

function createCredentialStore({ filePath, safeStorage } = {}) {
  const storage = safeStorage || null
  const target = filePath || ''

  function save(accessToken) {
    if (!accessToken || !storage || !target) return
    const encrypted = storage.encryptString(String(accessToken))
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.writeFileSync(target, encrypted)
  }

  function load() {
    if (!storage || !target || !fs.existsSync(target)) return null
    try {
      const buf = fs.readFileSync(target)
      return storage.decryptString(buf)
    } catch {
      return null
    }
  }

  function clear() {
    if (target && fs.existsSync(target)) {
      try { fs.unlinkSync(target) } catch { /* ignore */ }
    }
  }

  return { save, load, clear }
}

module.exports = { createCredentialStore }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd d:\DEMO\openagent-main\desktop && node --test test/credential-store.test.js`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add desktop/credential-store.js desktop/test/credential-store.test.js
git commit -m "feat(desktop): safeStorage credential store"
```

---

### Task 7: preload + main 集成（server-config、凭证、worker-host 改造、托盘占位）

**Files:**
- Modify: `desktop/preload.js`
- Modify: `desktop/main.js`

- [ ] **Step 1: 读现状**

读 `desktop/main.js` 全文（已熟悉）与 `desktop/preload.js`。

- [ ] **Step 2: 改 preload**

`desktop/preload.js` 增加：

```javascript
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('yuxinDesktop', {
  // ...既有方法保留...
  getDesktopConfig: () => ipcRenderer.invoke('desktop:get-config'),
  getCredential: () => ipcRenderer.invoke('desktop:get-credential'),
  setCredential: (token) => ipcRenderer.invoke('desktop:set-credential', token),
  clearCredential: () => ipcRenderer.invoke('desktop:clear-credential'),
  getWorkerVersions: () => ipcRenderer.invoke('desktop:worker-versions'),
  setLaunchAtLogin: (enabled) => ipcRenderer.invoke('desktop:set-launch-at-login', enabled),
  getLaunchAtLogin: () => ipcRenderer.invoke('desktop:get-launch-at-login'),
  checkForUpdates: () => ipcRenderer.invoke('desktop:check-for-updates'),
})
```

`main.js` 中 `app.whenReady` 内，在 createWindow 前注入到每个页面：

```javascript
const { loadServerConfig } = require('./server-config')
const { createCredentialStore } = require('./credential-store')

// 在 createWindow 中 webPreferences.preload 已有；此处把 config 放入待注入变量
let desktopRuntimeConfig = null
const credentialStore = createCredentialStore({
  filePath: path.join(app.getPath('userData'), 'credential.bin'),
  safeStorage: safeStorage.isEncryptionAvailable() ? safeStorage : null,
})
```

- [ ] **Step 3: worker-host 改造（spawn exe / 回退 python）**

在 `main.js` 增加：

```javascript
function workerCommand(name) {
  const exe = path.join(process.resourcesPath || '', 'yuxin-worker.exe')
  if (fs.existsSync(exe)) {
    return { cmd: exe, args: [name] }
  }
  // 开发模式回退 python
  return { cmd: pythonBin(), args: [workerScript(name)] }
}
```

并把 `startWorker` 改为使用 `workerCommand`：

```javascript
function startWorker(name, env) {
  const { cmd, args } = workerCommand(name)
  const child = spawn(cmd, args, { env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] })
  // ...原有 stdout/stderr/exit 处理不变
}
```

- [ ] **Step 4: IPC handlers**

在 `main.js` 注册：

```javascript
ipcMain.handle('desktop:get-config', async () => {
  if (!desktopRuntimeConfig) {
    const cachePath = path.join(app.getPath('userData'), 'server-config.json')
    desktopRuntimeConfig = await loadServerConfig({ cachePath })
  }
  return {
    apiBase: `${desktopRuntimeConfig.api_origin}${desktopRuntimeConfig.api_prefix}`,
    apiOrigin: desktopRuntimeConfig.api_origin,
    socketUrl: desktopRuntimeConfig.api_origin,
    socketPath: `${desktopRuntimeConfig.api_prefix}/socket.io`,
    appName: desktopRuntimeConfig.app_name,
  }
})
ipcMain.handle('desktop:get-credential', () => credentialStore.load())
ipcMain.handle('desktop:set-credential', (_e, token) => credentialStore.save(token))
ipcMain.handle('desktop:clear-credential', () => credentialStore.clear())
ipcMain.handle('desktop:set-launch-at-login', (_e, enabled) => app.setLoginItemSettings({ openAtLogin: Boolean(enabled) }))
ipcMain.handle('desktop:get-launch-at-login', () => app.getLoginItemSettings().openAtLogin)
```

- [ ] **Step 5: 注入到 renderer**

登录态同步：在 `createWindow` 里，`mainWindow.webContents.on('did-finish-load')` 后 `executeJavaScript` 写入 `window.__DESKTOP_CONFIG__` 会太晚（模块加载已执行）。正确做法：**自定义协议 + preload 注入**。preload 中同步暴露：

```javascript
// preload.js 顶部（同步、早于页面脚本）
const config = ipcRenderer.sendSync('desktop:get-config-sync')
contextBridge.exposeInMainWorld('__DESKTOP_CONFIG__', config)
```

对应 main.js 增加同步 handler（注意：sendSync 会阻塞，config 应先缓存好）：

```javascript
ipcMain.on('desktop:get-config-sync', (event) => {
  event.returnValue = syncConfig()
})
```

其中 `syncConfig()` 使用已缓存 config（首次未取到时用 entry origin 默认 + 异步后台刷新）。

- [ ] **Step 6: 冒烟验证（dev 模式）**

Run: `cd d:\DEMO\openagent-main\desktop && set DESKTOP_PYTHON=python && npm start`（先确认 ui/dist 已 build；若未 build 先 `cd ui && npm run build`）
Expected: Electron 窗口打开、能启动 worker、`desktop:get-config` 可调（在 console 验证）

- [ ] **Step 7: Commit**

```bash
git add desktop/main.js desktop/preload.js
git commit -m "feat(desktop): integrate server-config, credential store, worker-host exe"
```

---

### Task 8: 托盘、通知、开机自启、自动更新接入

**Files:**
- Create: `desktop/tray.js`、`desktop/updater.js`
- Modify: `desktop/main.js`

- [ ] **Step 1: 读现状并确认依赖**

读 `desktop/main.js` 生命周期；确认 `electron` 的 `Tray/Menu/Notification/nativeImage` 导入；package.json 是否已有 electron-updater（无则 Task 9 加依赖，本 Task 用可选 require 容错）。

- [ ] **Step 2: 实现 tray.js**

创建 `desktop/tray.js`：

```javascript
const { Tray, Menu, nativeImage } = require('electron')
const path = require('node:path')

function createTray({ iconPath, onShow, onQuit, getStatus }) {
  const icon = nativeImage.createFromPath(iconPath || path.join(__dirname, 'tray-icon.png'))
  const tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon)
  tray.setToolTip('钰心AI')
  const buildMenu = () => {
    const status = (getStatus && getStatus()) || {}
    return Menu.buildFromTemplate([
      { label: '显示钰心AI', click: onShow },
      { type: 'separator' },
      { label: `本机服务：${Object.keys(status).filter((k) => status[k]).length} 运行中`, enabled: false },
      { type: 'separator' },
      { label: '退出', click: onQuit },
    ])
  }
  tray.setContextMenu(buildMenu())
  tray.on('click', onShow)
  return tray
}

module.exports = { createTray }
```

- [ ] **Step 3: 实现 updater.js**

创建 `desktop/updater.js`（electron-updater 未装时降级）：

```javascript
let autoUpdater = null
try {
  ;({ autoUpdater } = require('electron-updater'))
} catch {
  autoUpdater = null
}

function setupUpdater({ onStatus, onError }) {
  if (!autoUpdater) return null
  autoUpdater.autoDownload = true
  autoUpdater.on('checking-for-update', () => onStatus && onStatus('checking'))
  autoUpdater.on('update-available', () => onStatus && onStatus('available'))
  autoUpdater.on('update-not-available', () => onStatus && onStatus('not-available'))
  autoUpdater.on('error', (err) => onError && onError(err))
  return autoUpdater
}

function checkForUpdates() {
  if (autoUpdater) autoUpdater.checkForUpdatesAndNotify()
}

module.exports = { setupUpdater, checkForUpdates }
```

- [ ] **Step 4: 集成 main.js**

在 `main.js`：
- 导入 `createTray`、`setupUpdater`/`checkForUpdates`。
- `app.whenReady` 后创建托盘（onShow 聚焦窗口、onQuit 真退出并停 worker）；`window-all-closed` 不再直接 quit（关闭到托盘），仅托盘"退出"调 `app.quit()` 并在 `before-quit` 停 worker。
- 通知：任务完成/worker 异常时 `new Notification({ title, body })`（主进程，Windows 可用）。
- 开机自启 IPC 已注册（Task 7）；`checkForUpdates` IPC 在 preload 已有。
- 更新状态经 `webContents.send('desktop:update-status', status)` 推给 renderer。

- [ ] **Step 5: 验证（dev 冒烟）**

Run: `cd d:\DEMO\openagent-main\desktop && npm start`
Expected: 托盘图标出现；关闭窗口程序驻留；右键菜单显示/退出可用

- [ ] **Step 6: Commit**

```bash
git add desktop/tray.js desktop/updater.js desktop/main.js
git commit -m "feat(desktop): tray, notifications, launch-at-login, updater integration"
```

---

### Task 9: 构建配置（PyInstaller spec + electron-builder NSIS）

**Files:**
- Create: `api/scripts/pyinstaller/worker.spec`
- Create: `desktop/build/worker-builder.md`（说明文档，含打包命令）
- Modify: `desktop/package.json`

- [ ] **Step 1: 实现 PyInstaller spec**

创建 `api/scripts/pyinstaller/worker.spec`：

```python
# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec：单一 worker exe（含 os/browser/computer/wake 四服务）
# 用法：pyinstaller --clean --noconfirm api/scripts/pyinstaller/worker.spec
# 产出：dist/yuxin-worker/yuxin-worker.exe（Electron 安装包以 extraResources 携带）

import os

block_cipher = None

a = Analysis(
    ['../worker_super.py'],
    pathex=['../..'],          # 使 scripts.* 可导入（api 为根）
    binaries=[],
    datas=[],
    hiddenimports=[
        'scripts.os_automation_worker',
        'scripts.browser_automation_worker',
        'scripts.computer_control_worker',
        'scripts.wake_word_worker',
        # 动态导入依赖（按需补充：playwright.sync_api 等，若打包 browser/computer 能力）
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='yuxin-worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # 后台进程需 console=False？Electron 隐藏窗口 spawn 时用 console=True + windows 隐藏
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

- [ ] **Step 2: 修改 package.json（electron-builder NSIS + extraResources + publish）**

`desktop/package.json` 的 `build` 增加：

```json
{
  "extraResources": [
    { "from": "../api/scripts/pyinstaller/dist/yuxin-worker/", "to": "yuxin-worker" }
  ],
  "publish": {
    "provider": "generic",
    "url": "https://openllm.cloud/desktop-updates"
  }
}
```

（`publish.url` 为占位，正式更新服务器就绪后替换。electron-builder 已含 updater 依赖则无需 `electron-updater` 单独装——若 package.json devDependencies 无 electron-updater，执行 `npm i -D electron-updater`。）

- [ ] **Step 3: 构建验证（本机已装 PyInstaller 时）**

Run（若 pyinstaller 未装先 `pip install pyinstaller`）：
```powershell
cd d:\DEMO\openagent-main\api\scripts\pyinstaller
pyinstaller --clean --noconfirm worker.spec
```
Expected: `dist/yuxin-worker/yuxin-worker.exe` 生成

Run（验证 exe 可启动 os 服务）：
```powershell
$env:OS_AUTOMATION_TOKEN='t'
.\dist\yuxin-worker\yuxin-worker.exe os --port 8899
```
Expected: 输出 listening 后 Ctrl+C（若本机无 playwright 等依赖导致 browser 子命令失败，记录并确认 os 可用即可）

- [ ] **Step 4: NSIS 打包（若 electron-builder 可运行）**

Run: `cd d:\DEMO\openagent-main\desktop && npm run dist`
Expected: `desktop/dist/yuxin-ai-desktop Setup.exe` 或类似产物（若因缺签名/图标资源失败，记录并降级为 `--dir` 免安装验证）

- [ ] **Step 5: Commit**

```bash
git add api/scripts/pyinstaller/worker.spec desktop/package.json desktop/build/worker-builder.md
git commit -m "build(desktop): worker exe spec and NSIS packaging config"
```

---

### Task 10: 设备面板完善 + UI 集成桌面配置

**Files:**
- Modify: `ui/src/components/DesktopDevicePanel.vue`
- Modify: `ui/src/i18n/messages/zh-CN.ts` / `en-US.ts`（新增文案）

- [ ] **Step 1: 扩展 preload 类型声明与面板**

先确认 `DesktopDevicePanel.vue` 的 `desktopApi` 类型（已含 workersStatus/recycleList/recycleRestore/wake*），按 Task 7 新增 IPC 扩展该类型与模板：

- 增加 `getWorkerVersions`、`getLaunchAtLogin`、`setLaunchAtLogin`、`checkForUpdates` 到 `desktopApi` 类型。
- 面板新增区块：worker 版本列表（os/browser/computer/wake 的版本与 running）、开机自启开关（`a-switch`，onMounted 拉取 `getLaunchAtLogin`，切换调 `setLaunchAtLogin`）、"检查更新"按钮（调 `checkForUpdates`）。
- 沿用既有 i18n 文案风格（`desktopDevice.*`），在 zh-CN/en-US 增补 key：`version`、`launchAtLogin`、`checkUpdate`、`updateChecking` 等。

- [ ] **Step 2: 验证（type-check + 冒烟）**

Run: `cd d:\DEMO\openagent-main\ui && npx vue-tsc --noEmit`（本文件无新增错误；工作区既有错误记录）
Run: `cd d:\DEMO\openagent-main\ui && npx vitest run src/components` （若有该面板 spec）
Expected: 无新增错误

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/DesktopDevicePanel.vue ui/src/i18n/messages/zh-CN.ts ui/src/i18n/messages/en-US.ts
git commit -m "feat(ui): enrich desktop device panel with versions, autostart, updates"
```

---

### Task 11: 登录态同步（renderer ↔ 主进程凭证）

**Files:**
- Modify: `ui/src/stores/credential.ts`（或调用的 utils/auth）——经 yuxinDesktop IPC 同步
- Modify: `ui/src/utils/login-redirect.ts`（桌面端可能无需，仅评估）

- [ ] **Step 1: 分析同步点**

读 `ui/src/stores/credential.ts`（已知：update/clear 写 localStorage）。目标：凭证变化时经 IPC 同步到主进程 safeStorage；应用启动时若 localStorage 无凭证但主进程有，则回填。

- [ ] **Step 2: 实现**

在 `credential.ts` 的 `update` 与 `clear` 内，检测桌面环境并同步：

```typescript
const desktopApi = (window as unknown as { yuxinDesktop?: { setCredential?: (t: string) => Promise<unknown>; clearCredential?: () => Promise<unknown>; getCredential?: () => Promise<string | null> } }).yuxinDesktop

const syncToDesktop = (accessToken: string) => {
  if (desktopApi?.setCredential && accessToken) {
    void desktopApi.setCredential(accessToken)
  } else if (desktopApi?.clearCredential) {
    void desktopApi.clearCredential()
  }
}
```

在 `update` 末尾调 `syncToDesktop(params.access_token || '')`；`clear` 调 `desktopApi?.clearCredential?.()`。
新增 `restoreFromDesktop()`：应用启动（HomeView/App onMounted）时若 `!getStoredCredential()?.access_token` 且 `desktopApi?.getCredential` 存在，取回并 `update({ access_token, expire_at: 0 })`（expire_at 0 会让 isCredentialLoggedIn 判未过期？——核对 `getCredentialAccessToken` 过期语义，见 `ui/src/utils/auth.ts`；若 expire_at 缺失视为有效则传 0，否则需主进程同时存 expire_at。**实施时核对后决定：建议主进程 credential.bin 存 JSON { access_token, expire_at }，此步按最终实现调整**）。

- [ ] **Step 3: 验证**

Run: `cd d:\DEMO\openagent-main\ui && npx vue-tsc --noEmit`（本文件无新增错误）

- [ ] **Step 4: Commit**

```bash
git add ui/src/stores/credential.ts
git commit -m "feat(ui): sync credential with desktop safeStorage"
```

---

## 自检

**Spec 覆盖：**
- A1 worker exe → Task 1（super）+ Task 9（PyInstaller spec）
- A2 服务器注入 → Task 2（后端接口）+ Task 3（UI 覆盖）+ Task 5（server-config）+ Task 7（注入）
- A3 原生体验 → Task 8（托盘/通知/自启/更新）
- A4 UI 原生化 + 设备面板 → Task 4（hash history）+ Task 10（面板）；UI 原生化（自绘标题栏）**未拆独立任务**——需补或标注为后续（spec §3.3 提到，但为控制 A 首版范围可延后）。已在 spec §5 列 A4 含"自绘标题栏"——补 Task 12 或在 A4 阶段执行时视 UI 集成复杂度决定。见下"范围说明"。
- A5 构建分发 → Task 9（NSIS）
- 登录态同步 → Task 6（credential-store）+ Task 11（sync）

**类型一致性：**
- preload 方法名：getDesktopConfig→get-config、credential get/set/clear、getWorkerVersions、set/getLaunchAtLogin、checkForUpdates —— Task 7/8/10/11 中一致使用。
- server-config 返回字段：api_origin/api_prefix/app_name；main.js 组装 apiBase/socketUrl/socketPath/appName 注入 —— Task 5/7 一致。
- credential-store API：save/load/clear —— Task 6/7/11 一致。

**范围说明（诚实标注）：**
1. UI 原生化（自绘标题栏）与"托盘图标资源"依赖 UI/图标素材，未拆为独立可测任务。**建议**：首版以"关闭驻留托盘 + 系统通知 + 登录态保持 + 设备面板"为交付；自绘标题栏作为 A 的后续增强（spec §3.3 保留，实施时按需在 A4 阶段增补任务）。
2. 自动更新依赖 electron-updater 与更新服务器；publish.url 为占位。未配服务器前 update 检查会失败——代码容错（Task 8 updater.js try/catch + 状态回调），不阻塞。
3. browser/wake 的运行时二进制（Chromium/模型）不在 PyInstaller 内，spec §3.2 已列 extraResources/按需下载；Task 9 构建验证仅保证 os 服务可用，browser/wake 完整分发留待打包环境具备时补。
