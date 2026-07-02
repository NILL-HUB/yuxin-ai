import hashlib
import base64
import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.app_entity import AppStatus
from internal.exception import NotFoundException, ForbiddenException, FailException
from internal.lib.helper import generate_random_string
from internal.model import App, Account
from .base_service import BaseService
from .icon_generator_service import IconGeneratorService


logger = logging.getLogger(__name__)


@inject
@dataclass
class AppIconService(BaseService):
    icon_generator_service: IconGeneratorService

    def regenerate_web_app_token(self, app_id: UUID, account: Account) -> str:
        """根据传递的应用id+账号重新生成WebApp凭证标识"""
        app = self.get_app(app_id, account)

        if app.status != AppStatus.PUBLISHED.value:
            raise FailException("应用未发布 无法生成WebApp凭证标识")

        token = generate_random_string(16)
        self.update(app, token=token)

        return token

    def regenerate_icon(self, app_id: UUID, account: Account) -> str:
        """根据传递的应用id重新生成应用图标"""
        app = self.get_app(app_id, account)

        try:
            logging.info(f"重新生成应用图标: app_id={app_id}, name={app.name}")
            icon_url = self.icon_generator_service.generate_icon(
                name=app.name,
                description=app.description or ""
            )
            logging.info(f"重新生成图标成功: {icon_url}")
        except Exception as e:
            logging.error(f"重新生成图标失败: {str(e)}")
            raise

        self.update(app, icon=icon_url)

        return icon_url

    def generate_icon_preview(self, name: str, description: str) -> str:
        """生成图标预览（不保存到应用）"""
        try:
            logging.info(f"生成图标预览: name={name}")
            icon_url = self.icon_generator_service.generate_icon(
                name=name,
                description=description or ""
            )
            logging.info(f"生成图标预览成功: {icon_url}")
            return icon_url
        except Exception as e:
            logging.error(f"生成图标预览失败: {str(e)}")
            raise

    def _generate_default_icon(self, app_name: str) -> str:
        """
        生成一个默认的彩色SVG图标

        Args:
            app_name: 应用名称

        Returns:
            str: 图标的COS URL或数据URI
        """
        hash_obj = hashlib.md5(app_name.encode())
        hash_hex = hash_obj.hexdigest()

        r = int(hash_hex[0:2], 16)
        g = int(hash_hex[2:4], 16)
        b = int(hash_hex[4:6], 16)

        brightness = (r * 299 + g * 587 + b * 114) / 1000
        if brightness < 100:
            r = min(255, r + 100)
            g = min(255, g + 100)
            b = min(255, b + 100)

        first_char = app_name[0].upper() if app_name else "A"

        svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
  <rect width="200" height="200" fill="rgb({r},{g},{b})" rx="40"/>
  <text x="100" y="120" font-size="100" font-weight="bold" fill="white" text-anchor="middle" font-family="Arial, sans-serif">{first_char}</text>
</svg>'''

        svg_bytes = svg_content.encode('utf-8')
        svg_base64 = base64.b64encode(svg_bytes).decode('utf-8')
        data_uri = f"data:image/svg+xml;base64,{svg_base64}"

        return data_uri

    def get_app(self, app_id: UUID, account: Account) -> App:
        """根据传递的id获取应用的基础信息"""
        app = self.get(App, app_id)

        if not app:
            raise NotFoundException("该应用不存在，请核实后重试")

        if app.account_id != account.id:
            raise ForbiddenException("当前账号无权限访问该应用，请核实后尝试")

        return app
