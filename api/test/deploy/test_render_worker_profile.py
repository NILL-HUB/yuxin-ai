"""云端 render worker 必须「保留但默认不启动」——可随时接通。"""
from pathlib import Path

COMPOSE = (
    Path(__file__).resolve().parents[3] / "docker" / "docker-compose.yaml"
)


def _render_service_block() -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    start = text.index("llmops-render-worker:")
    # 到下一个顶层服务定义（两个空格 + 非空字符）为止
    rest = text[start:]
    lines = rest.splitlines()
    block = [lines[0]]
    for line in lines[1:]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        block.append(line)
    return "\n".join(block)


def test_render_worker_has_profile_so_it_can_be_re_enabled():
    """用 profile 下线：docker compose --profile cloud-render up -d llmops-render-worker"""
    block = _render_service_block()
    assert "cloud-render" in block, "云端渲染未用 profile 下线，无法保留可接通路径"


def test_render_worker_definition_is_retained():
    """服务定义整体保留，不删除——这是「未来可随时接通」的前提。"""
    text = COMPOSE.read_text(encoding="utf-8")
    assert "llmops-render-worker:" in text
    assert "CELERY_QUEUES: render" in text


def test_render_worker_keeps_resource_limits():
    """离线不等于删除限流：重新启用时仍受内存限额保护。"""
    block = _render_service_block()
    assert "memory: 2800M" in block
