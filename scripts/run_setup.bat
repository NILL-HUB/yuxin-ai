@echo off
REM openagent 全面验证 + 批量导入脚本启动器
REM 双击此文件或在 cmd 中运行: scripts\run_setup.bat
REM 兼容 Windows PowerShell 5.1 (无需安装 pwsh)

cd /d "%~dp0\.."
echo ============================================================
echo  openagent 全面验证 + 批量导入 (MCP + Skills)
echo ============================================================
echo.
echo 将执行以下步骤:
echo   1. 重建 API 容器 (含 mcp SDK + nodejs)
echo   2. 验证数据库迁移
echo   3. 验证凭证加密
echo   4. 验证 mcp SDK + nodejs
echo   5. 预热 npx 包
echo   6. 批量导入 10 个 MCP 工具 + 33 个 Skill 工具
echo   7. 验证导入结果
echo   8. 前端构建验证
echo.
echo 预计耗时 5-10 分钟，请耐心等待...
echo.
pause

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\full_setup.ps1"

echo.
echo ============================================================
echo  脚本执行完毕，按任意键关闭窗口
echo ============================================================
pause
