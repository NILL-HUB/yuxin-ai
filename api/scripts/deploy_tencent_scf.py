"""部署技能/工作流代码执行器到腾讯云 SCF（函数侧实现见 `internal/core/skills/scf_handler.py`）。

用途：`tencent_scf` 沙箱后端对应的云函数**唯一部署入口**。函数代码不单独维护，
由本脚本把仓库内已测试的 `scf_handler.py` 打包为 `index.py` 上传，保证云端版本
与仓库版本同源（避免"云端代码与仓库代码各改一份"的漂移）。

用法：
    python scripts/deploy_tencent_scf.py \
        --secret-id <AKID...> --secret-key <...> \
        --token <SANDBOX_TOKEN> \
        [--function-name yujianwo-sandbox-runner] [--region ap-guangzhou]

- 函数不存在 → 创建；已存在 → 更新代码与配置（幂等）。
- SANDBOX_TOKEN 写入函数环境变量，函数内 fail-closed 校验（见 scf_handler）。
- 凭证只经命令行传入，不落盘、不写入仓库。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import zipfile
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
HANDLER_SOURCE = API_ROOT / "internal" / "core" / "skills" / "scf_handler.py"

DEFAULT_FUNCTION_NAME = "yujianwo-sandbox-runner"
DEFAULT_REGION = "ap-guangzhou"


def _build_zip() -> str:
    """把 scf_handler.py 打包为 index.py（SCF 入口模块名固定为 index）。"""
    if not HANDLER_SOURCE.is_file():
        raise SystemExit(f"函数源文件不存在: {HANDLER_SOURCE}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.py", HANDLER_SOURCE.read_text(encoding="utf-8"))
    return base64.b64encode(buffer.getvalue()).decode()


def _make_client(secret_id: str, secret_key: str, region: str):
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.scf.v20180416 import scf_client

    http_profile = HttpProfile()
    http_profile.endpoint = "scf.tencentcloudapi.com"
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    return scf_client.ScfClient(
        credential.Credential(secret_id, secret_key), region, client_profile
    )


def _function_exists(client, name: str) -> bool:
    from tencentcloud.scf.v20180416 import models

    request = models.GetFunctionRequest()
    request.from_json_string(json.dumps({"FunctionName": name}))
    try:
        client.GetFunction(request)
        return True
    except Exception:  # noqa: BLE001 - 不存在时 SDK 抛 ResourceNotFound
        return False


def _wait_active(client, name: str, attempts: int = 20, interval: float = 3.0) -> str:
    """等待函数状态回到 Active（更新期间调用其它变更接口会报 Updating）。"""
    from tencentcloud.scf.v20180416 import models

    status = "Unknown"
    for _ in range(attempts):
        request = models.GetFunctionRequest()
        request.from_json_string(json.dumps({"FunctionName": name}))
        status = client.GetFunction(request).Status
        if status == "Active":
            return status
        time.sleep(interval)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="部署沙箱执行器到腾讯云 SCF")
    parser.add_argument("--secret-id", required=True)
    parser.add_argument("--secret-key", required=True)
    parser.add_argument("--token", required=True, help="函数侧 SANDBOX_TOKEN（fail-closed 校验）")
    parser.add_argument("--function-name", default=DEFAULT_FUNCTION_NAME)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--memory", type=int, default=256)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    client = _make_client(args.secret_id, args.secret_key, args.region)
    zip_b64 = _build_zip()

    from tencentcloud.scf.v20180416 import models

    common = {
        "FunctionName": args.function_name,
        "Handler": "index.main_handler",
        "Runtime": "Python3.10",
        "MemorySize": args.memory,
        "Timeout": args.timeout,
        "Environment": {"Variables": [{"Key": "SANDBOX_TOKEN", "Value": args.token}]},
    }

    if _function_exists(client, args.function_name):
        update_code = models.UpdateFunctionCodeRequest()
        update_code.from_json_string(
            json.dumps({**common, "ZipFile": zip_b64})
        )
        client.UpdateFunctionCode(update_code)
        print(f"已更新函数代码: {args.function_name}（region={args.region}）")

        # 代码更新期间函数处于 Updating，需等回 Active 再改配置
        _wait_active(client, args.function_name)

        # 环境变量单独更新：UpdateFunctionCode 不改配置
        update_config = models.UpdateFunctionConfigurationRequest()
        update_config.from_json_string(
            json.dumps(
                {
                    "FunctionName": args.function_name,
                    "MemorySize": args.memory,
                    "Timeout": args.timeout,
                    "Environment": {"Variables": [{"Key": "SANDBOX_TOKEN", "Value": args.token}]},
                }
            )
        )
        client.UpdateFunctionConfiguration(update_config)
        print("已同步函数配置（内存/超时/SANDBOX_TOKEN）")
    else:
        create = models.CreateFunctionRequest()
        create.from_json_string(
            json.dumps(
                {
                    **common,
                    "ZipFile": zip_b64,
                    "Description": "yujianwo skill/workflow code runner (tencent_scf backend)",
                    "AutoCreateClsTopic": "TRUE",
                }
            )
        )
        response = client.CreateFunction(create)
        print(f"已创建函数: {args.function_name} (RequestId={response.RequestId})")

    # 等待状态收敛（Active），便于后续立即可用
    status = _wait_active(client, args.function_name)
    print(f"函数状态: {status}")

    print("部署完成。请在 admin 沙箱配置中为 skill_exec / workflow_code 选择")
    print(f"后端 tencent_scf，并填写 function_name={args.function_name}、region={args.region}")


if __name__ == "__main__":
    sys.exit(main())
