# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec：Yujianwo 桌面单一 worker exe（os/browser/computer/wake 四服务）
# 用法：
#   cd api/scripts/pyinstaller && pyinstaller --clean --noconfirm worker.spec
# 产出：dist/yujianwo-worker/yujianwo-worker.exe
#
# 说明：
# - worker_super 只 import 各 worker 模块，第三方依赖在各 worker 内部延迟 import；
#   computer worker 的 pyautogui/Pillow 已显式打包（见下 collect_all），使桌面端
#   安装包开箱即可真正操作鼠标/键盘/截屏，无需用户额外装 Python 依赖。
# - 仍未打包：browser worker 的 playwright、wake 的 openwakeword 及其模型；
#   执行到对应能力时 worker 会返回清晰的依赖缺失错误（各 worker 已内置处理）。
# - browser worker 的 Chromium 二进制与 wake 模型文件按设计放在 Electron
#   extraResources / 运行时目录，不打包进本 exe。

from PyInstaller.utils.hooks import collect_all  # noqa: E402

# pyautogui 全家桶延迟 import，PyInstaller 静态分析扫不到，需显式收集。
_computer_datas = []
_computer_binaries = []
_computer_hiddenimports = []
for _pkg in (
    'pyautogui',
    'pyscreeze',
    'pymsgbox',
    'pytweening',
    'pygetwindow',
    'pyrect',
    'mouseinfo',
    'pyperclip',
    'PIL',
):
    _d, _b, _h = collect_all(_pkg)
    _computer_datas += _d
    _computer_binaries += _b
    _computer_hiddenimports += _h

a = Analysis(
    ['../worker_super.py'],
    pathex=['../..'],
    binaries=_computer_binaries,
    datas=_computer_datas,
    hiddenimports=[
        'scripts.os_automation_worker',
        'scripts.browser_automation_worker',
        'scripts.computer_control_worker',
        # 本机渲染 worker：作为 render 子命令被 worker_super 动态导入
        'scripts.render_worker',
        # cua-driver 后端客户端：computer worker 探测 daemon 后按其路由到后台控制
        'scripts.cua_driver_client',
        'scripts.wake_word_worker',
        *_computer_hiddenimports,
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
    name='yujianwo-worker',
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
