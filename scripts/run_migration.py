"""重启 API 容器并运行迁移。

用法: python scripts/run_migration.py
"""
import subprocess
import time

# 1. 重启容器清空事务状态
print("=== 重启 llmops-api 容器 ===")
result = subprocess.run(["docker", "restart", "llmops-api"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
print(result.stdout)
print("等待容器启动...")
time.sleep(10)

# 2. 运行迁移
print("\n=== 运行 flask db upgrade ===")
result = subprocess.run(
    ["docker", "exec", "llmops-api", "flask", "db", "upgrade"],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
)
print("STDOUT:", result.stdout)
print("STDERR (last 1000):", result.stderr[-1000:] if result.stderr else "")
print("Return code:", result.returncode)

# 3. 查看当前版本
print("\n=== 当前迁移版本 ===")
result = subprocess.run(
    ["docker", "exec", "llmops-api", "flask", "db", "current"],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
)
print("CURRENT:", result.stdout)
