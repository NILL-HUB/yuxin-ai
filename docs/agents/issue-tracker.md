# Issue tracker：GitHub

本仓库的 issue 和 spec 都保存在 GitHub Issues 中。所有操作都使用 `gh` CLI。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`。多行正文使用 heredoc。
- **读取 issue**：`gh issue view <number> --comments`，用 `jq` 过滤评论，并同时获取标签。
- **列出 issue**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，配合 `--label` 和 `--state` 过滤器使用。
- **评论 issue**：`gh issue comment <number> --body "..."`
- **添加 / 移除标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭 issue**：`gh issue close <number> --comment "..."`

从 `git remote -v` 推断仓库；在 clone 内运行时 `gh` 会自动完成。

## 将 PR 作为请求入口

**PRs as a request surface: no.** （如果本仓库把外部 PR 也当作功能请求，请改为 `yes`；`/triage` 会读取这个标记。）

当设为 `yes` 时，PR 会与 issue 使用相同的标签和状态，只是使用 `gh pr` 对应的命令：

- **读取 PR**：`gh pr view <number> --comments`，diff 使用 `gh pr diff <number>`。
- **列出待 triage 的外部 PR**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，然后只保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 的条目（丢弃 `OWNER`/`MEMBER`/`COLLABORATOR`）。
- **评论 / 打标签 / 关闭**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 和 PR 共用同一套编号，因此单独的 `#42` 可能是其中任意一种——用 `gh pr view 42` 确认，失败再回退到 `gh issue view 42`。

## 当技能说“发布到 issue tracker”时

创建一个 GitHub issue。

## 当技能说“获取相关 ticket”时

运行 `gh issue view <number> --comments`。

## Wayfinding 操作

供 `/wayfinder` 使用。**map** 是一个单独的 issue，**子 issue** 就是 ticket。

- **Map**：一个标记为 `wayfinder:map` 的 issue，保存 Notes / Decisions-so-far / Fog 正文。创建方式：`gh issue create --label wayfinder:map`。
- **子 ticket**：一个通过 GitHub sub-issue 接口关联到 map 的 issue（使用 `gh api` 调用 sub-issues 接口）。如果 sub-issues 未启用，就把子项写进 map 正文的 task list，并在子项正文顶部加上 `Part of #<map>`。标签使用 `wayfinder:<type>`（`research`/`prototype`/`grilling`/`task`）。一旦被认领，ticket 就分配给负责开发的开发人员。
- **阻塞关系**：使用 GitHub 原生的 **issue dependencies**，这也是 UI 上可见的规范表示。用 `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>` 添加依赖边，其中 `<blocker-db-id>` 是阻塞项的数值型 **database id**（`gh api repos/<owner>/<repo>/issues/<n> --jq .id`，不是 `#number` 或 `node_id`）。GitHub 会通过 `issue_dependencies_summary.blocked_by` 报告依赖（只统计未关闭的阻塞项，作为实时门禁）。如果依赖功能不可用，就在子项正文顶部回退到 `Blocked by: #<n>, #<n>` 列表。当所有阻塞项都关闭后，ticket 才算解除阻塞。
- **Frontier 查询**：列出 map 下未关闭的子项（`gh issue list --state open`，限定到 map 的 sub-issues / task list），去掉仍有未关闭阻塞项（`issue_dependencies_summary.blocked_by > 0`，或 `Blocked by` 行中存在未关闭 issue）或已有 assignee 的项；按 map 顺序取第一项。
- **认领**：`gh issue edit <n> --add-assignee @me`——这是本次会话的第一次写入。
- **解决**：先 `gh issue comment <n> --body "<answer>"`，再 `gh issue close <n>`，然后把上下文指针（gist + 链接）追加到 map 的 Decisions-so-far。
