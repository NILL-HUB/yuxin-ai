"""
End-to-end validation script: Windows cmd.exe friendly, no head/tail/heredoc.
Writes results to scripts/validation_result.txt

用法: python scripts/run_validation.py
"""
import os
import subprocess
import time

# 结果文件放在脚本同级目录
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_FILE = os.path.join(_SCRIPT_DIR, "validation_result.txt")


def log(msg: str):
    print(msg, flush=True)
    with open(RESULT_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def run(cmd: str, timeout: int = 600) -> tuple[int, str]:
    """Run a shell command via cmd.exe; return (rc, combined output)."""
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except Exception as e:
        return 1, f"EXC: {e!r}"


def tail_lines(text: str, n: int = 60) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:]) if len(lines) > n else text


def head_lines(text: str, n: int = 25) -> str:
    lines = text.splitlines()
    return "\n".join(lines[:n]) if len(lines) > n else text


def write_remote_script(container: str, script_text: str, remote_path: str) -> tuple[int, str]:
    """Write a python script to a temp file on host, then docker cp into container."""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".py", prefix="remote_script_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(script_text)
        rc, out = run(f'docker cp "{tmp}" {container}:{remote_path}')
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    return rc, out


def main():
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        f.write("")

    # ===== Step 1: rebuild and restart API container =====
    log("=" * 60)
    log("Step 1: Rebuild and restart API container (with fix)")
    log("=" * 60)
    rc, out = run(
        'docker compose -f docker/docker-compose.yaml up -d --force-recreate --build llmops-api',
        timeout=900,
    )
    log(f"rc={rc}")
    log(tail_lines(out, 60))

    # ===== Poll for container health (max 90s) =====
    log("")
    log("Polling container status (max 90s)...")
    healthy = False
    last_status = ""
    for i in range(18):
        time.sleep(5)
        rc, out = run("docker ps --filter name=llmops-api --format {{.Status}}")
        status = out.strip()
        if status != last_status:
            log(f"  [{i*5}s] status: {status}")
            last_status = status
        if "Up" in status and "health" not in status:
            healthy = True
            break
        if "Up" in status and "(healthy)" in status:
            healthy = True
            break
    log(f"Container healthy: {healthy}")
    rc, out = run("docker ps --filter name=llmops-api")
    log(out)

    # ===== Step 1b: docker logs after rebuild =====
    log("")
    log("=" * 60)
    log("Step 1b: Docker logs after rebuild (last 80 lines)")
    log("=" * 60)
    rc, out = run("docker logs llmops-api 2>&1")
    log(f"rc={rc}")
    log(tail_lines(out, 80))

    # ===== Step 2: migration current =====
    log("")
    log("=" * 60)
    log("Step 2: Verify migration applied")
    log("=" * 60)
    rc, out = run(
        'docker exec llmops-api bash -c "cd /app/api && flask db current --directory internal/migration 2>&1"'
    )
    log(f"rc={rc}")
    log(tail_lines(out, 30))

    # ===== Step 3: verify new tables =====
    log("")
    log("=" * 60)
    log("Step 3: Verify new tables created")
    log("=" * 60)
    rc, out = run(
        'docker exec llmops-db psql -U postgres -d llmops -c "\\d builtin_tool_provider"'
    )
    log(f"rc={rc}")
    log("--- builtin_tool_provider (first 25 lines) ---")
    log(head_lines(out, 25))

    rc, out = run(
        'docker exec llmops-db psql -U postgres -d llmops -c "\\d builtin_tool"'
    )
    log(f"rc={rc}")
    log("--- builtin_tool (first 25 lines) ---")
    log(head_lines(out, 25))

    # ===== Step 4: builtin tools synced to DB =====
    log("")
    log("=" * 60)
    log("Step 4: Verify builtin tools synced to DB")
    log("=" * 60)
    rc, out = run(
        'docker exec llmops-db psql -U postgres -d llmops -c "SELECT COUNT(*) FROM builtin_tool_provider;"'
    )
    log(f"rc={rc}")
    log("count provider:")
    log(out)

    rc, out = run(
        'docker exec llmops-db psql -U postgres -d llmops -c "SELECT COUNT(*) FROM builtin_tool;"'
    )
    log(f"rc={rc}")
    log("count tool:")
    log(out)

    rc, out = run(
        "docker exec llmops-db psql -U postgres -d llmops -c \"SELECT name, label, task_keywords FROM builtin_tool WHERE name='current_time';\""
    )
    log(f"rc={rc}")
    log("current_time row:")
    log(out)

    # ===== Step 5: ToolSelectorService =====
    log("")
    log("=" * 60)
    log("Step 5: Verify ToolSelectorService still works")
    log("=" * 60)
    step5_script = (
        "from app.http.app import app\n"
        "from app.http.module import injector\n"
        "from internal.service.tool_selector_service import ToolSelectorService\n"
        "with app.app_context():\n"
        "    selector = injector.get(ToolSelectorService)\n"
        "    result = selector.select_tools('现在几点了', candidates=None, max_tools=3)\n"
        "    print('Result:', result)\n"
        "    assert any(r.get('tool_name') == 'current_time' for r in result), 'current_time not selected'\n"
        "    print('OK: ToolSelector still works')\n"
    )
    rc, out = write_remote_script("llmops-api", step5_script, "/tmp/step5.py")
    log(f"docker cp rc={rc}: {out}")
    rc, out = run(
        'docker exec llmops-api bash -c "cd /app/api && PYTHONPATH=/app/api python /tmp/step5.py 2>&1"'
    )
    log(f"rc={rc}")
    log(tail_lines(out, 20))

    # ===== Step 6: credential encryption =====
    log("")
    log("=" * 60)
    log("Step 6: Verify credential encryption")
    log("=" * 60)
    step6_script = (
        "from app.http.app import app\n"
        "from internal.service.tool_credential_encryptor import encrypt_headers, decrypt_headers, mask_headers, is_encrypted\n"
        "headers = [{'key': 'Authorization', 'value': 'Bearer sk-test123'}]\n"
        "enc = encrypt_headers(headers)\n"
        "print('Encrypted:', enc)\n"
        "print('Is encrypted:', is_encrypted(enc[0]['value']))\n"
        "dec = decrypt_headers(enc)\n"
        "print('Decrypted:', dec)\n"
        "masked = mask_headers(enc)\n"
        "print('Masked:', masked)\n"
        "assert dec[0]['value'] == 'Bearer sk-test123', 'decrypt failed'\n"
        "assert masked[0]['value'] != 'Bearer sk-test123', 'mask failed'\n"
        "print('OK: credential encryption works')\n"
    )
    rc, out = write_remote_script("llmops-api", step6_script, "/tmp/step6.py")
    log(f"docker cp rc={rc}: {out}")
    rc, out = run(
        'docker exec llmops-api bash -c "cd /app/api && PYTHONPATH=/app/api python /tmp/step6.py 2>&1"'
    )
    log(f"rc={rc}")
    log(tail_lines(out, 20))

    # ===== Step 7: API endpoints exist =====
    log("")
    log("=" * 60)
    log("Step 7: Verify new API endpoints exist")
    log("=" * 60)
    step7_script = (
        "from app.http.app import app\n"
        "with app.app_context():\n"
        "    rules = [r.rule for r in app.url_map.iter_rules()]\n"
        "    new_endpoints = [\n"
        "        '/admin/builtin-tools',\n"
        "        '/admin/mcp/import-mcp-json',\n"
        "        '/admin/mcp/preview-url',\n"
        "        '/admin/mcp/import-url',\n"
        "        '/admin/mcp/import-json',\n"
        "        '/admin/skills/import-zip',\n"
        "        '/admin/skills/import-github',\n"
        "        '/admin/skills/import-json',\n"
        "        '/admin/workflows/import',\n"
        "        '/workflows/import',\n"
        "    ]\n"
        "    for ep in new_endpoints:\n"
        "        matched = [r for r in rules if ep in r]\n"
        "        if matched:\n"
        "            print(f'OK: {ep} -> {matched[0]}')\n"
        "        else:\n"
        "            print(f'MISSING: {ep}')\n"
    )
    rc, out = write_remote_script("llmops-api", step7_script, "/tmp/step7.py")
    log(f"docker cp rc={rc}: {out}")
    rc, out = run(
        'docker exec llmops-api bash -c "cd /app/api && PYTHONPATH=/app/api python /tmp/step7.py 2>&1"'
    )
    log(f"rc={rc}")
    log(tail_lines(out, 30))

    # ===== Step 8: API startup log =====
    log("")
    log("=" * 60)
    log("Step 8: Check API startup log (last 60 lines)")
    log("=" * 60)
    rc, out = run(
        'docker exec llmops-api bash -c "tail -60 /app/api/storage/log/app.log 2>&1"'
    )
    log(f"rc={rc}")
    log(out)

    # ===== Step 9: docker logs (final) =====
    log("")
    log("=" * 60)
    log("Step 9: Check docker logs (last 80 lines)")
    log("=" * 60)
    rc, out = run("docker logs llmops-api 2>&1")
    log(f"rc={rc}")
    log(tail_lines(out, 80))

    log("")
    log("=" * 60)
    log("VALIDATION DONE. Result file: " + RESULT_FILE)
    log("=" * 60)


if __name__ == "__main__":
    main()
