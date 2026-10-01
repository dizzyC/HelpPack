"""Fresh read-only checks immediately before a system-changing command."""
from __future__ import annotations

import json

from helppack.english import text as msg

from .runner import CommandRunner


def check_preconditions(action_id: str, target: dict[str, str], runner: CommandRunner) -> None:
    from .repairs import RepairExecutionError, is_admin

    def query(script: str):
        result = runner.powershell_json("$ErrorActionPreference='Stop';" + script, timeout=30)
        if result.returncode != 0 or result.timed_out:
            raise RepairExecutionError(msg('无法复核执行条件，已取消本次修改'))
        try:
            value = result.json_value()
        except (ValueError, TypeError) as exc:
            raise RepairExecutionError(msg('安全检查未返回可靠数据，已取消修改')) from exc
        if value is None:
            raise RepairExecutionError(msg('安全检查结果为空，已取消修改'))
        return value

    if action_id.startswith("store_"):
        if is_admin():
            raise RepairExecutionError(msg('请以普通用户身份启动 HelpPack，再修复当前用户的商店'))
        from .store import read_store_state
        state = read_store_state(runner)
        if state["PolicyDisabled"]:
            raise RepairExecutionError(msg('Store 被策略禁用，已取消修改'))
        if action_id == "store_reregister":
            if not (state["Exists"] and state["ManifestExists"]):
                raise RepairExecutionError(msg('当前系统没有可验证的商店注册修复入口'))
        elif not state["Exists"]:
            raise RepairExecutionError(msg('当前用户尚未注册 Store；缓存清理或数据重置不适用'))
        if action_id == "store_cache_reset" and not state["WsresetAvailable"]:
            raise RepairExecutionError(msg('未找到 Windows 内置缓存清理程序，已取消操作'))
        if action_id == "store_reset_data" and not state["CanReset"]:
            raise RepairExecutionError(msg('当前 Windows 不支持 Reset-AppxPackage，请使用应用设置'))

    if action_id in {"renew_dhcp", "reset_dns_to_dhcp", "reset_tcp_ip", "reset_winsock"}:
        state = query(
            "@(Get-NetAdapter -IncludeHidden | ForEach-Object {"
            "$i=Get-NetIPInterface -InterfaceIndex $_.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue;"
            "[pscustomobject]@{Index=$_.ifIndex;Alias=$_.Name;Description=$_.InterfaceDescription;"
            "Physical=$_.HardwareInterface;Dhcp=[string]$i.Dhcp;Status=[string]$_.Status}})|ConvertTo-Json -Compress"
        )
        rows = state if isinstance(state, list) else [state]
        if action_id in {"reset_tcp_ip", "reset_winsock"}:
            # A global reset cannot be scoped to a selected adapter. Fail closed
            # when even a disconnected virtual adapter or static interface exists.
            if not rows or any(not row.get("Physical") or row.get("Dhcp") != "Enabled" for row in rows):
                raise RepairExecutionError(msg('存在静态或虚拟接口，禁止自动重置网络栈'))
            raise RepairExecutionError(msg('尚无可靠证据定位网络栈损坏，请先执行定向网络检测'))
        matches = [row for row in rows if (
            str(row.get("Index")) == target.get("interface_index")
            if "interface_index" in target else row.get("Alias") == target.get("interface_alias")
        )]
        if len(matches) != 1 or matches[0].get("Dhcp") != "Enabled" or not matches[0].get("Physical"):
            raise RepairExecutionError(msg('所选接口已变化、不是物理 DHCP 接口或无法唯一定位，已取消修改'))

    if action_id in {"service_start", "service_restart"}:
        name = target["service_name"]  # validated by the action whitelist
        state = query(f"Get-CimInstance Win32_Service -Filter \"Name='{name}'\" | Select-Object State,StartMode | ConvertTo-Json")
        if state.get("StartMode") == "Disabled":
            raise RepairExecutionError(msg('该服务已禁用；不会修改启动类型或覆盖管理设置'))

    if action_id in {"dism_restore_health", "sfc_scan"}:
        state = query(
            "$c=Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing' -ErrorAction SilentlyContinue;"
            "[pscustomobject]@{Pending=(Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing\\RebootPending');"
            "Repairable=[bool]$c.RepairNeeded}|ConvertTo-Json"
        )
        if state.get("Pending"):
            raise RepairExecutionError(msg('Windows 有待完成的重启，请先保存工作并自行重启'))
        if not state.get("Repairable"):
            raise RepairExecutionError(msg('尚未取得组件损坏证据，请先进行管理员只读组件检测'))


def serialize_evidence(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
