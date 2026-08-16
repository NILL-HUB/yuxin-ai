import json
import logging
from typing import Any
from uuid import UUID
from pydantic import ValidationError
import requests
import yaml
from internal.exception import ValidateErrorException, NotFoundException, FailException
from internal.lib.helper import escape_like_pattern
from injector import inject
from dataclasses import dataclass
from internal.core.tools.api_tools.entities import OpenAPISchema
from internal.schema.api_tool_schema import (
    CreateApiToolReq,
    GetApiToolProvidersWithPageReq,
    UpdateApiToolProviderReq
)
from pkg.sqlalchemy import SQLAlchemy
from internal.model import ApiToolProvider, ApiTool, Account
from internal.model.admin import AdminUser
from pkg.paginator import Paginator
from sqlalchemy import desc
from .base_service import BaseService
from internal.core.tools.api_tools.providers import ApiProviderManager
from .icon_generator_service import IconGeneratorService
from .tool_credential_encryptor import encrypt_headers, mask_headers

_HTTP_TIMEOUT_SECONDS = 30


def _schema_to_plain_dict(schema: OpenAPISchema) -> dict[str, Any]:
    """将 OpenAPISchema pydantic 模型还原为可 JSON 序列化的普通字典。"""
    return {
        "server": schema.server,
        "description": schema.description,
        "paths": schema.paths,
    }


@inject
@dataclass
class ApiToolService(BaseService):
    """自定义API插件服务"""
    db: SQLAlchemy
    api_provider_manager: ApiProviderManager
    icon_generator_service: IconGeneratorService
    def update_api_tool_provider(
            self,
            provider_id:UUID,
            req:UpdateApiToolProviderReq,
            account: Account
    ):
        """根据传递的provider_id+req更新对应的API工具提供者信息"""
        # 1.根据传递的provider_id查找API工具提供者信息并校验
        api_tool_provider = self.get(ApiToolProvider,provider_id)
        if api_tool_provider is None or api_tool_provider.account_id != account.id:
            raise ValidateErrorException("该工具提供者不存在")

        # 2.校验openapi_schema数据
        openapi_schema = self.parse_openapi_schema(req.openapi_schema.data)

        # 3.检测当前账号是否已经创建了除了此id以外同名的工具提供者 如果是则抛出错误
        check_api_tool_provider = self.db.session.query(ApiToolProvider).filter(
            ApiToolProvider.account_id == account.id,
            ApiToolProvider.name == req.name.data,
            ApiToolProvider.id != api_tool_provider.id,
        ).one_or_none()
        if check_api_tool_provider:
            raise ValidateErrorException(f"该工具提供者名字{req.name.data}已经存在")

        # 4.开启数据库的自动提交
        with self.db.auto_commit():
            # 5.先删除该工具提供者下的所有工具
            self.db.session.query(ApiTool).filter(
                ApiTool.provider_id == api_tool_provider.id,
                ApiTool.account_id == account.id,
            ).delete()

        # 6.修改工具提供者信息（headers 落库前加密）
        self.update(
            api_tool_provider,
            name=req.name.data,
            icon=req.icon.data,
            headers=encrypt_headers(req.headers.data),
            description=openapi_schema.description,
            openapi_schema=req.openapi_schema.data,
        )

        # 7.新增工具信息从而完成覆盖更新（task_keywords 透传到每个工具）
        task_keywords = req.task_keywords.data or []
        for path, path_item in openapi_schema.paths.items():
            for method, method_item in path_item.items():
                self.create(
                    ApiTool,
                    account_id=account.id,
                    provider_id=api_tool_provider.id,
                    name=method_item.get("operationId"),
                    description=method_item.get("description"),
                    url=f"{openapi_schema.server}{path}",
                    method=method,
                    parameters=method_item.get("parameters", []),
                    task_keywords=task_keywords,
                )

    def get_api_tool_providers_wiith_page(
            self,
            req: GetApiToolProvidersWithPageReq,
            account: Account
    ) -> tuple[list[Any],Paginator]:
        """获取自定义API工具服务提供者分页列表数据"""
        # 1.构建分页查询器
        paginator = Paginator(db=self.db, req=req)

        # 2.构建筛选器
        filters = [ApiToolProvider.account_id == account.id]
        if req.search_word.data:
            filters.append(ApiToolProvider.name.ilike(f"%{escape_like_pattern(req.search_word.data)}%"))

        # 3.执行分页并获取数据
        api_tool_providers = paginator.paginate(
            self.db.session.query(ApiToolProvider).filter(*filters).order_by(desc("created_at"))
        )
        # 4.对返回数据中的 headers 进行脱敏（已加密值会先解密再脱敏）
        for provider in api_tool_providers:
            if getattr(provider, "headers", None):
                provider.headers = mask_headers(provider.headers)
        return api_tool_providers,paginator

    def get_api_tool(
            self,
            provider_id: UUID,
            tool_name: str,
            account: Account
    ) -> ApiTool:
        """根据传递的provider_id + tool_name获取对应的参数详情信息"""
        api_tool = self.db.session.query(ApiTool).filter_by(
            provider_id=provider_id,
            name=tool_name
        ).one_or_none()

        if api_tool is None or str(api_tool.account_id) != str(account.id):
            raise NotFoundException("该工具不存在")
        return api_tool

    def get_api_tool_provider(
            self,
            provider_id: UUID,
            account: Account
    ):
        """根据传递的provider_id获取API工具提供者信息"""
        # 1.查询数据库获取对应的数据
        api_tool_provider = self.get(ApiToolProvider,provider_id)

        # 2.检验数据是否为空 并且判断该数据是否属于当前帐号
        if api_tool_provider is None or str(api_tool_provider.account_id) != str(account.id):
            raise NotFoundException("该工具提供者不存在")
        # 3.对 headers 进行脱敏处理（已加密值会先解密再脱敏）
        if api_tool_provider.headers:
            api_tool_provider.headers = mask_headers(api_tool_provider.headers)
        return api_tool_provider

    def create_api_tool(
            self,
            req: CreateApiToolReq,
            account: Account | None = None,
            *,
            created_by_admin=None,
    ) -> None:
        """根据传递的请求创建自定义API工具（管理端创建时 account 为空，记录 created_by_admin）"""
        # 1.检验并提取吧openapi_schema对应的数据
        openapi_schema = self.parse_openapi_schema(req.openapi_schema.data)

        # 2.查询当前登陆的账号是否已经创建了同名的工具提供者 如果是则抛出错误
        api_tool_provider = self.db.session.query(ApiToolProvider).filter_by(
            account_id=account.id if account is not None else None,
            name=req.name.data
        ).one_or_none()
        if api_tool_provider:
            raise ValidateErrorException(f"该工具提供者名字{req.name.data}已存在")


        # 3.首先创建工具提供者 并获取工具提供者的id信息 然后创建工具信息
        api_tool_provider = self.create(
            ApiToolProvider,
            account_id=account.id if account is not None else None,
            created_by_admin=created_by_admin,
            name=req.name.data,
            icon=req.icon.data,
            description=openapi_schema.description,
            openapi_schema=req.openapi_schema.data,
            headers=encrypt_headers(req.headers.data)
        )

        # 4.创建api工具并关联api_tool_provider（task_keywords 透传到每个工具）
        task_keywords = req.task_keywords.data or []
        for path, path_item in openapi_schema.paths.items():
            for method,method_item in path_item.items():
                self.create(
                    ApiTool,
                    account_id=account.id if account is not None else None,
                    provider_id=api_tool_provider.id,
                    name=method_item.get("operationId"),
                    description=method_item.get("description"),
                    url=f"{openapi_schema.server}{path}",
                    method=method,
                    parameters=method_item.get("parameters", []),
                    task_keywords=task_keywords,
                )

    # ------------------------------------------------------------------ #
    #  API 工具导入：URL / 文件（OpenAPI JSON 或 YAML）                     #
    # ------------------------------------------------------------------ #

    def _parse_openapi_text(self, content: str, *, source_label: str = "OpenAPI 文档") -> OpenAPISchema:
        """解析 OpenAPI 文本（兼容 JSON / YAML），返回 OpenAPISchema。"""
        content = (content or "").strip()
        if not content:
            raise ValidateErrorException(f"{source_label} 内容为空")

        data: Any = None
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            try:
                data = yaml.safe_load(content)
            except yaml.YAMLError as exc:
                raise ValidateErrorException(f"{source_label} 不是合法的 JSON 或 YAML: {exc}") from exc

        if not isinstance(data, dict):
            raise ValidateErrorException(f"{source_label} 根节点必须是 JSON 对象")

        try:
            return OpenAPISchema(**data)
        except ValidateErrorException as error:
            raise
        except ValidationError as error:
            first_error = error.errors()[0] if error.errors() else {}
            location = ".".join(str(item) for item in first_error.get("loc", []))
            message = first_error.get("msg", "字段校验失败")
            error_summary = f"{location}: {message}" if location else message
            raise ValidateErrorException(f"{source_label} 结构校验失败: {error_summary}") from error

    def _create_provider_from_schema(
        self,
        *,
        name: str,
        icon: str,
        description: str,
        openapi_schema_str: str,
        headers: list[dict[str, Any]] | None,
        task_keywords: list[str] | None,
        account: Account | None = None,
        overwrite: bool,
        created_by_admin=None,
    ) -> dict[str, Any]:
        """按 OpenAPI schema 文本创建/覆盖 provider + tools，返回统一结果。"""
        openapi_schema = self.parse_openapi_schema(openapi_schema_str)
        existing = self.db.session.query(ApiToolProvider).filter_by(
            account_id=account.id if account is not None else None,
            name=name,
        ).one_or_none()
        if existing and not overwrite:
            return {
                "action": "skipped",
                "reason": "已存在且 overwrite=False",
                "id": str(existing.id),
            }

        # 图标兜底
        final_icon = icon
        if not final_icon:
            try:
                final_icon = self.icon_generator_service.generate_icon(name=name, description=description)
            except Exception:
                final_icon = ""
        if not final_icon:
            final_icon = ""

        with self.db.auto_commit():
            if existing and overwrite:
                # 先删除旧工具，再更新 provider 并重建
                self.db.session.query(ApiTool).filter(
                    ApiTool.provider_id == existing.id,
                    ApiTool.account_id == (account.id if account is not None else None),
                ).delete()
                self.update(
                    existing,
                    name=name,
                    icon=final_icon,
                    description=openapi_schema.description,
                    openapi_schema=openapi_schema_str,
                    headers=encrypt_headers(headers),
                )
                provider = existing
                action = "updated"
            else:
                provider = self.create(
                    ApiToolProvider,
                    account_id=account.id if account is not None else None,
                    created_by_admin=created_by_admin,
                    name=name,
                    icon=final_icon,
                    description=openapi_schema.description,
                    openapi_schema=openapi_schema_str,
                    headers=encrypt_headers(headers),
                )
                action = "created"

            for path, path_item in openapi_schema.paths.items():
                for method, method_item in path_item.items():
                    self.create(
                        ApiTool,
                        account_id=account.id if account is not None else None,
                        provider_id=provider.id,
                        name=method_item.get("operationId"),
                        description=method_item.get("description"),
                        url=f"{openapi_schema.server}{path}",
                        method=method,
                        parameters=method_item.get("parameters", []),
                        task_keywords=task_keywords or [],
                    )

        return {
            "action": "imported",
            "id": str(provider.id),
            "is_new": action == "created",
            "name": name,
            "tool_count": len(openapi_schema.paths),
        }

    def import_from_url(
        self,
        url: str,
        name: str,
        description: str,
        headers: list | None,
        account: Account | None = None,
        *,
        overwrite: bool = False,
        task_keywords: list | None = None,
        created_by_admin=None,
    ) -> dict[str, Any]:
        """从 OpenAPI URL 导入 API 工具提供者。

        流程：拉取 URL 内容 → 解析 JSON/YAML → 校验 → 创建 provider + tools。
        """
        if not url or not str(url).strip():
            raise ValidateErrorException("url 不能为空")
        if not name or not str(name).strip():
            raise ValidateErrorException("name 不能为空")

        try:
            response = requests.get(str(url).strip(), timeout=_HTTP_TIMEOUT_SECONDS, allow_redirects=True)
        except requests.RequestException as exc:
            raise FailException(f"拉取 OpenAPI 文档失败: {exc}") from exc
        if response.status_code >= 400:
            raise FailException(f"拉取 OpenAPI 文档失败 ({response.status_code}): {url}")

        schema = self._parse_openapi_text(response.text, source_label=f"URL {url}")
        return self._create_provider_from_schema(
            name=name,
            icon="",
            description=description or schema.description,
            openapi_schema_str=json.dumps(_schema_to_plain_dict(schema), ensure_ascii=False),
            headers=headers,
            task_keywords=task_keywords,
            account=account,
            overwrite=overwrite,
            created_by_admin=created_by_admin,
        )

    def import_from_file(
        self,
        file_content: str,
        name: str,
        description: str,
        headers: list | None,
        account: Account | None = None,
        *,
        overwrite: bool = False,
        task_keywords: list | None = None,
        created_by_admin=None,
    ) -> dict[str, Any]:
        """从上传的 OpenAPI 文件内容（JSON/YAML 文本）导入 API 工具提供者。"""
        if not name or not str(name).strip():
            raise ValidateErrorException("name 不能为空")

        schema = self._parse_openapi_text(file_content, source_label="OpenAPI 文件")
        return self._create_provider_from_schema(
            name=name,
            icon="",
            description=description or schema.description,
            openapi_schema_str=json.dumps(_schema_to_plain_dict(schema), ensure_ascii=False),
            headers=headers,
            task_keywords=task_keywords,
            account=account,
            overwrite=overwrite,
            created_by_admin=created_by_admin,
        )

    def import_from_url_for_admin(
        self,
        url: str,
        name: str,
        description: str,
        headers: list | None,
        *,
        overwrite: bool = False,
        task_keywords: list | None = None,
        created_by_admin=None,
    ) -> dict[str, Any]:
        """管理员视角 URL 导入（平台级资源，记录创建管理员）。"""
        return self.import_from_url(
            url, name, description, headers, None,
            overwrite=overwrite,
            task_keywords=task_keywords,
            created_by_admin=created_by_admin,
        )

    def import_from_file_for_admin(
        self,
        file_content: str,
        name: str,
        description: str,
        headers: list | None,
        *,
        overwrite: bool = False,
        task_keywords: list | None = None,
        created_by_admin=None,
    ) -> dict[str, Any]:
        """管理员视角文件导入（平台级资源，记录创建管理员）。"""
        return self.import_from_file(
            file_content, name, description, headers, None,
            overwrite=overwrite,
            task_keywords=task_keywords,
            created_by_admin=created_by_admin,
        )

    def delete_api_tool_provider(
            self,
            provider_id: UUID,
            account: Account,
            *,
            retention_days: int | None = None,
            agent_id=None
    ):
        """根据传递的provider_id删除对应工具提供商+工具的所有信息（进入回收站，默认留存 30 天）"""
        # 1.先查找数据 检测下provider_id对应的数据是否存在 权限是否正确
        api_tool_provider = self.get(ApiToolProvider, provider_id)
        if api_tool_provider is None or str(api_tool_provider.account_id) != str(account.id):
            raise NotFoundException("该工具提供者不存在")

        # 2.写入回收站并物理删除原记录（含关联 ApiTool 子表）
        from internal.service.recycle_bin_service import RecycleBinService
        deleted = RecycleBinService().delete_resource(
            resource_type="api_tool",
            resource_id=api_tool_provider.id,
            resource_key=str(api_tool_provider.id),
            resource_name=api_tool_provider.name,
            deleted_by=account.id,
            deleted_by_type="agent" if agent_id else "user",
            retention_days=retention_days,
            agent_id=agent_id,
        )
        if not deleted:
            raise NotFoundException("该工具提供者不存在")

    def get_api_tool_providers_with_page_for_admin(
            self,
            req: GetApiToolProvidersWithPageReq,
    ) -> tuple[list[Any], Paginator]:
        """获取自定义API工具服务提供者分页列表数据（管理员视角，不过滤账号）"""
        # 1.构建分页查询器
        paginator = Paginator(db=self.db, req=req)

        # 2.构建筛选器（管理员视角不做账号过滤）
        filters = []
        if req.search_word.data:
            filters.append(ApiToolProvider.name.ilike(f"%{escape_like_pattern(req.search_word.data)}%"))

        # 3.执行分页并获取数据
        api_tool_providers = paginator.paginate(
            self.db.session.query(ApiToolProvider).filter(*filters).order_by(desc("created_at"))
        )
        # 4.对返回数据中的 headers 进行脱敏（管理员视角同样脱敏），并补充创建管理员展示名
        for provider in api_tool_providers:
            if getattr(provider, "headers", None):
                provider.headers = mask_headers(provider.headers)
            if getattr(provider, "created_by_admin", None):
                admin_user = (
                    self.db.session.query(AdminUser.name)
                    .filter(AdminUser.id == provider.created_by_admin)
                    .one_or_none()
                )
                if admin_user and admin_user[0]:
                    provider._creator_name = admin_user[0]
        return api_tool_providers, paginator

    def get_api_tool_provider_for_admin(self, provider_id: UUID):
        """根据传递的provider_id获取API工具提供者信息（管理员视角，不校验账号）"""
        api_tool_provider = self.get(ApiToolProvider, provider_id)
        if api_tool_provider is None:
            raise NotFoundException("该工具提供者不存在")
        # 管理员视角同样对 headers 做脱敏处理
        if api_tool_provider.headers:
            api_tool_provider.headers = mask_headers(api_tool_provider.headers)
        return api_tool_provider

    def update_api_tool_provider_for_admin(
            self,
            provider_id: UUID,
            req: UpdateApiToolProviderReq,
    ):
        """根据传递的provider_id+req更新对应的API工具提供者信息（管理员视角，不校验账号）"""
        # 1.根据传递的provider_id查找API工具提供者信息
        api_tool_provider = self.get(ApiToolProvider, provider_id)
        if api_tool_provider is None:
            raise NotFoundException("该工具提供者不存在")

        # 2.校验openapi_schema数据
        openapi_schema = self.parse_openapi_schema(req.openapi_schema.data)

        # 3.检测是否已经存在同名（排除自身）的工具提供者
        check_api_tool_provider = self.db.session.query(ApiToolProvider).filter(
            ApiToolProvider.name == req.name.data,
            ApiToolProvider.id != api_tool_provider.id,
        ).one_or_none()
        if check_api_tool_provider:
            raise ValidateErrorException(f"该工具提供者名字{req.name.data}已经存在")

        # 4.开启数据库的自动提交
        with self.db.auto_commit():
            # 5.先删除该工具提供者下的所有工具
            self.db.session.query(ApiTool).filter(
                ApiTool.provider_id == api_tool_provider.id,
            ).delete()

        # 6.修改工具提供者信息（headers 落库前加密）
        self.update(
            api_tool_provider,
            name=req.name.data,
            icon=req.icon.data,
            headers=encrypt_headers(req.headers.data),
            description=openapi_schema.description,
            openapi_schema=req.openapi_schema.data,
        )

        # 7.新增工具信息从而完成覆盖更新（沿用提供者归属的账号）
        for path, path_item in openapi_schema.paths.items():
            for method, method_item in path_item.items():
                self.create(
                    ApiTool,
                    account_id=api_tool_provider.account_id,
                    provider_id=api_tool_provider.id,
                    name=method_item.get("operationId"),
                    description=method_item.get("description"),
                    url=f"{openapi_schema.server}{path}",
                    method=method,
                    parameters=method_item.get("parameters", []),
                )

    def delete_api_tool_provider_for_admin(
        self,
        provider_id: UUID,
        *,
        retention_days: int | None = None,
        deleted_by=None,
    ):
        """根据传递的provider_id删除对应工具提供商+工具的所有信息（管理员视角，不校验账号）"""
        # 1.先查找数据 检测provider_id对应的数据是否存在
        api_tool_provider = self.get(ApiToolProvider, provider_id)
        if api_tool_provider is None:
            raise NotFoundException("该工具提供者不存在")

        from internal.service.recycle_bin_service import RecycleBinService
        deleted = RecycleBinService().delete_resource(
            resource_type="api_tool",
            resource_id=api_tool_provider.id,
            resource_key=str(api_tool_provider.id),
            resource_name=api_tool_provider.name,
            deleted_by=deleted_by,
            retention_days=retention_days,
        )
        if not deleted:
            raise NotFoundException("该工具提供者不存在")

    def regenerate_icon(self, provider_id: UUID, account: Account) -> str:
        """根据传递的provider_id重新生成插件图标"""
        # 1.获取插件提供者信息并校验权限
        api_tool_provider = self.get(ApiToolProvider, provider_id)
        if api_tool_provider is None or str(api_tool_provider.account_id) != str(account.id):
            raise NotFoundException("该工具提供者不存在")

        # 2.使用图标生成服务生成新图标
        try:
            logging.info(f"重新生成插件图标: provider_id={provider_id}, name={api_tool_provider.name}")
            icon_url = self.icon_generator_service.generate_icon(
                name=api_tool_provider.name,
                description=api_tool_provider.description or ""
            )
            logging.info(f"重新生成图标成功: {icon_url}")
        except Exception as e:
            logging.exception("重新生成图标失败: provider_id=%s", provider_id, exc_info=e)
            raise FailException("重新生成图标失败，请稍后重试")

        # 3.更新插件提供者图标
        self.update(api_tool_provider, icon=icon_url)

        return icon_url

    def generate_icon_preview(self, name: str, description: str) -> str:
        """生成图标预览（不保存到插件）"""
        try:
            logging.info(f"生成插件图标预览: name={name}")
            icon_url = self.icon_generator_service.generate_icon(
                name=name,
                description=description or ""
            )
            logging.info(f"生成图标预览成功: {icon_url}")
            return icon_url
        except Exception as e:
            logging.exception("生成图标预览失败: name=%s", name, exc_info=e)
            raise FailException("生成图标预览失败，请稍后重试")

    @classmethod
    def parse_openapi_schema(cls, openapi_schema_str: str) -> OpenAPISchema:
        """解析传递的openapi_schema字符串 如果出错则抛出错误"""
        try:
            data = json.loads((openapi_schema_str or "").strip())
        except json.JSONDecodeError as error:
            logging.debug("OpenAPI schema JSON解析失败: %s", error)
            raise ValidateErrorException("传递的数据必须符合OpenAPI规范的JSON字符串")

        if not isinstance(data, dict):
            logging.debug("OpenAPI schema JSON根节点必须是对象，当前类型: %s", type(data).__name__)
            raise ValidateErrorException("传递的数据必须符合OpenAPI规范的JSON字符串")

        try:
            return OpenAPISchema(**data)
        except ValidateErrorException as error:
            logging.debug("OpenAPI schema字段校验失败: %s", error)
            raise
        except ValidationError as error:
            first_error = error.errors()[0] if error.errors() else {}
            location = ".".join(str(item) for item in first_error.get("loc", []))
            message = first_error.get("msg", "字段校验失败")
            error_summary = f"{location}: {message}" if location else message
            logging.debug("OpenAPI schema结构校验失败: %s", error_summary)
            raise ValidateErrorException(f"OpenAPI schema格式错误: {error_summary}")
