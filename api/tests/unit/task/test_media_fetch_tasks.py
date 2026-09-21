from internal.task import media_fetch_tasks
from internal.task.media_fetch_tasks import media_fetch_task, _format_for


def test_task_registered_name():
    assert media_fetch_task.name == "internal.task.media_fetch_tasks.media_fetch_task"


def test_module_exports_task():
    assert callable(getattr(media_fetch_tasks, "media_fetch_task"))


def test_format_for_audio_vs_default():
    assert _format_for("audio") == "ba"
    assert _format_for("video") == "bv*+ba/b"
    assert _format_for("mixed") == "bv*+ba/b"