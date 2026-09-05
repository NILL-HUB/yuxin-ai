# 分销 / 余额 / 订单 / 自动续费 接口文档

> 对应实现：`api/app/http/commerce_routes.py`、`api/app/http/admin_commerce_routes.py`、`api/app/http/account_auth_routes.py`
> 规格：`docs/superpowers/specs/2026-08-28-distribution-balance-system-design.md`

## 通用约定

- 统一响应：`{ "code": "success", "message": "", "data": {...} }`；业务错误返回非 success code 与 HTTP 4xx/5xx。
- 认证：用户侧接口需登录态（Bearer）；管理侧接口需管理员登录态且配齐权限码（RBAC 种子见迁移 `fe1a2b3c4d5e`）。
- 分页：`paginator = { "total_record", "total_page", "current_page", "page_size" }`；入参 `current_page`、`page_size`（默认 1 / 20，上限 50）。
- 金额：Decimal，响应为 Number，展示保留 2 位小数；佣金率 `commission_rate` 字符串（如 `"0.20"`）。
- 分销总开关：`ENABLE_DISTRIBUTION`（feature flag，默认关闭）。关闭=邀请码可选 + 不产生新佣金；开启=注册邀请码必填 + 佣金结算生效。

## 一、用户侧接口

### 1. 注册与邀请码

| 方法/路径 | 说明 | 请求 | 响应要点 |
|---|---|---|---|
| `POST /auth/register/direct` | 直接注册 | `{username, password, invite_code?}` | `{access_token, expire_at}` |
| `POST /auth/register/verify` | 邮箱验证码注册 | `{email, password, code, username?, invite_code?}` | `{access_token, expire_at}` |
| `GET /auth/register/invite-info?code=` | 校验邀请码 + 注册必填状态 | — | `{valid, required, inviter_name}` |

邀请码：4–32 位，字母数字 + `-`/`_`，大小写不敏感（统一大写存储）；`?invite=CODE` 进入注册页时前端预填置灰。

| `POST /redeem-codes/redeem` | 卡密兑换 | `{code}` | `{plan, membership?, credit_account}` |

卡密按套餐 `plan_type` 入账：`balance`→余额充值（不返佣）；`membership`→会员时长+套餐额度（返佣）；`credits`→永久算力（返佣）。

### 2. 分销中心

| 方法/路径 | 说明 |
|---|---|
| `GET /distribution/me` | `{referral_code, share_url, superior{id,name}\|null, subordinate_count, high_rate_locked, commission_rate}` |
| `GET /distribution/subordinates?current_page&page_size` | `{list:[{id,name,bound_at,source}], paginator}`（直接下级，一级分销） |
| `GET /distribution/commissions?current_page&page_size` | `{list:[{id,amount,rate,source,source_id,description,created_at}], paginator}` |
| `PUT /distribution/referral-code` | `{code}` → 修改邀请码（唯一/大小写不敏感校验）→ 返回 `me` |
| `GET /distribution/qrcode` | 分享二维码 PNG（未装 qrcode 库则返回 `{share_url}`） |

### 3. 余额与算力

| 方法/路径 | 说明 |
|---|---|
| `GET /account/balance` | `{balance, recharge_balance, commission_balance, total_withdrawn, total_purchased, high_rate_locked, quota_credit, permanent_credit}` |
| `POST /balance/withdraw` | `{amount}` 申请提现（≥1 元，申请即扣余额挂起）→ `{id,amount,status,...}` |
| `GET /balance/withdrawals?status&current_page&page_size` | 我的提现记录 |
| `POST /balance/withdrawals/:id/cancel` | 取消待审核提现（金额回余额） |

余额=真金白银（充值+佣金共享），仅用于：购买套餐/算力、提现、自动续费；**不参与算力直接计费**（消费只烧套餐额度→永久算力，双 0 停止并引导充值）。

### 4. 套餐 / 统一订单 / 在线支付（预留）

| 方法/路径 | 说明 |
|---|---|
| `GET /plans` | 可购套餐列表（仅 active）：`{list:[{id,code,name,description,plan_type,duration_days,grant_token_credits,price,auto_renew_threshold_percent}]}` |
| `POST /orders` | `{plan_id, pay_method}`；`pay_method=balance/wechatpay/alipay`。规则：余额充值类订单仅支持在线渠道；直购支持余额/在线；在线渠道需已配置启用。余额即时支付返回 `{order:{...}, payment_params:null}`；在线返回订单 + `payment_params`（未接入 SDK 时明确报"支付渠道暂未开通"） |
| `GET /orders?current_page&page_size` | 我的订单：`{list:[{order_no,plan_id,plan_type,amount,pay_method,order_source,status,transaction_id,paid_at,created_at}], paginator}` |
| `GET /orders/:order_no` | 订单详情 |
| `POST /orders/:order_no/cancel` | 取消待支付订单（仅 pending→closed） |
| `POST /orders/:order_no/mock-paid` | 模拟支付成功（仅 `ALLOW_MOCK_PAYMENT=1` 时启用，联调用） |
| `POST /payments/notify/:provider` | 网关异步回调（provider=wechatpay/alipay；验签骨架，SDK 接入时补真实验签） |

订单状态：`pending / paid / failed / closed / refunded / refund_hold`；`order_source=normal/auto_renew`。
支付成功即履约+返佣：membership→会员+额度；credits→永久算力；balance 型→余额充值入账（不返佣、不给权益）。

### 5. 自动续费（连续包月）

| 方法/路径 | 说明 |
|---|---|
| `POST /auto-renewals` | `{plan_id, pay_method}`（`pay_method=balance` 本轮；微信/支付宝明确"暂未开通"；同套餐重复开通拦截） |
| `GET /auto-renewals` | `{list:[{id,plan_id,plan_name,plan_type,pay_method,status,trigger,threshold_percent,next_renew_at,last_renewed_at,renew_count,fail_count}]}`；`trigger=到期（membership）/余量（credits）` |
| `POST /auto-renewals/:id/pause\|resume\|cancel` | 状态流转；`cancelled` 后不可再操作 |

执行语义：membership=`expires_at-1天` 到期续；credits 余量触发=`permanent_credit ≤ grant×threshold%`（阈值按套餐配置，默认 5%），复购同一套餐；续费走统一订单（`pay_method=balance, order_source=auto_renew`）→扣余额+权益+**即时返佣**；余额不足计 `fail_count`，连续 3 次置 `failed` 并通知；Celery `run_auto_renewal_scan` 每小时兜底。

### 6. 售后退款

| 方法/路径 | 说明 |
|---|---|
| `POST /refunds` | `{order_no, reason}` 申请退款；直购订单要求支付后无任何算力消耗 |
| `GET /refunds?current_page&page_size` | `{list:[{id,order_no,plan_type,amount,reason,status,review_note,created_at}], paginator}` |

## 二、管理端接口（均需权限码）

| 方法/路径 | 权限码 | 说明 |
|---|---|---|
| `GET /admin/distribution/overview` | distribution:view | `{bound_users, commission_total, month_commission, inviter_users, distribution_enabled}` |
| `GET /admin/distribution/relations?current_page&page_size&inviter_id` | distribution:view | 全量绑定关系分页 |
| `GET /admin/distribution/commissions?user_id=&...` | distribution:view | 指定用户的佣金明细 |
| `PUT /admin/users/:id/superior` | distribution:manage | `{inviter_id}` 绑定或 `{inviter_id:null}` 解绑；自绑/互为上下级拦截；写审计 |
| `GET /admin/orders?status&order_source&account_id&...` | order:view | 订单列表（含 auto_renew 筛选） |
| `GET /admin/orders/:id` | order:view | 订单详情 |
| `POST /admin/orders/:id/close` | order:manage | 关闭待支付订单（写审计） |
| `GET /admin/withdrawals?status&...` | withdraw:view | 提现申请列表 |
| `POST /admin/withdrawals/:id/approve\|reject` | withdraw:manage | `{note?}` 审核（通过=线下打款；驳回=金额回余额，写审计） |
| `GET /admin/refunds?status&...` | refund:view | 退款申请列表 |
| `POST /admin/refunds/:id/approve\|reject` | refund:manage | `{note?}`；通过=资金回补+权益回收+**佣金回扣**（上级余额不足→订单 `refund_hold` 人工） |
| `GET /admin/payment-configs` | payment_config:read | 渠道列表（密钥脱敏；未配置自动补占位行） |
| `PUT /admin/payment-configs/:provider` | payment_config:manage | `{name?, configs{app_id,mch_id,mch_key,...}}`；密钥 Fernet 加密落库 |
| `POST /admin/payment-configs/:provider/enabled` | payment_config:manage | `{enabled}` 渠道启停 |

## 三、佣金规则速查

- 一级分销：A 邀请 B，B 的**每次权益购买支付**（卡密兑换权益卡 / 订单支付）按 `rate` 给 A 佣金，单次计税。
- 税率：默认 20%；A 直接下级满 5 人 → 永久锁定 30%（`balance_account.high_rate_locked`，不回退、不追溯既往）。
- 不计税：余额充值 top-up（卡密余额卡/在线充值）、提现、算力消耗、平台赠量、余额购买（购买已在支付时计税）。
- 佣金并入 A 的共享余额（`amount_type=commission`），可购买/提现/自动续费。
- 复购循环：佣金→余额→购买→再向 A 的上级计税；自动续费每期同样即时结算。
- 退款回扣：审核通过时从上级余额回扣佣金（`amount_type=refund`），不足置 `refund_hold`。

## 四、备用开关

- `ENABLE_DISTRIBUTION`：分销总开关（默认关闭）。
- `ALLOW_MOCK_PAYMENT`：`POST /orders/:no/mock-paid` 联调用（生产默认关闭）。