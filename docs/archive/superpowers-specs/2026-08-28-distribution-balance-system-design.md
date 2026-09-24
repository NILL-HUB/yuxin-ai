# 分销系统与余额体系设计

- 日期：2026-08-28
- 状态：待评审（v11：算力包自动续费改为按余量触发——余量≤套餐阈值%时自动复购同款；会员套餐按到期续）
- 范围：邀请码注册、一级分销佣金、余额/算力账户体系、统一订单与在线支付预留、余额购买、提现、售后退款、全套管理端面板、前端全量

## 1. 背景与目标

系统当前仅有「卡密兑换会员 + 算力值（CreditAccount）」体系，无真实支付、无余额、无分销。本设计在现有体系上扩展：

1. **邀请码注册机制**：新用户可凭老用户邀请码注册（分销开启时必填），支持扫码/分享链接带参预填；邀请码默认随机、可自定义、大小写不敏感去重。
2. **一级分销佣金**：A 邀请 B 后，B **每次支付购买权益**（卡密兑换权益卡 / 统一订单支付）按比例给 A 产生佣金（单次计税，形成复购循环）；A 直接下级满 5 人后佣金率 20%→30% 永久生效。
3. **余额体系**：余额=**真金白银**（充值+佣金共享一个余额账户），可**购买套餐/算力**、可**随时提现**、可**自动续费**。**余额不参与直接计费，只有算力值参与消费计费**（永久去除按量计费烧余额设定）。
4. **自动续费/连续包月**：**余额自动续费**（会员套餐按到期续、算力包按周期续）本轮实现，续费订单同样即时返佣；**微信/支付宝周期扣款预留位置**（模型与任务分支已留，SDK 接入后启用）。
5. **统一订单与完整支付链路**：余额购买与在线支付统一为 `purchase_order`；预置微信/支付宝渠道配置、网关适配器、回调验签、订单轮询；线上直购/充值 → 即时到账、即时结算返佣。
6. **售后管理**：退款申请 → 审核 → 权益回收 + 佣金回扣 + 资金回补，链路易审计。
7. **管理端全套**：订单管理、售后管理、分销管理、提现审核、支付配置、客户用户绑定、分销总开关、RBAC 权限码。
8. **前端全量**：注册页邀请码、会员页（余额/算力/分销中心/我的订单/售后/自动续费）、各管理端面板、i18n。

本轮真实资金入口为卡密兑换 + 线下提现打款；真实网关 SDK 密钥开通留待后续，但配置、订单、回调、返佣、退款链路全部预置。

## 2. 经济模型（货币与算力）

- **余额（元）**：共享钱包，**真金白银**，永不过期。入账来源=兑换「余额卡」充值 + 分销佣金；出账用途=**购买会员套餐/算力包**、**提现**（线下打款）。
- **套餐额度（算力）**：购买「会员套餐」获得，随套餐有效期，**到期作废清空**。
- **永久算力（算力）**：购买「永久算力包」获得，**永不过期**。
- **换算率**：1 元 = 100 算力（即 1 算力 = 0.01 元），用于定价换算与展示。
- **消费顺序与停止条件**：套餐额度 → 永久算力，两级自动无感切换；**两者均为 0 时停止工作与计费**，提醒用户充值算力。**余额不参与直接计费（永久去除"按量计费烧余额"设定），消费计费唯一凭算力值**；余额仅用于显式购买、提现、自动续费。
- **购买支付来源**（直接到权益）：① 卡密兑换权益卡；② 统一订单支付（直购，余额 / 在线支付）。「余额充值 top-up」仅充值余额（**卡密余额卡 / 在线支付充值**），不计税、不给权益。
- **单次计税原则**：佣金只对**权益购买支付**计税一次（卡密兑换 / 订单支付），同一笔购买只按支付金额 × rate 计税一次；余额充值 top-up、提现、算力消耗、平台赠量均不计税；退款时**回扣**该笔佣金（见 4.8）。

## 3. 数据模型

### 3.1 新增表（9 张）

| 表 | 关键字段 | 说明 |
|---|---|---|
| `referral_code` | account_id(UNIQUE)、code(UNIQUE，**统一大写存储，大小写不敏感**)、updated_at | 每用户 1 个邀请码；默认随机，可自定义 |
| `distribution_relation` | invitee_account_id(UNIQUE)、inviter_account_id、bound_at、source(`register/scan/admin`)、updated_by | 一级分销关系，每人最多 1 个上级 |
| `balance_account` | account_id(UNIQUE)、balance、total_recharged、total_commission、total_withdrawn、total_purchased、**high_rate_locked** | 共享余额钱包；high_rate_locked=满5人永久30% |
| `balance_transaction` | account_id、amount(±)、balance_after、**amount_type**(`recharge/commission/purchase/withdraw/refund/adjust`)、rate、source(`redeem_code/order`)、source_id、description | 余额流水；UNIQUE(source, source_id, amount_type) 幂等 |
| `withdrawal_request` | account_id、amount、status(`pending/approved/rejected/cancelled`)、reviewed_by/at、review_note | 提现申请；申请即扣余额挂起 |
| `payment_provider_config` | provider(`wechatpay/alipay`, UNIQUE)、name、configs(JSON，密钥加密)、enabled、updated_by | 支付渠道配置（两渠道可同时启用） |
| `purchase_order` | order_no(UNIQUE)、account_id、plan_id、**plan_type(`balance/membership/credits`)**、amount(Numeric12,2)、pay_method(`balance/wechatpay/alipay`)、**order_source(`normal/auto_renew`)**、status(`pending/paid/failed/closed/refunded`)、transaction_id、paid_at、refund_at | 统一订单：membership/credits 直购 + balance 在线充值；`pay_method=balance` 仅限直购（balance 型充值只能在线支付） |
| `return_request` | account_id、order_id、amount、reason、status(`pending/approved/rejected`)、reviewed_by/at、review_note | 退款申请（paid 直购未消耗订单 / 在线充值订单可退） |
| `auto_renewal` | account_id、plan_id、plan_type、pay_method(`balance/wechatpay/alipay`)、status(`active/paused/failed/cancelled`)、next_renew_at(仅 membership 用，可空)、last_renewed_at、renew_count、fail_count、created/updated | 自动续费（连续包月）；balance 本轮实现，wechatpay/alipay 预留 |

### 3.2 变更表

- `plan`：新增 `plan_type`（`balance/membership/credits`，默认 `membership`）、`auto_renew_threshold_percent`（算力包自动续费余量阈值%，默认 5，各套餐独立配置）：
  - `balance`：`price`=充值面额；`membership`：`duration_days`+`grant_token_credits`(套餐额度)；`credits`：`grant_token_credits`(永久算力含赠量)+`price`+`auto_renew_threshold_percent`
- `credit_account`：`permanent_credit`（存量 `balance` 迁移初值）、`quota_credit`（随会员过期清零）
- `credit_transaction`：`transaction_type` 支持 `plan_quota_grant/permanent_credit_grant/consume`

### 3.3 开关与权限

- 复用 `orchestration_feature_flag`，新增 `ENABLE_DISTRIBUTION`（默认 false）。
- RBAC 新权限码（写入权限目录迁移）：`distribution:view/manage`、`order:view/manage`、`refund:view/manage`、`payment_config:manage`、`withdraw:view/manage`。

## 4. 业务规则

### 4.1 邀请码注册

- 注册成功自动生成**随机邀请码**（全局唯一，规避已有码），格式与卡密 `OA-*` 区分。
- **用户可自定义**：`PUT /distribution/referral-code {code}` 修改自己的邀请码，规则：
  - 校验：长度 4–32；仅允许字母数字与 `-`/`_`；**统一转为大写后落库**，`abc` 与 `ABC` 视为同一码（大小写不敏感去重）；数据库中已存在（无论大小写）则拒绝。
  - 修改后旧码立即失效（旧分享链接随之失效），变更记录审计；随机生成器同样做唯一规避。
- **开关开启**：注册必填邀请码；校验存在/归属有效账户/非本账号，否则失败。
- **开关关闭**：邀请码可选；填写则绑定，不填为"无上级"用户。
- 两条注册路径（direct / verify）均支持 `invite_code`（输入统一大小写归一化后匹配）。
- 扫码/分享：`GET /auth/register/invite-info?code=xxx`；前端 `?invite=CODE` 预填置灰。相机扫码留待移动端。

### 4.2 卡密兑换（按 plan_type 入账）

- `balance`：余额 `+= price`（top-up，**不佣金**）。
- `membership`：会员时长叠加 + 套餐额度 `+= grant_token_credits`（**佣金=price×rate**）。
- `credits`：永久算力 `+= grant_token_credits`（**佣金=price×rate**）。
- 既有卡密唯一性与竞态保护保留。

### 4.3 消费与扣款顺序

- tokens → compute_units（1000 token=1）。
- 扣减：套餐额度（会员有效期内）→ 永久算力，自动切换。
- 两者均为 0 → `insufficient`（reason=`credits_exhausted`），停止工作与计费，提示充值。
- 消费写 credit_transaction(`consume`)，幂等基于 message_id/feature 现有机制。

### 4.4 分销佣金

- 一级分销：只取直接上级。
- **计税事件**：① 兑换权益卡（membership/credits 按 plan.price）；② **统一订单支付成功**（余额或在线支付，按订单金额，回调/扣款成功即结算）。
- **不计税**：余额充值 top-up、提现、算力消耗、赠量。
- **复购循环**：每月外部充 ¥100 → 余额购买包月 ¥100/月 → A 月得 ¥30（30% 单次）；A 收佣金 → 余额购买向其上级计税 → 佣金回流为购买。
- **比例**：默认 20%；直接下级 ≥5 置 `high_rate_locked=true` 永久 30%（不追溯历史）。
- **入账**：并入余额账户（amount_type=`commission`, source=`redeem_code|order`, source_id=幂等键，rate 记录），幂等防重；佣金/充值互通可提现。
- **不触发**：无上级、开关关闭、上级为管理员绑定/禁用账号（绑定校验阻止；存量关系仍结算）。

### 4.5 统一订单（余额购买 + 在线支付）

- **发起**：`POST /orders {plan_id, pay_method}`，校验套餐类型与支付方式匹配，创建 `pending` 订单（order_no 唯一）：
  - `plan_type=membership|credits`（直购权益）：
    - `pay_method=balance`：校验余额充足 → 余额 `-= amount`（amount_type=`purchase`, source=order）→ 订单置 `paid` → 授予权益 → **结算佣金**（幂等）。
    - `pay_method=wechatpay|alipay`：校验渠道已启用 → 调用适配器 `create_payment(order)` 生成支付参数（未接入时返回"渠道未开通"错误，桩保留）→ 等待回调。
  - `plan_type=balance`（**余额充值 top-up**）：`pay_method` 仅限 `wechatpay|alipay`（余额无法充值余额）→ 等待支付成功 → 余额 `+= amount`（amount_type=`recharge`, source=order）→ **不给权益、不返佣**（top-up 不计税）。
- **回调**：`POST /payments/notify/<provider>` → 适配器 `verify_callback` → 幂等置 `paid`、记录 transaction_id → 授予权益 → **结算佣金**。
- **本地联调**：`ALLOW_MOCK_PAYMENT=true`（默认 false）时 `POST /orders/<order_no>/mock-paid` 模拟支付成功。
- **取消**：`pending` 订单可 `POST /orders/<order_no>/cancel` → `closed`（仅在线支付）。
- **查询**：`GET /orders`（我的订单）、`GET /orders/<order_no>`（状态轮询）。

### 4.6 余额购买与提现

- 余额购买已并入 4.5 统一订单（`pay_method=balance`），余额 purchase 流水 + 订单 + 权益 + 佣金一致。
- 提现：`POST /balance/withdraw {amount}`（≥`MIN_WITHDRAW_AMOUNT`，默认 ¥10）→ 立即扣余额（amount_type=`withdraw`）挂 `pending` → 审核 approve=线下打款 / reject、用户 cancel=退款回余额（amount_type=`refund`）。

### 4.7 售后 / 退款

- **可退范围**：`paid` 订单（直购或在线充值）且：
  - 直购订单（membership/credits）：对应权益**未发生任何消耗**（无 consume 流水关联该订单授予的额度算力）。
  - 在线充值订单（balance）：直接可退（充值资金未产生购买）。
- **申请**：`POST /refunds {order_no, reason}` → 创建 `pending` 申请（同订单不可重复，幂等）。
- **审核 approved**：
  - 资金回补：余额购买直购 → 金额回余额（amount_type=`refund`, source=order）；在线充值 → **从余额扣回该金额**（amount_type=`refund`, 负向, source=order）并标记线下/未来网关退款，订单置 `refunded`。
  - 权益回收（仅直购）：`credits` 订单 → `permanent_credit -= grant`（不足则标记人工处理）；`membership` 订单 → 若本订单即当前会员来源且无叠加则终止会员并清零额度，叠加来源复杂场景转人工处理（审计）。
  - **佣金回扣（仅直购）**：向上级已结算的该笔佣金从上级余额扣回（amount_type=`refund`，source=order，幂等）；上级余额不足 → 订单置 `refund_hold` 状态交由人工处理（审计记录）。
- **审核 rejected** → 关闭申请，不动账。

### 4.8 自动续费 / 连续包月

- **开通**：`POST /auto-renewals {plan_id, pay_method}` → 校验套餐为 membership（按到期续）或 credits（按 `renew_cycle_days` 周期续）、`pay_method=balance` 本轮实现；`pay_method=wechatpay|alipay` **预留**（依赖网关周期扣款/预授权能力，未接入时明确返回"该渠道自动续费暂未开通"）。同一账户同一套餐仅一条活跃续费。
- **续费时机**：membership 于 `expires_at - 1 天` 尝试；credits 于 `next_renew_at` 到期尝试。
- **余额续费执行（Celery 定时任务）**：到时 → 校验活跃 → 走统一订单（`pay_method=balance`, `order_source=auto_renew`）→ 余额充足则扣款 + 授予权益（同 4.2/4.5 入账）+ **即时结算佣金**（购买即返，复购循环的"按月自动"形态）；余额不足则 `fail_count+=1`，到期日再补试一次；连续 3 次失败 → 状态置 `failed`（提示充值后可重试开启），并通知用户。
- **管理**：`GET /auto-renewals`（我的）；`POST /auto-renewals/<id>/pause|resume|cancel`；续费订单进入统一订单管理（`order_source=auto_renew` 可筛选）。
- 微信/支付宝自动续费：模型字段、任务分发分支 `switch(pay_method)` 均已预留，SDK 周期扣款能力接入后仅补实现。

### 4.9 管理端

- **分销总开关**：Feature Flag `ENABLE_DISTRIBUTION`（关闭=邀请码可选 + 停新增佣金；存量保留）。
- **客户用户绑定/换绑**：`PUT /admin/users/<uuid>/superior`；禁自绑/互为上下级；审计；只影响未来。
- **分销管理面板**：总览（绑定用户数、累计/本月佣金、平均下级数）、关系列表（用户/上级/来源/时间，搜索）、下级查看（点选用户展示直接下级）、佣金记录（用户/订单/金额/比例/时间，按上级筛选）。权限 `distribution:view/manage`。
- **订单管理面板**：订单列表（order_no/用户/渠道/套餐/金额/状态/时间，多条件筛选）+ 详情 + `pending` 手动关闭。权限 `order:view/manage`。
- **售后管理面板**：退款申请列表 + 审核（同意/驳回），处理详情含权益回收/佣金回扣流水。权限 `refund:view/manage`。
- **提现审核**：列表 + 通过/驳回，审计。权限 `withdraw:view/manage`。
- **支付配置**：微信/支付宝渠道 upsert（密钥加密、脱敏展示）与启停。权限 `payment_config:manage`。

## 5. API 设计

用户侧：
- `GET /auth/register/invite-info?code=xxx`、`POST /auth/register/direct|verify`（+invite_code）
- `GET /distribution/me`、`GET /distribution/subordinates`、`GET /distribution/commissions`、`PUT /distribution/referral-code {code}`（自定义邀请码）
- `GET /account/balance`（余额/算力分池）
- `POST /orders`、`GET /orders`、`GET /orders/<order_no>`、`POST /orders/<order_no>/cancel`、`POST /orders/<order_no>/mock-paid`（仅 dev）
- `POST /refunds {order_no, reason}`、`GET /refunds`（我的）
- `POST /balance/withdraw`、`GET /balance/withdrawals`
- `POST /auto-renewals {plan_id, pay_method}`、`GET /auto-renewals`、`POST /auto-renewals/<uuid>/pause|resume|cancel`
- `POST /payments/notify/<provider>`（网关回调）

管理侧：
- `GET /admin/users`（含 superior/subordinate_count）、`PUT /admin/users/<uuid>/superior`
- `GET /admin/distribution/overview`、`GET /admin/distribution/relations`、`GET /admin/distribution/commissions`
- `GET /admin/orders`、`GET /admin/orders/<uuid>`、`POST /admin/orders/<uuid>/close`
- `GET /admin/refunds`、`POST /admin/refunds/<uuid>/approve|reject`
- `GET /admin/withdrawals`、`POST /admin/withdrawals/<uuid>/approve|reject`
- `GET /admin/payment-configs`、`POST /admin/payment-configs/<provider>`、`POST /admin/payment-configs/<provider>/enable|disable`

## 6. 前端

- **注册页**：邀请码输入框（`?invite=` 预填置灰；开关必填联动）。
- **会员页**：余额卡片（充值/佣金分开展示 + **卡密/在线充值入口** + 购买入口 + 提现）、算力卡片（套餐额度/永久算力）、分销中心（邀请码展示 + **自定义修改** + 复制 + 分享链接/二维码 + 下级列表 + 佣金明细 + 佣金率）、购买弹窗（余额 / 微信 / 支付宝，渠道未配置置灰）、**我的订单 + 申请退款入口**、**自动续费管理（开通/暂停/恢复/取消；会员=到期续、算力包=余量≤阈值% 触发；下次触发条件与失败提示）**、算力耗尽充值引导。
- **管理端**：分销管理（总览/关系/佣金记录）、订单管理（列表/详情/关闭）、售后管理（退款审核）、提现审核、支付配置、客户用户绑定（抽屉）；各面板按 RBAC 权限码控制。
- **开关**：Feature Flag 页自动出现 `ENABLE_DISTRIBUTION`。
- **二维码**：优先后端 `qrcode` 库；前端链接复制按钮。
- i18n 文案（zh-CN/en-US）。

## 7. 错误处理

- 邀请码缺失/非法/归属禁用 → `400`（开关开启时）。
- 兑换/佣金/余额/订单/退款全部行锁 + 唯一索引幂等。
- 消费遇额度与永久算力均为 0 → `insufficient`（`credits_exhausted`），停止计费，流式输出充值引导。
- 订单：渠道未配置/未启用 → 明确错误码；余额不足 → `400`；回调重复幂等、验签失败 403。
- 退款：非 paid、已消耗、重复申请 → `400`；佣金回扣余额不足 → 订单 `refund_hold` 人工处理。
- 自动续费：余额不足 → 本次失败并计 `fail_count`，连续 3 次置 `failed` 并通知；渠道未支持（wechatpay/alipay）→ 明确"暂未开通"；同账户同套餐重复开通 → `400`。

## 8. 测试

- 服务单测：
  - 注册：开关 × 邀请码矩阵；invite-info；**自定义邀请码：长度/字符校验、大小写不敏感唯一（abc 与 ABC 视为重复拒绝）、随机生成规避已有码、修改后旧码失效**。
  - 卡密兑换：三 plan_type；额度过期清零。
  - 消费：顺序切换；双 0 停止（credits_exhausted）；无余额扣款；幂等。
  - 佣金：卡密兑换 / 订单支付（余额+在线）触发；top-up/提现/消耗不触发；20%→30% 锁定；单次计税；幂等；开关关闭；回扣逻辑。
  - 订单：创建（类型/支付方式匹配校验/渠道启用/order_no 唯一）；余额购买；**在线充值 order（plan_type=balance → 余额入账、不返佣、不给权益）**；mock-paid 回调（置 paid+权益/余额+返佣）；取消 pending；重复回调幂等。
  - 退款：仅未消耗可退；资金回补（余额/标记线退）；权益回收（永久算力扣回/会员终止）；佣金回扣（含余额不足 → refund_hold）；重复申请拦截。
  - 提现：申请/审核/驳回退款/取消；低于最小金额拦截。
  - 支付配置：upsert 加密落库/脱敏/启停；审计。
  - **自动续费：开通/重复拦截/暂停恢复取消；到期执行（订单+权益+佣金，order_source=auto_renew）；余额不足 fail_count → 连续 3 次 failed；wechatpay/alipay 明确"暂未开通"。**
  - 管理端：自绑/互为上下级拦截；换绑/解绑；面板数据正确。
- 路由测试：注册、/distribution/*、/orders/*、/refunds、/balance/*、/payments/*、admin 全部新端点。
- 迁移测试：存量 `credit_account.balance` → `permanent_credit` 保留。

## 9. 实施顺序（里程碑）

1. **P1 账户模型**：新表 + 迁移 + plan_type + credit_account 扩展 + 消费顺序改造。
2. **P2 卡密入账**：按 plan_type 入账；余额/额度/永久算力流水。
3. **P3 邀请码与注册**：referral/distribution、注册绑定、开关、invite-info。
4. **P4 佣金结算**：settle_commission（卡密+订单通用计税）+ 分销中心 API。
5. **P5 统一订单**：订单模型/创建（余额+在线）/回调/mock-paid/取消/轮询 + 支付渠道配置与适配器骨架。
6. **P6 自动续费**：auto_renewal 模型 + membership 到期续（Celery 每日扫描）+ credits 余量触发复购（消费后检测 + 周期兜底）+ 开通/暂停/恢复/取消 + 失败重试与通知；微信/支付宝分支预留。
7. **P7 提现与售后**：提现申请/审核；退款申请/审核 + 权益回收 + 佣金回扣 + refund_hold。
8. **P8 管理端**：分销管理/订单管理（含 auto_renew 筛选）/售后管理/提现审核/支付配置/客户绑定/feature flag/RBAC 权限码。
9. **P9 前端**：注册、会员页（余额/算力/分销中心/订单/退款/自动续费）、全部管理端面板、i18n。
10. **P10 测试与验证**：补齐单测/路由测试，跑通 pytest。

## 10. 非目标（本轮不做）

- 对接真实微信/支付宝网关 SDK 与正式密钥开通（适配器、配置、订单、回调、返佣、退款链路均已预置）。
- 微信/支付宝自动续费（周期扣款/预授权）真实开通——模型与任务分支已预留，余额自动续费本轮全功能。
- 移动端相机扫码。
- 部分消耗/超期订单的比例退款（仅支持"未消耗全额退款"，复杂场景人工处理）。