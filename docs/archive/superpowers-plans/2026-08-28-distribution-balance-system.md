# 分销系统与余额体系实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按规格 v11 全量实现「邀请码注册、一级分销佣金、余额/算力账户体系、统一订单、在线支付预留、售后退款、自动续费、全套管理端」。（规格：`docs/superpowers/specs/2026-08-28-distribution-balance-system-design.md`）

**Architecture:** 后端新增 9 张表（referral_code / distribution_relation / balance_account / balance_transaction / withdrawal_request / payment_provider_config / purchase_order / return_request / auto_renewal），4 个新服务（Distribution / Balance / Order / AutoRenewal / PaymentConfig）+ 管理端服务（AdminDistribution / AdminOrder / AdminRefund / AdminWithdraw），改造既有 account_service（注册绑定）、redeem_code_service（按 plan_type 入账）、credit_service（算力池消费顺序）、admin_customer_user_service（上级绑定）；前端在会员页扩展分销中心/余额/订单/自动续费，新增 5 个管理面板。

**Tech Stack:** Python Quart + SQLAlchemy + Alembic + Celery；Vue3 + Arco Design + Pinia + vue-i18n；Fernet(AES-256) 加密密钥。

**工作方式（用户要求）**：每个里程碑完成后执行测试并**回查**（对照规格逐条核对、清扫死代码/胶水代码）；互不干扰的子任务可派发子代理并行实现，但**必须核对子代理回报与实际代码一致性及需求符合度**。

---

## 文件结构总览

### 后端（api/）
| 文件 | 职责 |
|---|---|
| Create `internal/model/distribution.py` | 9 张新表模型 |
| Modify `internal/model/billing.py` | Plan+plan_type/auto_renew_threshold_percent；CreditAccount+permanent_credit/quota_credit |
| Modify `internal/model/__init__.py` | 注册新模型 |
| Create `internal/service/distribution_service.py` | 邀请码/关系/佣金率/分销中心 |
| Create `internal/service/balance_service.py` | 余额记账/提现 |
| Create `internal/service/order_service.py` | 统一订单/支付/授权/返佣 |
| Create `internal/service/auto_renewal_service.py` | 自动续费（到期货/余量触）+ 消费钩子 |
| Create `internal/service/payment_config_service.py` | 支付渠道配置（加密/脱敏） |
| Create `internal/service/admin_distribution_service.py` | 分销管理面板 |
| Create `internal/service/admin_order_service.py` | 订单管理面板 |
| Create `internal/service/admin_refund_service.py` | 售后/退款审核 |
| Create `internal/service/admin_withdraw_service.py` | 提现审核 |
| Modify `internal/service/credit_service.py` | 消费顺序（额度→永久算力→credits_exhausted）+ 消费后自动续费钩子 |
| Modify `internal/service/redeem_code_service.py` | 按 plan_type 入账 + 佣金钩子 |
| Modify `internal/service/account_service.py` | 注册接受 invite_code + 生成邀请码 + 绑关系 |
| Modify `internal/service/admin_customer_user_service.py` | 上级绑定/换绑 + 列表扩展 |
| Modify `internal/entity/orchestration_feature_flag_entity.py` | ENABLE_DISTRIBUTION 默认项 |
| Create `internal/schema/distribution_schema.py` | 分销/邀请码 schema |
| Create `internal/schema/balance_schema.py` | 余额/提现 schema |
| Create `internal/schema/order_schema.py` | 订单/退款/自动续费 schema |
| Create `internal/schema/admin_commerce_schema.py` | 管理面板 schema |
| Create `internal/schema/payment_config_schema.py` | 支付配置 schema |
| Create `app/http/commerce_routes.py` | 用户侧 /orders /payments /refunds /balance /distribution /auto-renewals |
| Modify `app/http/account_auth_routes.py` | 注册 invite_code + GET /auth/register/invite-info |
| Create `app/http/admin_commerce_routes.py` | admin 分销/订单/售后/提现/支付配置/上级绑定 |
| Modify `app/http/app.py` | 注册新路由模块、ensure defaults（支付配置） |
| Modify `app/http/module.py` | 绑定新服务 |
| Create `internal/task/auto_renewal_tasks.py` | Celery 周期扫描自动续费 |
| Modify `app/http/celery_app.py` | beat 登记自动续费扫描 |
| Create `internal/migration/versions/xxxx_add_commerce_distribution.py` | 全部新表 + 列变更 + RBAC 权限种子 |
| Modify `requirements.in/.txt` | 如引入 qrcode 则添加 |

### 前端（ui/）
| 文件 | 职责 |
|---|---|
| Create `src/models/distribution.ts`、`src/models/commerce.ts`、`src/models/payment-config.ts` | 类型 |
| Create `src/services/distribution.ts`、`src/services/commerce.ts`、`src/services/balance.ts`、`src/services/admin-commerce.ts`、`src/services/payment-config.ts` | API |
| Modify `src/services/admin-customer-users.ts` | 上级绑定 |
| Modify `src/hooks/use-auth.ts`、`src/services/auth.ts`、`src/models/auth.ts`、`src/views/auth/components/LoginForm.vue` | 注册邀请码 |
| Modify `src/views/membership/MembershipView.vue` | 余额/算力/分销中心/订单/退款/自动续费/购买弹窗 |
| Create `src/views/membership/components/`（DistributionCenter.vue、BalancePanel.vue、PurchaseDialog.vue、AutoRenewPanel.vue、OrdersPanel.vue） | 会员页子组件 |
| Create `src/views/admin/AdminDistributionView.vue`、`AdminOrdersView.vue`、`AdminRefundsView.vue`、`AdminWithdrawalsView.vue`、`AdminPaymentConfigView.vue` | 管理面板 |
| Modify `src/views/admin/CustomerUsersView.vue` | 上级绑定抽屉 |
| Modify `src/router/index.ts` | 管理路由 |
| Modify `src/i18n/messages/zh-CN.ts`、`en-US.ts` | 文案 |

### 测试（api/test/）
- `test_distribution_service.py`（邀请码/绑定/佣金率锁定）、`test_balance_service.py`、`test_order_service.py`、`test_auto_renewal_service.py`、`test_payment_config_service.py`、`test_admin_commerce.py`
- 扩展 `test_credit_service.py`（消费顺序/credits_exhausted/无余额扣款）、`test_redeem_code_service.py`（plan_type 入账）、`test_account_service.py`（注册绑定）、`test_admin_customer_user_service.py`（上级绑定）
- 路由测试：`test_commerce_routes.py`、扩展 `test_user_routes_9.py`、`test_admin_routes_*.py`

---

## P1 账户模型（新表 + 迁移 + 消费顺序）

### Task 1: 新模型 `internal/model/distribution.py`
**Files:** Create `api/internal/model/distribution.py`；Modify `api/internal/model/__init__.py`

- [ ] **Step 1: 写模型** 仿照 `billing.py` 风格（`pkg.sqlalchemy.Base`、`_utcnow_naive`、`PrimaryKeyConstraint/Index`）：

```python
# 关键表与字段（完整实现见需求，此处给出契约）
class ReferralCode(Base):
    __tablename__ = "referral_code"
    id = Column(UUID, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)          # UNIQUE
    code = Column(String(64), nullable=False)           # UNIQUE，统一大写存储（大小写不敏感）
    created_at / updated_at

class DistributionRelation(Base):
    __tablename__ = "distribution_relation"
    id / invitee_account_id(UNIQUE) / inviter_account_id / bound_at
    source = Column(String(32), default="register")     # register/scan/admin
    updated_by = Column(UUID, nullable=True)

class BalanceAccount(Base):
    __tablename__ = "balance_account"
    id / account_id(UNIQUE)
    balance = Column(Numeric(12, 2), server_default=text("0"))
    total_recharged / total_commission / total_withdrawn / total_purchased = Numeric(12,2)
    high_rate_locked = Column(Boolean, server_default=text("false"))

class BalanceTransaction(Base):
    __tablename__ = "balance_transaction"
    id / account_id / amount(Numeric12,2) / balance_after(Numeric12,2)
    amount_type = Column(String(32))   # recharge/commission/purchase/withdraw/refund/adjust
    rate = Column(Numeric(5, 2), nullable=True)  # 佣金比例
    source = Column(String(32))        # redeem_code/order
    source_id = Column(UUID)
    description = Column(String(1024))
    created_at
    # UNIQUE(source, source_id, amount_type)

class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_request"
    id / account_id / amount / status(pending/approved/rejected/cancelled)
    reviewed_by(UUID,nullable) / reviewed_at / review_note / created_at

class PaymentProviderConfig(Base):
    __tablename__ = "payment_provider_config"
    id / provider = Column(String(32), UNIQUE)   # wechatpay/alipay
    name / configs = Column(JSON, default={})     # 密钥 Fernet 加密存储
    enabled = Column(Boolean, default=False) / updated_by / created_at / updated_at

class PurchaseOrder(Base):
    __tablename__ = "purchase_order"
    id / order_no(String, UNIQUE) / account_id / plan_id / plan_type(balance/membership/credits)
    amount = Numeric(12,2) / pay_method(balance/wechatpay/alipay) / order_source(normal/auto_renew)
    status = Column(String(32), default="pending")   # pending/paid/failed/closed/refunded
    transaction_id(String, nullable) / paid_at / refund_at / client_ip / created_at / updated_at

class ReturnRequest(Base):
    __tablename__ = "return_request"
    id / account_id / order_id / amount / reason / status(pending/approved/rejected)
    reviewed_by / reviewed_at / review_note / created_at

class AutoRenewal(Base):
    __tablename__ = "auto_renewal"
    id / account_id / plan_id / plan_type / pay_method(balance/wechatpay/alipay)
    status = Column(String(32), default="active")  # active/paused/failed/cancelled
    next_renew_at(DateTime, nullable) / last_renewed_at / renew_count / fail_count
    created_at / updated_at
```

- [ ] **Step 2: 注册模型** 在 `internal/model/__init__.py` 的 import 与 `__all__` 追加 9 个模型（仿照 billing 行）。
- [ ] **Step 3: 改 billing.py** Plan 增加 `plan_type`（String(32), default `membership`）与 `auto_renew_threshold_percent`（BigInteger, default 5）；CreditAccount 增加 `permanent_credit`、`quota_credit`（BigInteger, default 0；保留原 `balance` 列作迁移源）。
- [ ] **Step 4: 写迁移** `internal/migration/versions/xxxx_add_commerce_distribution.py`：建 9 表 + plan 两列 + credit_account 两列 + 数据迁移 `UPDATE credit_account SET permanent_credit = balance WHERE balance > 0`。参照现有迁移（alembic op.create_table/op.add_column/op.execute）。
- [ ] **Step 5: 验证** `cd api && python -m pytest test/internal/model/test_model_properties.py test/internal/service/test_credit_service.py -q`；执行 `python scripts/run_migration.py`（或 alembic upgrade head）确认迁移可跑。
- [ ] **Step 6: Commit**

### Task 2: credit_service 消费顺序改造
**Files:** Modify `api/internal/service/credit_service.py`（`consume_for_message`/`consume_for_feature`）

- [ ] **Step 1: 写失败测试**（扩展 `test_credit_service.py`）——先扣 quota_credit、再扣 permanent_credit、双 0 返回 `insufficient=True, reason="credits_exhausted"`，**不发生余额扣款**；幂等保持。
- [ ] **Step 2: 实现** 扣减逻辑改为：

```python
def _apply_consume(self, credit_account, membership, compute_units):
    remaining = compute_units
    # 1) 套餐额度（会员有效期内）
    quota_used = 0
    if membership and membership.is_active and credit_account.quota_credit and credit_account.quota_credit > 0:
        quota_used = min(credit_account.quota_credit, remaining)
        credit_account.quota_credit -= quota_used
        remaining -= quota_used
    # 2) 永久算力
    perm_used = 0
    if remaining > 0 and credit_account.permanent_credit and credit_account.permanent_credit > 0:
        perm_used = min(credit_account.permanent_credit, remaining)
        credit_account.permanent_credit -= perm_used
        remaining -= perm_used
    insufficient = remaining > 0   # 双 0：停止工作与计费
    return {"quota_used": quota_used, "permanent_used": perm_used, "insufficient": insufficient,
            "reason": "credits_exhausted" if insufficient else None}
```

- [ ] **Step 3: 保留幂等**（现有 message_id / feature 幂等不变）；`insufficient` 结构化 reason 供流式提示。
- [ ] **Step 4: 测试通过** + 旧的"部分扣减放行"行为断言改成"双 0 → credits_exhausted"。
- [ ] **Step 5: 回查**：对照规格 4.3——切换无感、双 0 停止、绝无余额扣款；清扫自模型引入的胶水（如无用的 balance_after 计算）。
- [ ] **Step 6: Commit**

---

## P2 卡密入账（按 plan_type）+ 佣金钩子位

### Task 3: redeem_code_service 改造
**Files:** Modify `api/internal/service/redeem_code_service.py` + `internal/schema/redeem_code_schema.py`（PlanResp 增加 plan_type）

- [ ] **Step 1: 写失败测试**：三类型入账（balance→余额 recharge 流水；membership→额度+时长；credits→permanent_credit += grant）；结算阀口调用 DistributionService（先注入 stub 断言调用）。
- [ ] **Step 2: 实现** 在 `redeem()` 成功分支按 `plan.plan_type` 分流：调用 `BalanceService`/`CreditAccount` 更新；**仅 `membership`/`credits` 型**调用 `DistributionService.settle_commission_for_redeem(account_id, plan, redeem_code.id)`（`balance` 型不返佣，P4 落地前先留调用点，P4 补实现——本步先以 stub 注入，确保可测）。
- [ ] **Step 3: 测试通过**；**回查**：balance 型不返佣、不产权益；幂等唯一索引（source, source_id, amount_type）生效。
- [ ] **Step 4: Commit**

---

## P3 邀请码与注册绑定 + 开关

### Task 4: DistributionService（邀请码/关系/开关）
**Files:** Create `internal/service/distribution_service.py`

- [ ] **Step 1: 失败测试** `test_distribution_service.py`：随机邀请码生成唯一；`resolve_inviter_by_code`（大小写归一化）；`bind_superior` 规则（无上级可绑、禁自绑、禁互为上下级、register/scan/admin 来源）；`is_enabled()` 读 flag。
- [ ] **Step 2: 实现核心方法**：

```python
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 规避易混淆字符
def generate_plain_code(self) -> str:  # 随机 8 位，循环生成直到唯一
def normalize_code(code) -> str: return (code or "").strip().upper()
def resolve_inviter_by_code(self, code) -> Account | None   # normalized 精确匹配 + 账户 active
def bind_superior(self, invitee_id, inviter_id, source="register", operator_id=None) -> DistributionRelation
    # 校验：非相等、非互相(b 的上级是 a 且 a 的上级是 b)、inviter active；写审计（source=admin 时）
def ensure_referral_code(self, account_id) -> ReferralCode   # 懒生成
def update_referral_code(self, account_id, new_code) -> ReferralCode
    # 长度4-32、字符集[A-Z0-9-_]、大写归一、UNIQUE(含大小写归一)；记审计
def direct_subordinate_count(self, account_id) -> int
def commission_rate(self, balance_account, subordinate_count) -> Decimal
    # high_rate_locked=True → 0.30；否则 0.20；若 count>=5 置 lock
```

- [ ] **Step 3: Feature Flag** 在 `orchestration_feature_flag_entity.py` 的 `get_default_orchestration_feature_flags()` 追加 `ENABLE_DISTRIBUTION`（name/description/risk_level/fallback_behavior，enabled=False）。
- [ ] **Step 4: 测试通过**。**回查**：开关关闭=邀请码可选；开启=必填；存量无上级用户兼容；邀请码修改后旧码失效。
- [ ] **Step 5: Commit**

### Task 5: 注册链路改造
**Files:** Modify `account_service.py`（direct_register / register_by_email_code 增加 invite_code）、`account_auth_routes.py`（透传 invite_code + `GET /auth/register/invite-info`）、`redeem_code_schema.py` 或新 `distribution_schema.py`（InviteInfoResp）

- [ ] **Step 1: 失败测试**：开关开+缺邀请码→400；开+非法码→400；开+有效码→创建关系；关+无码→正常注册无上级；关+带码→照常绑定；`invite-info`（valid/required/inviter_name）。
- [ ] **Step 2: 实现** 注册方法末尾 `if invite_code: bind(account.id, resolved_inviter)`（先 resolve，开启时缺失直接 raise FailException）；`ensure_referral_code(account.id)`；`/auth/register/invite-info` 返回 `{valid, required(开关), inviter_name}`。
- [ ] **Step 3: 测试通过**；**回查**：OAuth 注册路径不受影响；邮箱验证码注册同样支持。
- [ ] **Step 4: Commit**

---

## P4 佣金结算 + 分销中心 API

### Task 6: BalanceService（余额记账）+ settle_commission 核心
**Files:** Create `internal/service/balance_service.py`；`internal/service/distribution_service.py` 内实现 `settle_commission`

- [ ] **Step 1: 失败测试** `test_balance_service.py` / `test_distribution_service.py`：
  - `credit_balance(account, amount, source, source_id, amount_type, rate)` 幂等（重复调用返回已有流水）；
  - 佣金比例：无 lock=0.20；count>=5 → 置 lock 且此后 0.30（不回退）；**不追溯历史**；
  - 单次计税反例：B 月充 100 买 100 → A 只得一单 30（无充值+购买双重）。
- [ ] **Step 2: 实现**

```python
# balance_service
def ensure_account(self, account_id) -> BalanceAccount
def ensure_transaction_idempotent(self, source, source_id, amount_type) -> BalanceTransaction | None
def credit(self, account_id, amount: Decimal, *, source, source_id, amount_type, rate=None, description="") -> BalanceTransaction
    # 行锁 account；balance+=amount；total_* 按 amount_type 累计；unique 索引兜底；IntegrityError→返回已有
def debit(self, account_id, amount, *, source, source_id, amount_type, description="") -> BalanceTransaction  # 校验足额

# distribution_service.settle_commission_for_redeem(account_id, plan, source_id)
relation = relation_of(account_id); if not relation: return None
if not is_enabled(): return None
ba = balance_service.ensure_account(relation.inviter_account_id)
rate = commission_rate(ba, direct_subordinate_count(inviter))
amount = (plan.price * rate).quantize(Decimal("0.01"))
if amount <= 0: return None
balance_service.credit(inviter, amount, source="redeem_code", source_id=source_id,
                       amount_type="commission", rate=rate, description=f"下级卡密兑换返佣 {rate:.0%}")

# settle_commission_for_order(account_id, order)  —— 同构，source="order", source_id=order.id
```

- [ ] **Step 3: 测试通过**；**回查**：top-up（balance 卡/在线充值）不触发；提现/消耗不触发；开关关闭后不新增；佣金并入余额账户 + amount_type=commission。
- [ ] **Step 4: Commit**

### Task 7: 分销中心 API（用户侧）
**Files:** Create `internal/schema/distribution_schema.py` + `app/http/commerce_routes.py`（本任务先注册 /distribution/* 段）

- [ ] **Step 1: 失败路由测试**：GET /distribution/me（referral_code/share_link/superior/subordinate_count/high_rate_locked/commission_rate）；GET /distribution/subordinates（分页）；GET /distribution/commissions（分页）；PUT /distribution/referral-code（自定义）；**GET /account/balance**（recharge_balance/commission_balance/balance/quota_credit/permanent_credit）；**GET /distribution/qrcode**（PNG 二维码，后端 `qrcode` 库生成——requirements.in/.txt 增加 `qrcode`；未装时仅返回分享链接）。
- [ ] **Step 2: 实现** 按 `user_routes_9.py` 的注册模式（`_get_service`、`a._to_thread`、RequestContext 取 account）。
- [ ] **Step 3: 测试通过**；注册 `commerce_routes.py` 于 `app.py`（仿 `user_routes_9` 注册段）。
- [ ] **Step 4: Commit**

---

## P5 统一订单 + 在线支付预留

### Task 8: 订单模型与创建/支付流转
**Files:** Create `internal/service/order_service.py` + `internal/schema/order_schema.py`；`internal/schema/payment_config_schema.py`

- [ ] **Step 1: 失败测试** `test_order_service.py`：
  - 创建校验：plan_type 匹配 pay_method（balance 型仅在线；直购允许 balance/在线）；渠道启用校验；order_no 唯一；
  - **余额直购**：扣余额(purchase 流水)→paid→权益（membership/credits 同 P2 入账）→上级佣金；
  - **在线回调/mock-paid**：验签（骨架）→paid→transaction_id→权益→佣金；重复回调幂等；验签失败 403；
  - **在线充值**：paid→余额 recharge 流水→无佣金无权益；
  - 取消 pending → closed（仅在线）。
- [ ] **Step 2: 实现** 关键方法：

```python
def create_order(self, account_id, plan_id, pay_method, order_source="normal") -> PurchaseOrder
def _grant_rights(self, order)   # membership: 会员叠加+quota_credit+=grant；credits: permanent_credit+=grant
def confirm_paid(self, order_no, transaction_id=None) -> PurchaseOrder  # 幂等：paid 已存在则直接返回
    # 按 order.plan_type 分流：直购→_grant_rights+settle_commission_for_order；balance 型→balance_service.credit(recharge)
def pay_with_balance(self, order) -> PurchaseOrder   # 校验足额→debit(purchase)→confirm_paid
```

- [ ] **Step 3: PaymentConfigService**（`payment_config_service.py`）：`SUPPORTED={wechatpay,alipay}`；`upsert` 用 `tool_credential_encryptor` 加密密钥字段（白名单键），`list` 返回脱敏（`appid/merchant_id` 等明文，secret 只显 `***`）；`set_enabled`；`ensure_defaults` 启动调用（`app.py` startup 段仿 storage）。
- [ ] **Step 4: PaymentGateway 适配器骨架**（`internal/service/payment/gateway_base.py`）：
  `PaymentGatewayProtocol(create_payment(order)->dict, verify_callback(payload)->dict, query_status(order_no))`；`WechatPayAdapter/AlipayAdapter` 实现：`create_payment` 抛 `PaymentChannelNotConfigured("支付渠道未开通")`，`verify_callback` 骨架返回 `{"order_no":..., "transaction_id":...}`（真实接入时补验签）。
- [ ] **Step 5: 路由**（`commerce_routes.py`）：`POST /orders`、`GET /orders`、`GET /orders/<order_no>`、`POST /orders/<order_no>/cancel`、`POST /orders/<order_no>/mock-paid`（`ALLOW_MOCK_PAYMENT==1` 才注册）、`POST /payments/notify/<provider>`。
- [ ] **Step 6: 测试通过**；**回查**：真实网关未接时 `create_payment` 返回"渠道未开通"明确错误；订单在管理面板可见（P8 联调）。
- [ ] **Step 7: Commit**

---

## P6 自动续费（到期触发 + 余量触发）

### Task 9: AutoRenewalService
**Files:** Create `internal/service/auto_renewal_service.py` + `internal/task/auto_renewal_tasks.py` + `app/http/celery_app.py`（beat 登记）

- [ ] **Step 1: 失败测试** `test_auto_renewal_service.py`：
  - 开通：membership 设 next_renew_at=expires_at；credits 置余量触发；同账户同套餐重复→400；wechatpay/alipay→"通道暂未开通"；
  - 到期执行（membership）：到 `expires_at-1d` → 走 order(pay_method=balance, order_source=auto_renew) → 扣余额+权益+佣金；
  - **余量触发（credits）**：`consume_check_after` 钩子——`permanent_credit ≤ plan.grant×5%` 且存在 active 续费 → 复购同一包；24h 冷却；
  - 余额不足：fail_count+=1；连续 3 次 → failed + 通知；
  - pause/resume/cancel。
- [ ] **Step 2: 实现**：

```python
def create(self, account_id, plan_id, pay_method) -> AutoRenewal
def _run_one(self, ar: AutoRenewal) -> str   # "renewed"/"failed"/"skipped"
def try_renew_membership(self, ar)   # next_renew_at<=now → order.create+pay_with_balance
def check_credits_threshold(self, account_id)  # 由 credit_service.consume 成功后回调
    # 遍历该账户 active credits 续费；permanent_credit <= grant*threshold%/100 → _run_renew(ar)
def run_due_scan(self) -> dict      # Celery 兜底：到期/达标但未触发的补扫
```

- [ ] **Step 3: Celery** `auto_renewal_tasks.py`：`@shared_task run_auto_renewal_scan`（每日/每小时，仿 `schedule_tasks.py` 的 injector/db 用法）；`celery_app.py` beat 添加 `run_auto_renewal_scan`。
- [ ] **Step 4: credit_service 消费钩子**：`consume_for_message/consume_for_feature` 成功后调用 `auto_renewal_service.check_credits_threshold(account_id)`（注入失败静默，不阻断主链路）。
- [ ] **Step 5: 路由**：`POST /auto-renewals`、`GET /auto-renewals`、`POST /auto-renewals/<id>/pause|resume|cancel`。
- [ ] **Step 6: 测试通过**；**回查**：续费订单 order_source=auto_renew 可筛；余量触发不重复（锁定冷却）；佣金随每期续费即时结算。
- [ ] **Step 7: Commit**

---

## P7 提现与售后

### Task 10: 提现 + 退款（含权益回收/佣金回扣/refund_hold）
**Files:** Create `internal/service/admin_withdraw_service.py`、`admin_refund_service.py`；Modify `balance_service.py`（withdraw/refund 辅助）

- [ ] **Step 1: 失败测试**：
  - 提现：申请扣余额挂 pending；低于 MIN_WITHDRAW_AMOUNT→400；重复/超额→400；审核通过/驳回退款/用户取消；
  - 退款：仅 paid；直购未消耗可退（含 consume 流水则拒）；在线充值可退；
  - 审核通过：资金回补（余额购买→回余额；在线充值→余额扣回并线退标记）；权益回收（credits→permanent_credit-=grant，不足→人工；membership→终止+清额度）；**佣金回扣**（上级余额-=comm，amount_type=refund，幂等；上级余额不足→refund_hold）；重复申请拦截。
- [ ] **Step 2: 实现**（`return_request` + 审核逻辑；`withdrawal_request` + 审核）。
- [ ] **Step 3: 路由**（用户）：`POST /refunds`、`GET /refunds`、`POST /balance/withdraw`、`GET /balance/withdrawals`；（admin）：`/admin/withdrawals`、`/admin/refunds`（P8 路由文件统一注册）。
- [ ] **Step 4: 测试通过**；**回查**：审计日志齐全；refund_hold 状态可被管理面板识别。
- [ ] **Step 5: Commit**

---

## P8 管理端（面板 + 权限 + 客户绑定 + 支付配置路由）

### Task 11: 管理端服务与路由
**Files:** Create `admin_distribution_service.py`、`admin_order_service.py`；Modify `admin_customer_user_service.py`；Create `app/http/admin_commerce_routes.py`；Modify `admin_routes_7.py`（users superior 端点可放新文件）

- [ ] **Step 1: 失败测试**：overview（绑定数/累计本月佣金/平均下级）；relations/commissions 分页；orders 列表（按 order_source 筛选）+ 详情 + 关闭 pending；superior 绑定（自绑/互为上下级/任意换绑/解绑 + 审计）；权限码校验 `distribution:view` 等。
- [ ] **Step 2: 实现** 服务 + 路由（`GET /admin/distribution/overview|relations|commissions`、`GET /admin/orders`、`GET /admin/orders/<id>`、`POST /admin/orders/<id>/close`、`PUT /admin/users/<id>/superior`、`GET /admin/withdrawals`、`POST /admin/withdrawals/<id>/approve|reject`、`GET /admin/refunds`、`POST /admin/refunds/<id>/approve|reject`、`/admin/payment-configs` 三件套）。superior 校验复用 distribution_service.bind_superior（source=admin）。
- [ ] **Step 3: RBAC 权限种子**：迁移中加入权限目录（`distribution:view/manage`、`order:view/manage`、`refund:view/manage`、`payment_config:manage`、`withdraw:view/manage`），仿 `h4c5d6e7f8a1_seed_admin_pool_permissions.py` 写法（插入 admin_permission 表 + 不必绑定角色，超管 full 授权即可）。
- [ ] **Step 4: 测试通过**；**回查**：admin_customer_user 列表序列化增加 `superior`/`subordinate_count` 且不破坏既有断言。
- [ ] **Step 5: Commit**

---

## P9 前端（会员页 + 管理面板 + 注册 + i18n）

### Task 12: 注册页邀请码
**Files:** Modify `src/services/auth.ts`、`src/hooks/use-auth.ts`、`src/models/auth.ts`、`src/views/auth/components/LoginForm.vue`；`src/i18n/messages/*`

- [ ] **Step 1: 实现** `directRegister/verifyRegister` 增加 `invite_code` 参数；注册表单增加邀请码输入框；`route.query.invite` 预填置灰；开关必填时前端提示（后端兜底校验）。
- [ ] **Step 2: 手动/组件测试通过**（`use-auth.spec.ts` 扩展）。

### Task 13: 会员页（余额/算力/分销中心/订单/退款/自动续费/购买）
**Files:** Create `src/models/commerce.ts`、`src/models/distribution.ts`、`src/services/commerce.ts`、`src/services/distribution.ts`、`src/services/balance.ts`；Create `src/views/membership/components/*`；Modify `MembershipView.vue`

- [ ] **Step 1: 类型与 service**（按 API 契约逐一映射）。
- [ ] **Step 2: 组件**：
  - BalancePanel：充值/佣金分开展示、总额；卡密兑换输入；在线充值（选余额卡 plan + 渠道，渠道未配置置灰提示）；提现申请（金额+最小额校验）；余额不足充值引导。
  - DistributionCenter：邀请码展示+自定义修改（大小写敏感提示）+复制+分享链接+二维码（`<img :src="GET /distribution/qrcode?invite=分享链接" />`，后端 qrcode 库生成，前端零新依赖）；下级列表；佣金明细（含 rate）；当前佣金率。
  - PurchaseDialog：选套餐（会员/算力包）→ 支付方式（余额/微信/支付宝，渠道未配置置灰）→ 创建订单 → 余额即时成功 / 在线显示"渠道未开通"或轮询。
  - AutoRenewPanel：开通（选套餐+余额）、暂停/恢复/取消、下次触发条件（会员=到期；算力包=余量≤X%）、失败提示。
  - OrdersPanel：我的订单 + 状态 + 申请退款。
- [ ] **Step 3: 路由** `/membership` 保持；子组件按需引入。

### Task 14: 管理面板（5 个视图 + 客户绑定抽屉）
**Files:** Create `src/services/admin-commerce.ts`、`src/services/payment-config.ts`（修改 `admin-customer-users.ts`）；Create `AdminDistributionView.vue`、`AdminOrdersView.vue`、`AdminRefundsView.vue`、`AdminWithdrawalsView.vue`、`AdminPaymentConfigView.vue`；Modify `CustomerUsersView.vue`、`src/router/index.ts`、`AdminLayout` 菜单（router meta）

- [ ] **Step 1: 实现各视图**（对齐既有 admin 面板的表格/抽屉/分页风格，权限按 store 的 permission 判断）。
- [ ] **Step 2: 路由/菜单注册**并跑 `npm run lint`、`npm run build`（或对应脚本）验证。
- [ ] **Step 3: 回查**：管理端各功能与 P8 接口一一对应；`ENABLE_DISTRIBUTION` 开关页自动出现；无死链。

---

## P10 测试与验证（全量回归 + 回查）

### Task 15: 补测与回归
- [ ] **Step 1:** 运行 `cd api && python -m pytest -q`，全绿（存量 + 新增）。
- [ ] **Step 2:** 前端 `cd ui && npm run test` 或触发器测试。
- [ ] **Step 3: 最终回查清单**（对照规格 v11 逐条）：
  - 4.1 邀请码：随机/自定义/大小写不敏感唯一/开关必填/扫码预填/invite-info ✅
  - 4.2 卡密入账三类型 + top-up 不返佣 ✅
  - 4.3 消费顺序 + credits_exhausted + 无余额扣款 ✅
  - 4.4 佣金：卡密/订单/在线支付触发；top-up/提现/消耗不触发；20%→30% 永久锁；单次计税；回扣 ✅
  - 4.5 订单：balance/在线/充值三类；mock-paid；取消；轮询 ✅
  - 4.6 提现 + 4.7 退款（权益回收/佣金回扣/refund_hold） ✅
  - 4.8 自动续费：到期 + 余量双触发；复购同款；失败重试；渠道预留 ✅
  - 4.9 管理端 5 面板 + 绑定 + 开关 + RBAC ✅
  - 无死代码/胶水：git diff 复核、删除未用 import/字段；迁移可重复执行。
- [ ] **Step 4: Commit**（全部改动）

---

## 并行开发划分（子代理）
- **串行不可并（有强依赖）**：P1（模型）→ P2（入账）→ P3（注册）→ P4（佣金）。P1 完成后测试并回查，再接 P2。
- **可与主线并行**（不依赖主线前置）：
  - **Stream A（后台）**：P5 订单 + 支付配置 + 适配器（依赖 P1 模型 + P4 settle 接口签名——先按上文签名字段实现，主线 P4 同时确认）。
  - **Stream B（后台）**：P6 自动续费（依赖 P1/P5 订单接口）。
  - **Stream C（后台）**：P7 提现/退款（依赖 P1/P4）。
  - **Stream D（前端）**：P9 会员页/管理面板按后端契约先行开发（mock 数据可先渲染），主线合并后联调。
- **严格审查要求**：每个子代理完成后，主线必须 `git diff` + 读关键文件核对：① 回报与实现一致；② 契约（方法名/字段/API）与规格一致；③ 无死代码/遗留桩（除明确标注的网关/渠道预留桩）。