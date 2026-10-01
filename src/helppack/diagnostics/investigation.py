from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from helppack.english import text as msg

from ..english import format_time
from ..english import label as display_label
from ..redaction import redact_text


@dataclass
class Finding:
    layer: str
    state: str
    detail: str


@dataclass
class Investigation:
    title: str
    symptom: str = ""
    findings: list[Finding] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))

    def markdown(self) -> str:
        rows = [f"## {self.title}", msg('检查时间：{0}', format_time(self.timestamp)), msg('症状：{0}', self.symptom or msg('未填写'))]
        for item in self.findings:
            rows.extend([f"### {display_label(item.layer)} · {display_label(item.state)}", item.detail])
        rows += [msg('### 有证据支持的下一步（不代表确定原因）'), *[f"- {r}" for r in self.recommendations]]
        return redact_text("\n\n".join(rows))


def ps_literal(text: str) -> str:
    if not isinstance(text, str) or any(c in text for c in "\x00\r\n"):
        raise ValueError(msg('输入包含不支持的控制字符'))
    return "'" + text.replace("'", "''") + "'"


def query(runner, script: str, timeout: int = 30):
    result = runner.powershell_json("$ErrorActionPreference='Stop';" + " ".join(script.splitlines()), timeout=timeout)
    if result.timed_out:
        raise TimeoutError(msg('查询超时'))
    if result.permission_denied:
        raise PermissionError("Permission denied")
    if result.returncode != 0:
        raise OSError(msg('系统接口查询失败'))
    return result.json_value()


def rows(value) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list) or any(not isinstance(r, dict) for r in value):
        raise ValueError(msg('系统接口没有返回预期结构'))
    return value


def readable(value) -> str:
    labels = {"Path": msg('安装路径'), "Version": msg('版本'), "Product": msg('产品'), "Signature": msg('签名状态'), "Publisher": msg('发布者'),
              "Id": msg('编号'), "Responding": msg('当前窗口响应'), "CPU": msg('累计 CPU 秒数'), "WorkingSet64": msg('内存（字节）'),
              "Runtime": msg('运行库注册项'), "Registered": msg('注册信息存在'), "Release": msg('版本标记'), "TimeCreated": msg('事件时间'),
              "ProviderName": msg('事件来源'), "Message": msg('记录内容'), "Log": msg('日志来源'), "State": msg('读取状态'), "Events": msg('匹配事件'),
              "ErrorType": msg('接口错误类别'), "Name": msg('名称'), "DisplayName": msg('显示名称'), "Status": msg('状态'), "FriendlyName": msg('设备名称'),
              "Default": msg('默认打印机'), "WorkOffline": msg('脱机标志'), "PrinterStatus": msg('打印机状态码'), "PrinterState": msg('打印机状态位'),
              "JobStatus": msg('队列状态'), "TotalPages": msg('总页数'), "PagesPrinted": msg('已打印页数'), "Printer": display_label("打印机")}
    if isinstance(value, dict):
        return "\n".join(f"- {labels.get(str(key), str(key))}：{readable(display_label(item) if key == 'State' and isinstance(item, str) else item)}" for key, item in value.items())
    if isinstance(value, list):
        return "\n\n".join(readable(item) for item in value) or msg('未取得记录；不等于没有故障')
    if value is None:
        return msg('未获得值')
    if isinstance(value, bool):
        return msg('是') if value else msg('否')
    return str(value)
