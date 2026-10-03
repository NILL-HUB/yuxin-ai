"""桌面 bridge 连接解析器。

解析优先级：
1. **按账号动态解析**：desktop_device 表中该账号已注册且在线的设备（推荐；
   桌面端每次启动随机生成 token 并主动注册，解决静态配置对不上的断链问题）；
2. **静态环境变量回退**：DESKTOP_BRIDGE_URL / DESKTOP_BRIDGE_TOKEN（兼容既有部署）。

工具层只依赖本函数，不直接读表或读环境变量，便于单测与替换。
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 「无可用桌面连接」的**统一用户可见文案**（单一事实源，4 处消费方共用）：
#   os_file_task / os_recycle_bin / os_snapshot（内置工具）与 recycle_bin_handlers（平台回收站）。
# 收敛原因：此前四处各写一份、措辞不一（"均未配置" vs "…或…未配置"），且只讲内部 env 名，
# 用户不知道该怎么办。这里统一为「可执行的引导」，并保留静态回退的准确出处。
DESKTOP_UNAVAILABLE_MESSAGE = (
    "未找到可用的本机连接：当前账号没有在线的桌面设备。"
    "本机操作需要桌面客户端在线——请安装并登录桌面端、保持其在线；"
    "管理员也可配置 OS_AUTOMATION_URL/TOKEN（或 DESKTOP_BRIDGE_URL/TOKEN）使用宿主机 worker。"
)

# 「指定设备不可用」的统一用户可见文案（会话绑定了 device_id 但解析不命中时使用）。
# 与 DESKTOP_UNAVAILABLE_MESSAGE 同源维护：两者都在本模块定义、由 resolve_unavailable_message 选择，
# 工具层不得各写一份判断。
DESKTOP_DEVICE_OFFLINE_MESSAGE = (
    "指定的设备当前不可用（离线或已解绑）：本机操作需要该设备的桌面客户端在线。"
    "请在设备列表中确认它已启动并保持在线，或改选其他设备后重试。"
)


def resolve_unavailable_message(device_id: Any = None) -> str:
    """无可用桌面连接时的统一文案选择（工具层唯一入口）。

    - 指定了 device_id：返回「指定设备离线」文案（不误导用户去装桌面端）；
    - 未指定：返回既有「无桌面设备」引导文案。
    """
    return (
        DESKTOP_DEVICE_OFFLINE_MESSAGE
        if str(device_id or "").strip()
        else DESKTOP_UNAVAILABLE_MESSAGE
    )


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def resolve_desktop_bridge(
    account_id: Any = None,
    *,
    purpose: str = "",
    device_id: Any = None,
) -> tuple[str, str] | None:
    """解析可用的桌面 bridge (origin, token)；无可用来源返回 None。

    Args:
        account_id: 当前账号 ID（工具实例的 requester）。缺失时跳过动态解析。
        purpose: 仅用于日志（如 "/file" / "/control"）。
        device_id: 会话绑定的设备标识。
            - 为空：保持既有行为（默认设备 > 最近在线 → 静态环境变量回退）；
            - 非空：**只解析指定设备**（校验归属 + 心跳租约），不命中直接返回 None，
              **不回退静态配置**——「指定设备」语义下静默换到别的机器执行是错误行为，
              调用方应以 resolve_unavailable_message(device_id) 返回明确文案。
    """
    requested = _normalize(device_id)
    if requested:
        if account_id:
            try:
                from internal.extension.database_extension import db
                from internal.service.desktop_device_service import DesktopDeviceService

                resolved = DesktopDeviceService(db=db).resolve_bridge_for(account_id, requested)
                if resolved:
                    origin, token = resolved
                    logger.info(
                        "桌面 bridge 按指定设备解析成功(%s) account=%s device=%s",
                        purpose,
                        account_id,
                        requested,
                    )
                    return origin, token
                logger.info(
                    "桌面 bridge 指定设备不可用(%s) account=%s device=%s",
                    purpose,
                    account_id,
                    requested,
                )
            except Exception:
                logger.warning(
                    "按指定设备解析桌面 bridge 失败(%s) account=%s device=%s，不回退静态配置",
                    purpose,
                    account_id,
                    requested,
                    exc_info=True,
                )
        return None

    if account_id:
        try:
            from internal.extension.database_extension import db
            from internal.service.desktop_device_service import DesktopDeviceService

            resolved = DesktopDeviceService(db=db).resolve_bridge(account_id)
            if resolved:
                origin, token = resolved
                logger.info("桌面 bridge 按账号解析成功(%s) account=%s", purpose, account_id)
                return origin, token
        except Exception:
            logger.warning(
                "按账号解析桌面 bridge 失败(%s) account=%s，回退静态配置",
                purpose,
                account_id,
                exc_info=True,
            )

    url = _normalize(os.getenv("DESKTOP_BRIDGE_URL"))
    token = _normalize(os.getenv("DESKTOP_BRIDGE_TOKEN"))
    if url and token:
        return url.rstrip("/"), token
    return None
