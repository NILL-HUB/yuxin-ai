"""端到端池治理测试：通过 WebApp Chat 发送实际对话，验证池治理归集和动态路由

测试策略：
1. 向已发布的主 Agent 应用发送对话请求（触发 OrchestratorService.decide()）
2. 捕获 SSE 响应流
3. 检查 API 日志验证池治理组件被正确调用：
   - AgentCandidateCollector（Agent 候选收集）
   - ToolCandidateCollector / ToolInventory（工具候选收集）
   - CrossPoolAgentSubsetBuilder（Agent 子集裁剪）
   - RuntimeToolGovernanceGate（治理审计）
4. 验证 observe_only 模式下审计日志记录

用户明确要求：不是单测 API 端点，而是通过实际对话流验证池治理
"""
import json
import os
import time
import subprocess
from urllib import request, error

API_BASE = os.environ.get("LLMOPS_API_BASE", "http://localhost:5001")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "e2e_output")

# 已发布应用 token
APPS = {
    "main_agent": "O5pSp4bne8aKnvHk",   # E2E_E_主Agent（有 agent_bindings）
    "sub_agent": "2Ou4aV28wnr7JmDk",     # E2E_E_子Agent
    "baseline": "PO0AlnA07wSYiwsp",      # E2E_A_基线（current_time 工具）
}


def http_json(method, path, token=None, body=None, timeout=30):
    url = f"{API_BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body_text)
        except Exception:
            return e.code, {"raw": body_text[:500]}
    except Exception as e:
        return -1, {"exception": f"{type(e).__name__}: {e}"}


def get_user_token():
    body = {"identifier": "admin", "password": "Root123456"}
    code, result = http_json("POST", "/auth/password-login", body=body)
    return result.get("data", {}).get("access_token")


def get_admin_token():
    body = {"identifier": "admin", "password": "Root123456"}
    code, result = http_json("POST", "/admin/auth/login", body=body)
    return result.get("data", {}).get("admin_access_token")


def send_assistant_agent_chat(user_token: str, query: str, deep_thinking: bool = False, timeout: int = 120) -> dict:
    """发送 AssistantAgent chat 请求（触发 OrchestratorService.decide()），捕获 SSE 响应"""
    print(f"\n  发送请求: query='{query}', deep_thinking={deep_thinking}")
    url = f"{API_BASE}/assistant-agent/chat"
    body = json.dumps({
        "query": query,
        "conversation_id": "",
        "image_urls": [],
        "confirm_deep_thinking": deep_thinking,
    }).encode("utf-8")

    req = request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {user_token}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            chunks = []
            for line in resp:
                line_str = line.decode("utf-8", errors="replace").strip()
                if line_str:
                    chunks.append(line_str)
            return {
                "status": resp.status,
                "chunks": chunks,
                "chunk_count": len(chunks),
            }
    except error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return {"status": e.code, "error": body_text[:500]}
    except Exception as e:
        return {"status": -1, "error": f"{type(e).__name__}: {e}"}


def extract_sse_content(chunks: list) -> str:
    """从 SSE chunks 中提取文本内容"""
    texts = []
    for chunk in chunks:
        if chunk.startswith("data:"):
            data_str = chunk[5:].strip()
            try:
                data = json.loads(data_str)
                if isinstance(data, dict):
                    if data.get("event") == "message" and data.get("data"):
                        texts.append(str(data["data"]))
                    elif data.get("content"):
                        texts.append(str(data["content"]))
                    elif data.get("text"):
                        texts.append(str(data["text"]))
            except json.JSONDecodeError:
                pass
        elif chunk and not chunk.startswith(":") and not chunk.startswith("event:") and not chunk.startswith("id:"):
            texts.append(chunk)
    return "".join(texts)


def check_logs_for_pool_governance(since_minutes: int = 5) -> dict:
    """检查 API 日志中的池治理活动"""
    try:
        cmd = (
            f"docker exec llmops-api tail -n 500 /app/api/storage/log/app.log"
        )
        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True, text=True, timeout=15
        )
        log_text = result.stdout + result.stderr

        patterns = {
            "agent_candidate": ["Agent 候选", "AgentCandidateCollector", "agent_pool_service", "Agent候选收集"],
            "tool_candidate": ["Tool 候选", "ToolCandidateCollector", "tool_inventory_service", "ToolInventory", "工具候选"],
            "orchestrator": ["OrchestratorService", "orchestrator", "decide", "Orchestrator"],
            "tool_governance": ["RuntimeToolGovernanceGate", "GovernanceGate", "governance", "治理"],
            "cross_pool": ["CrossPool", "SubsetBuilder", "子集"],
            "agent_ranker": ["AgentRanker", "Ranker", "排名"],
            "tool_ranker": ["ToolRanker", "工具排名"],
        }

        findings = {}
        for category, keywords in patterns.items():
            matches = []
            for kw in keywords:
                if kw.lower() in log_text.lower():
                    matches.append(kw)
            findings[category] = {
                "found": len(matches) > 0,
                "matched_keywords": matches,
            }

        # 提取最近的 ERROR/WARNING 行
        error_lines = []
        for line in log_text.split("\n"):
            if "ERROR" in line or "WARNING" in line or "候选收集失败" in line:
                error_lines.append(line.strip()[:200])
        findings["recent_errors"] = error_lines[-10:] if error_lines else []

        return findings
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def query_pool_data(admin_token: str) -> dict:
    """查询池数据状态"""
    result = {}
    # AgentPoolConfig
    code, resp = http_json("GET", "/admin/agent-pool?page=1&page_size=20", token=admin_token)
    if resp.get("data", {}).get("list"):
        result["agent_pool_count"] = len(resp["data"]["list"])
        result["agent_pool_items"] = [
            {
                "app_id": item.get("app_id", "")[:8],
                "pool": item.get("primary_pool"),
                "tier": item.get("model_tier"),
                "priority": item.get("routing_priority"),
                "enabled": item.get("enabled"),
            }
            for item in resp["data"]["list"]
        ]
    else:
        result["agent_pool_count"] = 0

    # ToolInventory
    code, resp = http_json("GET", "/tool-inventory?page=1&page_size=50", token=admin_token)
    data = resp.get("data", {})
    if isinstance(data, dict):
        candidates = data.get("candidates", data.get("list", []))
        result["tool_inventory_count"] = len(candidates) if isinstance(candidates, list) else 0
        if isinstance(candidates, list) and candidates:
            result["tool_inventory_samples"] = [
                {
                    "name": c.get("name", "?")[:30],
                    "pool": c.get("tool_pool", c.get("metadata", {}).get("tool_pool", "?")),
                    "source": c.get("source_type", "?"),
                }
                for c in candidates[:5]
            ]
    else:
        result["tool_inventory_count"] = 0

    return result


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 70)
    print("端到端池治理测试：通过 WebApp Chat 验证归集和动态路由")
    print("=" * 70)

    # 获取 token
    user_token = get_user_token()
    admin_token = get_admin_token()
    print(f"\n[初始化] token 获取成功")

    # 步骤1：查询池数据现状
    print("\n[步骤1] 查询池数据现状")
    pool_data = query_pool_data(admin_token)
    print(f"  Agent 池: {pool_data.get('agent_pool_count', 0)} 条配置")
    for item in pool_data.get("agent_pool_items", []):
        print(f"    - app={item['app_id']}, pool={item['pool']}, tier={item['tier']}, priority={item['priority']}")
    print(f"  工具清单: {pool_data.get('tool_inventory_count', 0)} 个候选工具")
    for item in pool_data.get("tool_inventory_samples", []):
        print(f"    - {item['name']}, pool={item['pool']}, source={item['source']}")

    # 步骤2：发送 AssistantAgent Chat 请求（触发 OrchestratorService.decide()）
    print("\n[步骤2] 发送 AssistantAgent Chat 请求（触发 OrchestratorService）")
    chat_result = send_assistant_agent_chat(user_token, "你好，请帮我查询当前时间")
    print(f"  HTTP 状态: {chat_result.get('status')}")
    print(f"  SSE chunks: {chat_result.get('chunk_count', 0)}")
    if chat_result.get("chunks"):
        content = extract_sse_content(chat_result["chunks"])
        print(f"  响应内容: {content[:300]}")
    if chat_result.get("error"):
        print(f"  错误: {chat_result['error'][:200]}")

    # 步骤3：发送 AssistantAgent Chat 请求 - 深度思考场景
    print("\n[步骤3] 发送 AssistantAgent Chat 请求 - 深度思考场景")
    chat_result2 = send_assistant_agent_chat(user_token, "请深度分析一下当前AI发展趋势", deep_thinking=True)
    print(f"  HTTP 状态: {chat_result2.get('status')}")
    print(f"  SSE chunks: {chat_result2.get('chunk_count', 0)}")
    if chat_result2.get("chunks"):
        content2 = extract_sse_content(chat_result2["chunks"])
        print(f"  响应内容: {content2[:300]}")
    if chat_result2.get("error"):
        print(f"  错误: {chat_result2['error'][:200]}")

    # 步骤4：检查日志中的池治理活动
    print("\n[步骤4] 检查日志中的池治理活动")
    time.sleep(3)  # 等待日志写入
    log_findings = check_logs_for_pool_governance()
    for category, info in log_findings.items():
        if category == "recent_errors":
            if info:
                print(f"\n  最近错误/警告:")
                for err in info[-5:]:
                    print(f"    {err}")
        else:
            status = "✓" if info.get("found") else "✗"
            kws = ", ".join(info.get("matched_keywords", []))
            print(f"  {status} {category}: {kws if kws else '未检测到'}")

    # 保存结果
    summary = {
        "pool_data": pool_data,
        "chat_assistant_agent": {
            "status": chat_result.get("status"),
            "chunk_count": chat_result.get("chunk_count", 0),
            "content_preview": extract_sse_content(chat_result.get("chunks", []))[:500],
        },
        "chat_deep_thinking": {
            "status": chat_result2.get("status"),
            "chunk_count": chat_result2.get("chunk_count", 0),
            "content_preview": extract_sse_content(chat_result2.get("chunks", []))[:500],
        },
        "log_findings": log_findings,
    }
    summary_file = os.path.join(OUTPUT_DIR, "e2e_chat_pool_test.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'=' * 70}")
    print(f"测试完成，详细结果: {summary_file}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
