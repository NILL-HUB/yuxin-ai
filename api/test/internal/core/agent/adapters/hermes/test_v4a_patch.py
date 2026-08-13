import json

from internal.core.agent.adapters.hermes import (
    parse_and_apply_patch,
    parse_v4a_patch,
)
from internal.core.agent.adapters.hermes.v4a_patch import FileTextOps


def test_parse_add_update_delete_move():
    patch = "*** Begin Patch\n"
    patch += "*** Add File: a.txt\n+hello\n+world\n"
    patch += "*** Update File: b.txt\n@@\n old\n-remove me\n+keep me\n"
    patch += "*** Delete File: c.txt\n"
    patch += "*** Move File: d.txt -> e.txt\n"
    patch += "*** End Patch\n"

    operations, error = parse_v4a_patch(patch)

    assert error is None
    assert [op.operation.value for op in operations] == [
        "add",
        "update",
        "delete",
        "move",
    ]


def test_parse_requires_operation():
    operations, error = parse_v4a_patch("随便一段文本")
    assert operations == []
    assert "未找到任何文件操作" in error


def test_apply_patch_against_tmp_dir(tmp_path):
    ops = FileTextOps()
    patch = "*** Begin Patch\n"
    patch += f"*** Add File: {tmp_path / 'a.txt'}\n+hello\n+world\n"
    patch += f"*** Update File: {tmp_path / 'b.txt'}\n@@\n old\n-remove me\n+keep me\n"
    patch += f"*** Delete File: {tmp_path / 'c.txt'}\n"
    patch += "*** End Patch\n"
    (tmp_path / "b.txt").write_text("old\nremove me\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("gone", encoding="utf-8")

    result = parse_and_apply_patch(patch, ops)

    assert result["ok"] is True
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello\nworld"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "old\nkeep me\n"
    assert not (tmp_path / "c.txt").exists()


def test_update_preserves_crlf(tmp_path):
    ops = FileTextOps()
    target = tmp_path / "win.txt"
    target.write_bytes(b"line1\r\nold\r\nline3\r\n")
    patch = "*** Begin Patch\n"
    patch += f"*** Update File: {target}\n@@\n line1\n-old\n+new\n line3\n"
    patch += "*** End Patch\n"

    result = parse_and_apply_patch(patch, ops)

    assert result["ok"] is True
    assert target.read_bytes() == b"line1\r\nnew\r\nline3\r\n"


def test_already_applied_is_noop(tmp_path):
    ops = FileTextOps()
    target = tmp_path / "applied.txt"
    target.write_text("keep\n", encoding="utf-8")
    patch = "*** Begin Patch\n"
    patch += f"*** Update File: {target}\n@@\n keep\n"
    patch += "*** End Patch\n"

    result = parse_and_apply_patch(patch, ops)

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "keep\n"
    assert "no-op" in result["results"][0]
    assert "已包含补丁结果" in result["results"][0]


def test_no_match_returns_diagnostic(tmp_path):
    ops = FileTextOps()
    target = tmp_path / "mismatch.txt"
    target.write_text("completely different content\n", encoding="utf-8")
    patch = "*** Begin Patch\n"
    patch += f"*** Update File: {target}\n@@\n-old line\n+new line\n"
    patch += "*** End Patch\n"

    result = parse_and_apply_patch(patch, ops)

    assert result["ok"] is False
    assert any("未找到补丁上下文" in line for line in result["errors"])
    assert any("空白或缩进不一致" in line for line in result["errors"])


def test_add_existing_file_is_error(tmp_path):
    ops = FileTextOps()
    target = tmp_path / "exists.txt"
    target.write_text("existing", encoding="utf-8")
    patch = "*** Begin Patch\n"
    patch += f"*** Add File: {target}\n+new content\n"
    patch += "*** End Patch\n"

    result = parse_and_apply_patch(patch, ops)

    assert result["ok"] is False
    assert "文件已存在" in result["errors"][0]


def test_move_file(tmp_path):
    ops = FileTextOps()
    source = tmp_path / "src.txt"
    target = tmp_path / "dst.txt"
    source.write_text("move me", encoding="utf-8")

    result = parse_and_apply_patch(
        f"*** Begin Patch\n*** Move File: {source} -> {target}\n*** End Patch\n",
        ops,
    )

    assert result["ok"] is True
    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "move me"


def test_result_shape_is_json_serializable(tmp_path):
    patch = "*** Begin Patch\n"
    patch += f"*** Add File: {tmp_path / 'x.txt'}\n+x\n"
    patch += "*** End Patch\n"
    result = parse_and_apply_patch(patch, FileTextOps())
    assert json.dumps(result, ensure_ascii=False)


def test_empty_add_creates_empty_file(tmp_path):
    ops = FileTextOps()
    target = tmp_path / "empty.txt"
    patch = f"*** Begin Patch\n*** Add File: {target}\n*** End Patch\n"

    result = parse_and_apply_patch(patch, ops)

    assert result["ok"] is True
    assert (tmp_path / "empty.txt").read_text(encoding="utf-8") == ""
