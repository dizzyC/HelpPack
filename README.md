# 求助包（HelpPack）

HelpPack 是一个面向普通 Windows 用户的本地故障信息整理工具。用户通过向导描述问题，应用按项采集必要的系统状态、自动脱敏，并导出可发给朋友、客服或 AI 的 Markdown 报告或 ZIP 求助包。

应用也提供保守的“本机诊断”：按问题类型执行 L0 只读检查，逐项展示证据、状态、严重程度、可信度和建议，再由用户决定是否把结果加入求助包。完整能力边界见 [诊断能力矩阵](docs/diagnostic-capability-matrix.md)。

## 产品与隐私边界

- 信息在本机处理，不需要服务器、账号或登录。
- 仅采集 Windows 版本、架构、CPU、内存、磁盘空间、可可靠读取的显卡信息、网络接口状态、默认网关/DNS 检测、当前时间和开机时间。
- 不自动读取浏览历史、文档内容、密码/密钥、剪贴板、Wi-Fi 密码或完整文件列表。
- 报告自动尝试隐藏用户名、用户目录、IP、MAC、邮箱和常见密钥字段。
- 截图不做 OCR 脱敏；用户必须在导出前自行检查。
- 自动脱敏基于规则，不能保证识别所有隐私或密钥格式。预览页允许删除系统字段并直接编辑报告。
- DNS 状态检测会解析 `www.microsoft.com`；默认网关检测会向本机网关发送一次 ping。除此之外应用不主动上传内容。
- 本机诊断默认只读。第一版自动修复白名单仅包含“禁用一个明确选择的 HKCU 启动项”和“重置当前用户代理/PAC”；均需对象级二次确认、修改前备份、执行后复查，并可回滚。
- SFC、DISM、网络栈/Winsock 重置、驱动或固件操作、磁盘修复、服务批量修改等不会由第一版自动执行。

## 目录结构

```text
src/helppack/
  app.py             应用入口
  models.py          数据模型
  collector.py       容错系统信息采集
  redaction.py       隐私脱敏
  report.py          Markdown 报告生成
  exporter.py        Markdown / ZIP / manifest 导出
  attachments.py     截图校验和命名
  workers.py         非阻塞采集线程
  diagnostics/       诊断模型、检查器、命令安全、修复/回滚编排
  ui/main_window.py  PySide6 向导界面
tests/                核心自动化测试
docs/                 诊断能力审计与边界
examples/             示例报告
```

## 开发环境搭建

要求 Windows 与 Python 3.12。以下命令只创建项目内虚拟环境，不修改系统级配置：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

## 启动

```powershell
.\run.ps1
```

或：

```powershell
.\.venv\Scripts\python.exe -m helppack
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

静态检查：

```powershell
.\.venv\Scripts\ruff.exe check src tests scripts helppack_launcher.py
```

执行真实采集并验证报告、ZIP、manifest 和 SHA-256：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_artifacts.py
```

仅执行 L0 综合诊断，并确认启动项和代理配置扫描前后未变化：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_diagnostics.py
```

界面事件、缩放、后台响应、取消和中文渲染截图验证：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_ui_runtime.py
```

扫描计划发布的源代码、测试和文档，阻止真实用户名、用户目录和常见真实密钥进入发布内容：

```powershell
.\.venv\Scripts\python.exe .\scripts\scan_release_content.py
```

当前发布门禁结果见 [发布前功能验证报告](docs/verification-report.md)。`dist/`、`build/`、虚拟环境、验证 ZIP 和截图不会提交到 GitHub。

## 截图与演示

仓库暂不提交本机验证过程中生成的界面截图或诊断输出，避免把用户环境信息带入公开仓库。后续可在完成独立演示环境录制后，将不含真实个人数据的截图放在此处。

无桌面会话时可做最小 Qt 构造检查：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -c "from PySide6.QtWidgets import QApplication; from helppack.ui.main_window import MainWindow; app=QApplication([]); w=MainWindow(); print(w.windowTitle())"
```

## Windows 打包

```powershell
.\build.ps1
```

输出为 `dist\HelpPack.exe`。脚本使用项目内 PyInstaller 和 `helppack.spec`，生成无控制台的单文件应用。建议在计划发布的 Windows 版本上再次进行人工界面与安全软件兼容测试；未签名 EXE 可能触发 SmartScreen 提示。

## ZIP 格式

ZIP 包含：

- `report.md`
- `attachments/` 下用户确认保留的截图
- `manifest.json`，记录应用版本、生成时间、附件名称，以及 ZIP 内报告/附件的 SHA-256

manifest 不保存截图的原始绝对路径。默认文件名为 `HelpPack_yyyyMMdd_HHmmss.zip`。

## 当前已知限制

- 截图不进行 OCR 或图像内容脱敏。
- 脱敏为规则匹配，可能漏掉非常见的账号标识或密钥格式，也可能对文本产生误判。
- 显卡信息依赖 Windows CIM；被策略禁用或查询超时时显示“无法读取”。
- 默认网关是否响应 ping 不等同于互联网一定可用；部分网关会禁用 ICMP。
- DNS 检测只验证一次指定域名解析，不代表所有 DNS 场景正常。
- 第一版不导出完整事件日志、不解析崩溃转储正文，也不遍历全部驱动详情；任何结果都不会自动断言故障原因。
- 诊断模块只读取最近事件摘要和转储文件元数据，不解析转储正文；部分事件日志、计划任务、PnP 或磁盘健康查询在普通权限下会显示“权限不足”。
- Windows 标准接口无法覆盖所有硬件温度、电池容量或 SMART 数据；缺失时会明确显示“不支持”或“数据不可用”。
- 应用与生成的 EXE 尚未进行代码签名。

## 许可证

项目代码见 [LICENSE](LICENSE)。第三方组件及许可证概述见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 贡献

欢迎通过 Issue 报告可复现的问题，或提交范围明确的 Pull Request。涉及新诊断或修复能力时，请同时说明所需权限、可能副作用、失败行为和回滚方式，并补充对应测试；不要在 Issue、日志或附件中上传真实密钥、完整用户路径或其他私人数据。
