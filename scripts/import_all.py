"""容器内批量导入 MCP 工具 + Skill 工具"""
import json
import sys
import os

def main():
    from app.http.app import app
    from app.http.module import injector
    from internal.service.mcp_import_service import McpImportService
    from internal.service.skill_import_service import SkillImportService
    from internal.model import Account
    from internal.extension.database_extension import db

    with app.app_context():
        # 获取 admin 账号
        account = db.session.query(Account).filter_by(email='admin@example.com').first()
        if not account:
            account = db.session.query(Account).first()
        if not account:
            print("ERROR: No admin account found")
            sys.exit(1)
        print(f"[1/4] Using account: {account.id} ({account.email})")

        # ---- MCP 导入 ----
        print("\n[2/4] Importing MCP tools...")
        mcp_service = injector.get(McpImportService)
        mcp_config = {
            "mcpServers": {
                "github-remote": {
                    "type": "sse",
                    "url": "https://api.github.com/mcp",
                    "description": "GitHub 官方远程 MCP 服务器"
                },
                "cloudflare-docs": {
                    "type": "http",
                    "url": "https://docs.mcp.cloudflare.com/sse",
                    "description": "Cloudflare 官方文档 MCP"
                },
                "cloudflare-observability": {
                    "type": "http",
                    "url": "https://observability.mcp.cloudflare.com/sse",
                    "description": "Cloudflare 可观测性 MCP"
                },
                "filesystem": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    "description": "文件系统操作",
                    "timeout_seconds": 120
                },
                "memory": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-memory"],
                    "description": "知识图谱记忆系统",
                    "timeout_seconds": 120
                },
                "fetch": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-fetch"],
                    "description": "Web 内容抓取",
                    "timeout_seconds": 120
                },
                "sequential-thinking": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
                    "description": "思维序列推理",
                    "timeout_seconds": 120
                },
                "time-mcp": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-time"],
                    "description": "时间和时区转换",
                    "timeout_seconds": 120
                },
                "everything": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-everything"],
                    "description": "参考/测试 MCP 服务器",
                    "timeout_seconds": 120
                },
                "sqlite": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "/tmp/test.db"],
                    "description": "SQLite 数据库交互",
                    "timeout_seconds": 120
                },
            }
        }
        json_str = json.dumps(mcp_config, ensure_ascii=False)
        mcp_result = mcp_service.import_from_mcp_json(json_str, account.id, overwrite=True)
        print(json.dumps(mcp_result, ensure_ascii=False, indent=2, default=str))

        # ---- Skill 导入 ----
        print("\n[3/4] Importing Skill tools...")
        skill_service = injector.get(SkillImportService)

        skills_path = "/tmp/collected_skills.json"
        if not os.path.exists(skills_path):
            print(f"WARNING: {skills_path} not found, skipping skill import")
            return

        with open(skills_path, encoding="utf-8") as f:
            skills = json.load(f)

        print(f"  Found {len(skills)} skills to import")
        imported_count = 0
        failed_count = 0
        for i, skill in enumerate(skills):
            try:
                skill_json = json.dumps(skill, ensure_ascii=False)
                result = skill_service.import_from_json(skill_json, overwrite=True)
                if result.get("imported"):
                    imported_count += 1
                    print(f"  [{i+1}/{len(skills)}] OK: {skill.get('source_key', '?')}")
                else:
                    failed_count += 1
                    print(f"  [{i+1}/{len(skills)}] SKIP: {skill.get('source_key', '?')} - {result}")
            except Exception as e:
                failed_count += 1
                print(f"  [{i+1}/{len(skills)}] FAIL: {skill.get('source_key', '?')} - {e}")

        print(f"\n  Skills: {imported_count} imported, {failed_count} failed")

        # ---- 汇总 ----
        print("\n[4/4] Summary:")
        print(f"  MCP imported: {len(mcp_result.get('imported', []))}")
        print(f"  MCP skipped:  {len(mcp_result.get('skipped', []))}")
        print(f"  MCP failed:   {len(mcp_result.get('failed', []))}")
        print(f"  Skills imported: {imported_count}")
        print(f"  Skills failed:   {failed_count}")
        print("\nDone!")


if __name__ == "__main__":
    main()
