"""worker.spec 必须显式登记每个 worker 模块（PyInstaller 不做动态发现）。"""
from pathlib import Path

SPEC = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "pyinstaller"
    / "worker.spec"
)


def test_spec_lists_all_worker_modules():
    text = SPEC.read_text(encoding="utf-8")
    for module in (
        "scripts.os_automation_worker",
        "scripts.browser_automation_worker",
        "scripts.computer_control_worker",
        "scripts.render_worker",
        "scripts.wake_word_worker",
    ):
        assert f"'{module}'" in text, f"{module} 未登记到 hiddenimports"


def test_spec_keeps_cua_driver_client():
    """既有登记不能被误删。"""
    text = SPEC.read_text(encoding="utf-8")
    assert "'scripts.cua_driver_client'" in text
