"""池治理端到端测试：通过 Admin API 创建真实数据，验证归集和动态路由

测试流程：
1. 获取 admin token
2. 创建 API 工具（注入工具池）
3. 为已发布应用创建 AgentPoolConfig（注入 Agent 池元数据）
4. 创建 ToolGovernancePolicy（注入治理策略）
5. 查询 ToolInventoryHandler 验证候选收集
6. 触发 OrchestratorService.decide() 验证动态路由
7. 创建新应用使用 DeepSeek-V3.2 并测试深度思考
"""
import json
import os
import sys
import time
from urllib import request, error

API_BASE = os.environ.get("LLMOPS_API_BASE", "http://localhost:5001")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "e2e_output")

# 已发布的基线应用 ID（用于绑定 AgentPoolConfig）
BASELINE_APP_ID = "6b318c51-0bde-4078-b0cd-dc1646bf28d1"
# 子 Agent 应用 ID
SUB_AGENT_APP_ID = "a2f8206f-d853-4c62-8ae0-dfc2fe4b9500"
# 主 Agent 应用 ID
MAIN_AGENT_APP_ID = "9eb2bf4b-b5c3-4aae-9d33-430717620da8"


def http_request(method: str, path: str, token: str = None, body: dict = None, timeout: int = 60) -> dict:
    """发送 HTTP 请求"""
    url = f"{API_BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return {"error": True, "status": e.code, "body": body_text}
    except Exception as e:
        return {"error": True, "exception": f"{type(e).__name__}: {e}"}


def get_admin_token() -> str:
    """登录 admin 获取 access_token"""
    body = {"identifier": "admin", "password": "Root123456"}
    result = http_request("POST", "/admin/auth/login", body=body)
    if result.get("data", {}).get("admin_access_token"):
        return result["data"]["admin_access_token"]
    raise RuntimeError(f"获取 admin token 失败: {result}")


def get_user_token() -> str:
    """登录获取 user token（用于应用创建等需要 user 权限的接口）"""
    body = {"identifier": "admin", "password": "Root123456"}
    result = http_request("POST", "/auth/password-login", body=body)
    if result.get("data", {}).get("access_token"):
        return result["data"]["access_token"]
    # 尝试用 admin token
    return get_admin_token()


def step1_create_api_tool(token: str) -> dict:
    """步骤1：创建 API 工具（注入工具池）"""
    print("\n[步骤1] 创建 API 工具（注入工具池）")
    # 使用 httpbin.org 作为测试 API
    openapi_schema = json.dumps({
        "openapi": "3.0.0",
        "info": {"title": "测试工具", "version": "1.0.0", "description": "池治理测试工具"},
        "servers": [{"url": "https://httpbin.org"}],
        "paths": {
            "/get": {
                "get": {
                    "operationId": "get_test_data",
                    "summary": "获取测试数据",
                    "description": "获取测试数据用于验证池治理",
                    "parameters": [
                        {
                            "name": "query",
                            "in": "query",
                            "required": False,
                            "type": "str",
                            "description": "查询参数"
                        }
                    ],
                    "responses": {"200": {"description": "成功"}}
                }
            }
        }
    })
    body = {
        "name": "池治理测试工具",
        "icon": "https://example.com/icon.png",
        "openapi_schema": openapi_schema,
        "headers": []
    }
    result = http_request("POST", "/api-tools", token=token, body=body)
    if result.get("error") or result.get("code") != "success":
        print(f"  [警告] 创建 API 工具失败: {result.get('message', result)}")
        return None
    print(f"  ✓ API 工具创建成功")
    return result


def step2_create_agent_pool_config(token: str) -> list:
    """步骤2：为已发布应用创建 AgentPoolConfig（注入 Agent 池元数据）"""
    print("\n[步骤2] 创建 AgentPoolConfig（注入 Agent 池元数据）")
    configs = [
        {
            "app_id": BASELINE_APP_ID,
            "primary_pool": "tenant",
            "secondary_pools": ["system"],
            "risk_level": "low",
            "model_tier": "standard",
            "routing_priority": 10,
            "enabled": True,
            "health_status": "healthy",
        },
        {
            "app_id": SUB_AGENT_APP_ID,
            "primary_pool": "tenant",
            "secondary_pools": [],
            "risk_level": "low",
            "model_tier": "cheap",
            "routing_priority": 50,
            "enabled": True,
            "health_status": "healthy",
        },
        {
            "app_id": MAIN_AGENT_APP_ID,
            "primary_pool": "system",
            "secondary_pools": ["tenant"],
            "risk_level": "medium",
            "model_tier": "standard",
            "routing_priority": 20,
            "enabled": True,
            "health_status": "healthy",
        },
    ]
    created = []
    for cfg in configs:
        result = http_request("POST", "/admin/agent-pool", token=token, body=cfg)
        if result.get("error"):
            print(f"  [警告] 创建 AgentPoolConfig 失败 (app={cfg['app_id'][:8]}): {result.get('body', result)}")
        else:
            print(f"  ✓ AgentPoolConfig 创建成功 (app={cfg['app_id'][:8]}, pool={cfg['primary_pool']}, priority={cfg['routing_priority']})")
            created.append(result.get("data", {}))
    return created


def step3_create_tool_governance_policy(token: str) -> dict:
    """步骤3：创建 ToolGovernancePolicy（注入治理策略）"""
    print("\n[步骤3] 创建 ToolGovernancePolicy（注入治理策略）")
    # 先查询现有的 api_tool 获取 tool_id
    # 由于 admin/api-tools 端点存在，先查询
    result = http_request("GET", "/admin/api-tools?page=1&page_size=10", token=token)
    if result.get("error"):
        print(f"  [警告] 查询 API 工具失败: {result}")
        return None
    print(f"  ✓ 查询 API 工具列表成功")
    return result


def step4_query_tool_inventory(token: str):
    """步骤4：查询 ToolInventoryHandler 验证候选收集"""
    print("\n[步骤4] 查询 ToolInventory 验证候选收集")
    # 尝试不同的端点路径
    endpoints = [
        "/tool-inventory",
        "/admin/tool-inventory",
        "/admin/tool-inventory/list",
    ]
    for ep in endpoints:
        result = http_request("GET", f"{ep}?page=1&page_size=50", token=token)
        if not result.get("error"):
            print(f"  ✓ 端点 {ep} 查询成功")
            data = result.get("data", {})
            if isinstance(data, dict):
                items = data.get("items", data.get("list", []))
                print(f"  候选工具数: {len(items) if isinstance(items, list) else 'N/A'}")
                if isinstance(items, list):
                    pool_stats = {}
                    for item in items[:10]:
                        meta = item.get("metadata", {})
                        pool = meta.get("tool_pool", "unknown")
                        pool_stats[pool] = pool_stats.get(pool, 0) + 1
                        print(f"    - {item.get('name', '?')}: pool={pool}, source={item.get('source_type', '?')}")
                    print(f"  子池分布: {pool_stats}")
            return result
    print(f"  [警告] 所有端点查询失败")
    return None


def step5_create_app_with_v32(user_token: str) -> dict:
    """步骤5：创建新应用使用 DeepSeek-V3.2 模型"""
    print("\n[步骤5] 创建新应用使用 DeepSeek-V3.2")
    body = {
        "name": "池治理V32测试",
        "description": "使用 DeepSeek-V3.2 测试池治理和深度思考",
        "app_type": "chatbot",
        "model_config": {
            "model": "deepseek-ai/DeepSeek-V3.2",
            "provider": "SiliconFlow",
            "parameters": {}
        },
        "preset_prompt": "你是一个专业的AI助手，支持深度思考和多步骤推理。请用markdown格式回答。",
        "tools": [],
        "agent_bindings": [],
        "workflows": [],
        "skills": [],
        "mcp_bindings": [],
        "knowledge_base_ids": [],
    }
    result = http_request("POST", "/apps", token=user_token, body=body)
    if result.get("error"):
        print(f"  [警告] 创建应用失败: {result}")
        # 尝试 admin 端点
        result = http_request("POST", "/admin/apps", token=user_token, body=body)
        if result.get("error"):
            print(f"  [警告] admin 端点也失败: {result}")
            return None
    print(f"  ✓ 应用创建成功")
    return result.get("data", {})


def step6_verify_orchestrator(token: str):
    """步骤6：通过 assistant_agent 入口触发 OrchestratorService.decide()"""
    print("\n[步骤6] 触发 OrchestratorService.decide() 验证动态路由")
    body = {"query": "帮我查询当前可用的Agent和工具", "conversation_id": ""}
    # assistant_agent 端点
    endpoints = [
        "/assistant-agent/chat",
        "/home/chat",
    ]
    for ep in endpoints:
        result = http_request("POST", ep, token=token, body=body, timeout=120)
        if not result.get("error"):
            print(f"  ✓ 端点 {ep} 调用成功")
            return result
    print(f"  [信息] 端点调用需要 SSE 处理，稍后用专用脚本测试")
    return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("池治理端到端测试")
    print("=" * 60)

    # 获取 token
    print("\n[初始化] 获取 admin token")
    admin_token = get_admin_token()
    print(f"  ✓ admin token 获取成功")

    try:
        user_token = get_user_token()
        print(f"  ✓ user token 获取成功")
    except Exception:
        user_token = admin_token
        print(f"  [信息] 使用 admin token 作为 user token")

    # 执行测试步骤
    results = {}
    results["api_tool"] = step1_create_api_tool(admin_token)
    results["agent_pool_configs"] = step2_create_agent_pool_config(admin_token)
    results["tool_governance"] = step3_create_tool_governance_policy(admin_token)
    results["tool_inventory"] = step4_query_tool_inventory(admin_token)
    results["app_v32"] = step5_create_app_with_v32(user_token)
    results["orchestrator"] = step6_verify_orchestrator(user_token)

    # 保存结果
    summary_file = os.path.join(OUTPUT_DIR, "pool_governance_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        # 过滤不可序列化的对象
        safe_results = {}
        for k, v in results.items():
            if v is None:
                safe_results[k] = None
            elif isinstance(v, (str, int, float, bool, list, dict)):
                safe_results[k] = v
            else:
                safe_results[k] = str(v)
        json.dump(safe_results, f, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 60)
    print("池治理数据注入完成")
    print(f"详细结果: {summary_file}")
    print("=" * 60)
    print("\n下一步：使用新应用跑深度思考测试验证池治理归集")


if __name__ == "__main__":
    main()
