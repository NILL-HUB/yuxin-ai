# Better Harness（QoderAI/better-harness）调研

## 结论

**可以用，而且很适合我们当前阶段。** Better Harness 不是模型，也不是新的编码 agent，而是一个“评估和改进 Coding Agent 工作流”的开源工具。它支持 Codex Desktop，直接作为 Codex 插件安装即可。

## 它是什么

- 项目：`QoderAI/better-harness`
- 定位：面向 Coding Agent 工作流的开源分析与持续改进工具
- 一句话：把项目里 `AGENTS.md`、Skills、Hooks、测试、MCP、Session 证据等“外圈机制”梳理成证据报告，而不是只看最后一次 diff
- 许可：MIT
- 版本：当前 `.codex-plugin/plugin.json` 版本为 `0.5.0`
- 创建时间：2026-07-21，目前约 1800 stars，8 个 open issues，属于较新但迭代很快的项目

## 它解决什么问题

官方把它叫做 Agent Work Loop 分析，从五个维度评估：

| 维度 | 回答的问题 |
| --- | --- |
| Task Understanding | Agent 是否清楚目标和“做完”的标准 |
| Controlled Execution | 工作是否走在可复现、受控的路径上 |
| Change Validation | 是否有证据证明改动真的有效 |
| Reliable Delivery | 是否绕过 review、审批、CI 等质量关卡 |
| Learning Capture | 这次任务的经验是否留给了下一次 |

报告会把缺失证据明确标出来，并生成有优先级、有修复范围、有验收方式的 finding，可以接着让 Agent 修。

## 工作方式

1. 收集一个版本化的证据包：Session 证据、Project Harness 证据、Agent 资产证据
2. 并行启动三个独立、只读的证据 Agent
3. 由主 Agent 统一核对、分级、打分
4. 生成 `findings.json`、`report.md`、`report.html`

Codex 的默认输出是自包含 HTML + Markdown，报告放在 `.codex/better-harness`。

## 我们能不能用

能，理由：

- 官方明确支持 Codex Desktop：Settings > Plugins > Add > From Marketplace
- 仓库 URL：`https://github.com/QoderAI/better-harness.git`，Git ref 用 `main`，Sparse paths 留空
- 本机 Node 为 `24.9.0`、npm 为 `11.6.0`，满足源码/CLI 路径要求的 `>=22.20.0 <25` 和 `>=10.9.3 <12`
- 我们仓库已经有它要分析的“harness”素材：`AGENTS.md`、`docs/agents/`、大量 Skills、`.codex/hooks.json`、git hooks、Graphify 图谱和报告
- 运行方式是 Codex 插件，不需要额外服务器

安装后在新任务里调用：

```text
@better-harness analyze this project's AI coding workflow and generate an evidence-backed report
```

如果以后用 Codex CLI，也可以：

```bash
codex plugin marketplace add "https://github.com/QoderAI/better-harness.git" --ref main
codex plugin list --marketplace better-harness
codex plugin add better-harness@better-harness
```

## 风险 / 注意点

- 运行时会并行启动三个证据 Agent，需要 Codex 侧支持子代理能力；当前这个会话没有直接暴露 `spawn_agent`，但插件安装后由 Better Harness 自己的工作流触发
- 它会读取 Session 和 Agent 配置类证据；Memory 正文、用户目录、全局配置等范围需要显式授权
- 项目较新，报告模型和安装契约还在演进，README 明确说不能跨 host 通用一个入口
- 它不会替代我们现有的 Graphify、Codex skills 或 git hooks，而是评估它们是否被真正接进工作流

## 来源

- GitHub 仓库：https://github.com/QoderAI/better-harness
- 官方 README：https://github.com/QoderAI/better-harness/blob/main/README.md
- 中文 README：https://github.com/QoderAI/better-harness/blob/main/README.zh-CN.md
- 安装文档：https://qoderai.github.io/better-harness/docs/installation
- Host Adapter Matrix：https://github.com/QoderAI/better-harness/blob/main/docs/adapters/README.md
- 架构说明：https://github.com/QoderAI/better-harness/blob/main/docs/ARCHITECTURE.md
- Codex 插件清单：https://github.com/QoderAI/better-harness/blob/main/.codex-plugin/plugin.json
