"""编排层运行时注入的元工具包。

这里的工具不属于 builtin provider 注册体系（无需 .yaml / providers.yaml），
而是在 Agent 执行前由编排层按需注入到 Agent 实例的工具列表，用于让子代理
在「现有工具不够用」时按能力描述申请追加工具。
"""
