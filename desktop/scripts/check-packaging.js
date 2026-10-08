// 打包清单校验：防止「main.js 新增了本地 require，但 build.files 漏登记」
// 导致装完后 Electron 启动即弹 “Error launching app”（app.asar 里缺文件）。
//
// 历史事故（2026-10-07 实测）：main.js 引入 `require('./device-gateway')`
// 但 device-gateway.js 未加入 build.files —— 安装版双击只显示 Error 对话框，
// 主进程逻辑（worker/配置拉取）全部未执行；源码模式却完全正常（文件都在磁盘）。
// 故在 pack/dist 前置执行本校验，清单不全直接阻断打包。
const fs = require('node:fs')
const path = require('node:path')

const root = path.join(__dirname, '..')
const pkg = require(path.join(root, 'package.json'))
const mainSrc = fs.readFileSync(path.join(root, 'main.js'), 'utf-8')

// 仅统计形如 require('./xxx') 的本地模块（含连字符命名），排除 require('./x/y') 子目录写法。
const requiredFiles = [
  ...new Set(
    [...mainSrc.matchAll(/require\('\.\/([a-zA-Z0-9_-]+)'\)/g)].map((m) => `${m[1]}.js`)
  ),
]

const declared = new Set(pkg.build && pkg.build.files ? pkg.build.files : [])
const missing = requiredFiles.filter((file) => !declared.has(file))

if (missing.length > 0) {
  console.error(
    `[packaging] 打包清单校验失败：main.js 依赖以下文件，但 package.json build.files 未登记：\n  - ${missing.join('\n  - ')}\n` +
      '请把它们加入 build.files，否则安装版启动会直接报 Error。'
  )
  process.exit(1)
}

console.log(
  `[packaging] 打包清单校验通过：main.js 的 ${requiredFiles.length} 个本地依赖均已登记。`
)
