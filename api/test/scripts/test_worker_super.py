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
