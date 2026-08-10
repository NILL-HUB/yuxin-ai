"""纯 SMTP 邮件扩展（替代 flask_mail，彻底移除 Flask 依赖）。

- ``Mail``：兼容 flask_mail 常用 API（``send(msg)`` / ``server`` 属性），
  底层使用标准库 smtplib，支持 TLS/SSL、超时、发送者配置。
- ``Message``：兼容 flask_mail.Message（``subject`` / ``recipients`` / ``body`` / ``html``）。
"""

import logging
import smtplib
import socket
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """邮件消息（兼容 flask_mail.Message 常用字段）。"""

    subject: str
    recipients: list[str]
    body: str = ""
    html: str = ""
    sender: Optional[str] = None


class Mail:
    """纯 SMTP 邮件客户端（API 兼容 flask_mail.Mail 常用子集）。"""

    def __init__(self):
        self._config: dict = {}
        self.server: Optional[str] = None

    def init_app(self, config) -> None:
        """从配置对象读取 SMTP 参数。"""
        self._config = {
            "server": getattr(config, "MAIL_SERVER", None),
            "port": int(getattr(config, "MAIL_PORT", 587) or 587),
            "use_tls": bool(getattr(config, "MAIL_USE_TLS", True)),
            "use_ssl": bool(getattr(config, "MAIL_USE_SSL", False)),
            "username": getattr(config, "MAIL_USERNAME", None),
            "password": getattr(config, "MAIL_PASSWORD", None),
            "default_sender": getattr(config, "MAIL_DEFAULT_SENDER", None),
            "timeout": int(getattr(config, "MAIL_TIMEOUT", 10) or 10),
        }
        self.server = self._config.get("server")

    def send(self, message: Message) -> None:
        """同步发送邮件（由调用方决定线程模型）。"""
        cfg = self._config
        sender = message.sender or cfg.get("default_sender")
        if not sender:
            raise RuntimeError("邮件缺少发送者地址（sender / MAIL_DEFAULT_SENDER）")
        if not cfg.get("server"):
            raise RuntimeError("邮件服务器未配置（MAIL_SERVER）")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = message.subject
        msg["From"] = formataddr(("", sender))
        msg["To"] = ", ".join(message.recipients)
        if message.body:
            msg.attach(MIMEText(message.body, "plain", "utf-8"))
        if message.html:
            msg.attach(MIMEText(message.html, "html", "utf-8"))

        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(cfg.get("timeout") or None)
            host = self.server or cfg.get("server")
            if cfg.get("use_ssl"):
                smtp = smtplib.SMTP_SSL(host, cfg["port"])
            else:
                smtp = smtplib.SMTP(host, cfg["port"])
                if cfg.get("use_tls"):
                    smtp.starttls()
            try:
                if cfg.get("username"):
                    smtp.login(cfg["username"], cfg["password"] or "")
                smtp.sendmail(sender, message.recipients, msg.as_string())
            finally:
                smtp.quit()
        except Exception as e:
            logger.error("SMTP 发送邮件失败: %s", e)
            raise
        finally:
            socket.setdefaulttimeout(old_timeout)


mail = Mail()
