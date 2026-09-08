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
      try {
        fs.unlinkSync(target)
      } catch {
        /* ignore */
      }
    }
  }

  return { save, load, clear }
}

module.exports = { createCredentialStore }
