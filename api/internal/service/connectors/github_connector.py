import logging
import base64
from typing import Any

import requests

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource

from .base_connector import BaseConnector, ExternalConnectorError

logger = logging.getLogger(__name__)

# GitHub REST API 基础地址
GITHUB_API_BASE = "https://api.github.com"
# 单次 HTTP 请求超时时间（秒）
_REQUEST_TIMEOUT = 30
# 拉取的 markdown 文件扩展名
_MARKDOWN_EXTENSIONS = (".md", ".markdown")
# 默认拉取的文档目录
_DEFAULT_DOCS_PATH = "docs"


class GithubConnector(BaseConnector):
    """GitHub 连接器

    通过 GitHub REST API 拉取仓库 README 与 docs 目录下的 markdown 文件。
    凭证从 ExternalDataSource.config 读取：
        token / personal_access_token（GitHub Personal Access Token）
        repo（owner/repo 格式）
        path（可选，默认 docs，指定拉取的文档目录）
        include_readme（可选，默认 True，是否拉取根 README）
    """

    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
    ) -> str:
        token = auth_config.get("token") or data_source.config.get("token", "")
        repo = auth_config.get("repo") or data_source.config.get("repo", "")
        if not token or not repo:
            raise ValueError("GitHub 连接需要 token 和 repo（owner/repo 格式）")
        if "/" not in repo:
            raise ValueError("repo 需为 owner/repo 格式")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        """拉取 GitHub 仓库 README 与 docs 目录 markdown 文件"""
        config = data_source.config or {}
        # 兼容 token 与 personal_access_token 两种字段名
        token = config.get("token", "") or config.get("personal_access_token", "")
        repo = config.get("repo", "")
        # 凭证缺失时降级返回空列表 + warning，避免开发环境报错
        if not token or not repo:
            logger.warning("GitHub 连接器未配置 token/repo，跳过同步并返回空列表")
            return []
        if "/" not in repo:
            raise ExternalConnectorError("GitHub repo 需为 owner/repo 格式")

        owner, repo_name = repo.split("/", 1)
        docs_path = config.get("path", _DEFAULT_DOCS_PATH) or _DEFAULT_DOCS_PATH
        include_readme = config.get("include_readme", True)
        headers = self._build_headers(token)

        try:
            documents: list[dict[str, str]] = []
            # 拉取根 README
            if include_readme:
                readme_doc = self._fetch_readme(headers, owner, repo_name)
                if readme_doc:
                    documents.append(readme_doc)
            # 拉取 docs 目录下的 markdown 文件
            documents.extend(self._fetch_directory_markdown(headers, owner, repo_name, docs_path))
            return documents
        except ExternalConnectorError:
            raise
        except Exception as exc:
            # 兜底：将未预期异常统一包装为连接器异常，便于上层 catch
            raise ExternalConnectorError(f"拉取 GitHub 文档失败: {exc}") from exc

    @staticmethod
    def _build_headers(token: str) -> dict[str, str]:
        """构建 GitHub API 请求头"""
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @classmethod
    def _fetch_readme(cls, headers: dict[str, str], owner: str, repo: str) -> dict[str, str] | None:
        """拉取仓库根 README 文件内容"""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme"
        try:
            resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise ExternalConnectorError(f"请求 GitHub README 网络异常: {exc}") from exc
        # README 不存在时返回 404，视为无 README，不报错
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ExternalConnectorError(
                f"GitHub README 接口返回非 200 状态码: {resp.status_code}"
            )
        data = resp.json()
        name = data.get("name", "README.md")
        content = cls._decode_file_content(data)
        html_url = data.get("html_url", "") or data.get("download_url", "")
        return {
            "name": name,
            "content": content,
            "source_url": html_url,
        }

    @classmethod
    def _fetch_directory_markdown(
        cls,
        headers: dict[str, str],
        owner: str,
        repo: str,
        path: str,
    ) -> list[dict[str, str]]:
        """列出指定目录下的 markdown 文件并逐个拉取内容"""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise ExternalConnectorError(f"请求 GitHub 目录列表网络异常: {exc}") from exc
        # 目录不存在时返回 404，视为无文档，不报错
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise ExternalConnectorError(
                f"GitHub 目录列表接口返回非 200 状态码: {resp.status_code}"
            )
        data = resp.json()
        # contents 接口对目录返回列表，对单文件返回对象
        if isinstance(data, dict):
            data = [data]
        documents: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "file":
                continue
            name = item.get("name", "")
            if not name.lower().endswith(_MARKDOWN_EXTENSIONS):
                continue
            content = cls._fetch_file_raw(headers, item)
            html_url = item.get("html_url", "") or item.get("download_url", "")
            documents.append({
                "name": name,
                "content": content,
                "source_url": html_url,
            })
        return documents

    @classmethod
    def _fetch_file_raw(cls, headers: dict[str, str], item: dict) -> str:
        """拉取单个文件原始内容，优先用 download_url，失败则回退 base64 解码"""
        download_url = item.get("download_url", "")
        if download_url:
            try:
                resp = requests.get(download_url, headers=headers, timeout=_REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                raise ExternalConnectorError(f"请求 GitHub 文件内容网络异常: {exc}") from exc
            if resp.status_code == 200:
                return resp.text
            # download_url 失败则回退到 base64 解码 content 字段
        return cls._decode_file_content(item)

    @staticmethod
    def _decode_file_content(item: dict) -> str:
        """解码 GitHub contents 接口返回的 base64 文件内容"""
        encoding = item.get("encoding", "")
        content = item.get("content", "")
        if not content:
            return ""
        if encoding == "base64":
            try:
                return base64.b64decode(content).decode("utf-8", errors="ignore")
            except Exception:
                return ""
        return content
