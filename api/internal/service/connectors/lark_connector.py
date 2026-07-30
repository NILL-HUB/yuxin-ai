import logging
import time
from typing import Any

import requests

from internal.entity.knowledge_entity import ExternalAuthorizationStatus
from internal.model.knowledge import ExternalDataSource

from .base_connector import BaseConnector, ExternalConnectorError

logger = logging.getLogger(__name__)

# 飞书开放平台 OpenAPI 基础地址
LARK_BASE_URL = "https://open.feishu.cn/open-apis"
# 单次 HTTP 请求超时时间（秒）
_REQUEST_TIMEOUT = 30
# token 缓存提前刷新阈值（秒），避免临界过期
_TOKEN_REFRESH_LEAD = 60
# 模块级 tenant_access_token 缓存：{app_id: (token, expire_timestamp)}
# 飞书 tenant_access_token 有效期约 2 小时，缓存避免每次同步重复获取
_tenant_token_cache: dict[str, tuple[str, float]] = {}


class LarkConnector(BaseConnector):
    """飞书云文档连接器

    通过飞书开放平台 OpenAPI 拉取指定文件夹下的文档（docx）内容。
    凭证从 ExternalDataSource.config 读取：app_id / app_secret / folder_token。
    """

    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
    ) -> str:
        app_id = auth_config.get("app_id") or data_source.config.get("app_id", "")
        app_secret = auth_config.get("app_secret") or data_source.config.get("app_secret", "")
        if not app_id or not app_secret:
            raise ValueError("飞书连接需要 app_id 和 app_secret")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(self, data_source: ExternalDataSource) -> list[dict[str, str]]:
        """拉取飞书文件夹下的 docx 文档并返回统一文档结构"""
        config = data_source.config or {}
        app_id = config.get("app_id", "")
        app_secret = config.get("app_secret", "")
        # 凭证缺失时降级返回空列表 + warning，避免开发环境报错
        if not app_id or not app_secret:
            logger.warning("飞书连接器未配置 app_id/app_secret，跳过同步并返回空列表")
            return []

        folder_token = config.get("folder_token", "")
        try:
            tenant_token = self._get_tenant_access_token(app_id, app_secret)
            files = self._list_folder_files(tenant_token, folder_token)
            documents: list[dict[str, str]] = []
            for file_meta in files:
                # 当前仅处理 docx 类型文档，其它类型（sheet/bitable 等）跳过
                if file_meta.get("type") != "docx":
                    continue
                document_id = file_meta.get("token", "")
                if not document_id:
                    continue
                name = file_meta.get("name", "lark_document")
                source_url = file_meta.get("url", "")
                content = self._fetch_docx_raw_content(tenant_token, document_id)
                documents.append({
                    "name": name,
                    "content": content,
                    "source_url": source_url,
                })
            return documents
        except ExternalConnectorError:
            raise
        except Exception as exc:
            # 兜底：将未预期异常统一包装为连接器异常，便于上层 catch
            raise ExternalConnectorError(f"拉取飞书文档失败: {exc}") from exc

    @classmethod
    def _get_tenant_access_token(cls, app_id: str, app_secret: str) -> str:
        """获取飞书 tenant_access_token，命中缓存且未过期则直接返回"""
        cached = _tenant_token_cache.get(app_id)
        if cached and cached[1] > time.time() + _TOKEN_REFRESH_LEAD:
            return cached[0]

        url = f"{LARK_BASE_URL}/auth/v3/tenant_access_token/internal"
        try:
            resp = requests.post(
                url,
                json={"app_id": app_id, "app_secret": app_secret},
                timeout=_REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ExternalConnectorError(f"请求飞书 tenant_access_token 网络异常: {exc}") from exc

        if resp.status_code != 200:
            raise ExternalConnectorError(
                f"飞书 tenant_access_token 接口返回非 200 状态码: {resp.status_code}"
            )
        data = resp.json()
        if data.get("code") != 0:
            raise ExternalConnectorError(
                f"飞书 tenant_access_token 接口返回错误: code={data.get('code')} msg={data.get('msg')}"
            )
        token = data.get("tenant_access_token", "")
        expire = int(data.get("expire", 7200) or 7200)
        _tenant_token_cache[app_id] = (token, time.time() + expire)
        return token

    @staticmethod
    def _list_folder_files(tenant_token: str, folder_token: str) -> list[dict]:
        """列出文件夹下文件，循环处理 page_token 分页"""
        headers = {"Authorization": f"Bearer {tenant_token}"}
        files: list[dict] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 200}
            if folder_token:
                params["folder_token"] = folder_token
            if page_token:
                params["page_token"] = page_token
            url = f"{LARK_BASE_URL}/drive/v1/files"
            try:
                resp = requests.get(
                    url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT
                )
            except requests.RequestException as exc:
                raise ExternalConnectorError(f"请求飞书文件列表网络异常: {exc}") from exc
            if resp.status_code != 200:
                raise ExternalConnectorError(
                    f"飞书文件列表接口返回非 200 状态码: {resp.status_code}"
                )
            data = resp.json()
            if data.get("code") != 0:
                raise ExternalConnectorError(
                    f"飞书文件列表接口返回错误: code={data.get('code')} msg={data.get('msg')}"
                )
            page_data = data.get("data", {}) or {}
            files.extend(page_data.get("files", []) or [])
            if not page_data.get("has_more"):
                break
            page_token = page_data.get("next_page_token", "")
            if not page_token:
                break
        return files

    @staticmethod
    def _fetch_docx_raw_content(tenant_token: str, document_id: str) -> str:
        """获取 docx 文档纯文本内容"""
        url = f"{LARK_BASE_URL}/docx/v1/documents/{document_id}/raw_content"
        headers = {"Authorization": f"Bearer {tenant_token}"}
        try:
            resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise ExternalConnectorError(f"请求飞书文档内容网络异常: {exc}") from exc
        if resp.status_code != 200:
            raise ExternalConnectorError(
                f"飞书文档内容接口返回非 200 状态码: {resp.status_code}"
            )
        data = resp.json()
        if data.get("code") != 0:
            raise ExternalConnectorError(
                f"飞书文档内容接口返回错误: code={data.get('code')} msg={data.get('msg')}"
            )
        return (data.get("data", {}) or {}).get("content", "") or ""
