# Orca（stablyai/orca）调研

## 结论

Orca 可以用于我们的工作流，但它不是一个 Codex skill，而是一个独立的桌面 Agent 开发环境（ADE）。它适合在同一个仓库里并行跑多个编码 agent，比较结果后选择或合并；不适合当作“装进 Codex 的技能”来使用。

当前机器是 Windows x64，且已经安装了 Codex CLI，所以直接下载官方 Windows 安装包即可使用。

## 它是什么

- 项目：`stablyai/orca`
- 定位：The AI Orchestrator for 100x builders，官方文档称其为“用于并排运行多个 AI 编码 agent 的桌面 IDE”
- 许可：MIT，免费开源
- 最新版：v1.4.180（GitHub API 查询），Windows 安装包约 187 MB
- 作者/公司：Stably AI，不是 Stability AI

核心模型是“bring your own subscription”：Orca 本身不是模型，也不托管模型额度。它调度你已经有的 CLI agent，例如 Codex、Claude Code、OpenCode、Cursor CLI、Grok、Pi 等。

## 核心能力

- **并行 worktree**：每个任务用真实 `git worktree` 隔离，互不踩文件；可让多个 agent 同时尝试同一个任务，再对比 diff 选赢家
- **Terminal splits**：内置终端，支持多分屏和重启后保留 scrollback
- **Design Mode**：在真实 Chromium 窗口里点 UI 元素，把 HTML/CSS/截图直接送进 agent prompt
- **GitHub / Linear 原生集成**：在应用内浏览 PR、issue、看板，从任务创建 worktree
- **SSH worktrees**：把 agent 跑在远程机器或 VPS 上
- **Annotate AI Diffs**：在 diff 行上评论并把反馈送回 agent
- **Orca CLI**：`orca worktree create`、`snapshot`、`click`、`fill` 等，可被 agent 或脚本驱动
- **Mobile Companion**：手机端查看 agent 完成状态、发 follow-up
- 支持“任何能在终端里运行的 CLI agent”

## 我们能不能用

能。依据：

- 官方支持 Windows，最新 release 提供 `orca-windows-setup.exe`
- 本机是 Windows 11（build 26200，x64）
- 本机已安装 Codex CLI：`C:\Program Files\WindowsApps\OpenAI.Codex_...\app\resources\codex.exe`
- MIT 许可，没有授权费用

使用前提：

- 需要安装 Orca 桌面应用
- 需要已有 Codex / Claude Code 等 CLI agent 的账号或订阅，Orca 复用这些身份
- 第一次使用前要把仓库加入 Orca，之后每个任务会创建独立 git worktree

## 落地建议

- 适合：多个 agent 并行尝试同一 bug、方案对比、跨 agent 并行实现、远程机器跑长任务
- 不适合：普通单 agent 日常开发，这种场景下 Orca 是额外的桌面层
- 本项目仓库较大且 `ui/node_modules` 被 gitignore，新 worktree 默认是干净 checkout，不会带依赖。正式使用前建议配置 worktree shared directories（`orca.yaml` 的 `worktree.sharedDirectories` 或仓库根目录 `.worktreeinclude`），避免每个 worktree 重新安装依赖
- 如果只想在无桌面 VPS 上跑，官方支持 `orca serve` 的无头 Linux 模式，但不是 Windows 本机的默认用法
- 如果想从源码开发 Orca，仓库要求 Node 24 和 `pnpm@10.24.0`，比直接下载安装包重得多

## 风险 / 注意点

- 项目迭代非常快，release 几乎每天发布，当前 GitHub 上有 3500+ open issues，功能变化大
- 并行 agent 会同时消耗多个订阅额度，需要关注 usage tracking
- worktree 隔离只解决文件冲突，不替代人工 diff review；提交前仍要审核 AI 改动
- Orca 是桌面应用，不改变 Codex、Graphify 等现有工具的工作方式

## 来源

- GitHub README：https://github.com/stablyai/orca
- 官方文档：https://www.onorca.dev/docs
- Worktree 文档：https://www.onorca.dev/docs/model/worktrees
- Headless Linux Server 文档：https://github.com/stablyai/orca/blob/main/docs/reference/headless-linux-server.md
- 最新 release / Windows 安装包：https://github.com/stablyai/orca/releases/latest
- YC 公司页：https://www.ycombinator.com/companies/stably-ai-orca
