# 求助包（HelpPack）

当前版本为 **0.2.2**。用户已确认按当前验收范围上传；这不代表所有新增修复已通过真实验收。新增修复尚未完成可还原 Windows 环境实测，模拟测试和正常启动不能代替真实修复验收。请勿在重要电脑上试用未验收的系统修改。详细状态见 [0.2.2 验证记录](docs/verification-v0.2.2.md)。

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
- 商店连接检查读取 Internet 选项的 TLS 配置、用户/电脑协议策略和 Schannel 客户端显式禁用项。针对 0x80131500 提供 TLS 1.2/1.3 检查步骤；Windows 10 不强行启用不受支持的 TLS 1.3。缺少注册表值按系统默认处理，不判断为关闭。此项不自动修改安全设置，尚未进行真实商店连接验证。
- 本机诊断默认只读。新增 DNS 缓存清理、指定 DHCP 接口续租/DNS 恢复、Store 缓存清理/已注册包的当前用户注册修复、白名单服务启动或重启，以及 Windows Update 单项驱动安装流程。未注册的 Store 只给人工检查步骤，不推断整机已卸载；数据重置不作为诊断推荐动作。
- 所有修复逐项确认；高风险修复二次确认，商店数据重置要求输入“重置”。请求具有过期时间、内容校验和单次使用限制。管理员动作请求 UAC，当前用户 Store 操作不通过管理员辅助进程执行。始终由用户自行重启。
- 新增操作尚未完成 Windows 虚拟机实测；不要把开发预览用于重要电脑的系统修复。当前全局网络栈修复、INF 安装及系统组件修复仍受安全条件限制，不属于已完成验收的能力。
- “驱动安装与更新”是独立的联网检查，综合检查不运行 Windows Update 驱动搜索。搜索会向 Windows Update 服务请求适用驱动；只有用户再次确认后才可能下载安装。
- Windows Update 驱动安装要求唯一硬件匹配、可比较且更高的版本、已接受的系统许可和可导出的原签名 OEM 驱动；条件不足会拒绝安装。备份只支持人工尽力恢复，不保证回滚。
- 厂商来源目前提供 Dell、Lenovo、HP、Intel、NVIDIA、AMD 官方 HTTPS 页面入口；尚未实现厂商安装包自动下载与签名验证，不会静默运行下载的 EXE。
- 操作记录和恢复快照只保存在本机应用数据目录。代理及网络快照由 Windows DPAPI 加密；导出仅包含脱敏操作摘要。使用另一管理员账户提权不受支持，所有者校验会拒绝该请求。

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

保留现有 EXE 并创建独立版本构建：

```powershell
.\build.ps1 -OutputDirectory dist\v0.2.2 -WorkDirectory build\v0.2.2
```

输出为 `dist\v0.2.2\HelpPack.exe`，该目录不会提交。本机构建不等同于 GitHub 正式 Release。

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
