"""邮箱发送配置服务：单行 JSONB 存储（id=1），发送走 smtplib 动态构建。"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

from internal.extension.database_extension import db
from internal.model.auth_channel_config import MailConfig

DEFAULT_KEYS = {
    "smtp_host": "",
    "smtp_port": "587",
    "use_tls": True,
    "use_ssl": False,
    "username": "",
    "password": "",
    "default_sender": "",
    "from_name": "",
    "timeout": "30",
}

_STR_KEYS = {"smtp_host", "smtp_port", "username", "password", "default_sender", "from_name", "timeout"}
_BOOL_KEYS = {"use_tls", "use_ssl"}


class MailConfigService:
    """邮件发送配置：单行记录（id=1），configs JSONB 持久化 SMTP 参数。"""

    def __init__(self, session=None):
        self.session = session or db.session

    def _row(self) -> MailConfig:
        row = self.session.query(MailConfig).filter(MailConfig.id == 1).one_or_none()
        if row is None:
            row = MailConfig(id=1, configs={})
            self.session.add(row)
            self.session.flush()
        return row

    def get_config(self) -> dict:
        cfg = dict(DEFAULT_KEYS)
        row = self._row()
        if row.configs:
            cfg.update({k: v for k, v in row.configs.items() if k in DEFAULT_KEYS})
        return cfg

    def update_config(self, payload: dict) -> dict:
        cfg = self.get_config()
        for k in DEFAULT_KEYS:
            if k not in payload:
                continue
            val = payload[k]
            if k in _BOOL_KEYS:
                cfg[k] = str(val).lower() in ("true", "1", "yes", "on")
            elif val is not None and str(val).strip() != "":
                cfg[k] = str(val).strip()
        host = cfg.get("smtp_host", "")
        if not host:
            raise ValueError("smtp_host 不能为空")
        row = self._row()
        row.configs = cfg
        self.session.commit()
        return cfg

    def send_test(self, *, recipient: str) -> dict:
        cfg = self.get_config()
        if not recipient:
            raise ValueError("收件邮箱不能为空")
        result = send_smtp(
            cfg,
            recipients=[recipient],
            subject="【系统测试】邮件通道配置验证",
            body="这是一封测试邮件：邮件通道配置成功。",
            html="<h3>邮件通道配置成功</h3>",
        )
        return {"ok": True, "detail": result}


def _resolve_sender(cfg: dict):
    name = cfg.get("from_name") or ""
    sender = cfg.get("default_sender") or cfg.get("username") or ""
    if not sender:
        raise RuntimeError("未配置 default_sender/username，无法确定发件人")
    return formataddr((name, sender)) if name else sender


def send_smtp(cfg: dict, *, recipients: list[str], subject: str, body: str, html: str | None = None) -> dict:
    """用 DB 配置发送邮件；成功返回 {"server": host, "recipients": n}。"""
    host = cfg.get("smtp_host") or ""
    if not host:
        raise RuntimeError("邮件发送未配置：请先在系统配置-邮件发送中填写 SMTP 配置")
    port = int(cfg.get("smtp_port") or 587)
    use_ssl = bool(cfg.get("use_ssl"))
    use_tls = bool(cfg.get("use_tls")) and not use_ssl
    username = cfg.get("username") or None
    password = cfg.get("password") or None
    timeout = int(cfg.get("timeout") or 30)

    msg = MIMEText(html or body, "html" if html else "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = _resolve_sender(cfg)
    msg["To"] = ", ".join(recipients)

    if use_ssl:
        smtp = smtplib.SMTP_SSL(host, port, timeout=timeout)
    else:
        smtp = smtplib.SMTP(host, port, timeout=timeout)
    try:
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()
        if username:
            smtp.login(username, password)
        smtp.sendmail(msg["From"], recipients, msg.as_string())
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    return {"server": host, "recipients": len(recipients)}
