"""worker_super：单一 worker exe 的子命令分发测试。"""
import importlib
import os
import sys

import pytest

from scripts import worker_super


class _FakeWorker:
    """记录 worker main 收到 argv 的假 worker，用于断言注入结果。"""

    def __init__(self, main):
        self.main = main


class _FakeImportlib:
    def __init__(self, main):
        self._main = main

    def import_module(self, name):
        return _FakeWorker(self._main)


def _stub_worker(monkeypatch, main, argv=None):
    """替换 worker 模块解析与 sys.argv，返回假 entry。"""
    monkeypatch.setattr(worker_super, "_module_and_entry", lambda service: (None, "main"))
    monkeypatch.setattr(worker_super, "importlib", _FakeImportlib(main))
    original = ["yuxin-worker.exe"] if argv is None else list(argv)
    monkeypatch.setattr(sys, "argv", original)
    return original


class TestDispatch:
    def test_parse_subcommand(self):
        args = worker_super.parse_args(["os", "--port", "8765"])
        assert args.service == "os"
        assert args.port == 8765

    def test_rejects_unknown_service(self):
        with pytest.raises(SystemExit):
            worker_super.parse_args(["unknown"])

    def test_imports_each_worker_module(self):
        # 各 worker 模块可被 import（PyInstaller 隐藏导入的验证依据）
        for mod in ("os_automation_worker", "browser_automation_worker",
                    "computer_control_worker", "wake_word_worker"):
            importlib.import_module(f"scripts.{mod}")


class TestArgvInjection:
    """按服务白名单把 --host/--port 注入 worker argv，绝不把 host/port 塞给 wake。"""

    def test_os_injects_host_and_port(self, monkeypatch):
        seen = {}

        def fake_main():
            seen["argv"] = list(sys.argv)
            return 0

        _stub_worker(monkeypatch, fake_main)
        assert worker_super.main(["os", "--host", "0.0.0.0", "--port", "8899"]) == 0
        assert seen["argv"] == ["yuxin-worker.exe", "--host", "0.0.0.0", "--port", "8899"]

    def test_wake_never_receives_host_port(self, monkeypatch):
        seen = {}

        def fake_main():
            seen["argv"] = list(sys.argv)
            return 0

        _stub_worker(monkeypatch, fake_main)
        assert worker_super.main(["wake", "--host", "0.0.0.0", "--port", "8899"]) == 0
        assert seen["argv"] == ["yuxin-worker.exe"]

    def test_default_injects_nothing(self, monkeypatch):
        seen = {}

        def fake_main():
            seen["argv"] = list(sys.argv)
            return 0

        _stub_worker(monkeypatch, fake_main)
        assert worker_super.main(["os"]) == 0
        assert seen["argv"] == ["yuxin-worker.exe"]

    def test_restores_sys_argv_on_exit(self, monkeypatch):
        original = _stub_worker(
            monkeypatch,
            lambda: (_ for _ in ()).throw(SystemExit(2)),
            argv=["python", "worker_super.py"],
        )
        with pytest.raises(SystemExit) as excinfo:
            worker_super.main(["os", "--port", "8899"])
        assert excinfo.value.code == 2
        assert sys.argv == original


class TestExitCodeWrapping:
    def test_system_exit_code_2_reported_and_reraised(self, monkeypatch, capsys):
        _stub_worker(monkeypatch, lambda: (_ for _ in ()).throw(SystemExit(2)))
        with pytest.raises(SystemExit) as excinfo:
            worker_super.main(["os"])
        assert excinfo.value.code == 2
        assert "yuxin-worker os 启动失败" in capsys.readouterr().err

    def test_system_exit_zero_passthrough_without_message(self, monkeypatch, capsys):
        _stub_worker(monkeypatch, lambda: (_ for _ in ()).throw(SystemExit(0)))
        with pytest.raises(SystemExit) as excinfo:
            worker_super.main(["wake"])
        assert excinfo.value.code == 0
        assert capsys.readouterr().err == ""


class TestHostWatchdog:
    """宿主存活看门狗：注入 YUXIN_HOST_PID 后，worker 应检测宿主并自杀。"""

    def test_parse_host_pid_from_env(self, monkeypatch):
        monkeypatch.setenv(worker_super.HOST_PID_ENV, "12345")
        assert worker_super._parse_host_pid() == 12345

    def test_parse_host_pid_absent(self, monkeypatch):
        monkeypatch.delenv(worker_super.HOST_PID_ENV, raising=False)
        assert worker_super._parse_host_pid() is None

    def test_parse_host_pid_invalid(self, monkeypatch):
        monkeypatch.setenv(worker_super.HOST_PID_ENV, "abc")
        assert worker_super._parse_host_pid() is None

    def test_pid_exists_for_current_process(self):
        assert worker_super._pid_exists(os.getpid())

    def test_pid_exists_for_unknown(self):
        # 找一个必然不存在的 PID
        unknown = 2**30
        while worker_super._pid_exists(unknown):
            unknown += 1
        assert not worker_super._pid_exists(unknown)

    def test_host_alive_returns_true_for_self(self):
        assert worker_super._host_alive(os.getpid()) is True

    def test_run_with_watchdog_returns_entry_result(self, monkeypatch):
        host_pid = os.getpid()
        monkeypatch.setattr(worker_super, "_start_host_watchdog", lambda *_: None)
        result = worker_super._run_with_host_watchdog(host_pid, lambda: 7, "os")
        assert result == 7

    def test_run_with_watchdog_reraise_system_exit(self, monkeypatch, capsys):
        host_pid = os.getpid()
        monkeypatch.setattr(worker_super, "_start_host_watchdog", lambda *_: None)

        def boom():
            raise SystemExit(3)

        with pytest.raises(SystemExit) as excinfo:
            worker_super._run_with_host_watchdog(host_pid, boom, "os")
        assert excinfo.value.code == 3
        assert "yuxin-worker os 启动失败" in capsys.readouterr().err
