# 邮件/短信通道与邮箱手机号登录注册、新IP验证开关设计

> 日期：2026-08-31
> 状态：已确认（业务开关板块 = 功能开关页新增分组；无通道账户跳过验证；短信供应商先阿里云+腾讯云）

## 1. 背景与问题

当前认证体系存在以下缺口：

1. **邮箱验证码发送不可用**：SMTP 配置只走 `MAIL_*` env（docker 未配置），后台无法配置 → "收不到码"。
2. **异地登录（新 IP）验证只支持邮箱码**：无邮箱账户（用户名+密码注册）无法收取 → 登录被卡死。
3. **无手机号能力**：`account` 无 phone 字段，无短信发送，无手机验证码登录/注册/绑定。
4. **开关缺失**：邮箱/手机号通道、新 IP 验证都没有启停开关。

## 2. 目标

1. 系统配置菜单新增**邮件发送配置**、**短信发送配置**两个板块（DB 持久化 + 测试发送，可即时验证）。
2. 登录/注册支持邮箱与手机号两个通道，各自有启停开关（放"功能开关"页面的**业务开关**分组统一管理）。
   - 邮箱开关开 → 邮箱+密码登录、邮箱验证码注册/登录/改密/绑定。
   - 手机开关开 → 手机号+验证码登录、注册、改密、绑定。
3. **新 IP 登录验证**做成开关；联动校验：该开关必须依赖至少一个通道开关开启。
4. 挑战弹窗按"已启用且已绑定的通道"展示：单通道直接显示脱敏目标并发码；双通道先选择；**无可用通道（未绑邮箱且未绑手机号）→ 跳过验证直接放行**（记安全日志）。
5. 补全**手机号绑定/换绑/解绑**功能，与邮箱绑定并列。

## 3. 术语

| 术语 | 含义 |
|---|---|
| 通道（channel） | 邮箱或手机号，用于接收验证码 / 作为登录标识 |
| 业务开关 | 认证类功能开关（邮箱/手机号/新IP验证），与编排类开关同表不同分组 |
| 挑战（challenge） | 异地新 IP 登录时的二次验证流程 |
| 脱敏 | 邮箱 `a***@x.com`、手机号 `138****8888` |
| 免密登录 | 凭验证码直接登录（手机或邮箱验证码），不输密码 |

## 4. 架构设计

### 4.1 数据模型

**account 表新增列**（迁移）：

```text
phone               VARCHAR(32)   NOT NULL DEFAULT ''    -- 手机号（含区号时存 +86 前缀或纯号，规范见 4.5）
phone_verified_at   DATETIME      NULL                    -- 手机号认证时间（绑定时写入）
email_verified_at   DATETIME      NULL                    -- 邮箱认证时间（邮箱验证码注册/绑定/已验证登录时写入）
```

索引：`account_phone_idx(UNIQUE)` 前缀索引（仅 phone != '' 唯一，Postgres 用 partial unique index `WHERE phone <> ''`）。

**mail_config 表**（单行配置，仿 storage_config 风格）：

```text
id            INTEGER  PK                 -- 固定为 1
configs       JSONB    NOT NULL DEFAULT '{}'   -- {"smtp_host":"smtp.qq.com","smtp_port":587,"use_tls":true,"use_ssl":false,"username":"","password":"","default_sender":"","from_name":"","timeout":30}
updated_at / created_at
```

**sms_config 表**（单行配置）：

```text
id            INTEGER  PK                 -- 固定为 1
configs       JSONB    NOT NULL DEFAULT '{}'   -- {"provider":"aliyun"|"tencent", "access_key":"", "access_secret":"", "sign_name":"", "region":"", "template_codes":{"verify_code":"SMS_XXXX"}}
updated_at / created_at
```

**业务开关**：复用 `orchestration_feature_flag` 表（code/enabled/risk_level/fallback_behavior 已存在，与编排开关同构）。新增三个 code（启动种子 + 迁移插入，默认值保持现状行为）：

| code | 默认 | 含义 |
|---|---|---|
| `AUTH_EMAIL_ENABLED` | true | 邮箱通道：邮箱+密码登录、邮箱验证码注册/登录/改密/换绑邮箱/挑战发码 |
| `AUTH_PHONE_ENABLED` | false | 手机通道：手机号+验证码登录/注册/改密/绑定/挑战发码 |
| `AUTH_LOGIN_CHALLENGE_ENABLED` | true | 异地新 IP 登录二次验证 |

**联动校验**（admin 更新任一开关时执行）：
- `AUTH_LOGIN_CHALLENGE_ENABLED=true` 且 `AUTH_EMAIL_ENABLED=false` 且 `AUTH_PHONE_ENABLED=false` → 拒绝（"新IP验证需至少启用邮箱或手机号通道"）。
- 开关服务端做同一校验（前端仅提示）。

### 4.2 邮件发送配置（mail_config）
- 服务 `mail_config_service`：`get_config()/update_config(payload)/send_test(to)`。
- 邮件发送改造：**邮件配置唯一来源为 DB（mail_config 表）**。`email_service`/`email_task` 发送时读取 DB 配置动态构建 SMTP；`smtp_host` 为空 → 抛"邮件发送未配置，请联系管理员在系统配置-邮件发送中填写"。
- **清理旧配置**：删除 `config.py` 中 `MAIL_SERVER/MAIL_PORT/MAIL_USE_TLS/MAIL_USE_SSL/MAIL_USERNAME/MAIL_PASSWORD/MAIL_DEFAULT_SENDER/MAIL_TIMEOUT` 的 env 读取、`api/.env.example` 中 `MAIL_*` 示例与 `mail_extension` 的 env 初始化路径（无其他调用方引用这些 env），避免双源不一致；`mail_extension` 保留为纯 SMTP 封装工具（实例化参数全部来自 DB 配置）。
- `send_test`: 向指定地址发一封测试邮件（标题【系统测试】邮件通道配置验证），返回成功/失败详情（SMTP 报错原文脱敏）。
- 校验表单：host 必填（配置时）、port 1-65535、use_tls 与 use_ssl 互斥（tls 优先）、username/password 可选（匿名 SMTP）、default_sender 必须是合法邮箱。

### 4.3 短信发送配置（sms_config）
- 供应商适配器：`sms_service.send_verification_code(phone, code, scene)` 按 `provider` 分发：
  - **阿里云**：`SendSms`（dysmsapi.aliyuncs.com，RPC 签名，JSON 响应）；参数 AccessKeyId/AccessSecret/SignName/PhoneNumbers/TemplateCode/TemplateParam。
  - **腾讯云**：`SendSms`（sms.tencentcloudapi.com，TC3-HMAC-SHA256 签名）；同上。
  - 实现方式：用项目已有的 `httpx` 直连 REST API + 内置签名算法（阿里云 HMAC-SHA1 V1.0、腾讯云 TC3-HMAC-SHA256），**不引入重量级官方 SDK**；两适配器独立模块 `internal/service/sms/aliyun_*.py` `tencent_*.py`，共享 `sms_service` 入口。
- 模板：`template_codes.verify_code`（阿里云 `SMS_xxx` / 腾讯云模版 ID），参数统一 `{"code": "123456"}`；短信正文由模板决定（建议模板含"5分钟内有效"）。
- 配置校验：provider ∈ (aliyun, tencent)；access_key/secret 必填；sign_name 必填；verify_code 模板必填。
- `send_test`: 向指定手机发测试短信（复用 verify_code 模板），返回成功/失败详情（供应商返回码原文脱敏）。
- provider 未配置/`{}`：视为短信未启用，`sms_service` 抛"短信发送未配置"。

### 4.4 验证码通道统一

现有 `email_service`（SMTP + Redis + 频率限制）扩展为 `verification_service` 语义（保留 email_service 兼容名与既有场景）：

- 新增场景常量：`email_login` / `email_verify`（验证已填邮箱）/ `phone_login` / `phone_register` / `phone_bind` / `phone_unbind`（既有 `password_reset` / `change_email` / `login_challenge` / `register` 保留）。
- 新增统一发送入口 `send_code(scene, *, email=None, phone=None)`：
  - 据 `email/phone` 参数路由到 `email_service.send_verification_code` 或 `sms_service.send_verification_code`；
  - 通道启用校验：email 场景需 `AUTH_EMAIL_ENABLED`，phone 场景需 `AUTH_PHONE_ENABLED`，未启用抛引导错误。
- 验证码 Redis key、TTL（5 分钟）、60s 冷却、10 次/30 分/小时限制、5 次错误锁定等既有防爆破机制在 email/phone 上分别独立计数（`{scene}:{target}`）。
- 校验统一 `verify_code(scene, *, email=None, phone=None, code)`（保持既有签名兼容）。

### 4.5 手机号规范与脱敏
- 规范：优先纯 11 位中国大陆手机号（`1[3-9]\d{9}`）；支持 `+86` 前缀（校验时归一化存储为 `+86138...` 或去掉 `+86` 统一纯 11 位——**设计：统一存纯 11 位，校验时间接接受 +86**。国际号支持留待后续。
- 脱敏：`mask_email(email)`：`^(.{1,2})` 保留 + `***` + `@域名`；`mask_phone(phone)`：`前3 + **** + 后4`。工具放 `internal/lib/mask_utils.py`（邮箱脱敏逻辑从 account_service 现有实现收敛到此处，避免重复）。

### 4.6 登录/注册扩展

**登录**：
- `POST /auth/password-login`：identifier 解析扩展——先走现有（@→邮箱；否则 username），**username 不存在且串目为手机号且 `AUTH_PHONE_ENABLED`** → 按 phone 查。前端用 tab 显式区分，避免歧义。**登录成功顺带验证**：经邮箱匹配登录 → 写 `email_verified_at`（空则填）；经手机号匹配登录 → 写 `phone_verified_at`。密码登录即证明持有该标识，无需再走验证码。
- `POST /auth/phone-code-login`（`AUTH_PHONE_ENABLED` 才允许）：`{phone, code}` → `verify_code('phone_login', phone)` → 按 phone 查账户：存在则**直接登录**（验证码强验证，跳过 IP 挑战，`risk_reason=None`，签发凭证，更新 last_login）；不存在 → 明确错误"该手机号未注册，请先注册"。注册态手机号登录：注册页手机验证码流程（见下）。
- `POST /auth/email-code-login`（`AUTH_EMAIL_ENABLED` 才允许）：`{email, code}` → 验证码校验 → 按 email 查账户（存在登录 / 不存在引导注册）。邮箱验证码登录成功后写 `email_verified_at`。

**注册**：
- 现有 `register/direct`（用户名+密码+可选邀请码）保留；
- 邮箱验证码注册保留现有 `register/prepare` + `register/verify`（UI 此前未启用，本设计补前端 tab；成功写 `email_verified_at`）；
- 新增手机验证码注册：`POST /auth/register/phone-prepare`（`{phone, invite_code?}` → 发码，同 `phone_register` 场景）+ `POST /auth/register/phone-verify`（`{phone, code, username?, password?}` → 校验 → 创建账户并绑定 phone + `phone_verified_at`，username 可选自动生成 `user_xxxx`，password 可选——不设密码则仅支持验证码登录）。

**发送接口**：`POST /auth/send-code` `{scene, email?, phone?}` 作为统一发码入口（内部走 4.4），供登录/注册/改密/挑战/绑定复用；**既有的 `send-reset-code`/`register/prepare` 等接口保持兼容**（内部改走统一入口）。

### 4.7 异地登录挑战改造

触发判定保持现有 `_should_require_login_challenge`（新 IP 且历史会话无此 IP），但在 `begin_login` 处叠加开关与通道过滤：

1. `AUTH_LOGIN_CHALLENGE_ENABLED=false` → 不触发（直接登录）。
2. 收集该账户可用通道（**邮箱与手机号均要求已验证**）：
   - email：`AUTH_EMAIL_ENABLED=true` 且 `account.email != ''` 且 `email_verified_at` 非空。
   - phone：`AUTH_PHONE_ENABLED=true` 且 `account.phone != ''` 且 `phone_verified_at` 非空。
3. 无可用通道 → **跳过挑战**：直接签发凭证 + 安全日志 `challenge_skipped_no_channel(account_id, ip)`；不弹窗。（未验证但已填邮箱/手机号的账户同样跳过，登录后引导到安全设置完成验证/绑定。）
4. 单通道 → challenge 响应返回 `{challenge_id, channels:[{type:'email'|'phone', masked:'a***@x.com'|'138****8888'}]}`；前端弹窗显示脱敏目标 + "发送验证码"按钮（`send-code scene=login_challenge target=...`）。
5. 双通道 → 同上但 channels 含两项；前端先选择通道再发码。
6. `verify_login_challenge`：`{challenge_id, target(email|phone), code}` → 对应通道 `verify_code` → 删除 challenge → 签发凭证；`resend` 同 target 语义。
7. Redis challenge payload 增加 `channels` 快照（防挑战期内通道变化）。

### 4.8 手机号绑定（用户中心"安全设置"）

- `POST /account/security/send-bind-phone-code`：已登录用户，发起绑定/换绑，发 `phone_bind` 码（60s 冷却复用）；若已绑定手机号 → 需先验证旧号或密码（**决策：二次校验用当前密码或邮箱/手机验证码，与改邮箱流程对齐**）。
- `POST /account/security/bind-phone`：`{phone, code}` → 校验 → 写 `phone` + `phone_verified_at`（覆盖旧号视为换绑）。
- `POST /account/security/verify-email-code` / `bind-email`：现有改邮箱流程保留，补 `email_verified_at` 写入。
- `POST /account/security/send-verify-email-code` / `POST /account/security/verify-email`（新增）：对当前已填但未验证的邮箱发 `email_verify` 码并验证，写入 `email_verified_at`（供"填了邮箱从未验证"的账户补通道，避免长期处于挑战跳过状态）。
- `POST /account/security/unbind-phone`：`{code}`（发到当前手机号）→ 解绑；**约束**：解绑后账户仍须有至少一个登录通道（email 非空或 password 已设），否则拒绝（"请先设置邮箱或密码再解绑手机号"）。
- 前端用户中心"安全设置"卡片：显示脱敏邮箱/手机号 + 绑定状态徽标（已验证/未验证）+ 绑定/换绑/解绑操作。

## 5. 前端改动

1. **系统配置菜单**新增两个板块（AdminLayout systemConfig 分组）：
   - `/admin/mail-config` 邮件发送配置（AdminMailConfigView：表单 + 测试发送按钮 + 测试结果区）
   - `/admin/sms-config` 短信发送配置（AdminSmsConfigView：供应商下拉 + 密钥 + 签名/模板 + 测试发送）
2. **功能开关页**（OrchestrationFlagsView）新增 **业务开关** 分组：复用现有分组机制（按 code 白名单/前缀分类），展示 AUTH_* 三开关（开关状态/风险级提示/确认弹窗复用现有交互）；切换时前端提示联动规则（挑战开关需至少一个通道开关），后端保存时二次校验并返回错误。
3. **登录页 LoginForm**：
   - 登录表单类型 tabs：`账号密码`（现有）/ `手机验证码`（`AUTH_PHONE_ENABLED` 时显示）/ `邮箱验证码`（`AUTH_EMAIL_ENABLED` 时显示）；登录态通过 `/auth/login-methods` 接口按开关返回可用 tab（开关变化立即反映）。
   - 注册 tabs：`用户名密码`（现有）/ `邮箱验证码` / `手机验证码`。
   - 挑战弹窗：按 channels 渲染（单通道显示脱敏目标 + 发码；双通道先选择）；"收不到验证码？"引导：去绑定手机号/邮箱（跳到安全设置或注册页提示）。
4. **用户中心安全设置**：手机绑定/换绑/解绑 UI（与改邮箱 UI 并列）。路径沿用现有账户设置页或新增区块。

## 6. 接口清单（新增/变更）

| 方法/路径 | 说明 | 影响开关 |
|---|---|---|
| GET /auth/login-methods | 返回 `{email_enabled, phone_enabled, challenge_enabled}`（驱动 UI tabs） | - |
| POST /auth/send-code | 统一发码 `{scene, email?, phone?}` | AUTH_* |
| POST /auth/phone-code-login | 手机验证码免密登录 | AUTH_PHONE_ENABLED |
| POST /auth/email-code-login | 邮箱验证码免密登录 | AUTH_EMAIL_ENABLED |
| POST /auth/register/phone-prepare / phone-verify | 手机号验证码注册 | AUTH_PHONE_ENABLED |
| POST /auth/login-challenge/verify | 变更：支持 target(email/phone) | AUTH_LOGIN_CHALLENGE_ENABLED |
| POST /auth/login-challenge/resend | 变更：支持 target | 同上 |
| GET/PUT /admin/mail-config | 读/存邮件配置 | - |
| POST /admin/mail-config/test | 测试发送 {to} | - |
| GET/PUT /admin/sms-config | 读/存短信配置 | - |
| POST /admin/sms-config/test | 测试发送 {phone} | - |
| PATCH /admin/orchestration-flags/<code> | 变更：执行业务开关联动校验 | - |
| POST /account/security/send-bind-phone-code | 发绑手机码 | AUTH_PHONE_ENABLED |
| POST /account/security/bind-phone | 绑定/换绑 | 同上 |
| POST /account/security/unbind-phone | 解绑（需保留至少一通道） | 同上 |
| POST /account/security/send-verify-email-code / verify-email | 验证已填邮箱（补通道） | AUTH_EMAIL_ENABLED |
| POST /auth/password-login | 变更：identifier 支持手机号兜底 | AUTH_PHONE_ENABLED |

## 7. 测试策略

- 开关：默认值种子、联动校验（challenge 开需有通道、全关拒绝）、开关关闭后发码/登录被拦。
- 邮件：DB 配置优先 + env 兜底 + 双空报错；测试发送（mock smtplib）成功/失败详情。
- 短信：aliyun/tencent 适配器签名请求（mock httpx 断言请求参数/签名头）、未配置报错、测试发送。
- 验证码：phone/email 场景路由、各自防爆破计数（隔离）、TTL。
- 登录/注册：手机验证码登录（存在/不存在）、邮箱验证码登录、手机注册、identifier 手机号兜底、无密码账户仅验证码登录。
- 挑战：开关关不触发；无通道跳过+日志；**已填邮箱/手机号但未验证视为无通道→跳过**；邮箱+密码登录顺带写 `email_verified_at` 后再挑战走邮箱码；单通道脱敏；双通道选择；target 校验；verify/resend。
- 绑定：绑定、换绑（旧通道二次校验）、解绑约束（最后通道拒绝）；脱敏函数单测。
- 前端：登录 tabs 按开关渲染、挑战弹窗选择、绑定表单、配置页测试发送结果展示（vitest + mock）。
- E2E：NILL（有邮箱）新 IP 挑战→邮箱码；新建纯用户名账户（无通道）新 IP 登录直接放行；手机注册→登录→绑定完整链路。

## 8. 分期实施

- **S1 基础设施**：迁移（account 列 + mail/sms_config 表 + AUTH_* 种子）；mail_config/sms_config 服务与 admin 接口 + 测试发送；email_service 改读 DB 配置；sms 适配器（aliyun/tencent，httpx 直连）与 sms_service；脱敏工具。
- **S2 认证通道**：统一 send-code + verify；手机/邮箱验证码登录、手机注册、identifier 手机号兜底；登录方式接口；绑定/换绑/解绑手机号；email_verified_at 落库。
- **S3 挑战改造**：开关联动校验（admin flags 接口增强 + 种子默认值复核）；无通道跳过/单通道/双通道；verify/resend target 化。
- **S4 前端**：邮件/短信配置页；功能开关"业务开关"分组与联动提示；登录/注册 tabs；挑战弹窗改造；用户中心安全设置（手机绑定）。
- **S5 验收**：全量回归（后端 pytest + 前端 vitest + vue-tsc）+ E2E（NILL 挑战、无通道放行、手机注册登录绑定）+ graphify 更新。

## 9. 风险与兜底

- 短信费用/通道未开通：`provider` 未配置时验证码发送报错并引导后台配置；前端登录 tab 依赖开关（未开不显示）。
- 阿里云/腾讯云签名实现复杂：两适配器独立且以测试覆盖请求构造；签名失败报供应商原文（脱敏）。
- 无通道跳过验证的安全权衡：与决策一致——跳过时强制记安全日志（含 ip/ua），后续可扩展"跳过次数阈值"或"跳过需密码"策略。
- 手机号唯一性：partial unique index；绑定冲突提示"该手机号已绑定其他账户"。
- 既有邮箱功能兼容：升级后需在后台"系统配置-邮件发送"完成 SMTP 配置方可用邮件验证码（旧 `MAIL_*` env 不再读取）；配置保存即时生效，无需重启。