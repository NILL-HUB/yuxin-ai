# 认证通道 S1+S2：邮件/短信配置与邮箱手机登录注册实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后台邮件/短信配置板块（DB 持久化+测试发送）、账号模型手机号/验证态字段、邮箱+手机号双通道验证码登录注册后端，与业务开关（AUTH_EMAIL_ENABLED / AUTH_PHONE_ENABLED / AUTH_LOGIN_CHALLENGE_ENABLED）联动。

**Architecture:** 复用 `orchestration_feature_flag` 表存认证开关（默认 email=true/phone=false/challenge=true）；新增 `mail_config`/`sms_config` 单行 JSONB 表；`email_task` 发信改为 DB 配置优先、env 兜底；短信用 httpx 直连阿里云/腾讯云 REST（自实现签名，纯函数可测）；账号服务扩展手机/邮箱验证码登录注册与验证态写入。

**Tech Stack:** Python / Quart / SQLAlchemy / Alembic / smtplib / httpx / Redis

**规范来源:** `docs/superpowers/specs/2026-08-31-auth-channel-login-challenge-design.md`
**迁移链头:** `g1a2b3c4d5e7`（新迁移 down_revision）

---

## 文件总览

| 职责 | 文件 |
|---|---|
| 迁移 | `api/internal/migration/versions/h2c3d4e5f6a8_add_auth_channels.py` |
| ORM | `api/internal/model/account.py`（Account 三列）；Create `api/internal/model/auth_channel_config.py`（MailConfig/SmsConfig） |
| 配置服务 | Create `api/internal/service/mail_config_service.py`、`sm_...` 拆为 `mail_config_service.py` + `sms_config_service.py` |
| 短信 | Create `internal/service/sms/aliyun.py`、`tencent.py`、`sms_service.py` |
| 统一验证码 | Modify `api/internal/service/email_service.py`（场景常量/统一发送入口 SMS 路由） |
| 认证扩展 | Modify `api/internal/service/account_service.py`、`api/app/http/account_auth_routes.py` |
| admin | Modify `api/app/http/admin_routes_8.py`（邮件/短信配置+测试发送）；权限登记 `api/app/http/support.py` |
| 脱敏 | Create `api/internal/lib/mask_utils.py` |

---

### Task 1: 迁移（账号列 + 配置表 + 认证开关种子）

**Files:**
- Create: `api/internal/migration/versions/h2c3d4e5f6a8_add_auth_channels.py`

- [ ] **Step 1: 写迁移文件**

```python
"""add auth channels: phone fields, mail/sms config, auth switches

Revision ID: h2c3d4e5f6a8
Revises: g1a2b3c4d5e7
Create Date: 2026-08-31 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "h2c3d4e5f6a8"
down_revision = "g1a2b3c4d5e7"
branch_labels = None
depends_on = None


def upgrade():
    # account 手机号与验证态
    op.add_column("account", sa.Column("phone", sa.String(32), nullable=False, server_default=sa.text("''::character varying")))
    op.add_column("account", sa.Column("phone_verified_at", sa.DateTime(), nullable=True))
    op.add_column("account", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.execute(
        "CREATE UNIQUE INDEX account_phone_active_idx ON account (phone) "
        "WHERE phone <> ''"
    )

    # 邮件/短信配置（单行 JSONB）
    op.create_table(
        "mail_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("configs", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
    )
    op.create_table(
        "sms_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("configs", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
    )
    op.execute("INSERT INTO mail_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    op.execute("INSERT INTO sms_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")

    # 认证业务开关种子（或 orchestration_feature_flag 表可能为 code 建立唯一索引；若无唯一约束先加）
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO orchestration_feature_flag (code, enabled, risk_level, fallback_behavior, description, updated_at, created_at) VALUES "
        "('AUTH_EMAIL_ENABLED', true, 'low', 'block', '邮箱通道：邮箱+密码登录、邮箱验证码注册/登录/改密/挑战', CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0)),"
        "('AUTH_PHONE_ENABLED', false, 'low', 'block', '手机通道：手机号+验证码登录/注册/改密/挑战/绑定', CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0)),"
        "('AUTH_LOGIN_CHALLENGE_ENABLED', true, 'medium', 'block', '异地新IP登录二次验证开关', CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0)) "
        "ON CONFLICT (code) DO NOTHING"
    ))


def downgrade():
    op.execute("DROP INDEX IF EXISTS account_phone_active_idx")
    op.drop_column("account", "email_verified_at")
    op.drop_column("account", "phone_verified_at")
    op.drop_column("account", "phone")
    op.drop_table("sms_config")
    op.drop_table("mail_config")
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM orchestration_feature_flag WHERE code IN ('AUTH_EMAIL_ENABLED','AUTH_PHONE_ENABLED','AUTH_LOGIN_CHALLENGE_ENABLED')"))
```

> 说明：先确认 `orchestration_feature_flag` 表实际列名与唯一约束（`code` 上是否 unique）。若列名不同（如 `description` 缺失或 `fallback_behavior` 默认值不同），按实际表结构适配 INSERT 列清单；若 code 无唯一索引，先 `CREATE UNIQUE INDEX orchestration_feature_flag_code_uniq ON orchestration_feature_flag(code)`（升级）再 INSERT。

- [ ] **Step 2: 升级验证**

```bash
docker exec -w /app/api llmops-api python scripts/verify_migration_upgrade.py
docker exec llmops-db psql -U postgres -d llmops -c "SELECT column_name FROM information_schema.columns WHERE table_name='account' AND column_name IN ('phone','phone_verified_at','email_verified_at'); SELECT code, enabled FROM orchestration_feature_flag WHERE code LIKE 'AUTH_%';"
```
Expected: 三列存在；三条 AUTH 开关 seed 就位（email=true/phone=false/challenge=true）。

- [ ] **Step 3: Commit**

```bash
git add api/internal/migration/versions/h2c3d4e5f6a8_add_auth_channels.py
git commit -m "feat(auth): phone fields, mail/sms config tables, AUTH_* switch seeds"
```

---

### Task 2: ORM 实体

**Files:**
- Modify: `api/internal/model/account.py`（Account 三列）
- Create: `api/internal/model/auth_channel_config.py`

- [ ] **Step 1: Account 加列（email 之后）**

```python
    email = Column(String(255), nullable=False, server_default=text("''::character varying"))
    email_verified_at = Column(DateTime, nullable=True)      # 邮箱验证时间（注册/邮箱码登录/邮箱+密码登录顺带验证）
    phone = Column(String(32), nullable=False, server_default=text("''::character varying"))  # 手机号（纯11位，+86 归一）
    phone_verified_at = Column(DateTime, nullable=True)      # 手机号验证时间（手机码登录/注册/绑定）
```

- [ ] **Step 2: 新实体文件**

```python
from datetime import UTC, datetime
from sqlalchemy import Column, DateTime, Integer, text
from sqlalchemy.dialects.postgresql import JSONB

from internal.extension.database_extension import db
from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class MailConfig(Base):
    """邮件发送配置（单行，id=1）"""
    __tablename__ = "mail_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    configs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class SmsConfig(Base):
    """短信发送配置（单行，id=1）"""
    __tablename__ = "sms_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    configs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
```

- [ ] **Step 3: 验证**

```bash
docker exec llmops-api python -c "from internal.model.account import Account; from internal.model.auth_channel_config import MailConfig, SmsConfig; print([c.name for c in Account.__table__.columns if c.name in ('phone','phone_verified_at','email_verified_at')]); print(MailConfig.__tablename__, SmsConfig.__tablename__)"
```

- [ ] **Step 4: Commit**

```bash
git add api/internal/model/account.py api/internal/model/auth_channel_config.py
git commit -m "feat(auth): ORM for phone/verified_at columns and mail/sms config tables"
```

---

### Task 3: 邮件配置服务 + SMTP 动态化 + admin 接口

**Files:**
- Create: `api/internal/service/mail_config_service.py`
- Modify: `api/internal/task/email_task.py`（DB 配置优先）
- Modify: `api/app/http/admin_routes_8.py`（GET/PUT/test）
- Modify: `api/app/http/support.py`（权限登记 `mail-config` → `system_config:manage`）

- [ ] **Step 1: 失败测试（service）**

```python
def test_mail_config_update_and_get_roundtrip(fake_session_factory):
    svc = MailConfigService(session=fake_session_factory)
    payload = {
        "smtp_host": "smtp.qq.com", "smtp_port": "587", "use_tls": "true",
        "username": "noreply@x.com", "password": "authcode",
        "default_sender": "noreply@x.com", "from_name": "平台", "timeout": "30",
    }
    svc.update_config(payload)
    cfg = svc.get_config()
    assert cfg["smtp_host"] == "smtp.qq.com"
    assert cfg["use_tls"] is True
```

- [ ] **Step 2: 实现 `mail_config_service.py`**

```python
"""邮箱发送配置服务：单行 JSONB 存储（id=1），env 兜底。"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

from internal.extension.database_extension import db
from internal.model.auth_channel_config import MailConfig

DEFAULT_KEYS = {
    "smtp_host": "", "smtp_port": "587", "use_tls": True, "use_ssl": False,
    "username": "", "password": "", "default_sender": "", "from_name": "", "timeout": "30",
}

_STR_KEYS = {"smtp_host", "smtp_port", "username", "password", "default_sender", "from_name", "timeout"}
_BOOL_KEYS = {"use_tls", "use_ssl"}


class MailConfigService:
    def __init__(self, session=None):
        self.session = session or db.session

    def _row(self):
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
        return cfg

    def send_test(self, *, recipient: str) -> dict:
        cfg = self.get_config()
        if not recipient:
            raise ValueError("收件邮箱不能为空")
        result = send_smtp(cfg, recipients=[recipient],
                           subject="【系统测试】邮件通道配置验证",
                           body="这是一封测试邮件：邮件通道配置成功。",
                           html="<h3>邮件通道配置成功</h3>")
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
```

- [ ] **Step 3: email_task 改造为纯 DB 配置**

在 `send_verification_email_task` 中，邮件发送主体替换为：

```python
    from internal.service.mail_config_service import MailConfigService, send_smtp
    ...
    try:
        cfg = MailConfigService().get_config()
        if not cfg.get("smtp_host"):
            raise RuntimeError("邮件发送未配置")
        send_smtp(cfg, recipients=[email], subject=subject, body=body, html=html)
    except RuntimeError:
        redis_client.delete(EmailService._send_pending_key(email, scene))
        redis_client.delete(EmailService._send_pending_ip_key(client_ip, scene))
        raise FailException("邮件发送未配置，请联系管理员配置邮件通道")
```

（不再使用 `injector.get(Mail)` env 初始化的发信路径：`injector.get(Mail)` 相关 import 与 `original_server` IPv4 处理逻辑一并移除；`email_task` 的 import 精简为 `EmailService`/`MailConfigService`/`send_smtp`/`redis_client`。）

- [ ] **Step 4: admin 接口（admin_routes_8.py 追加）**

```python
    @quart_app.get("/admin/mail-config")
    async def admin_mail_config_get():
        from app.http import asgi_app as a
        admin, err = await a._resolve_admin_permission("system_config:manage")
        if err is not None:
            return err
        from internal.service.mail_config_service import MailConfigService
        cfg = await a._to_thread(a._get_service(MailConfigService).get_config)
        return a._ok({"configs": cfg})

    @quart_app.put("/admin/mail-config")
    async def admin_mail_config_put():
        from app.http import asgi_app as a
        admin, err = await a._resolve_admin_permission("system_config:manage")
        if err is not None:
            return err
        payload = await request.get_json(force=True, silent=True) or {}
        from internal.service.mail_config_service import MailConfigService
        try:
            cfg = await a._to_thread(a._get_service(MailConfigService).update_config, payload.get("configs") or {})
        except ValueError as exc:
            return a._json_resp(code="validate_error", message=str(exc), data={"configs": [str(exc)]}, status=400)
        return a._ok({"configs": cfg})

    @quart_app.post("/admin/mail-config/test")
    async def admin_mail_config_test():
        from app.http import asgi_app as a
        admin, err = await a._resolve_admin_permission("system_config:manage")
        if err is not None:
            return err
        payload = await request.get_json(force=True, silent=True) or {}
        to = str(payload.get("to") or "").strip()
        from internal.service.mail_config_service import MailConfigService
        try:
            result = await a._to_thread(a._get_service(MailConfigService).send_test, recipient=to)
        except Exception as exc:
            return a._ok({"ok": False, "detail": f"{type(exc).__name__}: {str(exc)[:200]}"})
        return a._ok(result)
```

`support._admin_route_permission` 登记 `mail-config` → `system_config:manage`。若无 `system_config:manage` 权限码，先查 support 现有权限清单复用相近权限（如 `storage:manage`/`payment_config:manage` 同级的通用权限码），在报告说明实际采用的权限码。

- [ ] **Step 5: 测试**

```bash
docker exec -w /app/api llmops-api python -m pytest test/internal/service/test_mail_config_service.py test/app/http/test_admin_routes_8.py -o addopts="" -p no:cacheprovider
```
（新建 test_mail_config_service.py 含 Step1 测试 + send_test 用 monkeypatch mock `send_smtp` 断言参数；cut 中如 SMTP 测试用 fake。）

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/mail_config_service.py api/internal/task/email_task.py api/app/http/admin_routes_8.py api/app/http/support.py api/test/internal/service/test_mail_config_service.py
git commit -m "feat(auth): mail config service, DB-first SMTP sending, admin config pages endpoints"
```

---

### Task 3b: 清理旧 MAIL_* env 配置（已并入 DB）

**Files:**
- Modify: `api/config/config.py`（删除 MAIL_* 属性与读取）
- Modify: `api/.env.example`（删除 MAIL_* 示例）
- Modify: `api/internal/extension/mail_extension.py`（去除 env 初始化路径，保留纯 SMTP 封装）
- Verify: 全局 grep `MAIL_` 确认无残留引用

- [ ] **Step 1: 失败测试（无 MAIL_ env 引用的静态检查）**

```bash
docker exec -w /app/api llmops-api grep -rn "MAIL_" app internal config 2>/dev/null | grep -v "mail_config\|mail-extension\|MAIL_TIMEOUT_CONTROL" || echo "no residuals"
# expected: no residuals（除 mail_config 相关与场景内文案外）
```

- [ ] **Step 2: 删除 config.py 中 MAIL_* 段**

`api/config/config.py` 中删除：

```python
        self.MAIL_SERVER = _get_env("MAIL_SERVER")
        self.MAIL_PORT = int(_get_env("MAIL_PORT")) if _get_env("MAIL_PORT") else 587
        self.MAIL_USE_TLS = _get_env("MAIL_USE_TLS", "false").lower() in ("true", "1", "yes")
        self.MAIL_USE_SSL = _get_env("MAIL_USE_SSL", "false").lower() in ("true", "1", "yes")
        self.MAIL_USERNAME = _get_env("MAIL_USERNAME")
        self.MAIL_PASSWORD = _get_env("MAIL_PASSWORD")
        self.MAIL_DEFAULT_SENDER = _get_env("MAIL_DEFAULT_SENDER")
        self.MAIL_TIMEOUT = int(_get_env("MAIL_TIMEOUT")) if _get_env("MAIL_TIMEOUT") else 30
```

（以实际代码为准整段删除；若个别配置（如 MAIL_TIMEOUT）仍被其他读取方使用，先确认再删，报告中说明处理。）

- [ ] **Step 3: 删除 .env.example MAIL_* 段**

`api/.env.example` 中删除 `MAIL_SERVER ... MAIL_TIMEOUT` 整段示例（含注释），替换为一行注释：

```
# 邮件/短信通道配置请通过管理后台「系统配置」板块填写（持久化到数据库）
```

- [ ] **Step 4: mail_extension 去 env**

`api/internal/extension/mail_extension.py`：删除基于 `current_app.config` 读取 MAIL_* 的初始化逻辑（如 `server=current_app.config.get("MAIL_SERVER")` 之类），保留 `Mail`/`Message` 的纯 SMTP 封装构造（`Mail(server=..., port=..., use_tls=..., use_ssl=..., username=..., password=..., default_sender=..., timeout=...)` 由调用方显式传参），并同步删除 `injector.get(Mail)` 的注册点（若存在）。

- [ ] **Step 5: 回归验证**

```bash
docker exec -w /app/api llmops-api python -m pytest test/internal/extension test/internal/task test/app/http/test_admin_routes_8.py test/internal/service/test_email_service.py -o addopts="" -p no:cacheprovider
```
（预期只有与本变更相关的既有 email 测试按新语义调整：不配置时抛"邮件发送未配置"。既有调用 `injector.get(Mail)` 的测试若存在需同步删/改。）

- [ ] **Step 6: Commit**

```bash
git add api/config/config.py api/.env.example api/internal/extension/mail_extension.py
git commit -m "refactor(auth): remove legacy MAIL_* env config, DB-only mail settings"
```

---

### Task 4: 短信适配器（阿里云/腾讯云）+ 配置服务 + admin

**Files:**
- Create: `api/internal/service/sms/aliyun.py`、`api/internal/service/sms/tencent.py`、`api/internal/service/sms_service.py`
- Modify: `api/app/http/admin_routes_8.py`（GET/PUT/test sms）+ `support.py`
- Test: `api/test/internal/service/test_sms_service.py`

- [ ] **Step 1: 失败测试（纯函数 build_request + 配置/发送路由）**

```python
from internal.service.sms.aliyun import build_aliyun_request
from internal.service.sms.tencent import build_tencent_request


def test_aliyun_build_request_shape():
    req = build_aliyun_request(
        access_key="AKID", access_secret="SECRET", sign_name="平台",
        phone="13800138000", template_code="SMS_1", params={"code": "123456"},
    )
    assert req["url"] == "https://dysmsapi.aliyuncs.com/"
    assert req["body"]["PhoneNumbers"] == "13800138000"
    assert req["body"]["SignName"] == "平台"
    assert "Signature" in req["body"]


def test_tencent_build_request_shape():
    req = build_tencent_request(
        access_key="AKID", access_secret="SECRET", region="ap-guangzhou",
        sign_name="平台", phone="13800138000", template_code="123456", params={"code": "123456"},
    )
    assert req["host"] == "sms.tencentcloudapi.com"
    assert "Authorization" in req["headers"]
    assert "13800138000" in req["body"]
```

- [ ] **Step 2: `aliyun.py`**

```python
"""阿里云短信 SendSms：RPC 签名（HMAC-SHA1 V1.0）—— 纯函数，供测试与发送。"""
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

ALIYUN_ENDPOINT = "https://dysmsapi.aliyuncs.com/"


def _percent_encode(s: str) -> str:
    from urllib.parse import quote_plus
    return quote_plus(s)


def build_aliyun_request(*, access_key, access_secret, sign_name, phone, template_code, params: dict) -> dict:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    common = {
        "AccessKeyId": access_key,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone,
        "RegionId": "cn-hangzhou",
        "SignName": sign_name,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": str(uuid.uuid4()),
        "SignatureVersion": "1.0",
        "TemplateCode": template_code,
        "TemplateParam": json.dumps(params, ensure_ascii=False),
        "Timestamp": ts,
        "Version": "2017-05-25",
    }
    sorted_keys = sorted(common.items())
    query = "&".join(f"{_percent_encode(k)}={_percent_encode(str(v))}" for k, v in sorted_keys)
    string_to_sign = f"GET&%2F&{_percent_encode(query)}"
    sign = hmac.new(
        (access_secret + "&").encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    import base64
    common["Signature"] = base64.b64encode(sign).decode("utf-8")
    return {"url": ALIYUN_ENDPOINT, "body": common}
```

- [ ] **Step 3: `tencent.py`**

```python
"""腾讯云短信 SendSms：TC3-HMAC-SHA256 签名 —— 纯函数返回 (url, headers, body)。"""
import hashlib
import hmac
import json
from datetime import UTC, datetime

TENCENT_HOST = "sms.tencentcloudapi.com"
TENCENT_SERVICE = "sms"
TC3_VERSION = "2021-01-11"


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def build_tencent_request(*, access_key, access_secret, region, sign_name, phone, template_code, params: dict) -> dict:
    ts = datetime.now(UTC)
    date = ts.strftime("%Y-%m-%d")
    timestamp = str(int(ts.timestamp()))
    payload_obj = {
        "PhoneNumberSet": [phone],
        "SmsSdkAppId": "",            # SDKAppID 由 control 侧配置传入（service 层填充）
        "SignName": sign_name,
        "TemplateId": template_code,
        "TemplateParamSet": [str(params.get("code", ""))],
        "SenderId": "",
    }
    body_str = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":"))
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{TENCENT_HOST}\nx-tc-action:send sms\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(body_str.encode("utf-8")).hexdigest()
    canonical_request = "\n".join(["POST", "/", "", canonical_headers, signed_headers, hashed_payload])
    credential_scope = f"{date}/{TENCENT_SERVICE}/tc3_request"
    string_to_sign = "\n".join(["TC3-HMAC-SHA256", timestamp, credential_scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
    secret_date = _hmac(("TC3" + access_secret).encode("utf-8"), date)
    secret_service = _hmac(secret_date, TENCENT_SERVICE)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"TC3-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "url": f"https://{TENCENT_HOST}/",
        "headers": {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": TENCENT_HOST,
            "X-TC-Action": "SendSms",
            "X-TC-Timestamp": timestamp,
            "X-TC-Version": TC3_VERSION,
            "X-TC-Region": region or "ap-guangzhou",
        },
        "body": body_str,
    }
```

> 实现时允许修正签名细节（阿里云 percent-encode 需按官方 RFC3986 规则；腾讯 X-TC-Action 正确值以官方文档为准），但保持纯函数签名 `build_*_request(...) -> dict` 不变，测试断言只检查结构/必填字段/含签名头，不做真实外呼。

- [ ] **Step 4: `sms_service.py`（配置读取 + 发送 + 测试）**

```python
"""短信发送服务：读 sms_config（provider: aliyun/tencent），httpx 发送。"""
from __future__ import annotations

import json

import httpx

from internal.extension.database_extension import db
from internal.model.auth_channel_config import SmsConfig
from internal.service.sms.aliyun import build_aliyun_request
from internal.service.sms.tencent import build_tencent_request

DEFAULTS = {"provider": "", "access_key": "", "access_secret": "", "sign_name": "", "region": "", "sdk_app_id": "", "verify_code_template": ""}


class SmsService:
    def __init__(self, session=None, http: httpx.Client | None = None):
        self.session = session or db.session
        self._http = http or httpx.Client(timeout=15)

    def _row(self):
        row = self.session.query(SmsConfig).filter(SmsConfig.id == 1).one_or_none()
        if row is None:
            row = SmsConfig(id=1, configs={})
            self.session.add(row)
            self.session.flush()
        return row

    def get_config(self) -> dict:
        cfg = dict(DEFAULTS)
        row = self._row()
        if row.configs:
            cfg.update({k: v for k, v in row.configs.items() if k in DEFAULTS})
        return cfg

    def update_config(self, payload: dict) -> dict:
        cfg = self.get_config()
        for k in DEFAULTS:
            if k not in payload:
                continue
            val = payload[k]
            if val is not None and str(val).strip() != "":
                cfg[k] = str(val).strip()
        if cfg["provider"] not in ("", "aliyun", "tencent"):
            raise ValueError("provider 仅支持 aliyun/tencent")
        if cfg["provider"] and not (cfg["access_key"] and cfg["access_secret"] and cfg["sign_name"] and cfg["verify_code_template"]):
            raise ValueError("开启短信需完整填写 access_key/access_secret/sign_name/验证码模板")
        row = self._row()
        row.configs = cfg
        return cfg

    def is_configured(self) -> bool:
        cfg = self.get_config()
        return bool(cfg["provider"] and cfg["access_key"] and cfg["verify_code_template"])

    def send_verification_code(self, phone: str, code: str) -> None:
        """发送短信验证码（供验证码统一入口调用）。"""
        cfg = self.get_config()
        if not self.is_configured():
            raise RuntimeError("短信发送未配置，请联系管理员配置短信通道")
        self._send(cfg, phone=phone, template_code=cfg["verify_code_template"], params={"code": code})

    def _send(self, cfg: dict, *, phone: str, template_code: str, params: dict) -> dict:
        provider = cfg["provider"]
        if provider == "aliyun":
            req = build_aliyun_request(access_key=cfg["access_key"], access_secret=cfg["access_secret"],
                                       sign_name=cfg["sign_name"], phone=phone, template_code=template_code, params=params)
            resp = self._http.post(req["url"], data=req["body"])
            body = resp.json()
            if body.get("Code") != "OK":
                raise RuntimeError(f"阿里云短信失败: {body.get('Code')} {body.get('Message', '')[:200]}")
            return {"provider": "aliyun", "code": body.get("Code")}
        if provider == "tencent":
            req = build_tencent_request(access_key=cfg["access_key"], access_secret=cfg["access_secret"], region=cfg.get("region", ""),
                                        sign_name=cfg["sign_name"], phone=phone, template_code=template_code, params=params)
            resp = self._http.post(req["url"], headers=req["headers"], content=req["body"])
            body = resp.json()
            err = (body.get("Response") or {}).get("Error")
            if err:
                raise RuntimeError(f"腾讯云短信失败: {err.get('Code')} {err.get('Message', '')[:200]}")
            return {"provider": "tencent", "code": "OK"}
        raise RuntimeError("短信发送未配置")

    def send_test(self, *, recipient: str) -> dict:
        cfg = self.get_config()
        if not self.is_configured():
            raise RuntimeError("短信发送未配置")
        return {"ok": True, **self._send(cfg, phone=recipient, template_code=cfg["verify_code_template"], params={"code": "123456"})}
```

- [ ] **Step 5: admin 接口（同 Task 3 模式：GET/PUT/POST /admin/sms-config + /admin/sms-config/test）+ support 权限登记（`sms-config` 同权限码）**

- [ ] **Step 6: 测试（mock httpx：断言阿里/腾讯请求被构造、返回 OK/异常传播）+ 全绿**

```bash
docker exec -w /app/api llmops-api python -m pytest test/internal/service/test_sms_service.py test/app/http/test_admin_routes_8.py -o addopts="" -p no:cacheprovider
```

- [ ] **Step 7: Commit**

```bash
git add api/internal/service/sms/ api/internal/service/sms_service.py api/app/http/admin_routes_8.py api/app/http/support.py api/test/internal/service/test_sms_service.py
git commit -m "feat(auth): sms config service with aliyun/tencent adapters and admin endpoints"
```

---

### Task 5: 脱敏工具 + 登录方式接口

**Files:**
- Create: `api/internal/lib/mask_utils.py`
- Modify: `api/app/http/account_auth_routes.py`（GET /auth/login-methods）

- [ ] **Step 1: 失败测试**

```python
from internal.lib.mask_utils import mask_email, mask_phone


def test_mask_email():
    assert mask_email("zhangsan@qq.com") == "zh***an@qq.com"


def test_mask_phone():
    assert mask_phone("13800138000") == "138****8000"
```

- [ ] **Step 2: 实现**

```python
"""脱敏工具。"""
import re


def mask_email(email: str) -> str:
    email = (email or "").strip()
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"{local}***@{domain}"
    return f"{local[:2]}***{local[-1:]}@{domain}"


def mask_phone(phone: str) -> str:
    phone = (phone or "").strip()
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"
```

（account_service 现有 `_mask_email` 改为调用 `mask_email`，消除重复。）

- [ ] **Step 3: login-methods 接口**

```python
    @quart_app.get("/auth/login-methods")
    async def async_login_methods() -> Response:
        payload = await _get_service(AccountService).login_methods()
        return _ok(payload)
```

服务实现：

```python
    def login_methods(self) -> dict[str, bool]:
        from internal.service.auth_switch_service import get_auth_switches
        sw = get_auth_switches()
        return {"email_enabled": sw["AUTH_EMAIL_ENABLED"], "phone_enabled": sw["AUTH_PHONE_ENABLED"], "challenge_enabled": sw["AUTH_LOGIN_CHALLENGE_ENABLED"]}
```

- [ ] **Step 4: 测试 + Commit**

```bash
docker exec -w /app/api llmops-api python -m pytest test/internal/service/ -k "mask or login_methods or auth_switch" -o addopts="" -p no:cacheprovider
git add api/internal/lib/mask_utils.py api/app/http/account_auth_routes.py api/internal/service/account_service.py api/test/...
git commit -m "feat(auth): mask utils and login-methods endpoint"
```

---

### Task 6: 认证开关读取 + 联动校验（admin flags 增强）

**Files:**
- Create: `api/internal/service/auth_switch_service.py`
- Modify: `api/app/http/admin_routes_8.py`（update_flag 后对 AUTH_* 联动校验）

- [ ] **Step 1: `auth_switch_service.py`**

```python
"""认证业务开关读取与联动校验。复用 orchestration_feature_flag 表。"""
from __future__ import annotations

from internal.extension.database_extension import db
from internal.model.orchestration_feature_flag import OrchestrationFeatureFlag

AUTH_CODES = ("AUTH_EMAIL_ENABLED", "AUTH_PHONE_ENABLED", "AUTH_LOGIN_CHALLENGE_ENABLED")
DEFAULTS = {"AUTH_EMAIL_ENABLED": True, "AUTH_PHONE_ENABLED": False, "AUTH_LOGIN_CHALLENGE_ENABLED": True}


def _flag_enabled(session, code: str, default: bool) -> bool:
    try:
        row = session.query(OrchestrationFeatureFlag).filter(OrchestrationFeatureFlag.code == code).one_or_none()
        if row is not None:
            return bool(row.enabled)
    except Exception:
        pass
    return default


def get_auth_switches(session=None) -> dict[str, bool]:
    session = session or db.session
    return {code: _flag_enabled(session, code, DEFAULTS[code]) for code in AUTH_CODES}


def validate_auth_switch_combination(switches: dict[str, bool]) -> str | None:
    """返回错误消息；None=通过。挑战开关需至少一个通道开启。"""
    if switches.get("AUTH_LOGIN_CHALLENGE_ENABLED") and not (
        switches.get("AUTH_EMAIL_ENABLED") or switches.get("AUTH_PHONE_ENABLED")
    ):
        return "新IP验证开关需至少启用邮箱或手机号通道之一"
    return None
```

- [ ] **Step 2: admin update_flag 联动校验（admin_routes_8.py 的 update handler 内、update_flag 调用前）**

```python
        from internal.service.auth_switch_service import AUTH_CODES, validate_auth_switch_combination
        if code in AUTH_CODES:
            svc = a._get_service(OrchestrationFeatureFlagService)
            flags = await a._to_thread(svc.list_flags)
            current = {f.code: bool(f.enabled) for f in flags}
            current[code] = enabled if code != "AUTH_LOGIN_CHALLENGE_ENABLED" or True else enabled
            current[code] = enabled
            err = validate_auth_switch_combination(current)
            if err:
                return a._json_resp(code="validate_error", message=err, data={"code": [err]}, status=400)
```

- [ ] **Step 3: 测试（组合校验：challenge on + 全通道 off → 拒绝；通道 on → 通过）+ Commit**

```bash
git add api/internal/service/auth_switch_service.py api/app/http/admin_routes_8.py api/test/internal/service/test_auth_switch_service.py
git commit -m "feat(auth): auth switches with challenge-on-needs-channel validation"
```

---

### Task 7: 统一发码 send-code 与手机/邮箱验证码登录注册（S2 主体）

**Files:**
- Modify: `api/internal/service/email_service.py`（新增场景常量 + `send_code` 统一入口加 SMS 路由）
- Modify: `api/internal/service/account_service.py`（`phone_code_login`、`email_code_login`、`phone_register_prepare/verify` 的调用封装）
- Modify: `api/app/http/account_auth_routes.py`（`/auth/send-code`、`/auth/phone-code-login`、`/auth/email-code-login`、`/auth/register/phone-prepare`、`/auth/register/phone-verify`）
- Schema: 新增校验在路由内（与既有路由风格一致，不建独立 schema 文件也可）

- [ ] **Step 1: 失败测试（服务层）**

```python
def test_phone_code_login_success_writes_verified(fake_session, monkeypatch):
    from internal.service.account_service import AccountService
    svc = AccountService(session=fake_session)
    existing = fake_session.add_account(phone="13800138000", password="hash")
    monkeypatch.setattr(svc, "_verify_phone_code", lambda *_a, **_k: None)  # stub
    cred = svc.phone_code_login(phone="13800138000", code="123456")
    assert existing.phone_verified_at is not None
```

- [ ] **Step 2: email_service 扩展（场景常量与方法）**

```python
    PHONE_REGISTER_SCENE = "phone_register"
    PHONE_LOGIN_SCENE = "phone_login"
    PHONE_BIND_SCENE = "phone_bind"
    EMAIL_LOGIN_SCENE = "email_login"
    EMAIL_VERIFY_SCENE = "email_verify"

    def send_code(self, scene: str, *, email: str | None = None, phone: str | None = None) -> str:
        """统一发码入口：按 email/phone 路由；通道开关校验在路由层完成。"""
        from internal.service.auth_switch_service import get_auth_switches
        switches = get_auth_switches()
        if phone:
            if not switches["AUTH_PHONE_ENABLED"]:
                raise FailException("手机号通道未开启，请联系管理员")
            from internal.service.sms_service import SmsService
            code = self.generate_verification_code()
            SmsService().send_verification_code(phone, code)
            from internal.extension.redis_extension import redis_client
            from datetime import timedelta
            redis_client.setex(self._code_key(phone, scene), timedelta(seconds=self.CODE_TTL_SECONDS), code)
            return ""
        if email:
            if not switches["AUTH_EMAIL_ENABLED"]:
                raise FailException("邮箱通道未开启，请联系管理员")
            return self.send_verification_code(email, scene=scene)
        raise FailException("email/phone 至少提供一个")
```

> `verify_code` 保持兼容：`verify_code(scene, *, email=None, phone=None, code)`——phone 传入时 key 使用 `{scene}:{phone}`，内部以统一 `_code_key(target, scene)` 判断。实现时若既有 verify_code 只接受 email，扩展签名为 `verify_code(scene, code, contact=None)` 的兼容写法（contact 可为 email 或 phone），保证既有调用不受影响。

- [ ] **Step 3: account_service 登录/注册方法**

```python
    def _verify_phone_code(self, phone: str, code: str) -> None:
        self.email_service.verify_code(self.email_service.PHONE_LOGIN_SCENE, code, contact=phone)

    def phone_code_login(self, phone: str, code: str):
        from internal.model.account import Account
        from internal.service.auth_switch_service import get_auth_switches
        if not get_auth_switches()["AUTH_PHONE_ENABLED"]:
            raise FailException("手机号通道未开启")
        self._verify_phone_code(phone, code)
        account = self.session.query(Account).filter(Account.phone == phone).one_or_none()
        if account is None:
            raise FailException("该手机号未注册，请先注册")
        if account.is_disabled:
            raise FailException("账号已被禁用")
        account.phone_verified_at = account.phone_verified_at or self._now()
        return self._complete_login(account, challenge_policy="skip")  # 验证码登录视为强验证

    def email_code_login(self, email: str, code: str):
        from internal.service.auth_switch_service import get_auth_switches
        if not get_auth_switches()["AUTH_EMAIL_ENABLED"]:
            raise FailException("邮箱通道未开启")
        self.email_service.verify_code(self.email_service.EMAIL_LOGIN_SCENE, code, contact=email)
        account = self.session.query(Account).filter(Account.email == email).one_or_none()
        if account is None:
            raise FailException("该邮箱未注册，请先注册")
        account.email_verified_at = account.email_verified_at or self._now()
        return self._complete_login(account, challenge_policy="skip")

    def phone_register(self, *, phone: str, code: str, username: str = "", password: str = ""):
        from internal.service.auth_switch_service import get_auth_switches
        if not get_auth_switches()["AUTH_PHONE_ENABLED"]:
            raise FailException("手机号通道未开启")
        self.email_service.verify_code(self.email_service.PHONE_REGISTER_SCENE, code, contact=phone)
        existing = self.session.query(Account).filter(Account.phone == phone).one_or_none()
        if existing:
            raise FailException("该手机号已注册，请直接登录")
        username = username.strip() or f"user_{phone[-4:]}_{uuid4().hex[:6]}"
        account = Account(username=username, name=username, email="", phone=phone,
                          phone_verified_at=self._now())
        if password:
            self._set_password(account, password)  # 既有密码哈希/盐逻辑复用
        self.session.add(account)
        self.session.flush()
        return self._complete_login(account, challenge_policy="skip")
```

> `_complete_login(account, challenge_policy="skip"|"auto"|"challenge")`：对齐既有签发凭证路径。实现时优先复用现有 `begin_login`/签发逻辑，增加参数控制是否跳过挑战（验证码登录 skip，密码登录 auto）。若改动面大，可采用"调用既有签发函数但绕过 `_should_require_login_challenge` 判定"的方式，保证三个新登录入口逻辑一致。

- [ ] **Step 4: 路由（account_auth_routes.py 追加，风格完全对齐现有路由：参数校验 + _to_thread + _ok）**

- `POST /auth/send-code`：`{scene, email?, phone?}` → scene 白名单（login_challenge/phone_register/phone_login/phone_bind/email_login/email_verify/password_reset/change_email/register）→ 调 `email_service.send_code(scene, email=, phone=)` → `_ok_msg("验证码已发送")`
- `POST /auth/phone-code-login`：`{phone, code}` → `phone_code_login` → `_ok(PasswordLoginResp().dump(cred))`
- `POST /auth/email-code-login`：`{email, code}` → `email_code_login` → `_ok(...)`
- `POST /auth/register/phone-prepare`：`{phone}` → 校验手机号格式 → `send_code('phone_register', phone=)` → `_ok_msg(...)`
- `POST /auth/register/phone-verify`：`{phone, code, username?, password?}` → `phone_register(...)` → `_ok(...)`

手机号校验：`re.fullmatch(r"1[3-9]\d{9}", phone)`；提交时对 `+86` 前缀归一（`phone = phone[3:] if phone.startswith("+86") else phone`）。

- [ ] **Step 5: password-login identifier 手机号兜底 + 顺带验证**

`get_account_by_identifier` 之后（account_service 登录路径）补充：

```python
        if account is None and re.fullmatch(r"1[3-9]\d{9}", normalized):
            from internal.service.auth_switch_service import get_auth_switches
            if get_auth_switches()["AUTH_PHONE_ENABLED"]:
                account = self.get_account_by_phone(normalized)
        # 登录成功后顺带验证（在密码校验通过后）
        if account and (is_email_login or account.identifier_was_phone) ...:
            if matched_by_email: account.email_verified_at = account.email_verified_at or now
            if matched_by_phone: account.phone_verified_at = account.phone_verified_at or now
```

（实现上：在 `get_account_by_identifier` 或登录成功分支记录匹配方式，仅在密码校验成功后写 verified。以最小侵入实现，避免破坏现有登录测试。）

- [ ] **Step 6: 测试 + Commit**

覆盖：手机登录成功/未注册/开关关、邮箱登录成功/未注册、手机注册（自动用户名/带密码）、identifier 手机兜底 + verified 写入、send-code 场景白名单与开关拦截。

```bash
docker exec -w /app/api llmops-api python -m pytest test/internal/service/test_account_service.py test/app/http/test_account_auth_routes.py test/internal/service/test_email_service.py -o addopts="" -p no:cacheprovider
git add api/internal/service/email_service.py api/internal/service/account_service.py api/app/http/account_auth_routes.py api/test/...
git commit -m "feat(auth): unified send-code + phone/email code login/register"
```

---

### Task 8: 手机号绑定/邮箱验证安全设置接口

**Files:**
- Modify: `api/internal/service/account_service.py`（bind/unbind phone、verify email）
- Modify: `api/app/http/account_auth_routes.py`（`/account/security/*`）

- [ ] **Step 1: 服务方法**

```python
    def send_bind_phone_code(self, account: Account, *, phone: str) -> str:
        from internal.service.auth_switch_service import get_auth_switches
        if not get_auth_switches()["AUTH_PHONE_ENABLED"]:
            raise FailException("手机号通道未开启")
        existing = self.session.query(Account).filter(Account.phone == phone, Account.id != account.id).one_or_none()
        if existing:
            raise FailException("该手机号已绑定其他账户")
        self.email_service.send_code(self.email_service.PHONE_BIND_SCENE, phone=phone)
        return ""

    def bind_phone(self, account: Account, *, phone: str, code: str) -> None:
        self.email_service.verify_code(self.email_service.PHONE_BIND_SCENE, code, contact=phone)
        existing = self.session.query(Account).filter(Account.phone == phone, Account.id != account.id).one_or_none()
        if existing:
            raise FailException("该手机号已绑定其他账户")
        account.phone = phone
        account.phone_verified_at = self._now()

    def unbind_phone(self, account: Account, *, code: str) -> None:
        if not account.phone:
            raise FailException("当前未绑定手机号")
        self.email_service.verify_code(self.email_service.PHONE_BIND_SCENE, code, contact=account.phone)
        if not account.email and not account.is_password_set:
            raise FailException("请先设置邮箱或密码再解绑手机号")
        account.phone = ""
        account.phone_verified_at = None

    def send_verify_email_code(self, account: Account) -> str:
        from internal.service.auth_switch_service import get_auth_switches
        if not get_auth_switches()["AUTH_EMAIL_ENABLED"]:
            raise FailException("邮箱通道未开启")
        if not account.email:
            raise FailException("尚未填写邮箱，请先在安全设置中绑定邮箱")
        self.email_service.send_code(self.email_service.EMAIL_VERIFY_SCENE, email=account.email)
        return ""

    def verify_email(self, account: Account, *, code: str) -> None:
        if not account.email:
            raise FailException("尚未填写邮箱")
        self.email_service.verify_code(self.email_service.EMAIL_VERIFY_SCENE, code, contact=account.email)
        account.email_verified_at = self._now()
```

（`unbind_phone` 复用 `PHONE_BIND_SCENE` 发到已绑手机号；`verify_email` 对应既有 `change_email` 场景可并存。）

- [ ] **Step 2: 路由（`/account/security/send-bind-phone-code`、`/account/security/bind-phone`、`/account/security/unbind-phone`、`/account/security/send-verify-email-code`、`/account/security/verify-email`）—— 复用现有 `/account/*` 路由的鉴权与 `_get_service` 模式，取当前登录账户。**

- [ ] **Step 3: 测试 + Commit**

```bash
git add api/internal/service/account_service.py api/app/http/account_auth_routes.py api/test/...
git commit -m "feat(auth): phone bind/unbind and email verify endpoints"
```

---

### S1+S2 完成检查

- [ ] 迁移可升级/回滚；`AUTH_*` 三开关就位
- [ ] mail/sms 配置 service + admin 测试发送可用（真实 SMTP/短信未配置时返回明确错误）
- [ ] 手机验证码登录/注册、邮箱验证码登录、password-login 手机兜底 + 顺带 verified 生效
- [ ] 开关联动校验在 admin 更新 AUTH_* 时生效
- [ ] `pytest`（上述涉及文件）全绿；`flask` 运行日志无 Traceback