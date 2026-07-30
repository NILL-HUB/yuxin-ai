from dataclasses import dataclass
from uuid import UUID

from flask import request
from flask_login import login_required, current_user
from injector import inject

from internal.schema.knowledge_base_schema import (
    CreateKnowledgeBaseReq,
    UpdateKnowledgeBaseReq,
    GetKnowledgeBaseResp,
    GetKnowledgeBasesWithPageReq,
    GetKnowledgeBasesWithPageResp,
    HitReq,
    GetKnowledgeDocumentsWithPageReq,
    GetKnowledgeDocumentsWithPageResp,
    GetKnowledgeDocumentResp,
    GetKnowledgeSegmentsWithPageReq,
    GetKnowledgeSegmentsWithPageResp,
    UpdateKnowledgeSegmentReq,
)
from internal.service import KnowledgeBaseService
from pkg.paginator import PageModel
from pkg.response import validate_error_json, success_message, success_json


@inject
@dataclass
class KnowledgeBaseHandler:
    """用户端知识库处理器（仅管理 user_content 知识库）"""
    knowledge_base_service: KnowledgeBaseService

    @login_required
    def get_knowledge_bases_with_page(self):
        """获取用户端知识库分页列表"""
        # 1.提取查询参数并校验
        req = GetKnowledgeBasesWithPageReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务获取分页数据
        knowledge_bases, paginator = self.knowledge_base_service.list_user_content_bases(
            req, current_user,
        )

        # 3.构建响应
        resp = GetKnowledgeBasesWithPageResp(many=True)
        return success_json(PageModel(list=resp.dump(knowledge_bases), paginator=paginator))

    @login_required
    def create_knowledge_base(self):
        """创建用户端知识库"""
        # 1.提取请求并校验
        req = CreateKnowledgeBaseReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务创建知识库
        self.knowledge_base_service.create_user_content_base_with_req(req, current_user)

        # 3.返回成功提示
        return success_message("创建知识库成功")

    @login_required
    def get_knowledge_base(self, knowledge_base_id: UUID):
        """获取用户端知识库详情"""
        knowledge_base = self.knowledge_base_service.get_user_content_base_detail(
            knowledge_base_id, current_user,
        )
        resp = GetKnowledgeBaseResp()
        return success_json(resp.dump(knowledge_base))

    @login_required
    def update_knowledge_base(self, knowledge_base_id: UUID):
        """更新用户端知识库"""
        # 1.提取请求并校验
        req = UpdateKnowledgeBaseReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务更新知识库
        self.knowledge_base_service.update_user_content_base(
            knowledge_base_id, req, current_user,
        )

        return success_message("更新知识库成功")

    @login_required
    def delete_knowledge_base(self, knowledge_base_id: UUID):
        """删除用户端知识库"""
        self.knowledge_base_service.delete_user_content_base(knowledge_base_id, current_user)
        return success_message("删除知识库成功")

    @login_required
    def hit_test(self, knowledge_base_id: UUID):
        """知识库召回测试"""
        # 1.提取请求并校验
        req = HitReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务执行检索
        hit_result = self.knowledge_base_service.hit_test(knowledge_base_id, req, current_user)

        return success_json(hit_result)

    @login_required
    def get_documents_with_page(self, knowledge_base_id: UUID):
        """获取知识库下文档分页列表"""
        # 1.提取查询参数并校验
        req = GetKnowledgeDocumentsWithPageReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务获取分页数据
        documents, paginator = self.knowledge_base_service.get_documents_with_page(
            knowledge_base_id, req, current_user,
        )

        # 3.构建响应
        resp = GetKnowledgeDocumentsWithPageResp(many=True)
        return success_json(PageModel(list=resp.dump(documents), paginator=paginator))

    @login_required
    def get_document(self, knowledge_base_id: UUID, document_id: UUID):
        """获取知识库下指定文档详情"""
        document = self.knowledge_base_service.get_document_detail(
            knowledge_base_id, document_id, current_user,
        )
        resp = GetKnowledgeDocumentResp()
        return success_json(resp.dump(document))

    @login_required
    def delete_document(self, knowledge_base_id: UUID, document_id: UUID):
        """删除知识库下指定文档"""
        self.knowledge_base_service.delete_document(
            knowledge_base_id, document_id, current_user,
        )
        return success_message("删除文档成功")

    @login_required
    def get_segments_with_page(self, knowledge_base_id: UUID, document_id: UUID):
        """获取文档下片段分页列表"""
        # 1.提取查询参数并校验
        req = GetKnowledgeSegmentsWithPageReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务获取分页数据
        segments, paginator = self.knowledge_base_service.get_segments_with_page(
            knowledge_base_id, document_id, req, current_user,
        )

        # 3.构建响应
        resp = GetKnowledgeSegmentsWithPageResp(many=True)
        return success_json(PageModel(list=resp.dump(segments), paginator=paginator))

    @login_required
    def update_segment(self, knowledge_base_id: UUID, document_id: UUID, segment_id: UUID):
        """更新文档片段内容或启用状态"""
        # 1.提取请求并校验
        req = UpdateKnowledgeSegmentReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务更新片段
        self.knowledge_base_service.update_segment(
            knowledge_base_id, document_id, segment_id, req, current_user,
        )

        return success_message("更新片段成功")

    @login_required
    def upload_document(self, knowledge_base_id: UUID):
        """上传文档到知识库"""
        # 1.提取上传文件
        file = request.files.get("file")
        if file is None or not file.filename:
            return validate_error_json({"file": ["请选择要上传的文件"]})

        # 2.调用服务上传文档（内部完成 COS 上传 + 文档记录创建 + 索引构建）
        self.knowledge_base_service.upload_document(knowledge_base_id, file, current_user)

        return success_message("上传文档成功")

    @login_required
    def regenerate_icon(self, knowledge_base_id: UUID):
        """重新生成知识库图标"""
        icon_url = self.knowledge_base_service.regenerate_icon(knowledge_base_id, current_user)
        return success_json({"icon": icon_url})

    @login_required
    def generate_icon_preview(self):
        """生成知识库图标预览（不保存到知识库）"""
        # 1.获取请求数据
        data = request.get_json(force=True, silent=True) or {}
        name = data.get("name", "").strip()
        description = data.get("description", "").strip()

        # 2.校验名称不能为空
        if not name:
            return validate_error_json({"name": ["知识库名称不能为空"]})

        # 3.调用服务生成图标
        icon_url = self.knowledge_base_service.generate_icon_preview(name, description)

        return success_json({"icon": icon_url})

    @login_required
    def list_system_knowledge_bases(self):
        """列出所有对 Agent 可读的系统知识库（enabled=True）

        供用户端 App 配置选择知识库时调用。admin 通过 enabled 开关控制系统知识库是否生效：
            - enabled=True  → Agent 可读，App 可引用
            - enabled=False → Agent 不可读，不会出现在此列表中

        用户对系统知识库只读，无法编辑/删除/上传文档，仅能在自己的 App 配置中引用。
        """
        from internal.service.scoped_knowledge_service import UserContentKnowledgeService

        user_content_service = UserContentKnowledgeService(self.knowledge_base_service.db)
        bases = user_content_service.list_readable_system_bases()

        # 构建响应：仅暴露必要字段，不暴露 owner_admin_user_id 等内部字段
        result = [
            {
                "id": str(base.id),
                "name": base.name,
                "description": base.description or "",
                "knowledge_scope": base.knowledge_scope,
            }
            for base in bases
        ]
        return success_json({"list": result})
