import time
from typing import Optional
from langchain_core.runnables import RunnableConfig
from internal.core.agent.backends import HttpSandboxHandle, build_sandbox_backend
from internal.core.agent.entities.sandbox_runtime_entity import CAPABILITY_WORKFLOW_CODE
from internal.core.agent.sandbox_runtime_registry import get_sandbox_runtime
from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import VARIABLE_TYPE_DEFAULT_VALUE_MAP
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state
from internal.exception import FailException
from .code_entity import CodeNodeData


def _resolve_http_sandbox_handle() -> HttpSandboxHandle | None:
    """解析工作流代码能力域当前激活的 HTTP 沙箱句柄。

    沙箱配置的**唯一权威入口**：经注册表读取运行时快照（由 `SandboxConfigService
    .resolve_runtime` 解析，admin 热切换后生效），再经工厂构造 HTTP 传输句柄。
    本模块**不再读 env、不再自己发请求**。
    """
    handle = build_sandbox_backend(get_sandbox_runtime(CAPABILITY_WORKFLOW_CODE))
    return handle if isinstance(handle, HttpSandboxHandle) else None


class CodeNode(BaseNode):
    """Python代码运行节点"""
    node_data: CodeNodeData

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """Python代码运行节点，执行的代码函数名字必须为main，并且参数名为params，有且只有一个参数，通过腾讯云函数沙箱执行"""
        # 1.从状态中提取输入数据
        start_at = time.perf_counter()
        inputs_dict = extract_variables_from_state(self.node_data.inputs, state)

        # 2.通过腾讯云函数沙箱执行Python代码
        result = self._execute_function(self.node_data.code, params=inputs_dict)

        # 3.检测函数的返回值是否为字典
        if not isinstance(result, dict):
            raise FailException("main函数的返回值必须是一个字典")

        # 4.提取输出数据
        outputs_dict = {}
        outputs = self.node_data.outputs
        for output in outputs:
            # 5.提取输出数据(非严格校验)
            outputs_dict[output.name] = result.get(
                output.name,
                VARIABLE_TYPE_DEFAULT_VALUE_MAP.get(output.type),
            )

        # 6.构建状态数据并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED.value,
                    inputs=inputs_dict,
                    outputs=outputs_dict,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }

    @classmethod
    def _execute_function(cls, code: str, *args, **kwargs):
        """通过远端沙箱服务执行Python代码（句柄经沙箱配置中心解析，统一传输入口）。"""
        try:
            # 1.解析该能力域当前激活的 HTTP 沙箱句柄（admin 可配、热切换）
            handle = _resolve_http_sandbox_handle()
            if handle is None:
                raise FailException("工作流代码沙箱未配置：请在 admin 沙箱配置中启用并填写 endpoint")

            # 2.构建请求参数
            # 优先支持传入 params=... 的场景（你的 invoke 会传 params=inputs_dict）
            payload_args = []
            payload_kwargs = {}

            # 如果调用时显式传入 params（常用约定），把它作为第一个位置参数传递
            if "params" in kwargs:
                payload_args = [kwargs.pop("params")]
            else:
                # 如果调用时传了位置参数，就直接传这些位置参数
                if args:
                    # args 可能是元组，转换为 list
                    payload_args = list(args)

            # 其余剩下的 kwargs 一并透传（若为空，则传空对象）
            payload_kwargs = kwargs or {}

            payload = {
                "code": code,
                "func_name": "main",   # 强制要求 main
                "args": payload_args,
                "kwargs": payload_kwargs,
            }

            # 3.经统一 HTTP 句柄发送（endpoint 校验/超时/状态码/非JSON/网络异常由句柄收敛）
            response_data = handle.execute(payload, timeout=30)

            # 4.检查是否有错误信息
            if isinstance(response_data, dict) and "error" in response_data:
                # 如果 trace 可用也带上
                tb = response_data.get("traceback")
                if tb:
                    raise FailException(f"代码执行出错: {response_data['error']}\n{tb}")
                raise FailException(f"代码执行出错: {response_data['error']}")

            # 5.返回执行结果（期望 cloud 返回 {"result": ...}）
            if isinstance(response_data, dict) and "result" in response_data:
                return response_data["result"]
            raise FailException(f"云函数返回数据格式错误: {response_data}")

        except FailException:
            raise
        except Exception as e:
            raise FailException(f"Python代码执行出错: {str(e)}")
