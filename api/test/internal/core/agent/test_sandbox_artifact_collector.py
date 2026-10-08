"""沙箱产物收集模块：扫描 / 下载 / 入库的共享机制。

深思考与 execute_code 共用本模块；此处只测机制本身
（扫描解析、标记过滤、逐文件入库、失败与上限），编排归属各消费方。
"""
from types import SimpleNamespace

from internal.core.agent.entities.sandbox_policy_entity import SandboxPolicy
from internal.core.agent.sandbox_artifact_collector import (
    ArtifactPersistResult,
    extract_artifact_paths,
    prepare_artifact_markers,
    scan_artifacts,
)
from internal.core.agent import sandbox_artifact_collector as collector


class _ScanBackend:
    """按命令类型返回响应的假后端：标记 / 扫描 / 其他。"""

    def __init__(self, *, marker_output="", scan_output="", scan_exit_code=0, scan_error=""):
        self.commands: list[str] = []
        self._marker_output = marker_output
        self._scan_output = scan_output
        self._scan_exit_code = scan_exit_code
        self._scan_error = scan_error

    def execute(self, command, timeout=None):
        self.commands.append(command)
        if " -type f" in command:
            return SimpleNamespace(exit_code=self._scan_exit_code, output=self._scan_output)
        if "yujianwo_artifact_marker" in command:
            return SimpleNamespace(exit_code=0, output=self._marker_output)
        return SimpleNamespace(exit_code=0, output="")


def test_extract_artifact_paths_skips_stderr_and_blank_lines():
    output = "\n[stderr] find: warning\n/workspace/artifacts/t/report.docx\n  \n"

    assert extract_artifact_paths(output) == ["/workspace/artifacts/t/report.docx"]


def test_prepare_artifact_markers_returns_root_to_marker_map():
    backend = _ScanBackend(
        marker_output="/home/user/artifacts/.yujianwo_artifact_marker_artifacts\n"
    )

    marked = prepare_artifact_markers(
        backend, roots=["/home/user/artifacts"], marker_name=".yujianwo_artifact_marker_artifacts"
    )

    assert marked == {
        "/home/user/artifacts": "/home/user/artifacts/.yujianwo_artifact_marker_artifacts"
    }


def test_scan_artifacts_only_scans_marked_roots_and_filters_by_marker():
    backend = _ScanBackend(scan_output="/home/user/artifacts/new.csv\n")
    marker = {"path": "/home/user/artifacts/.yujianwo_artifact_marker_artifacts"}
    marker_paths_by_root = {"/home/user/artifacts": marker["path"]}

    result = scan_artifacts(
        backend,
        roots=["/home/user/artifacts", "/mnt/data"],
        marker_paths_by_root=marker_paths_by_root,
        max_depth=1,
    )

    assert result.paths == ["/home/user/artifacts/new.csv"]
    command = backend.commands[0]
    assert "/home/user/artifacts" in command
    assert "/mnt/data" not in command  # 未打标记的目录不扫（避免误收旧文件）
    assert "-newer" in command
    assert "-maxdepth 1" in command


def test_scan_artifacts_reports_failure_separately_from_empty_result():
    backend = _ScanBackend(scan_exit_code=1, scan_output="[stderr] find: no such dir")

    result = scan_artifacts(backend, roots=["/workspace/artifacts/t"])

    assert result.failed is True
    assert result.paths == []
    assert "no such dir" in result.error


def test_scan_artifacts_skips_execution_when_no_root_is_marked():
    backend = _ScanBackend()

    result = scan_artifacts(
        backend, roots=["/home/user/artifacts"], marker_paths_by_root={"/other": "/x"}
    )

    assert result.paths == []
    assert backend.commands == []


def _response(path, *, content=b"data", error=None):
    return SimpleNamespace(path=path, content=content, error=error)


class _DownloadBackend:
    def __init__(self, responses):
        self._responses = responses
        self.requested: list[list[str]] = []

    def download_files(self, paths):
        self.requested.append(list(paths))
        return self._responses


def _patch_file_center(monkeypatch, *, saved=None, fail_names=()):
    """替换文件中心：返回固定的入库结果，指定文件名抛错。"""
    calls: list[dict] = []

    def _save_generated_asset(account_id, *, filename, content, mime_type="", folder=""):
        calls.append({
            "account_id": account_id,
            "filename": filename,
            "content": content,
            "mime_type": mime_type,
            "folder": folder,
        })
        if filename in fail_names:
            raise RuntimeError("存储不可用")
        return saved or {
            "upload_file": SimpleNamespace(
                id="file-1", name=filename, size=len(content), extension="csv",
                mime_type=mime_type,
            ),
            "url": f"https://cdn.example.com/{filename}",
        }

    service = SimpleNamespace(save_generated_asset=_save_generated_asset)
    monkeypatch.setattr(
        "app.http.module.injector", SimpleNamespace(get=lambda _cls: service)
    )
    return calls


def test_download_and_persist_artifacts_downloads_one_file_at_a_time(monkeypatch):
    calls = _patch_file_center(monkeypatch)
    backend = _DownloadBackend([_response("/mnt/data/a.csv")])

    result = collector.download_and_persist_artifacts(
        backend, account_id="acc-1", paths=["/mnt/data/a.csv"], folder="artifacts"
    )

    assert len(result.artifacts) == 1
    assert result.artifacts[0]["name"] == "a.csv"
    assert result.artifacts[0]["url"] == "https://cdn.example.com/a.csv"
    assert result.artifacts[0]["path"] == "/mnt/data/a.csv"
    assert result.failures == []
    # 逐个下载：单次只请求一个路径，避免大文件批量撑爆内存
    assert backend.requested == [["/mnt/data/a.csv"]]
    assert calls[0]["account_id"] == "acc-1"
    assert calls[0]["folder"] == "artifacts"


def test_download_and_persist_artifacts_records_download_and_upload_failures(monkeypatch):
    _patch_file_center(monkeypatch, fail_names={"bad.csv"})
    backend = _DownloadBackend([_response("/mnt/data/missing.csv", content=None, error="not found")])

    result = collector.download_and_persist_artifacts(
        backend, account_id="acc-1", paths=["/mnt/data/missing.csv"]
    )
    assert result.artifacts == []
    assert result.failures == [("/mnt/data/missing.csv", "not found")]

    backend = _DownloadBackend([_response("/mnt/data/bad.csv")])
    result = collector.download_and_persist_artifacts(
        backend, account_id="acc-1", paths=["/mnt/data/bad.csv"]
    )
    assert result.artifacts == []
    assert result.failures[0][0] == "/mnt/data/bad.csv"
    assert "存储不可用" in result.failures[0][1]


def test_download_and_persist_artifacts_requires_account(monkeypatch):
    _patch_file_center(monkeypatch)
    backend = _DownloadBackend([_response("/mnt/data/a.csv")])

    result = collector.download_and_persist_artifacts(
        backend, account_id="", paths=["/mnt/data/a.csv"]
    )

    assert isinstance(result, ArtifactPersistResult)
    assert result.artifacts == []
    assert result.failures == [("/mnt/data/a.csv", "缺少账号上下文，无法入库")]
    assert backend.requested == []


def test_download_and_persist_artifacts_skips_oversized_and_excess_files(monkeypatch):
    _patch_file_center(monkeypatch)
    backend = _DownloadBackend([_response("/mnt/data/big.bin", content=b"x" * 32)])

    result = collector.download_and_persist_artifacts(
        backend,
        account_id="acc-1",
        paths=["/mnt/data/big.bin"],
        max_file_bytes=16,
    )
    assert result.artifacts == []
    assert "上限" in result.failures[0][1]

    result = collector.download_and_persist_artifacts(
        _DownloadBackend([_response("/mnt/data/a.csv")]),
        account_id="acc-1",
        paths=["/mnt/data/a.csv", "/mnt/data/b.csv"],
        max_files=1,
    )
    assert [artifact["path"] for artifact in result.artifacts] == ["/mnt/data/a.csv"]
    assert result.failures == [("/mnt/data/b.csv", "超过单次 1 个产物上限，未入库")]


def test_resolve_artifact_root_probes_writable_base_dir():
    class _ProbeBackend:
        def execute(self, command, timeout=None):
            assert "artifacts/task-1" in command
            return SimpleNamespace(exit_code=0, output="/home/user/artifacts/task-1")

    removed = collector.resolve_artifact_root(_ProbeBackend(), task_id="task-1")
    assert removed == "/home/user/artifacts/task-1"


def test_resolve_artifact_root_falls_back_to_default_when_probe_fails():
    class _ProbeBackend:
        def execute(self, command, timeout=None):
            return SimpleNamespace(exit_code=1, output="[stderr] read-only")

    root = collector.resolve_artifact_root(_ProbeBackend(), task_id="task-1")

    assert root == SandboxPolicy.build_default_artifact_root("task-1")


def test_build_find_command_marks_and_filters_marker_files():
    command = SandboxPolicy.build_find_command(
        ["/mnt/data"],
        marker_paths_by_root={"/mnt/data": "/mnt/data/.yujianwo_artifact_marker_artifacts"},
    )

    assert "find /mnt/data -type f -newer /mnt/data/.yujianwo_artifact_marker_artifacts" in command
    assert "! -name '.yujianwo_artifact_marker_*'" in command
    assert command.endswith("| sort -u")


def test_prepare_artifact_markers_ignores_unwritable_roots():
    class _PartiallyWritableBackend:
        def execute(self, command, timeout=None):
            # 只有第二个根目录创建成功
            return SimpleNamespace(
                exit_code=0, output="/tmp/artifacts/.yujianwo_artifact_marker_artifacts\n"
            )

    marked = prepare_artifact_markers(
        _PartiallyWritableBackend(),
        roots=["/workspace/artifacts", "/tmp/artifacts"],
        marker_name=".yujianwo_artifact_marker_artifacts",
    )

    assert marked == {"/tmp/artifacts": "/tmp/artifacts/.yujianwo_artifact_marker_artifacts"}


def test_persist_sandbox_file_guesses_mime_type_from_extension(monkeypatch):
    calls = _patch_file_center(monkeypatch)

    collector.persist_sandbox_file(
        account_id="acc-1", path="/mnt/data/out.zip", content=b"zip"
    )

    assert calls[0]["filename"] == "out.zip"
    assert calls[0]["mime_type"] == "application/zip"
