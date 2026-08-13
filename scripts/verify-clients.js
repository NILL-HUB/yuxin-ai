const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const requiredFiles = [
  'desktop/main.js',
  'desktop/preload.js',
  'desktop/bridge.js',
  'desktop/package.json',
  'desktop/README.md',
  'mobile/package.json',
  'mobile/capacitor.config.ts',
  'mobile/README.md',
]

let failed = false
for (const file of requiredFiles) {
  const full = path.join(root, file)
  if (!fs.existsSync(full)) {
    console.error(`MISSING ${file}`)
    failed = true
  }
}

for (const file of ['desktop/main.js', 'desktop/preload.js', 'desktop/bridge.js']) {
  try {
    execFileSync(process.execPath, ['--check', path.join(root, file)], { stdio: 'pipe' })
  } catch (error) {
    console.error(`SYNTAX FAIL ${file}: ${error.stderr || error.message}`)
    failed = true
  }
}

for (const file of ['desktop/package.json', 'mobile/package.json']) {
  try {
    JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'))
  } catch (error) {
    console.error(`JSON FAIL ${file}: ${error.message}`)
    failed = true
  }
}

try {
  execFileSync(process.execPath, ['--test', path.join(root, 'desktop', 'test', 'bridge.test.js')], {
    stdio: 'inherit',
  })
} catch {
  failed = true
}

if (failed) {
  console.error('Client verification failed')
  process.exit(1)
}
console.log('Client verification OK: desktop + mobile')
