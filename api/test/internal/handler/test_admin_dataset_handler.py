import os

from pkg.response import HttpCode

os.environ["ADMIN_BOOTSTRAP_ENABLED"] = "0"


def _mock_current_admin(monkeypatch, permissions):
    """为后台接口测试注入稳定的管理员身份与权限集合。"""

    def _get_current_admin_from_token(self, token):
        return {
            "id": "admin-1",
            "email": "root@example.com",
            "name": "Root",
            "avatar": "",
            "status": "active",
            "roles": ["super_admin"],
            "permissions": permissions,
        }

    monkeypatch.setattr(
        "internal.service.admin_user_service.AdminUserService.get_current_admin_from_token",
        _get_current_admin_from_token,
    )


class TestAdminDatasetHandler:
    def test_list_returns_real_dataset_page(self, app, monkeypatch):
        """返回真实后台数据集分页，而不是固定空分页。"""
        _mock_current_admin(monkeypatch, ["dataset:read"])
        captured = {}

        def _list_datasets(_self, *, search_word, current_page, page_size):
            captured["search_word"] = search_word
            captured["current_page"] = current_page
            captured["page_size"] = page_size
            return {
                "list": [
                    {
                        "id": "00000000-0000-0000-0000-000000000001",
                        "name": "CRM Knowledge Base",
                        "icon": "https://example.com/dataset.png",
                        "description": "customer support docs",
                        "document_count": 1,
                        "related_app_count": 1,
                        "character_count": 128,
                        "creator_name": "Alice",
                        "creator_avatar": "https://example.com/alice.png",
                        "upload_at": 1710000000,
                        "updated_at": 1710000000,
                        "created_at": 1700000000,
                    }
                ],
                "paginator": {
                    "total_record": 1,
                    "total_page": 1,
                    "current_page": current_page,
                    "page_size": page_size,
                },
            }

        monkeypatch.setattr(
            "internal.service.admin_dataset_service.AdminDatasetService.list_datasets",
            _list_datasets,
        )

        with app.test_client() as http_client:
            response = http_client.get(
                "/admin/datasets?current_page=1&page_size=20&search_word=Knowledge",
                headers={"Authorization": "Bearer admin-token"},
            )

        assert response.status_code == 200
        assert response.json["code"] == HttpCode.SUCCESS
        data = response.json["data"]
        assert data["paginator"]["total_record"] == 1
        assert len(data["list"]) == 1
        assert data["list"][0]["name"] == "CRM Knowledge Base"
        assert data["list"][0]["creator_name"] == "Alice"
        assert data["list"][0]["creator_avatar"] == "https://example.com/alice.png"
        assert data["list"][0]["document_count"] == 1
        assert data["list"][0]["character_count"] == 128
        assert data["list"][0]["related_app_count"] == 1
        assert captured == {
            "search_word": "Knowledge",
            "current_page": 1,
            "page_size": 20,
        }

    def test_list_rejects_missing_permission(self, app, monkeypatch):
        """缺少 dataset:read 权限时拒绝访问后台数据集列表。"""
        _mock_current_admin(monkeypatch, ["admin:access"])

        with app.test_client() as http_client:
            response = http_client.get(
                "/admin/datasets",
                headers={"Authorization": "Bearer admin-token"},
            )

        assert response.status_code == 200
        assert response.json["code"] == HttpCode.FORBIDDEN
