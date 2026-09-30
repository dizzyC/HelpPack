"""Shared Microsoft Store probe and version-compatible repair commands."""
from __future__ import annotations

FAMILY = "Microsoft.WindowsStore_8wekyb3d8bbwe"

STORE_PROBE = r"""
$ErrorActionPreference='Stop';
$packages=@(Get-AppxPackage -Name Microsoft.WindowsStore -ErrorAction Stop);
$p=$packages | Where-Object {$_.PackageFamilyName -eq 'Microsoft.WindowsStore_8wekyb3d8bbwe'} | Select-Object -First 1;
$blocked=$false;
foreach($h in @('HKLM:','HKCU:')) {
  $k=Join-Path $h 'SOFTWARE\Policies\Microsoft\WindowsStore';
  if(Test-Path -LiteralPath $k) {
    $policy=Get-ItemProperty -LiteralPath $k -ErrorAction Stop;
    if($policy.RemoveWindowsStore -eq 1){$blocked=$true}
  }
};
$add=Get-Command Add-AppxPackage -ErrorAction SilentlyContinue;
$reset=Get-Command Reset-AppxPackage -ErrorAction SilentlyContinue;
$manifest=$false;
if($p -and $p.InstallLocation) {$manifest=Test-Path -LiteralPath (Join-Path $p.InstallLocation 'AppxManifest.xml')};
[pscustomobject]@{
  Exists=[bool]$p;Status=[string]$p.Status;PolicyDisabled=$blocked;
  CanRegisterByFamily=[bool]($add -and $add.Parameters.ContainsKey('RegisterByFamilyName'));
  CanReset=[bool]$reset;ManifestExists=$manifest;
  Version=[string]$p.Version;
  WsresetAvailable=(Test-Path -LiteralPath (Join-Path $env:SystemRoot 'System32\wsreset.exe'))
}|ConvertTo-Json -Compress
"""

STORE_REGISTER = r"""
$ErrorActionPreference='Stop';
$p=Get-AppxPackage -Name Microsoft.WindowsStore -ErrorAction Stop |
  Where-Object {$_.PackageFamilyName -eq 'Microsoft.WindowsStore_8wekyb3d8bbwe'} | Select-Object -First 1;
if($p -and $p.InstallLocation) {
  $manifest=Join-Path $p.InstallLocation 'AppxManifest.xml';
  if(-not (Test-Path -LiteralPath $manifest)){throw 'Store 安装文件不完整，请使用 Windows 修复设置'};
  Add-AppxPackage -DisableDevelopmentMode -Register $manifest -ErrorAction Stop;
} else {throw '当前用户未注册商店；需先确认机器级包存在，不能直接执行注册'};
if(-not (Get-AppxPackage -Name Microsoft.WindowsStore -ErrorAction Stop)){throw '未恢复当前用户注册'};
"""


def read_store_state(runner) -> dict:
    command = runner.powershell_json(" ".join(STORE_PROBE.splitlines()), timeout=30)
    if command.timed_out or command.returncode != 0:
        raise RuntimeError("商店状态读取失败，不能据此判断应用缺失")
    state = command.json_value()
    fields = ("Exists", "PolicyDisabled", "CanRegisterByFamily", "CanReset", "ManifestExists", "WsresetAvailable")
    if not isinstance(state, dict) or any(type(state.get(field)) is not bool for field in fields):
        raise ValueError("商店检查没有返回完整、可验证的数据")
    return state
