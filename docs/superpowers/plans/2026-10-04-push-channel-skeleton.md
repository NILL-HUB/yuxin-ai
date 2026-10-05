# 系统推送接入（个推为主 / 友盟为辅）Implementation Plan —— 批次 1：骨架

> 依据：[手机端遥控与多设备协作设计（spec）](../specs/2026-10-03-mobile-remote-control-multi-device-design.md) §4.7 / §6.1；主备次序已确认：**个推为主、友盟为辅**。
> 本批次交付**服务端骨架**（配置 / 适配器 / 令牌注册 / 事件接线），移动端 SDK 集成与厂商资质并行推进。

**Goal:** 打通「服务端 → 个推/友盟 → 手机」的推送链路骨架：admin 可配置两家凭证（加密存储、掩码展示）与主备切换；服务端按账号已注册的设备令牌发推；主通道失败自动切备；一个真实事件源（定时任务结果）接入，验证链路可调用。

**边界（本批不做）**：
- 移动端 SDK 集成与双 token 上报（App 侧另行接入，接口先行）；
- admin 前端页面（后端 GET/PUT 先行，UI 随后补——mail/sms 同款卡片合并进「消息配置」页）；
- 推送分级/打扰预算（spec §4.7 后续演进）；iOS APNs 直连（走聚合 SDK，无需自研）。

**已核实事实**：
- 配置模式先例：`mail_config` / `sms_config` / `desktop_client_config` 均为**单行 JSONB（id=1）+ XxxConfigService + /admin/xxx-config**（`auth_channel_config.py`、`admin_routes_8.py`、`system_config:manage` 权限）。
- 个推 REST v2（官方文档 `docs.getui.com/getui/server/rest_v2/`）：`POST {BaseUrl}/auth`，body `{sign, timestamp, appkey}`，`sign = sha256(appkey+timestamp+mastersecret)`；token 有效期约 1 天、业务返回 `10001` 时需被动刷新；单推 `POST {BaseUrl}/push/single/cid`，Header `token`，body `{request_id, audience:{cid:[...]}, push_message:{notification:{title, body, click_type, url?}}, settings:{ttl}}`；响应 `{code, msg, data}`（code=0 成功）。BaseUrl：`https://restapi.getui.com/v2/{appId}`。
- 友盟 U-Push 服务端（`https://msgapi.umeng.com/api/send`）：body `{appkey, timestamp, type:"unicast", device_tokens, payload:{display_type:"notification", body:{ticker,title,text,after_open:"go_app"}}, production_mode}`，`sign = md5("POST"+url+body+app_master_secret)`，响应 `{ret:"SUCCESS"|"FAIL"}`。**官方文档抓取受限，签名与字段按公开约定实现，资质开通后需按官方文档核对（本批含纯函数单测锁定机械结构）**。
- 事件源：`schedule_execution_service._push_notification()` 已向 WS 推 `schedule_task_result`（L523-535），推送扇出加在此处。
- 加密先例：`tool_credential_encryptor._encrypt_value/_decrypt_value`（Fernet），`desktop_device` 同款。

## 文件结构

```text
api/
├─ internal/model/push_channel.py           # PushConfig（单行 JSONB）+ PushDevice（令牌注册表）
├─ internal/migration/versions/e1f2a3b4c5d6_add_push_config_and_device.py
├─ internal/service/push_config_service.py  # 凭证加密/掩码/运行时读取
├─ internal/service/push_service.py         # Provider 适配器（个推/友盟）+ 主备编排
├─ app/http/push_routes.py                  # 用户侧令牌注册（Bearer 账号）
├─ app/http/admin_routes_8.py               # + GET/PUT /admin/push-config、POST /admin/push-config/test
└─ test/...（服务与路由测试）
```

## Task 1: 配置骨架（模型 + 迁移 + 服务 + admin 路由）
- [ ] PushConfig/PushDevice 模型 + 迁移（`down_revision=f3a4b5c6d7e8`，单 head）；PushDevice 唯一约束 (account_id, provider, token)。
- [ ] `PushConfigService`：默认键（enabled=false / primary_provider=getui / fallback_enabled=true / 两家凭证）；密钥字段（`*secret*`）落库前 Fernet 加密、读取掩码（`******`）；`update_config` 空值不覆盖已存在密钥；`get_runtime_config()` 返回解密凭证（仅服务端消费）。
- [ ] 路由：GET/PUT `/admin/push-config`（`system_config:manage`）、POST `/admin/push-config/test`（指定 provider + 目标令牌发测试推，返回 {ok, detail}）。
- [ ] 测试：加密落库不落明文、掩码、空值不覆盖、枚举校验、路由鉴权与错误码。

## Task 2: Provider 适配器 + 主备编排
- [ ] `push_service.py`：纯函数请求构造 `build_getui_auth_request` / `build_getui_single_push_request` / `build_umeng_unicast_request`（含签名）；`_post_json` 为唯一 HTTP 缝（测试注入）。
- [ ] `PushGatewayService.notify_account(account_id, title, body, data)`：按 `push_device` 中 enabled 令牌 → 主通道发送 → 失败自动切备（`fallback_enabled`）→ 返回逐设备结果与失败原因；未配置/无令牌/未启用 → 静默跳过（返回 skipped）。
- [ ] 令牌失效语义：个推 `10001`/友盟 `FAIL` → 触发一次 token 刷新重试；仍失败才切备。
- [ ] 测试：请求构造（含签名哈希固定值）、主通道成功不触发备通道、失败切备、双失败聚合、无令牌跳过、未启用跳过。

## Task 3: 设备令牌注册（接口先行）
- [ ] `POST /push/devices/register`（账号 Bearer）：body `{platform, provider, token}` → 幂等 UPSERT（同账号同 provider 同 token 置 enabled）；`POST /push/devices/unregister` 置 disabled。
- [ ] 测试：注册/幂等/禁用/越权（只能操作自己账号）。

## Task 4: 事件接线（唯一生产调用方）
- [ ] `schedule_execution_service._push_notification`：WS 推送后追加 `PushGatewayService.notify_account(...)`（账号维度、标题/正文来自任务名与结果状态）；异常吞掉不影响主流程。
- [ ] 测试：调度结果触发 notify（mock 网关断言被调用且参数正确）。

## Task 5: 收尾
- [ ] 文档：09 模块文档补「系统推送」小节（配置与主备、令牌注册、接入位置）；spec §9 状态更新；README 登记本计划。
- [ ] 接线审查（新符号逐个点名调用方）；`python -m graphify update .`；提交序列 `feat(push): ...`。

## 外部并行事项（用户侧）
- 个推/友盟开发者资质：企业认证、App 备案、部分厂商要软著；拿到 AppKey/AppSecret/MasterSecret 后填入 `/admin/push-config` 并用 `/test` 联调。
- 移动端：App 同时集成两家 SDK、上报双 token（调用本批 Task 3 的接口）。
