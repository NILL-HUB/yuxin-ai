import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _bash_available() -> bool:
    """entrypoint.sh 为 bash 脚本，需真实 bash（Linux/容器内可用；Windows 本机 WSL 挂载失败则跳过）。"""
    if not shutil.which("bash"):
        return False
    try:
        result = subprocess.run(
            ["bash", "-c", "exit 0"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(
    not _bash_available(),
    reason="bash 不可用（Windows 本机无可用 bash/WSL），entrypoint 脚本验证需在 Linux/容器环境执行",
)


def _write_capture_command(tmp_path: Path, command_name: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    command_path = bin_dir / command_name
    command_path.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$0 $*\" > \"$CAPTURE_FILE\"\n",
        encoding="utf-8",
    )
    command_path.chmod(0o755)


def _run_api_entrypoint(tmp_path: Path, *, extra_env: dict[str, str] | None = None) -> str:
    project_root = Path(__file__).resolve().parents[4]
    bin_dir = tmp_path / "bin"
    capture_file = tmp_path / "capture.txt"

    for command_name in ("uvicorn", "celery"):
        _write_capture_command(tmp_path, command_name)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "CAPTURE_FILE": str(capture_file),
            "MODE": "asgi",
            "MIGRATION_ENABLED": "false",
            "APP_ENV": "production",
            "SQLALCHEMY_DATABASE_URI": "postgresql://postgres:pwd@localhost:5432/llmops",
            "REDIS_HOST": "localhost",
            "REDIS_PORT": "6379",
            "JWT_SECRET_KEY": "secret",
        }
    )
    if extra_env:
        env.update(extra_env)

    subprocess.run(
        ["bash", str(project_root / "api" / "docker" / "entrypoint.sh")],
        check=True,
        cwd=project_root / "api",
        env=env,
        capture_output=True,
        text=True,
    )

    return capture_file.read_text(encoding="utf-8").strip()


def test_api_entrypoint_should_default_to_single_asgi_worker(tmp_path):
    command = _run_api_entrypoint(tmp_path)

    assert "uvicorn" in command
    assert "--workers 1" in command


def test_api_entrypoint_should_scale_asgi_workers_when_configured(tmp_path):
    command = _run_api_entrypoint(
        tmp_path,
        extra_env={
            "ASGI_WORKER_AMOUNT": "4",
        },
    )

    assert "uvicorn" in command
    assert "--workers 4" in command
