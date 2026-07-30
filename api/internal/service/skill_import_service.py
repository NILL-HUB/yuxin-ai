from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import requests
import yaml
from injector import inject

from internal.exception import FailException, NotFoundException, ValidateErrorException
from internal.model import SkillPackage
from pkg.sqlalchemy import SQLAlchemy

from .base_service import BaseService
from .skill_service import SkillService

logger = logging.getLogger(__name__)


_VALID_EXECUTOR_TYPES = {"scf", "prompt"}
_SAFE_SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?(?:/.*)?(?:\?.*)?$",
    re.IGNORECASE,
)
_GITHUB_RAW_RE = re.compile(
    r"^https?://raw\.githubusercontent\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<branch>[^/]+)/(?P<path>.+)$",
    re.IGNORECASE,
)
_DEFAULT_BRANCHES = ("main", "master")
_HTTP_TIMEOUT_SECONDS = 30


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return bool(value)


@inject
@dataclass
class SkillImportService(BaseService):
    """技能包导入服务，支持 zip 包、GitHub URL、JSON 文本三种导入方式。"""

    db: SQLAlchemy
    skill_service: SkillService

    # ------------------------------------------------------------------ #
    #  公共入口                                                             #
    # ------------------------------------------------------------------ #

    def import_from_zip(
        self,
        file_bytes: bytes,
        account_id: UUID | None = None,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """从 zip 包导入技能包。

        zip 内部结构：
            manifest.yaml    # 必需
            skill.py         # scf 类型必需
            skill.md         # 可选
            icon.svg         # 可选（仅以文本形式存入 bundle）
        """
        if not file_bytes:
            raise ValidateErrorException("zip 文件内容为空")

        try:
            buffer = io.BytesIO(file_bytes)
            with zipfile.ZipFile(buffer, "r") as zf:
                # 安全校验：防止 path traversal
                self._validate_zip_members(zf)
                manifest_text = self._read_zip_member(zf, "manifest.yaml", required=True)
                skill_code = self._read_zip_member(zf, "skill.py", required=False) or ""
                readme = self._read_zip_member(zf, "skill.md", required=False) or ""
        except zipfile.BadZipFile as exc:
            raise ValidateErrorException(f"zip 文件格式无效: {exc}") from exc

        manifest = self._parse_manifest(manifest_text)
        self._validate_manifest(manifest, skill_code=skill_code)

        payload = self._build_payload_from_manifest(
            manifest,
            skill_code=skill_code,
            readme=readme,
        )
        return self._do_import(payload, overwrite=overwrite)

    def import_from_github_url(self, github_url: str, *, overwrite: bool = False) -> dict[str, Any]:
        """从 GitHub URL 导入技能包。

        支持以下 URL 形式：
            - 仓库根 URL: https://github.com/owner/repo
            - 仓库 + 分支: https://github.com/owner/repo/tree/branch
            - raw 文件 URL: https://raw.githubusercontent.com/owner/repo/branch/manifest.yaml
        拉取仓库根目录的 manifest.yaml（以及 scf 类型的 skill.py）。
        """
        normalized_url = _normalize_text(github_url)
        if not normalized_url:
            raise ValidateErrorException("github_url 不能为空")

        manifest_url, skill_url = self._resolve_github_urls(normalized_url)
        if not manifest_url:
            raise ValidateErrorException(
                f"无法从 GitHub URL 解析 manifest.yaml 地址: {normalized_url}"
            )

        manifest_text = self._fetch_text(manifest_url, label="manifest.yaml")
        if not manifest_text:
            raise FailException("manifest.yaml 内容为空")

        manifest = self._parse_manifest(manifest_text)
        # scf 类型需要 skill.py
        skill_code = ""
        if _normalize_text(manifest.get("executor_type")).lower() == "scf":
            if skill_url:
                try:
                    skill_code = self._fetch_text(skill_url, label="skill.py") or ""
                except NotFoundException:
                    skill_code = ""
            if not skill_code:
                raise ValidateErrorException("scf 类型技能包缺少 skill.py")

        self._validate_manifest(manifest, skill_code=skill_code)

        payload = self._build_payload_from_manifest(
            manifest,
            skill_code=skill_code,
            readme="",
        )
        return self._do_import(payload, overwrite=overwrite)

    def import_from_json(self, json_str: str, *, overwrite: bool = False) -> dict[str, Any]:
        """从 JSON 文本导入技能包（支持 prompt 类型，无需 skill.py）。"""
        normalized = _normalize_text(json_str)
        if not normalized:
            raise ValidateErrorException("config_json 不能为空")

        try:
            data = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ValidateErrorException(f"JSON 解析失败: {exc}") from exc

        if not isinstance(data, dict):
            raise ValidateErrorException("JSON 顶层必须是对象")

        manifest = data
        skill_code = _normalize_text(data.get("skill_code"))
        readme = _normalize_text(data.get("readme"))
        self._validate_manifest(manifest, skill_code=skill_code)

        payload = self._build_payload_from_manifest(
            manifest,
            skill_code=skill_code,
            readme=readme,
        )
        return self._do_import(payload, overwrite=overwrite)

    # ------------------------------------------------------------------ #
    #  内部辅助                                                             #
    # ------------------------------------------------------------------ #

    def _do_import(self, payload: dict[str, Any], *, overwrite: bool) -> dict[str, Any]:
        """执行实际导入：处理 overwrite 与调用 skill_service 创建记录。"""
        source_key = _normalize_text(payload.get("source_key"))
        if not source_key:
            raise ValidateErrorException("source_key 不能为空")

        existing = self._find_existing_package(source_key)
        if existing:
            if not overwrite:
                raise ValidateErrorException(
                    f"source_key 已存在: {source_key}（如需覆盖请设置 overwrite=true）"
                )
            # 覆盖：先删除已有记录（含版本），失败则抛出原始异常
            self.skill_service.delete_skill_package_for_admin(existing.id)

        result = self.skill_service.create_skill_package_for_admin(payload)
        return {"imported": [result], "failed": []}

    def _find_existing_package(self, source_key: str) -> SkillPackage | None:
        try:
            return (
                self.db.session.query(SkillPackage)
                .filter(SkillPackage.source_key == source_key)
                .one_or_none()
            )
        except Exception:
            return None

    def _validate_zip_members(self, zf: zipfile.ZipFile) -> None:
        """校验 zip 成员路径，防止 path traversal。"""
        for member in zf.namelist():
            normalized = member.replace("\\", "/")
            if normalized.startswith("/"):
                raise ValidateErrorException(f"zip 包含绝对路径，已拒绝: {member}")
            parts = [p for p in normalized.split("/") if p not in ("", ".")]
            if any(part == ".." for part in parts):
                raise ValidateErrorException(f"zip 包含非法路径，已拒绝: {member}")

    def _read_zip_member(self, zf: zipfile.ZipFile, member_name: str, *, required: bool) -> str:
        """从 zip 中按文件名（顶级）读取文本成员。"""
        target = member_name
        for member in zf.namelist():
            normalized = member.replace("\\", "/").lstrip("./")
            if normalized == target or normalized.endswith("/" + target):
                try:
                    with zf.open(member, "r") as f:
                        return f.read().decode("utf-8", errors="replace")
                except (KeyError, OSError) as exc:
                    if required:
                        raise ValidateErrorException(f"读取 zip 内 {member_name} 失败: {exc}") from exc
                    return ""
        if required:
            raise ValidateErrorException(f"zip 包内缺少必需文件: {member_name}")
        return ""

    def _parse_manifest(self, manifest_text: str) -> dict[str, Any]:
        """用 PyYAML safe_load 解析 manifest.yaml。"""
        try:
            manifest = yaml.safe_load(manifest_text) or {}
        except yaml.YAMLError as exc:
            raise ValidateErrorException(f"manifest.yaml 解析失败: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValidateErrorException("manifest.yaml 顶层必须是对象")
        return manifest

    def _validate_manifest(self, manifest: dict[str, Any], *, skill_code: str) -> None:
        """校验 manifest 必需字段与一致性。"""
        source_key = _normalize_text(manifest.get("source_key"))
        if not source_key:
            raise ValidateErrorException("manifest 中 source_key 不能为空")
        if not _SAFE_SOURCE_KEY_RE.match(source_key):
            raise ValidateErrorException(
                "source_key 必须使用 ASCII 格式(仅支持字母、数字、下划线和连字符)"
            )

        description = _normalize_text(manifest.get("description"))
        if not description:
            # description 非强制，但建议存在；保留为空字符串即可
            manifest["description"] = ""

        executor_type = _normalize_text(manifest.get("executor_type") or "prompt").lower() or "prompt"
        if executor_type not in _VALID_EXECUTOR_TYPES:
            raise ValidateErrorException(
                f"executor_type 必须为 {sorted(_VALID_EXECUTOR_TYPES)} 之一"
            )
        manifest["executor_type"] = executor_type

        if executor_type == "scf" and not _normalize_text(skill_code):
            raise ValidateErrorException("scf 类型技能包必须提供 skill.py / skill_code")

        # 校验 tools（如果提供）
        tools = manifest.get("tools")
        if tools is not None and not isinstance(tools, list):
            raise ValidateErrorException("manifest 中 tools 必须是列表")

        # scf 类型 skill.py 语法校验
        if executor_type == "scf" and _normalize_text(skill_code):
            self._validate_python_syntax(skill_code, source_key=source_key)

    @staticmethod
    def _validate_python_syntax(skill_code: str, *, source_key: str) -> None:
        """校验 skill.py 语法，避免运行时 SyntaxError。"""
        try:
            compile(skill_code, f"<skill:{source_key}>/skill.py", "exec")
        except SyntaxError as exc:
            raise ValidateErrorException(
                f"skill.py 语法错误 (line {exc.lineno}): {exc.msg}"
            ) from exc

    def _build_payload_from_manifest(
        self,
        manifest: dict[str, Any],
        *,
        skill_code: str,
        readme: str,
    ) -> dict[str, Any]:
        """从 manifest 构造 create_skill_package_for_admin 所需 payload。"""
        source_key = _normalize_text(manifest.get("source_key"))
        name = _normalize_text(manifest.get("name") or source_key)
        executor_type = _normalize_text(manifest.get("executor_type") or "prompt").lower() or "prompt"

        tools_raw = []
        if executor_type == "scf" and isinstance(manifest.get("tools"), list):
            tools_raw = manifest.get("tools") or []

        tags_raw = manifest.get("tags") or []
        if not isinstance(tags_raw, list):
            tags_raw = []
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]

        capabilities = manifest.get("capabilities")
        if not isinstance(capabilities, dict):
            capabilities = {}

        task_keywords_raw = manifest.get("task_keywords") or []
        if not isinstance(task_keywords_raw, list):
            task_keywords_raw = []
        task_keywords = [str(k).strip() for k in task_keywords_raw if isinstance(k, str) and str(k).strip()]

        return {
            "source_key": source_key,
            "name": name,
            "label": _normalize_text(manifest.get("label") or name),
            "description": _normalize_text(manifest.get("description")),
            "category": _normalize_text(manifest.get("category") or "通用"),
            "icon": _normalize_text(manifest.get("icon") or ""),
            "executor_type": executor_type,
            "enabled": _normalize_bool(manifest.get("enabled"), True),
            "readme": _normalize_text(readme) or _normalize_text(manifest.get("readme")),
            "skill_code": _normalize_text(skill_code) if executor_type == "scf" else "",
            "tools": tools_raw,
            "tags": tags,
            "capabilities": capabilities,
            "task_keywords": task_keywords,
        }

    # ------------------------------------------------------------------ #
    #  GitHub URL 处理                                                     #
    # ------------------------------------------------------------------ #

    def _resolve_github_urls(self, github_url: str) -> tuple[str, str]:
        """根据输入 URL 推导 manifest.yaml 与 skill.py 的 raw URL。

        返回 (manifest_url, skill_url)；skill_url 可能为空字符串。
        """
        # 1) raw URL 直接命中
        raw_match = _GITHUB_RAW_RE.match(github_url)
        if raw_match:
            owner = raw_match.group("owner")
            repo = raw_match.group("repo")
            branch = raw_match.group("branch")
            path = raw_match.group("path")
            base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"
            # 若已是 manifest.yaml 直接命中
            if path.lower().endswith("manifest.yaml"):
                return github_url, base + "skill.py"
            # 若指向 skill.py
            if path.lower().endswith("skill.py"):
                return base + "manifest.yaml", github_url
            # 其他情况：按目录处理
            dir_path = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
            return base + dir_path + "manifest.yaml", base + dir_path + "skill.py"

        # 2) 仓库 URL：尝试 main / master 分支
        repo_match = _GITHUB_REPO_RE.match(github_url)
        if repo_match:
            owner = repo_match.group("owner")
            repo = repo_match.group("repo")
            # 解析可能的分支信息 /tree/<branch>
            branch = self._extract_branch_from_path(github_url) or ""
            candidate_branches = [branch] if branch else list(_DEFAULT_BRANCHES)
            for candidate in candidate_branches:
                base = f"https://raw.githubusercontent.com/{owner}/{repo}/{candidate}/"
                manifest_url = base + "manifest.yaml"
                if self._remote_file_exists(manifest_url):
                    return manifest_url, base + "skill.py"
            return "", ""

        # 3) 无法识别
        return "", ""

    def _extract_branch_from_path(self, github_url: str) -> str:
        """从 GitHub URL 的 path 中提取分支（仅识别 /tree/<branch> 模式）。"""
        try:
            parsed = urlparse(github_url)
        except Exception:
            return ""
        parts = [p for p in parsed.path.split("/") if p]
        # 形如 /owner/repo/tree/<branch>[/...]
        if len(parts) >= 4 and parts[2].lower() == "tree":
            return parts[3]
        return ""

    def _remote_file_exists(self, url: str) -> bool:
        try:
            response = requests.head(url, timeout=_HTTP_TIMEOUT_SECONDS, allow_redirects=True)
            return response.status_code == 200
        except Exception:
            return False

    def _fetch_text(self, url: str, *, label: str) -> str:
        """拉取远端文本文件，处理 404/403 等错误。"""
        try:
            response = requests.get(url, timeout=_HTTP_TIMEOUT_SECONDS, allow_redirects=True)
        except requests.RequestException as exc:
            raise FailException(f"拉取 {label} 失败: {exc}") from exc

        if response.status_code == 404:
            raise NotFoundException(f"{label} 不存在 (404): {url}")
        if response.status_code == 403:
            raise FailException(f"拉取 {label} 被拒绝 (403): {url}")
        if response.status_code >= 400:
            raise FailException(f"拉取 {label} 失败 ({response.status_code}): {url}")

        try:
            return response.text or ""
        except Exception as exc:
            raise FailException(f"解析 {label} 响应失败: {exc}") from exc
