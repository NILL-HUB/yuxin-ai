from __future__ import annotations

import json
import logging
import os
import re
import shlex
import signal
import subprocess
import sys
import textwrap
import tempfile
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from internal.core.agent.backends import (
    HttpSandboxHandle,
    RemoteExecHandle,
    build_sandbox_backend,
)
from internal.core.agent.backends.endpoint_utils import is_placeholder_endpoint
from internal.core.agent.entities.sandbox_runtime_entity import (
    BACKEND_HTTP_SANDBOX,
    BACKEND_TENCENT_SCF,
    CAPABILITY_SKILL_EXEC,
    E2B_PROTOCOL_BACKENDS,
)
from internal.core.agent.sandbox_runtime_registry import get_sandbox_runtime
from internal.exception import FailException

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  本地兜底执行的子进程资源上限（S5）
#  仅在管理员显式开启 allow_local_exec 时启用；由 runner 在子进程内 setrlimit
#  best-effort 生效（平台不支持则忽略）。这是"故障/资源围栏"，不是安全沙箱。
# --------------------------------------------------------------------------- #
_LOCAL_EXEC_CPU_SECONDS = 60                       # CPU 时间上限（秒）
_LOCAL_EXEC_MEMORY_BYTES = 1024 * 1024 * 1024      # 地址空间上限 1 GiB
_LOCAL_EXEC_FILE_SIZE_BYTES = 64 * 1024 * 1024     # 单文件写入上限 64 MiB
_LOCAL_EXEC_MAX_PROCESSES = 512                    # 进程数上限（防 fork 炸弹；NPROC 按 UID 计，留足够余量）
_LOCAL_EXEC_MAX_OPEN_FILES = 256                   # 打开句柄上限
# 父进程 env 白名单：只有这些键会被传入子进程（其余一律不继承，避免泄漏 API 密钥）
_LOCAL_EXEC_ENV_ALLOWLIST = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)


_SAFE_SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _sanitize_source_key(value: str) -> str:
    if value and _SAFE_SOURCE_KEY_RE.match(value):
        return value
    logger.warning("技能 source_key 包含非法字符，已回退为默认值: %r", value)
    return "skill"


def _is_safe_relative_path(value: str) -> bool:
    if not value:
        return False
    parts = value.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        return False
    return True


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_timeout(value: Any, default: int = 60) -> int:
    try:
        timeout = int(value)
    except Exception:
        return default
    return timeout if timeout > 0 else default


def _normalize_payload_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


@dataclass(slots=True)
class SkillScfClient:
    """技能包的 SCF 同步与执行客户端。

    配置来源（唯一权威入口）：`skill_exec` 能力域的沙箱运行时快照
    （`SandboxConfigService.resolve_runtime`）。`endpoint` / `timeout_seconds`
    为可选**显式覆盖**（测试或高级用法）；留空则每次使用前从配置中心解析，
    使长生命周期客户端也能跟上 admin 热切换。
    """

    endpoint: str = ""
    timeout_seconds: int = 0  # 0 = 从配置中心解析

    def __post_init__(self) -> None:
        self.endpoint = _normalize_text(self.endpoint)
        self.timeout_seconds = int(self.timeout_seconds or 0)

    @staticmethod
    def _runtime():
        return get_sandbox_runtime(CAPABILITY_SKILL_EXEC)

    def _build_handle(self) -> RemoteExecHandle | None:
        """解析远端执行句柄 —— **远端后端的唯一入口**（工厂/显式覆盖二选一）。

        显式 `endpoint`（测试/高级用法）优先；否则经 `build_sandbox_backend` 按
        `skill_exec` 运行时快照构造（工厂已保证 enabled 且 endpoint 非空；占位符
        endpoint 在 service 层已判为未启用）。返回 None = 该能力域当前无可用远端后端。
        """
        if self.endpoint:
            if is_placeholder_endpoint(self.endpoint):
                return None
            return HttpSandboxHandle(
                endpoint=self.endpoint,
                timeout_seconds=self._resolve_timeout(),
            )
        handle = build_sandbox_backend(self._runtime())
        return handle if isinstance(handle, RemoteExecHandle) else None

    def _resolve_timeout(self) -> int:
        if self.timeout_seconds:
            return _normalize_timeout(self.timeout_seconds, default=60)
        return _normalize_timeout(self._runtime().get_int("timeout_seconds", 60), default=60)

    @property
    def is_configured(self) -> bool:
        """可发起请求 = 能解析出 HTTP 传输句柄（endpoint 非空且非占位符、能力域已启用）。

        占位符 URL（如 https://your-scf-url.tencentscf.com）视为未配置，
        避免 sync_package/execute_skill 请求无效地址产生网络错误。
        """
        return self._build_handle() is not None

    def sync_package(self, payload: dict[str, Any]) -> dict[str, Any]:
        """同步/更新技能包到 SCF。"""
        if not self.is_configured:
            logger.warning("skill_exec 远端未配置，跳过技能包同步: %s", payload.get("source_key", ""))
            return {
                "skipped": True,
                "reason": "技能远端服务未配置（admin 沙箱配置 → skill_exec 选择 http_sandbox 或 tencent_scf 并填写配置）",
            }
        return self._post(self._build_sync_request_payload(payload))

    def execute_skill(self, payload: dict[str, Any]) -> Any:
        """调用 SCF 执行技能包工具。"""
        if not self.is_configured:
            raise FailException("技能远端服务未配置（admin 沙箱配置 → skill_exec 选择 http_sandbox 或 tencent_scf 并填写配置）")
        return self._post(self._build_execute_request_payload(payload))

    def _build_sync_request_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        skill_payload = payload.get("skill")
        if not isinstance(skill_payload, dict) or not skill_payload:
            skill_payload = payload

        source_key = _normalize_payload_text(skill_payload.get("source_key") or payload.get("source_key"))
        version = skill_payload.get("version") or payload.get("version")
        if isinstance(version, dict):
            version = version.get("version") or version.get("id")
        sync_payload = {
            "source_key": source_key,
            "version": version,
        }
        sync_code = textwrap.dedent(
            f"""
            def sync_package(payload):
                return {{
                    "synced": True,
                    "source_key": {source_key!r},
                    "version": {version!r},
                }}
            """
        ).strip()

        request_payload = dict(payload)
        request_payload["action"] = "sync_package"
        request_payload["code"] = sync_code
        request_payload["func_name"] = "sync_package"
        request_payload["args"] = [sync_payload]
        request_payload["kwargs"] = {}
        return request_payload

    def _build_execute_request_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = dict(payload)
        request_payload["action"] = "execute_skill"

        code = self._extract_skill_code(request_payload)
        if not code:
            raise FailException("技能云函数执行失败：缺少 skill.py 代码")

        func_name = _normalize_payload_text(
            request_payload.get("func_name") or request_payload.get("entrypoint") or request_payload.get("tool_name")
        )
        if not func_name:
            raise FailException("技能云函数执行失败：缺少入口函数")

        args = request_payload.get("args")
        if not isinstance(args, list):
            args = [request_payload.get("input") or {}]

        kwargs = request_payload.get("kwargs")
        if not isinstance(kwargs, dict):
            kwargs = {}

        request_payload["code"] = code
        request_payload["func_name"] = func_name
        request_payload["args"] = args
        request_payload["kwargs"] = kwargs

        # 透传技能包 env（已解密），由云函数侧注入 os.environ
        bundle = request_payload.get("bundle")
        if isinstance(bundle, dict):
            env_values = _decrypt_bundle_env(bundle)
            if env_values:
                request_payload["env"] = env_values
        return request_payload

    def _extract_skill_code(self, payload: dict[str, Any]) -> str:
        code = _normalize_payload_text(payload.get("code"))
        if code:
            return code

        bundle = payload.get("bundle")
        if isinstance(bundle, dict):
            code = _normalize_payload_text(bundle.get("skill.py"))
            if code:
                return code

        return ""

    def _post(self, payload: dict[str, Any]) -> Any:
        """经统一 HTTP 句柄发请求，并解释技能侧契约（`error` / `result`）。"""
        handle = self._build_handle()
        if handle is None:
            raise FailException("技能远端服务未配置（admin 沙箱配置 → skill_exec 选择 http_sandbox 或 tencent_scf 并填写配置）")

        try:
            # endpoint 校验、超时、状态码、非 JSON、网络异常统一由 HttpSandboxHandle 收敛
            response_data = handle.execute(payload)
        except FailException:
            raise
        except Exception as exc:
            raise FailException(f"技能云函数调用失败: {str(exc)}")

        if isinstance(response_data, dict) and "error" in response_data:
            error_message = str(response_data.get("error", ""))
            traceback = str(response_data.get("traceback", "")).strip()
            if traceback:
                raise FailException(f"云函数执行出错: {error_message}\n{traceback}")
            raise FailException(f"云函数执行出错: {error_message}")

        if isinstance(response_data, dict) and "result" in response_data:
            skill_payload = payload.get("skill") if isinstance(payload.get("skill"), dict) else {}
            logger.info(
                "技能工具 SCF success: execution_id=%s action=%s func_name=%s source_key=%s",
                payload.get("execution_id"),
                payload.get("action"),
                payload.get("func_name") or payload.get("entrypoint") or payload.get("tool_name"),
                payload.get("source_key") or payload.get("skill_id") or skill_payload.get("source_key"),
            )
            return response_data["result"]

        return response_data


def _decrypt_bundle_env(bundle: dict[str, Any]) -> dict[str, str]:
    """解密 bundle.__env__ 为真实 env 字典；失败/缺失返回空 dict。

    供 SkillScfClient / SkillSandboxExecutor 共用：技能包内 .env 的值在导入时
    已用 Fernet 加密存入 bundle 的 __env__ 键，执行前在此解密。
    """
    raw = bundle.get("__env__")
    if not raw:
        return {}
    try:
        encrypted_env = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("技能包 __env__ 解析失败，已忽略: %s", exc)
        return {}
    if not isinstance(encrypted_env, dict):
        return {}
    try:
        from internal.service.tool_credential_encryptor import decrypt_env

        real_env = decrypt_env(encrypted_env)
    except Exception as exc:
        logger.warning("技能包 __env__ 解密失败，已忽略: %s", exc)
        return {}
    return {str(k): str(v) for k, v in real_env.items() if isinstance(k, str) and k}


@dataclass(slots=True)
class SkillSandboxExecutor:
    """技能包的隔离沙箱执行器。

    当 SCF 执行失败时，使用沙箱在隔离环境中执行入口函数。
    后端与凭证由 `skill_exec` 能力域的沙箱运行时快照决定（admin 可配、热切换）：
    仅当该能力域激活 `baidu_cfc` 时才走远端沙箱。

    **安全（S5）**：本地兜底执行默认**关闭**；仅当该能力域配置显式开启
    `allow_local_exec` 时才可用。开启后也**不再在 API 进程内 exec**，而是：
    独立临时工作目录 + 独立进程组 + 子进程内 setrlimit（CPU/内存/文件/进程/句柄）
    + 超时整组强杀 + 最小化子进程 env（不继承父进程密钥，技能包 env 只注入子进程）。
    """

    timeout_seconds: int = 0  # 0 = 从配置中心解析
    sandbox_timeout: int = 0  # 0 = 从配置中心解析

    @staticmethod
    def _runtime():
        return get_sandbox_runtime(CAPABILITY_SKILL_EXEC)

    @property
    def is_configured(self) -> bool:
        runtime = self._runtime()
        return runtime.enabled and runtime.backend in E2B_PROTOCOL_BACKENDS

    def _resolve_timeouts(self, runtime) -> int:
        """解析单次执行超时：显式覆盖优先，否则取配置中心。"""
        if self.timeout_seconds:
            return _normalize_timeout(self.timeout_seconds, default=60)
        return _normalize_timeout(runtime.get_int("timeout_seconds", 60), default=60)

    def execute_skill(self, payload: dict[str, Any]) -> Any:
        runtime = self._runtime()
        if not (runtime.enabled and runtime.backend in E2B_PROTOCOL_BACKENDS):
            if runtime.get_bool("allow_local_exec", False):
                return self._execute_skill_locally(payload)
            raise FailException(
                "技能沙箱不可用：请在 admin 沙箱配置中为 skill_exec 启用后端"
                "（http_sandbox / tencent_scf / baidu_cfc / aliyun_sandbox）；"
                "如需本地兜底执行请显式开启 allow_local_exec"
            )

        bundle = payload.get("bundle")
        if not isinstance(bundle, dict) or not bundle:
            raise FailException("技能沙箱执行失败：缺少 bundle 内容")

        entrypoint = _normalize_payload_text(payload.get("entrypoint") or payload.get("tool_name"))
        if not entrypoint:
            raise FailException("技能沙箱执行失败：缺少入口函数")

        source_key = _sanitize_source_key(
            _normalize_payload_text(payload.get("source_key") or "skill")
        )
        workspace_dir = f"/tmp/skill_runtime/{source_key}"

        files_to_upload: list[tuple[str, bytes]] = []
        for relative_path, content in bundle.items():
            normalized_path = str(relative_path or "").strip().lstrip("/")
            if not normalized_path or not _is_safe_relative_path(normalized_path):
                logger.warning("技能 bundle 跳过越界相对路径: %r", relative_path)
                continue
            files_to_upload.append((f"{workspace_dir}/{normalized_path}", str(content).encode("utf-8")))

        runner_script = self._build_runner_script()
        input_payload = {
            "tool_name": payload.get("tool_name"),
            "entrypoint": entrypoint,
            "input": payload.get("input") or {},
            # 服务端解密技能包 env，随 input 传入远程沙箱，由 runner 注入
            "env": _decrypt_bundle_env(bundle),
        }
        files_to_upload.append((f"{workspace_dir}/_skill_runner.py", runner_script.encode("utf-8")))
        files_to_upload.append((f"{workspace_dir}/_skill_input.json", _coerce_json_text(input_payload).encode("utf-8")))

        backend = build_sandbox_backend(runtime)
        if backend is None:
            raise FailException(
                f"技能沙箱后端不可用：backend={runtime.backend} reason={runtime.reason}"
            )
        execute_timeout = self._resolve_timeouts(runtime)

        try:
            with backend as sandbox:
                quoted_workspace_dir = shlex.quote(workspace_dir)
                sandbox.execute(f"mkdir -p {quoted_workspace_dir}")
                upload_results = sandbox.upload_files(files_to_upload)
                failed_uploads = [item for item in upload_results if getattr(item, "error", None)]
                if failed_uploads:
                    raise FailException(
                        "技能沙箱执行失败：文件上传失败 "
                        + ", ".join(f"{item.path}: {item.error}" for item in failed_uploads)
                    )

                execution = sandbox.execute(
                    f"cd {quoted_workspace_dir} && python3 _skill_runner.py || python _skill_runner.py",
                    timeout=execute_timeout,
                )
                result = self._parse_runner_output(execution.output)
                if not result.get("ok", False):
                    error_message = _normalize_payload_text(result.get("error")) or "沙箱执行失败"
                    traceback_text = _normalize_payload_text(result.get("traceback"))
                    if traceback_text:
                        raise FailException(f"{error_message}\n{traceback_text}")
                    raise FailException(error_message)

                if result.get("stderr"):
                    logger.info("技能沙箱 stderr: %s", result.get("stderr"))
                logger.info(
                    "技能工具 sandbox remote success: execution_id=%s entrypoint=%s source_key=%s sandbox_id=%s",
                    payload.get("execution_id"),
                    entrypoint,
                    source_key,
                    sandbox.id,
                )
                return result.get("result")
        except FailException:
            raise
        except Exception:
            if runtime.get_bool("allow_local_exec", False):
                return self._execute_skill_locally(payload)
            raise

    def _execute_skill_locally(self, payload: dict[str, Any]) -> Any:
        """在受限子进程中执行 skill.py（S5：不再在 API 进程内 exec_module）。

        - 独立临时工作目录（退出即清理）
        - 子进程内 setrlimit（CPU / 内存 / 文件大小 / 进程数 / 句柄）
        - 技能包 env 经 Popen(env=...) 只注入子进程，父进程 os.environ 不被修改
        - 超时即整组强杀（start_new_session + killpg）
        """
        bundle = payload.get("bundle")
        if not isinstance(bundle, dict) or not bundle:
            raise FailException("技能本地执行失败：缺少 bundle 内容")

        entrypoint = _normalize_payload_text(payload.get("entrypoint") or payload.get("tool_name"))
        if not entrypoint:
            raise FailException("技能本地执行失败：缺少入口函数")
        source_key = _normalize_payload_text(payload.get("source_key") or "skill")

        with tempfile.TemporaryDirectory(prefix="skill_local_") as tmp_dir:
            base_dir = Path(tmp_dir)
            for relative_path, content in bundle.items():
                normalized_path = str(relative_path or "").strip().lstrip("/")
                if not normalized_path or not _is_safe_relative_path(normalized_path):
                    logger.warning("技能 bundle 跳过越界相对路径: %r", relative_path)
                    continue
                file_path = base_dir / normalized_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(str(content), encoding="utf-8")

            if not (base_dir / "skill.py").exists():
                raise FailException("技能本地执行失败：bundle 中缺少 skill.py")

            # 技能包 env 只注入子进程（不落盘、不写父进程 os.environ）
            child_env = self._build_child_env(_decrypt_bundle_env(bundle), home=tmp_dir)
            input_payload = {
                "tool_name": payload.get("tool_name"),
                "entrypoint": entrypoint,
                "input": payload.get("input") or {},
                # 本地路径不经 payload 传 env（改由 Popen env 注入），避免密钥落盘
                "env": {},
                "limits": self._child_limits(),
            }
            (base_dir / "_skill_runner.py").write_text(self._build_runner_script(), encoding="utf-8")
            (base_dir / "_skill_input.json").write_text(_coerce_json_text(input_payload), encoding="utf-8")

            stdout, stderr, exit_code = self._run_isolated_subprocess(base_dir, child_env)
            if stderr.strip():
                logger.info("技能本地执行 stderr: %s", stderr.strip())

            result = self._parse_runner_output(stdout)
            if not result.get("ok", False):
                error_message = _normalize_payload_text(result.get("error")) or "本地执行失败"
                traceback_text = _normalize_payload_text(result.get("traceback"))
                if traceback_text:
                    raise FailException(f"{error_message}\n{traceback_text}")
                raise FailException(error_message)

            logger.info(
                "技能工具 sandbox local-subprocess success: execution_id=%s entrypoint=%s source_key=%s exit_code=%s",
                payload.get("execution_id"),
                entrypoint,
                source_key,
                exit_code,
            )
            return result.get("result")

    @staticmethod
    def _child_limits() -> dict[str, int]:
        """子进程资源上限（由 runner 在子进程内 best-effort setrlimit）。"""
        return {
            "cpu_seconds": _LOCAL_EXEC_CPU_SECONDS,
            "address_space_bytes": _LOCAL_EXEC_MEMORY_BYTES,
            "file_size_bytes": _LOCAL_EXEC_FILE_SIZE_BYTES,
            "max_processes": _LOCAL_EXEC_MAX_PROCESSES,
            "max_open_files": _LOCAL_EXEC_MAX_OPEN_FILES,
        }

    @staticmethod
    def _build_child_env(skill_env: dict[str, str], *, home: str) -> dict[str, str]:
        """构造最小子进程环境：父进程白名单变量 + 技能包 env。

        刻意**不继承父进程完整 env**，避免把 API 的密钥/连接串泄漏给第三方技能代码；
        HOME/TMPDIR 指向独立临时目录，避免读写宿主个人目录。
        """
        child_env: dict[str, str] = {}
        for key in _LOCAL_EXEC_ENV_ALLOWLIST:
            value = os.environ.get(key)
            if value:
                child_env[key] = value
        child_env.setdefault("PATH", "/usr/local/bin:/usr/local/sbin:/usr/bin:/bin")
        child_env.setdefault("LANG", "C.UTF-8")
        child_env.update(
            {
                "HOME": home,
                "TMPDIR": home,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            }
        )
        for key, value in (skill_env or {}).items():
            child_env[str(key)] = str(value)
        return child_env

    def _run_isolated_subprocess(
        self, work_dir: Path, child_env: dict[str, str]
    ) -> tuple[str, str, int]:
        """在独立进程组内运行 runner，返回 (stdout, stderr, exit_code)；超时整组强杀。"""
        command = [sys.executable or "python3", str(work_dir / "_skill_runner.py")]
        timeout = _normalize_timeout(self._resolve_timeouts(self._runtime()), default=60)
        process = subprocess.Popen(
            command,
            cwd=str(work_dir),
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._terminate_process_group(process)
            raise FailException(f"技能本地执行超时（>{timeout}s），已终止子进程")
        return stdout or "", stderr or "", process.returncode or 0

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen) -> None:
        """强杀整个子进程组（含其 fork 出的后代），并回收。

        Windows 没有 killpg/getpgid（此前超时分支会在此抛 AttributeError，
        导致子进程与临时目录泄漏），改用 taskkill /T 终止整棵进程树。
        """
        if os.name == "nt":
            with contextlib.suppress(Exception):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    check=False,
                )
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        with contextlib.suppress(Exception):
            process.kill()
        with contextlib.suppress(Exception):
            process.wait(timeout=5)

    def _build_runner_script(self) -> str:
        return textwrap.dedent(
            """
            from __future__ import annotations

            import contextlib
            import importlib.util
            import io
            import json
            import os
            import pathlib
            import traceback

            MARKER = "__SKILL_RESULT__"

            def _apply_limits(limits: dict) -> None:
                \"\"\"在子进程内设置资源上限（best-effort；平台不支持或越权则忽略）。\"\"\"
                if not isinstance(limits, dict):
                    return
                try:
                    import resource
                except Exception:
                    return

                def _set(resource_id, value) -> None:
                    if resource_id is None or not value:
                        return
                    try:
                        _soft, hard = resource.getrlimit(resource_id)
                        new_hard = value if hard == resource.RLIM_INFINITY else max(value, hard)
                        resource.setrlimit(resource_id, (value, new_hard))
                    except Exception:
                        try:
                            resource.setrlimit(resource_id, (value, value))
                        except Exception:
                            pass

                _set(getattr(resource, "RLIMIT_CPU", None), int(limits.get("cpu_seconds") or 0))
                _set(getattr(resource, "RLIMIT_AS", None), int(limits.get("address_space_bytes") or 0))
                _set(getattr(resource, "RLIMIT_FSIZE", None), int(limits.get("file_size_bytes") or 0))
                _set(getattr(resource, "RLIMIT_NPROC", None), int(limits.get("max_processes") or 0))
                _set(getattr(resource, "RLIMIT_NOFILE", None), int(limits.get("max_open_files") or 0))
                _set(getattr(resource, "RLIMIT_CORE", None), 1)

            def main() -> None:
                base_dir = pathlib.Path(__file__).resolve().parent
                with (base_dir / "_skill_input.json").open("r", encoding="utf-8") as f:
                    payload = json.load(f)

                # 资源上限（best-effort；本地兜底执行时由服务端注入）
                _apply_limits(payload.get("limits") or {})

                # 注入技能包 env（服务端已解密）
                env_values = payload.get("env") or {}
                if isinstance(env_values, dict):
                    for env_key, env_value in env_values.items():
                        os.environ[str(env_key)] = str(env_value)

                module_path = base_dir / "skill.py"
                if not module_path.exists():
                    raise FileNotFoundError(f"skill.py not found: {module_path}")

                spec = importlib.util.spec_from_file_location("skill_module", module_path)
                if spec is None or spec.loader is None:
                    raise RuntimeError("无法加载 skill.py 模块")

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                entrypoint = str(payload.get("entrypoint") or "").strip()
                func = getattr(module, entrypoint, None)
                if not callable(func):
                    raise RuntimeError(f"Function {entrypoint!r} not found or not callable")

                call_input = payload.get("input") or {}
                stdout_buffer = io.StringIO()
                stderr_buffer = io.StringIO()
                with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                    result = func(call_input)

                print(
                    MARKER
                    + json.dumps(
                        {
                            "ok": True,
                            "result": result,
                            "stdout": stdout_buffer.getvalue(),
                            "stderr": stderr_buffer.getvalue(),
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )

            if __name__ == "__main__":
                try:
                    main()
                except Exception as exc:
                    print(
                        MARKER
                        + json.dumps(
                            {
                                "ok": False,
                                "error": str(exc),
                                "traceback": traceback.format_exc(),
                            },
                            ensure_ascii=False,
                            default=str,
                        )
                    )
            """
        ).strip()

    def _parse_runner_output(self, output: str | None) -> dict[str, Any]:
        text = _normalize_payload_text(output)
        if not text:
            raise FailException("技能沙箱执行失败：没有返回结果")

        marker = "__SKILL_RESULT__"
        for line in reversed(text.splitlines()):
            stripped = line.strip()
            if not stripped.startswith(marker):
                continue
            try:
                parsed = json.loads(stripped[len(marker) :])
            except Exception as exc:
                raise FailException(f"技能沙箱执行失败：结果解析失败 {exc}") from exc
            if isinstance(parsed, dict):
                return parsed
            raise FailException("技能沙箱执行失败：结果格式非法")

        raise FailException(f"技能沙箱执行失败：未找到结果标记，原始输出: {text}")


@dataclass(slots=True)
class SkillExecutor:
    """技能执行的**单一入口**：按 `skill_exec` 当前 active 后端选择执行协议。

    为什么是两个实现类而不是一个：技能有**两种语义不同的执行协议**——
    - `SkillScfClient`（HTTP 函数调用）：把代码 + 入参塞进一次请求；远端无文件系统。
    - `SkillSandboxExecutor`（E2B 机器）：先铺文件再跑 shell 脚本；远端有文件系统。
    强行合并会造出远端并不支持的假契约（HTTP 没有 upload_files 等语义）。

    但这个「用哪个协议」的**决策必须在唯一一处**。此前它藏在 `SkillToolFactory`
    的 try/except 里（先试 SCF、失败再兜 E2B），带来两个实际问题：
    1. active 为 `baidu_cfc` 时，第一次调用**必然**抛错并被吞 → 每次执行都刷一条
       `WARNING 技能工具 SCF 执行失败，尝试沙箱回退`（伪警告，纯噪音）；
    2. 两条链路都失败时，用户只看到兜底错误，**原始错误被替换**（诊断信息丢失）。
    故改为显式按后端分发；新增第三种协议时只需在 `execute_skill` 加一个分支。
    """

    scf_client: SkillScfClient = field(default_factory=SkillScfClient)
    sandbox_executor: SkillSandboxExecutor = field(default_factory=SkillSandboxExecutor)

    @staticmethod
    def _runtime():
        return get_sandbox_runtime(CAPABILITY_SKILL_EXEC)

    def execute_skill(self, payload: dict[str, Any]) -> Any:
        """按 active 后端分发执行（不依赖「先试 A 再兜 B」的异常控制流）。"""
        backend = self._runtime().backend
        if backend in (BACKEND_HTTP_SANDBOX, BACKEND_TENCENT_SCF):
            # 两种后端对 SCF 客户端是同一契约（execute(payload) -> JSON），
            # 传输差异（HTTP POST / SDK 直调）收敛在句柄内部
            return self.scf_client.execute_skill(payload)
        # baidu_cfc → 真 E2B 执行；disabled → 由沙箱执行器统一走
        # 「未开通」或 `allow_local_exec` 分支（如实报错，不静默降级）
        return self.sandbox_executor.execute_skill(payload)

