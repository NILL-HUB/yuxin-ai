# 认证通道 S3+S4+S5：挑战改造、前端与管理端界面、验收实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 异地登录挑战支持邮箱/手机双通道（无通道跳过）、业务开关联动、管理端邮件/短信配置页与"业务开关"分组、登录/注册/挑战前端改造、手机绑定 UI，最终全量验收。

**Architecture:** 挑战从"固定邮箱码"改为"通道感知"（创建时不发码、前端选通道后再发，Redis payload 存 channels/target）；开关机制复用 orchestration_feature_flag + 前端"功能开关"页新增 AUTH_* 分组；登录页按 `/auth/login-methods` 渲染 tabs；安全设置补手机绑定/邮箱验证。

**Tech Stack:** Vue3 / Arco Design / Quart / pytest / vitest / Playwright

**规范来源:** `docs/superpowers/specs/2026-08-31-auth-channel-login-challenge-design.md`

---

### Task 1: 挑战通道化改造（S3 主体）

**Files:**
- Modify: `api/internal/service/account_service.py`（begin_login 风险判定与 challenge 创建/验证/重发）
- Modify: `api/app/http/account_auth_routes.py`（/auth/login-challenge/verify|resend 增 target；/auth/send-code 支持 login_challenge scene）
- Test: `api/test/internal/service/test_account_service.py` 追加

- [ ] **Step 1: 失败测试**

```python
def test_begin_login_skips_challenge_when_no_verified_channel(fake_session, monkeypatch):
    from internal.service.account_service import AccountService
    svc = AccountService(session=fake_session)
    account = fake_session.add_account(username="plain", email="", phone="")
    account.last_login_ip = "1.1.1.1"
    account.last_login_at = now()
    monkeypatch.setattr(svc, "_is_unusual_login_ip", lambda *a, **k: True)
    monkeypatch.setattr(svc, "_normalize_ip", lambda ip: ip or "")
    monkeypatch.setattr("internal.service.auth_switch_service.get_auth_switches",
                       lambda **k: {"AUTH_EMAIL_ENABLED": True, "AUTH_PHONE_ENABLED": True, "AUTH_LOGIN_CHALLENGE_ENABLED": True})
    result = svc.begin_login(account, "2.2.2.2", user_agent="ua")
    assert result.get("challenge_required") is False


def test_begin_login_returns_multi_channels_when_both_verified(fake_session, monkeypatch):
    svc = AccountService(session=fake_session)
    account = fake_session.add_account(username="both", email="a@x.com", phone="13800138000")
    account.email_verified_at = now()
    account.phone_verified_at = now()
    monkeypatch.setattr(svc, "_is_unusual_login_ip", lambda *a, **k: True)
    monkeypatch.setattr(svc, "_normalize_ip", lambda ip: ip or "")
    monkeypatch.setattr("internal.service.auth_switch_service.get_auth_switches",
                       lambda **k: {"AUTH_EMAIL_ENABLED": True, "AUTH_PHONE_ENABLED": True, "AUTH_LOGIN_CHALLENGE_ENABLED": True})
    monkeypatch.setattr(svc.email_service, "send_login_challenge_code", lambda *a, **k: "")
    result = svc.begin_login(account, "2.2.2.2", user_agent="ua")
    assert result["challenge_required"] is True
    assert {c["type"] for c in result["channels"]} == {"email", "phone"}
```

- [ ] **Step 2: 实现**

在 `account_service` 内新增：

```python
    def _collect_challenge_channels(self, account: Account) -> list[dict]:
        from internal.service.auth_switch_service import get_auth_switches
        sw = get_auth_switches()
        channels = []
        if sw["AUTH_EMAIL_ENABLED"] and account.email and account.email_verified_at:
            channels.append({"type": "email", "masked": mask_email(account.email)})
        if sw["AUTH_PHONE_ENABLED"] and account.phone and account.phone_verified_at:
            channels.append({"type": "phone", "masked": mask_phone(account.phone)})
        return channels
```

`_should_require_login_challenge` 之前（begin_login 调用处）叠加开关：

```python
        from internal.service.auth_switch_service import get_auth_switches
        switches = get_auth_switches()
        if not switches.get("AUTH_LOGIN_CHALLENGE_ENABLED"):
            return self._complete_normal_login(...)   # 直接返回凭证（跳过挑战）
        if not self._should_require_login_challenge(account, client_ip):
            return self._complete_normal_login(...)
        channels = self._collect_challenge_channels(account)
        if not channels:
            self._log_auth_security("challenge_skipped_no_channel", account, client_ip)  # 安全日志
            return self._complete_normal_login(...)
        return self._create_login_challenge(account, risk_reason="new_ip", channels=channels)
```

`_create_login_challenge` 改造：

```python
    def _create_login_challenge(self, account: Account, *, risk_reason: str, channels: list[dict]) -> dict[str, Any]:
        challenge_id = str(uuid4())
        payload = {
            "account_id": str(account.id),
            "channels": channels,
            "target": None,
            "risk_reason": risk_reason,
            "created_at": int(self._now().replace(tzinfo=UTC).timestamp()),
        }
        redis_client.setex(self._login_challenge_key(challenge_id),
                           timedelta(seconds=self.LOGIN_CHALLENGE_TTL_SECONDS), json.dumps(payload))
        return {
            "challenge_required": True,
            "challenge_id": challenge_id,
            "challenge_type": "verification_code",
            "channels": channels,
            "risk_reason": risk_reason,
        }
```

> 注意：创建时**不再立即发码**。`_load_login_challenge` 的兼容校验（payload 需要有 account_id + channels；既有断言 `payload.get("email")` 改为 `payload.get("channels")`）。

新增发码/验证/重发（统一走 S1 Task 6 的 send_code + verify_code）：

```python
    def send_login_challenge_code(self, challenge_id: str, *, channel: str) -> dict:
        payload = self._load_login_challenge(challenge_id)
        channel_info = next((c for c in payload["channels"] if c["type"] == channel), None)
        if channel_info is None:
            raise FailException("验证通道无效，请刷新后重试")
        from internal.service.auth_switch_service import get_auth_switches
        sw = get_auth_switches()
        if channel == "phone":
            if not sw["AUTH_PHONE_ENABLED"]:
                raise FailException("手机号通道未开启")
            account = self.session.query(Account).filter(Account.id == UUID(payload["account_id"])).one_or_none()
            self.email_service.send_code(self.email_service.LOGIN_CHALLENGE_SCENE, phone=account.phone)
            payload["target"] = account.phone
        else:
            if not sw["AUTH_EMAIL_ENABLED"]:
                raise FailException("邮箱通道未开启")
            account = self.session.query(Account).filter(Account.id == UUID(payload["account_id"])).one_or_none()
            self.email_service.send_code(self.email_service.LOGIN_CHALLENGE_SCENE, email=account.email or payload["channels"][0].get("email", ""))
            payload["target"] = account.email
        redis_client.setex(self._login_challenge_key(challenge_id),
                           timedelta(seconds=self.LOGIN_CHALLENGE_TTL_SECONDS), json.dumps(payload))
        return {"challenge_id": challenge_id, "channel": channel, "masked": channel_info["masked"]}

    def verify_login_challenge(self, challenge_id: str, code: str, *, channel: str = "") -> Any:
        payload = self._load_login_challenge(challenge_id)
        target = payload.get("target") or (payload["channels"][0].get("target") if payload["channels"] else "")
        # target 兼容：channels 里存 email/phone 原值（_create 时写入），便于 verify
        account = self.session.query(Account).filter(Account.id == UUID(payload["account_id"])).one_or_none()
        if account is None:
            raise FailException("账号不存在")
        channel = channel or (payload["channels"][0]["type"] if payload["channels"] else "email")
        if channel == "phone":
            self.email_service.verify_code(self.email_service.LOGIN_CHALLENGE_SCENE, code, contact=account.phone)
        else:
            self.email_service.verify_code(self.email_service.LOGIN_CHALLENGE_SCENE, code, contact=account.email)
        redis_client.delete(self._login_challenge_key(challenge_id))
        return self._complete_login_after_challenge(account)  # 复用既有签发逻辑（skip_login_alert=True）
```

（`_create_login_challenge` 写入 channels 时同时把 `email`/`phone` 原值放进每条 channel 的 dict，如 `{"type":"email","masked":"a***@x.com","email":"a@x.com"}`，供发码/验证取用，避免再查库。）

路由变更：

- `POST /auth/login-challenge/verify`：body 增 `channel`（可选，缺省取 channels[0]）；调 `verify_login_challenge(challenge_id, code, channel=channel)`
- `POST /auth/login-challenge/resend`：body 增 `channel`（必填）；调 `send_login_challenge_code(challenge_id, channel=channel)`，返回 `_ok({"challenge_id":..., "channel":..., "masked":...})`
- `POST /auth/send-code` 对 `scene=login_challenge` 接受 `{challenge_id, channel}`：调 `send_login_challenge_code`（复用统一发码路由；前端挑战场景走它）。

- [ ] **Step 3: 测试 + Commit**

```bash
docker exec -w /app/api llmops-api python -m pytest test/internal/service/test_account_service.py test/app/http/test_account_auth_routes.py -o addopts="" -p no:cacheprovider
git add api/internal/service/account_service.py api/app/http/account_auth_routes.py api/test/...
git commit -m "feat(auth): channel-aware login challenge with no-channel skip"
```

---

### Task 2: 邮件/短信配置管理页（S4）

**Files:**
- Create: `ui/src/views/admin/AdminMailConfigView.vue`、`ui/src/views/admin/AdminSmsConfigView.vue`
- Create: `ui/src/services/admin-message-config.ts`
- Modify: `ui/src/layouts/AdminLayout.vue`（systemConfig 分组加两菜单项）
- Modify: `ui/src/router/index.ts`（两条路由）
- i18n: `ui/src/i18n/messages/zh-CN.ts` / `en-US.ts`（`admin.messageConfig.mail*` / `admin.messageConfig.sms*`）

- [ ] **Step 1: 增加菜单与路由（AdminLayout.vue systemConfig items 追加）**

```ts
{ to: '/admin/mail-config', label: t('admin.adminLayout.menu.mailConfig'), permission: 'system_config:manage' },
{ to: '/admin/sms-config', label: t('admin.adminLayout.menu.smsConfig'), permission: 'system_config:manage' },
```

router 注册 `/admin/mail-config` → `AdminMailConfigView`、`/admin/sms-config` → `AdminSmsConfigView`。

- [ ] **Step 2: service 封装（admin-message-config.ts）**

```ts
import { get, post, put } from '@/utils/request'

export interface MailConfigPayload {
  smtp_host: string
  smtp_port: string
  use_tls: boolean
  use_ssl: boolean
  username: string
  password: string
  default_sender: string
  from_name: string
  timeout: string
}
export function getMailConfig() { return get<{ configs: MailConfigPayload }>('/admin/mail-config') }
export function saveMailConfig(configs: MailConfigPayload) { return put<{ configs: MailConfigPayload }>('/admin/mail-config', { configs }) }
export function testMailSend(to: string) { return post<{ ok: boolean; detail?: string }>('/admin/mail-config/test', { to }) }

export interface SmsConfigPayload {
  provider: '' | 'aliyun' | 'tencent'
  access_key: string
  access_secret: string
  sign_name: string
  region: string
  sdk_app_id: string
  verify_code_template: string
}
export function getSmsConfig() { return get<{ configs: SmsConfigPayload }>('/admin/sms-config') }
export function saveSmsConfig(configs: SmsConfigPayload) { return put<{ configs: SmsConfigPayload }>('/admin/sms-config', { configs }) }
export function testSmsSend(phone: string) { return post<{ ok: boolean; detail?: string }>('/admin/sms-config/test', { phone }) }
```

- [ ] **Step 3: 视图（AdminMailConfigView.vue 要点，Arco 表单 + 保存 + 测试发送）**

```vue
      <a-form :model="form" layout="vertical">
        <a-form-item label="SMTP 服务器" field="smtp_host" :rules="[{ required: true, message: '必填' }]">
          <a-input v-model:value="form.smtp_host" placeholder="smtp.qq.com" />
        </a-form-item>
        <a-form-item label="端口" field="smtp_port"><a-input-number v-model:value="form.smtp_port" :min="1" :max="65535" /></a-form-item>
        <a-form-item label="TLS"><a-switch v-model:checked="form.use_tls" />
          <span style="margin-left:16px">SSL</span><a-switch v-model:checked="form.use_ssl" /></a-form-item>
        <a-form-item label="账号" field="username"><a-input v-model:value="form.username" /></a-form-item>
        <a-form-item label="授权码/密码" field="password"><a-input-password v-model:value="form.password" /></a-form-item>
        <a-form-item label="发件人" field="default_sender"><a-input v-model:value="form.default_sender" placeholder="noreply@x.com" /></a-form-item>
        <a-form-item label="发件人名称" field="from_name"><a-input v-model:value="form.from_name" /></a-form-item>
      </a-form>
      <a-space>
        <a-button type="primary" :loading="saving" @click="onSave">保存</a-button>
        <a-input v-model:value="testTo" placeholder="测试收件邮箱" style="width: 220px" />
        <a-button :loading="testing" @click="onTest">测试发送</a-button>
      </a-space>
      <a-alert v-if="testResult" :type="testResult.ok ? 'success' : 'error'" :content="String(testResult.detail ?? (testResult.ok ? '发送成功' : '发送失败'))" />
```

核心逻辑：mount 时 `getMailConfig()` 回填；保存 `saveMailConfig`；测试 `testMailSend(testTo)`（成功/失败展示供应商/异常原文）。

`AdminSmsConfigView.vue` 同构：provider 用 `a-radio-group`（aliyun/腾讯云/未配置）、access_key/access_secret 用输入框、sign_name、region（默认提示）、verify_code_template、测试发送输入手机号。保存/测试结果展示。

- [ ] **Step 4: vitest（两视图基本渲染+保存调用）+ vue-tsc 0 错误 + Commit**

```bash
cd ui && npx vitest run src/views/admin/__tests__/AdminMailConfigView.spec.ts src/views/admin/__tests__/AdminSmsConfigView.spec.ts && npx vue-tsc --noEmit
git add ui/src/views/admin/AdminMailConfigView.vue ui/src/views/admin/AdminSmsConfigView.vue ui/src/services/admin-message-config.ts ui/src/layouts/AdminLayout.vue ui/src/router/index.ts ui/src/i18n/messages/zh-CN.ts ui/src/i18n/messages/en-US.ts api/test 2>/dev/null; git add ui/src/views/admin/__tests__/AdminMailConfigView.spec.ts ui/src/views/admin/__tests__/AdminSmsConfigView.spec.ts
git commit -m "feat(admin-ui): mail & sms config pages with test send"
```

---

### Task 3: 功能开关页"业务开关"分组 + 联动提示（S4）

**Files:**
- Modify: `ui/src/views/admin/OrchestrationFlagsView.vue`（分组逻辑加 business）
- i18n: `admin.orchestrationFlags.businessGroup` 等键

- [ ] **Step 1: 分组扩展**

在 `groups` computed 增加 business 分组：

```ts
const AUTH_FLAG_CODES = ['AUTH_EMAIL_ENABLED', 'AUTH_PHONE_ENABLED', 'AUTH_LOGIN_CHALLENGE_ENABLED']
const authFlags = computed(() => flags.value.filter((f) => AUTH_FLAG_CODES.includes(f.code)))
// groups.push({ key: 'business', flags: authFlags.value })
```

`groupTitle` 增加：`if (key === 'business') return t('admin.orchestrationFlags.businessGroup')`（zh: 业务开关 / en: Business Flags）。

分组排序：business 放最前；`other` 分组过滤掉 AUTH_ 项（现有 `otherFlags` 已排除 POOL_GOVERNANCE 与 FEATURE，需再排除 AUTH_FLAG_CODES）。

- [ ] **Step 2: 联动提示（challenge 开关确认弹窗时）**

```ts
const AUTH_EMAIL = 'AUTH_EMAIL_ENABLED'
const AUTH_PHONE = 'AUTH_PHONE_ENABLED'
const AUTH_CHALLENGE = 'AUTH_LOGIN_CHALLENGE_ENABLED'
const challengeDepHint = computed(() => {
  // 挑战开启但邮箱+手机全关 → 展示红色提示
  if (confirmFlag.value?.code === AUTH_CHALLENGE && nextValue.value === true) {
    const emailOn = flags.value.find((f) => f.code === AUTH_EMAIL)?.enabled
    const phoneOn = flags.value.find((f) => f.code === AUTH_PHONE)?.enabled
    if (!emailOn && !phoneOn) return t('admin.orchestrationFlags.challengeNeedsChannel')
  }
  return ''
})
```

确认弹窗区域渲染该提示红字；后端拒绝时把 400 消息展示（现有错误处理复用）。

- [ ] **Step 3: 测试 + Commit**

```bash
cd ui && npx vitest run src/views/admin/__tests__/OrchestrationFlagsView.spec.ts
git add ui/src/views/admin/OrchestrationFlagsView.vue ui/src/views/admin/__tests__/OrchestrationFlagsView.spec.ts ui/src/i18n/messages/zh-CN.ts ui/src/i18n/messages/en-US.ts
git commit -m "feat(admin-ui): business flags group and challenge dependency hint"
```

---

### Task 4: 登录/注册/挑战前端改造（S4）

**Files:**
- Modify: `ui/src/services/auth.ts`（新接口封装）
- Modify: `ui/src/views/auth/components/LoginForm.vue`（登录 tabs / 注册 tabs / 挑战弹窗）
- i18n: auth 相关新键
- Test: `ui/src/views/auth/__tests__/LoginForm.spec.ts`

- [ ] **Step 1: auth.ts 新接口**

```ts
export function getLoginMethods() {
  return get<{ email_enabled: boolean; phone_enabled: boolean; challenge_enabled: boolean }>('/auth/login-methods')
}
export function sendCode(payload: { scene: string; email?: string; phone?: string; challenge_id?: string; channel?: string }) {
  return post<unknown>('/auth/send-code', payload)
}
export function phoneCodeLogin(payload: { phone: string; code: string }) {
  return post<CredentialResp>('/auth/phone-code-login', payload)
}
export function emailCodeLogin(payload: { email: string; code: string }) {
  return post<CredentialResp>('/auth/email-code-login', payload)
}
export function phoneRegisterRequest(payload: { phone: string }) {
  return post<unknown>('/auth/register/phone-prepare', payload)
}
export function phoneRegisterVerify(payload: { phone: string; code: string; username?: string; password?: string }) {
  return post<CredentialResp>('/auth/register/phone-verify', payload)
}
export function verifyLoginChallenge(payload: { challenge_id: string; target: string; channel: string; code: string }) {
  return post<CredentialResp>('/auth/login-challenge/verify', payload)
}
```

- [ ] **Step 2: LoginForm 交互改造（要点）**

- mount 时 `getLoginMethods()` → `methods` ref；`loginTab = 'password' | 'phone' | 'email'` 默认 password；phone tab 仅 `methods.phone_enabled` 显示，email tab 仅 `methods.email_enabled`。
- 登录 tab 切换渲染现有 password 表单 / 手机表单（phone + code + 获取验证码按钮 + 60s 倒计时，调 `sendCode({scene:'phone_login', phone})`）/ 邮箱表单（email + code，`sendCode({scene:'email_login', email})`）；提交分别走 `login()` / `phoneCodeLogin` / `emailCodeLogin`。
- 注册 tabs：现有 direct 注册 + `邮箱验证码`（复用现有 registerVerify 状态与 `register/prepare`）、`手机验证码`（新：phone → `phoneRegisterRequest` → 输码+可选 username/password → `phoneRegisterVerify`）。
- 挑战视图改造：后端 challenge 响应含 `channels`（`[{type,masked}]`）：
  - 单通道 → 直接显示"验证码已发送至 {masked}"并调 `sendCode({scene:'login_challenge', channel})` 触发发码（或展示"获取验证码"按钮）；
  - 双通道 → 先渲染两个选择卡（邮箱/手机，显示 masked），选择后激活发码；
  - 提交 `verifyLoginChallenge({challenge_id, target, channel, code})`。
- 验证码输入组件统一：6 位数字、倒计时重发复用现有改为 target 化。

测试断言：tabs 按 mock 的 login-methods 渲染/隐藏；挑战弹窗双通道选择后调 verify 带 channel。

- [ ] **Step 3: vitest + vue-tsc + Commit**

```bash
cd ui && npx vitest run src/views/auth/__tests__/LoginForm.spec.ts && npx vue-tsc --noEmit
git add ui/src/services/auth.ts ui/src/views/auth/components/LoginForm.vue ui/src/views/auth/__tests__/LoginForm.spec.ts ui/src/i18n/messages/zh-CN.ts ui/src/i18n/messages/en-US.ts
git commit -m "feat(web): login/register tabs and channel-aware challenge UI"
```

---

### Task 5: 用户中心安全设置——手机绑定/邮箱验证 UI（S4）

**Files:**
- 找到现有"账户设置/安全设置"用户页面（grep `change_email|修改邮箱|安全设置` 于 ui/src/views 定位）
- Modify: 该页面（或新增安全设置卡片区块）+ `ui/src/services/account-security.ts`
- i18n 键
- Test: 该页面 spec 追加

- [ ] **Step 1: service**

```ts
export function sendBindPhoneCode(phone: string) { return post<unknown>('/account/security/send-bind-phone-code', { phone }) }
export function bindPhone(phone: string, code: string) { return post<unknown>('/account/security/bind-phone', { phone, code }) }
export function unbindPhone(code: string) { return post<unknown>('/account/security/unbind-phone', { code }) }
export function sendVerifyEmailCode() { return post<unknown>('/account/security/send-verify-email-code', {}) }
export function verifyEmail(code: string) { return post<unknown>('/account/security/verify-email', { code }) }
```

- [ ] **Step 2: 安全设置区块（要点）**

- 展示两行：邮箱（脱敏由后端 profile 接口提供或前端 mask；标注"已验证/未验证"+ [验证邮箱] 按钮走 `sendVerifyEmailCode`→输码→`verifyEmail`）；手机号（[绑定/换绑] → 输入手机号→`sendBindPhoneCode`→输码→`bindPhone`；已绑定时显示后四位脱敏 + [解绑] → `unbindPhone`）。
- 校验与错误提示与页面既有风格一致。

- [ ] **Step 3: 测试 + Commit**

```bash
cd ui && npx vitest run <该页面spec> && npx vue-tsc --noEmit
git add <页面文件> ui/src/services/account-security.ts <spec> ui/src/i18n/messages/zh-CN.ts ui/src/i18n/messages/en-US.ts
git commit -m "feat(web): security settings phone bind and email verify"
```

---

### Task 6: 全量验收（S5）

**Files:** 临时验收脚本（验收后删除）

- [ ] **Step 1: 后端全量回归**

```bash
docker exec -w /app/api llmops-api python -m pytest test -o addopts="" -p no:cacheprovider -q 2>&1 | tail -10
```
基线：3525 passed / 4 failed（4 个已知环境性失败：test_v4a_patch CRLF、test_api_entrypoint workers、test_os_automation_worker ×2）。任何超出基线的失败：列出并整改。

- [ ] **Step 2: 前端全量**

```bash
cd ui && npx vitest run 2>&1 | tail -6 && npx vue-tsc --noEmit
```

- [ ] **Step 3: E2E（浏览器必要时降级 ASGI+DB 核验）**

场景：
1. NILL（有已验证邮箱）：从新 IP 登录 → challenge 弹窗（邮箱通道 masked）→ 收码（无真实邮件时用 Redis 直写验证码）→ 登录成功。
2. 纯用户名账户（无邮箱/手机）：新 IP 登录 → 直接放行（无 challenge），安全日志含 `challenge_skipped_no_channel`。
3. 手机注册 → 手机验证码登录 → 安全设置绑定手机号已在注册时绑定（profile 显示）+ 解绑按钮存在。
4. 管理端邮件配置页：保存配置 + 测试发送（无真实 SMTP 时断言返回"未配置"错误文案合理）。
5. 短信配置页：选择 aliyun 保存（缺密钥被拦），测试发送（未配置报错文案）。
6. 功能开关页：业务开关分组显示三开关；关闭邮箱+手机后开启挑战 → 后端拒绝并提示。

- [ ] **Step 4: graphify + 收尾提交**

```bash
python -m graphify update .
git add -A && git commit -m "feat(auth): auth channels verified end-to-end"
```

---

### S3-S5 完成检查

- [ ] 挑战：无通道跳过 / 单通道 / 双通道选择 / 开关联动全绿
- [ ] 管理端：邮件/短信配置页可保存与测试发送（错误文案明确）；功能开关业务分组 + 联动提示
- [ ] 用户端：登录 tabs、注册 tabs、挑战弹窗、安全设置绑定手机号可用
- [ ] 全量回归零新增失败 + E2E 6 场景通过