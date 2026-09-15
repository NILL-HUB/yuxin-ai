"""L2 按需解析任务测试。

L2 目标：让素材「能被精细修改」——视频逐场景视觉详述与精细时间轴。
L2 回填同一批 Segment 的 content/metadata，**不新建 Segment**（避免重复）。
"""
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
CELERY_APP = API_ROOT / "app/http/celery_app.py"
TASK_FILE = API_ROOT / "internal/task/knowledge_l2_tasks.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestKnowledgeL2TaskRegistration:
    def test_task_module_exists(self):
        assert TASK_FILE.is_file(), "缺少 L2 解析任务模块"

    def test_task_module_registered_in_celery(self):
        """只靠 include 在部分 celery 版本下惰性加载不可靠，必须进 TASK_MODULES。"""
        source = _read(CELERY_APP)
        assert "knowledge_l2_tasks" in source, "任务模块必须登记进 TASK_MODULES"

    def test_task_module_explicitly_imported(self):
        """仅靠 include 在部分 celery 版本下惰性加载不可靠，须有显式 import 语句。"""
        source = _read(CELERY_APP)
        assert "internal.task.knowledge_l2_tasks as" in source

    def test_task_uses_shared_task_with_explicit_name(self):
        source = _read(TASK_FILE)
        assert "@shared_task" in source
        assert "internal.task.knowledge_l2_tasks." in source

    def test_task_is_retryable(self):
        source = _read(TASK_FILE)
        assert "max_retries" in source
        assert "self.retry" in source

    def test_task_fetches_service_from_injector(self):
        """任务内不得直接构造服务，须经 injector 拿依赖。"""
        source = _read(TASK_FILE)
        assert "injector" in source


class TestKnowledgeIndexingL2:
    def test_build_document_l2_exists(self):
        from internal.service.knowledge_indexing_service import KnowledgeIndexingService

        assert hasattr(KnowledgeIndexingService, "build_document_l2")
