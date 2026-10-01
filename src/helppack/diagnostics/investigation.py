from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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
        rows = [f"## {self.title}", f"检查时间：{self.timestamp}", f"症状：{self.symptom or '未填写'}"]
        for item in self.findings:
            rows.extend([f"### {item.layer} · {item.state}", item.detail])
        rows += ["### 有证据支持的下一步（不代表确定原因）", *[f"- {r}" for r in self.recommendations]]
        return redact_text("\n\n".join(rows))


def ps_literal(text: str) -> str:
    if not isinstance(text, str) or any(c in text for c in "\x00\r\n"):
        raise ValueError("输入包含不支持的控制字符")
    return "'" + text.replace("'", "''") + "'"


def query(runner, script: str, timeout: int = 30):
    result = runner.powershell_json("$ErrorActionPreference='Stop';" + " ".join(script.splitlines()), timeout=timeout)
    if result.timed_out:
        raise TimeoutError("查询超时")
    if result.permission_denied:
        raise PermissionError("权限不足")
    if result.returncode != 0:
        raise OSError("系统接口查询失败")
    return result.json_value()


def rows(value) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list) or any(not isinstance(r, dict) for r in value):
        raise ValueError("系统接口没有返回预期结构")
    return value


def readable(value) -> str:
    labels = {"Path": "安装路径", "Version": "版本", "Product": "产品", "Signature": "签名状态", "Publisher": "发布者",
              "Id": "编号", "Responding": "当前窗口响应", "CPU": "累计 CPU 秒数", "WorkingSet64": "内存（字节）",
              "Runtime": "运行库注册项", "Registered": "注册信息存在", "Release": "版本标记", "TimeCreated": "事件时间",
              "ProviderName": "事件来源", "Message": "记录内容", "Log": "日志来源", "State": "读取状态", "Events": "匹配事件",
              "ErrorType": "接口错误类别", "Name": "名称", "DisplayName": "显示名称", "Status": "状态", "FriendlyName": "设备名称",
              "Default": "默认打印机", "WorkOffline": "脱机标志", "PrinterStatus": "打印机状态码", "PrinterState": "打印机状态位",
              "JobStatus": "队列状态", "TotalPages": "总页数", "PagesPrinted": "已打印页数", "Printer": "打印机"}
    if isinstance(value, dict):
        return "\n".join(f"- {labels.get(str(key), str(key))}：{readable(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "\n\n".join(readable(item) for item in value) or "未取得记录；不等于没有故障"
    if value is None:
        return "未获得值"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)
