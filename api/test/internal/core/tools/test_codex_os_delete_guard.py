"""delete_guard：识别终端删除命令的单元测试。"""
from internal.core.tools.builtin_tools.providers.codex_os.delete_guard import (
    find_delete_command,
    DELETE_COMMANDS,
)


class TestFindDeleteCommand:
    def test_returns_none_when_no_delete_command(self):
        assert find_delete_command("Write-Output hello") is None
        assert find_delete_command("ls -la") is None
        assert find_delete_command("Get-Content file.txt") is None

    def test_returns_powershell_remove_item(self):
        assert find_delete_command("Remove-Item C:\\temp\\x.txt") is not None

    def test_returns_powershell_del_alias(self):
        assert find_delete_command("del C:\\temp\\x.txt") is not None

    def test_returns_cmd_del(self):
        assert find_delete_command("del /f /q C:\\temp\\x.txt") is not None

    def test_returns_unix_rm(self):
        assert find_delete_command("rm -rf /home/user/tmp") is not None

    def test_returns_unix_rmdir(self):
        assert find_delete_command("rmdir /home/user/old") is not None

    def test_powershell_remove_item_case_insensitive(self):
        assert find_delete_command("remove-item file.txt") is not None

    def test_tolerates_multiline_scripts(self):
        script = (
            "$files = Get-ChildItem C:\\temp\n"
            "foreach ($f in $files) { Remove-Item $f.FullName }\n"
        )
        assert find_delete_command(script) is not None

    def test_returns_exact_command_text_for_report(self):
        match = find_delete_command("  Remove-Item  C:\\temp\\x.txt  ")
        assert match is not None
        assert "Remove-Item" in match.command
        assert match.index >= 0

    def test_recognizes_variable_assignment_prefix(self):
        assert find_delete_command("$x = Remove-Item C:\\temp\\x.txt") is not None

    def test_match_returns_command_and_reason(self):
        match = find_delete_command("rm -rf /home/user/tmp")
        assert match is not None
        assert match.command == "rm -rf /home/user/tmp"
        assert match.index >= 0
        assert match.reason
        assert "rm" in match.reason.lower()

    def test_delete_commands_exported(self):
        assert "rm" in DELETE_COMMANDS
        assert "remove-item" in DELETE_COMMANDS
        assert "del" in DELETE_COMMANDS
        assert "rmdir" in DELETE_COMMANDS
        assert "rd" in DELETE_COMMANDS
        assert "erase" in DELETE_COMMANDS
        assert "ri" in DELETE_COMMANDS
        assert "unlink" in DELETE_COMMANDS


class TestNoFalsePositive:
    """防误报回归红线：行首/注释/非执行语义中的删除字样一律不命中。

    保守启发式语义：只有"命令名出现在行首或命令边界"才算命中；
    这些场景全部落在执行语义之外，历史上曾回归风险高，锁死不许误报。
    """

    def test_comment_text_with_delete_words_is_ignored(self):
        assert find_delete_command("# rm -rf /") is None
        assert find_delete_command("# Remove-Item x") is None
        assert find_delete_command("rem del file.txt") is None
        assert find_delete_command("# 不要执行 rm -rf /") is None

    def test_non_delete_statement_containing_command_words(self):
        assert find_delete_command("Write-Output \"rm -rf /\"") is None
        assert find_delete_command("echo del file.txt") is None
        assert find_delete_command("Get-Help Remove-Item") is None

    def test_delete_word_as_argument_value_has_no_command_boundary(self):
        assert find_delete_command("Get-Content notes.txt -Path \"del\"") is None
        assert find_delete_command("Write-Output 'rm'") is None

    def test_parameter_zone_only_collision_is_not_a_hit(self):
        assert find_delete_command("Get-ChildItem -Filter 'rm *'") is None
