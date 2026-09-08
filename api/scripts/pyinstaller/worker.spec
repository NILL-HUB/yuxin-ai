# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec：YuxinAI 桌面单一 worker exe（os/browser/computer/wake 四服务）
# 用法：
#   cd api/scripts/pyinstaller && pyinstaller --clean --noconfirm worker.spec
# 产出：dist/yuxin-worker/yuxin-worker.exe
#
# 说明：
# - worker_super 只 import 各 worker 模块；playwright/pyautogui/openwakeword 等
#   第三方依赖在各 worker 内部延迟 import，故本 exe 不含它们，服务可正常启动，
#   执行到对应能力时 worker 会返回清晰的依赖缺失错误（各 worker 已内置处理）。
# - browser worker 的 Chromium 二进制与 wake 模型文件按设计放在 Electron
#   extraResources / 运行时目录，不打包进本 exe。

a = Analysis(
    ['../worker_super.py'],
    pathex=['../..'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'scripts.os_automation_worker',
        'scripts.browser_automation_worker',
        'scripts.computer_control_worker',
        'scripts.wake_word_worker',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='yuxin-worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
