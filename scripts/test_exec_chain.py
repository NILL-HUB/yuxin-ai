#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""执行链路端到端测试：验证不同复杂度的用户请求能正确完成。"""
import json
import sys
import time
import subprocess
import requests

BASE = "http://127.0.0.1:5001"


def login() -> str:
    """登录测试账号。"""
    # 先尝试已知的测试账号
    for user, pwd in [("testexec", "Test123456"), ("testuserpub", "Root123456"), ("NILL", "Root123456")]:
        try:
            resp = requests.post(
                f"{BASE}/auth/password-login",
                json={"username": user, "password": pwd},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") == "success":
                token = data["data"]["access_token"]
                print(f"[login] {user} 登录成功")
                return token
        except Exception:
            pass
    # 注册新账号（用时间戳生成唯一用户名）
    import time as _t
    uname = f"test{int(_t.time()) % 100000}"
    resp = requests.post(
        f"{BASE}/auth/register/direct",
        json={"name": "测试用户", "username": uname, "password": "Test123456"},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") == "success":
        print(f"[login] 新注册 {uname} 登录成功")
        return data["data"]["access_token"]
    print(f"[login] FAILED: {data}")
    sys.exit(1)


def send_message(token: str, query: str, label: str = "") -> dict:
    """发送消息并收集 SSE 事件。"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "query": query,
        "image_urls": [],
        "conversation_id": "",
        "confirm_deep_thinking": False,
    }
    print(f"\n{'='*60}")
    print(f"[测试] {label}")
    print(f"[发送] {query}")
    print(f"{'='*60}")

    events = []
    event_types = set()
    answer_text = ""
    has_agent_end = False
    has_error = False

    try:
        resp = requests.post(
            f"{BASE}/assistant-agent/chat",
            headers=headers,
            json=payload,
            stream=True,
            timeout=120,
        )
        if resp.status_code != 200:
            print(f"[FAILED] HTTP {resp.status_code}: {resp.text[:200]}")
            return {"ok": False, "error": f"HTTP {resp.status_code}"}

        current_event = None
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                current_event = None
                continue
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()
                try:
                    data = json.loads(data_str)
                except Exception:
                    data = data_str
                events.append({"event": current_event, "data": data})
                event_types.add(current_event)
                if current_event == "agent_message":
                    if isinstance(data, dict) and data.get("answer"):
                        answer_text = data["answer"]
                elif current_event == "agent_end":
                    has_agent_end = True
                elif current_event == "error":
                    has_error = True
                    print(f"  [ERROR] {data}")
    except Exception as e:
        print(f"[异常] {e}")
        return {"ok": False, "error": str(e), "events": events}

    # 结果摘要
    print(f"\n[结果]")
    print(f"  事件类型: {sorted(event_types)}")
    print(f"  事件总数: {len(events)}")
    print(f"  有 AGENT_END: {has_agent_end}")
    print(f"  有 ERROR: {has_error}")
    print(f"  回答长度: {len(answer_text)} 字符")
    if answer_text:
        preview = answer_text[:150].replace('\n', ' ')
        print(f"  回答预览: {preview}")

    # 成功条件：有回答 + 有 billing_final 或 agent_end + 无 error
    has_stream_end = has_agent_end or "billing_final" in event_types
    return {
        "ok": has_stream_end and not has_error and len(answer_text) > 0,
        "events": events,
        "event_types": sorted(event_types),
        "answer": answer_text,
        "has_agent_end": has_agent_end,
    }


def check_db(label: str, sql: str):
    """查询数据库。"""
    print(f"\n--- {label} ---")
    result = subprocess.run(
        ["docker", "exec", "llmops-db", "psql", "-U", "postgres", "-d", "llmops", "-c", sql],
        capture_output=True, text=True
    )
    print(result.stdout.strip())


def main():
    print("=" * 60)
    print("OpenAgent 执行链路端到端测试")
    print("=" * 60)

    token = login()

    # 测试 1：简单问答（应走 direct_answer 路径）
    r1 = send_message(token, "你好，请简单介绍一下你自己", "简单问答 - direct_answer")

    # 测试 2：中等任务（应走 single_agent 路径）
    r2 = send_message(token, "帮我用 Python 写一个简单的 hello world 程序", "中等任务 - single_agent")

    # 测试 3：含"总结"关键词（修复前会被错误触发深度思考，修复后应直接回答）
    r3 = send_message(token, "请总结一下什么是机器学习", "含'总结'关键词 - 验证不误触发深度思考")

    # 测试 4：含"分析"关键词
    r4 = send_message(token, "分析一下 Python 和 Java 的区别", "含'分析'关键词 - 验证不误触发深度思考")

    # 测试 5：多角度问题（修复前会走 multi_agent 100%失败，修复后降级 single_agent）
    r5 = send_message(token, "请分别从性能和易用性两个角度对比 Python 和 Go", "多角度问题 - MultiAgent降级")

    # 等待记忆写入（记忆写入涉及 LLM 调用，需要较长时间）
    print("\n[等待] 25s 让记忆异步写入（涉及 LLM 调用）...")
    time.sleep(25)

    # 数据库验证
    print("\n" + "=" * 60)
    print("数据库持久化验证")
    print("=" * 60)
    check_db(
        "最近10条消息 answer 落库情况",
        "SELECT created_at, status, LEFT(answer, 50) as answer_preview FROM message ORDER BY created_at DESC LIMIT 10;"
    )
    check_db(
        "最近1小时 agent_thought 记录数",
        "SELECT COUNT(*) FROM message_agent_thought WHERE created_at > NOW() - INTERVAL '1 hour';"
    )
    check_db(
        "最近1小时 user_memory 记录数（验证记忆写入修复）",
        "SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '10 minutes') as last_10min FROM user_memory;"
    )

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    results = [
        ("简单问答", r1),
        ("中等任务", r2),
        ("含'总结'关键词", r3),
        ("含'分析'关键词", r4),
        ("多角度问题(MultiAgent降级)", r5),
    ]
    for label, r in results:
        status = "✓ 通过" if r.get("ok") else "✗ 失败"
        print(f"  {label}: {status}")

    passed = sum(1 for _, r in results if r.get("ok"))
    print(f"\n总计: {passed}/{len(results)} 通过")


if __name__ == "__main__":
    main()
