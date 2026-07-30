import logging
from typing import Any

import requests

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource

from .base_connector import BaseConnector, ExternalConnectorError

logger = logging.getLogger(__name__)

# Notion API 基础地址
NOTION_BASE_URL = "https://api.notion.com/v1"
# Notion API 版本号，必须在请求头中指定
NOTION_VERSION = "2022-06-28"
# 单次 HTTP 请求超时时间（秒）
_REQUEST_TIMEOUT = 30
# 含 rich_text 文本的 block 类型集合，这些 block 通过 {type}.rich_text 提取文本
_TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "quote",
    "callout",
    "code",
}


class NotionConnector(BaseConnector):
    """Notion 连接器

    通过 Notion API 拉取数据库页面或页面子块文本。
    凭证从 ExternalDataSource.config 读取：
        integration_token（Notion Internal Integration token，secret_xxx）
        database_id 或 page_id（可选，指定同步范围）
    """

    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
    ) -> str:
        integration_token = (
            auth_config.get("integration_token")
            or data_source.config.get("integration_token", "")
        )
        if not integration_token:
            raise ValueError("Notion 连接需要 integration_token")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        """拉取 Notion 数据库页面或单页内容并返回统一文档结构"""
        config = data_source.config or {}
        integration_token = config.get("integration_token", "")
        # 凭证缺失时降级返回空列表 + warning，避免开发环境报错
        if not integration_token:
            logger.warning("Notion 连接器未配置 integration_token，跳过同步并返回空列表")
            return []

        database_id = config.get("database_id", "")
        page_id = config.get("page_id", "")
        if not database_id and not page_id:
            # 未指定同步范围时降级返回空列表
            logger.warning("Notion 连接器未配置 database_id 或 page_id，跳过同步并返回空列表")
            return []

        headers = {
            "Authorization": f"Bearer {integration_token}",
            "Notion-Version": NOTION_VERSION,
        }
        try:
            if database_id:
                return self._sync_database(headers, database_id)
            return self._sync_page(headers, page_id)
        except ExternalConnectorError:
            raise
        except Exception as exc:
            # 兜底：将未预期异常统一包装为连接器异常，便于上层 catch
            raise ExternalConnectorError(f"拉取 Notion 文档失败: {exc}") from exc

    @classmethod
    def _sync_database(cls, headers: dict[str, str], database_id: str) -> list[dict[str, str]]:
        """查询数据库所有页面，逐页提取标题与正文"""
        url = f"{NOTION_BASE_URL}/databases/{database_id}/query"
        documents: list[dict[str, str]] = []
        start_cursor = ""
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if start_cursor:
                body["start_cursor"] = start_cursor
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=_REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                raise ExternalConnectorError(f"请求 Notion 数据库查询网络异常: {exc}") from exc
            if resp.status_code != 200:
                raise ExternalConnectorError(
                    f"Notion 数据库查询接口返回非 200 状态码: {resp.status_code}"
                )
            data = resp.json()
            for page in data.get("results", []) or []:
                doc = cls._page_to_document(headers, page)
                if doc:
                    documents.append(doc)
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor", "") or ""
            if not start_cursor:
                break
        return documents

    @classmethod
    def _sync_page(cls, headers: dict[str, str], page_id: str) -> list[dict[str, str]]:
        """将单个 page 作为文档，拼接其子块文本"""
        content = cls._fetch_block_children_text(headers, page_id)
        page_url = f"{NOTION_BASE_URL}/pages/{page_id}"
        return [{
            "name": page_id,
            "content": content,
            "source_url": page_url,
        }]

    @classmethod
    def _page_to_document(cls, headers: dict[str, str], page: dict) -> dict[str, str] | None:
        """将一个 Notion page 转换为统一文档结构"""
        page_id = page.get("id", "")
        if not page_id:
            return None
        title = cls._extract_page_title(page)
        content = cls._fetch_block_children_text(headers, page_id)
        source_url = page.get("url", "") or f"{NOTION_BASE_URL}/pages/{page_id}"
        return {
            "name": title or page_id,
            "content": content,
            "source_url": source_url,
        }

    @staticmethod
    def _extract_page_title(page: dict) -> str:
        """从 page.properties 中提取标题属性文本"""
        properties = page.get("properties", {}) or {}
        for prop in properties.values():
            if not isinstance(prop, dict):
                continue
            if prop.get("type") == "title":
                return NotionConnector._extract_rich_text(prop.get("title", []))
        return ""

    @classmethod
    def _fetch_block_children_text(cls, headers: dict[str, str], block_id: str) -> str:
        """拉取并拼接 block 的子块文本（分页处理 start_cursor）"""
        url = f"{NOTION_BASE_URL}/blocks/{block_id}/children"
        lines: list[str] = []
        start_cursor = ""
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if start_cursor:
                params["start_cursor"] = start_cursor
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                raise ExternalConnectorError(f"请求 Notion 块内容网络异常: {exc}") from exc
            if resp.status_code != 200:
                raise ExternalConnectorError(
                    f"Notion 块内容接口返回非 200 状态码: {resp.status_code}"
                )
            data = resp.json()
            for block in data.get("results", []) or []:
                text = cls._extract_block_text(block)
                if text:
                    lines.append(text)
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor", "") or ""
            if not start_cursor:
                break
        return "\n\n".join(lines)

    @staticmethod
    def _extract_block_text(block: dict) -> str:
        """从单个 block 中提取文本内容"""
        block_type = block.get("type", "")
        if block_type in _TEXT_BLOCK_TYPES:
            block_data = block.get(block_type, {}) or {}
            return NotionConnector._extract_rich_text(block_data.get("rich_text", []))
        return ""

    @staticmethod
    def _extract_rich_text(rich_text_list: list) -> str:
        """拼接 rich_text 数组中的 plain_text"""
        parts: list[str] = []
        for rt in rich_text_list or []:
            if isinstance(rt, dict):
                parts.append(rt.get("plain_text", "") or "")
        return "".join(parts)
