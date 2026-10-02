# 求助包（HelpPack）

## 本地诊断与修复计划更新

结果页新增“查看修复计划”：只根据本次证据生成候选，逐项选择后确认执行；高影响动作另行确认。支持安全服务启动、DNS 缓存刷新、白名单缓存隔离、所选启动项，以及本应用修改的冲突安全恢复。未能安全定位的问题仅提供说明和人工设置入口，不固定运行一组优化命令。

详见 [使用方法、现状审计及动作回滚表](docs/repair-plan-verification.md) 和 [本轮实际验证结果](docs/repair-plan-results.md)。验收后用户已另行授权上传源码，见 [上传范围与检查记录](docs/github-upload.md)；本机构建输出位于 `dist\repair-plan\HelpPack.exe`，不随源码上传。执行 `python -m helppack --plan-self-check dist\plan-native` 可运行只读原生界面验收，预览计划后取消，报告使用虚构数据。

已发布版本为 **0.2.2**。本地现已增加功能完整性扩展，尚未发布或替换已有 Release。系统修改类修复仍未完成可还原 Windows 环境实测，不能把模拟测试和正常启动当作真实修复验收。请勿在重要电脑上试用未验收的系统修改。历史发布记录见 [0.2.2 验证记录](docs/verification-v0.2.2.md)，本轮结果见 [功能完整性与验证记录](docs/feature-completeness.md)。

HelpPack 是一个面向普通 Windows 用户的本地故障信息整理工具。用户通过向导描述问题，应用按项采集必要的系统状态、自动脱敏，并导出可发给朋友、客服或 AI 的 Markdown 报告或 ZIP 求助包。

应用也提供保守的“本机诊断”：按问题类型执行 L0 只读检查，逐项展示证据、状态、严重程度、可信度和建议，再由用户决定是否把结果加入求助包。完整能力边界见 [诊断能力矩阵](docs/diagnostic-capability-matrix.md)。

## 新增功能的使用入口

首页点击 **“症状向导与专项排查”**，进入八个真实功能页。结果区域可滚动、选择复制，并可加入原有求助报告。

| 页面 | 可执行能力 | 边界 |
|---|---|---|
| 症状 | 自然语言关键词/七种预设，在本机选择相关只读检查并展示证据与下一步 | 本地规则，不是远程 AI；目标网站/EXE 需在专项页主动指定 |
| 网络 | 适配器→网关→系统 DNS/指定 DNS→代理→直连/静态代理 HTTPS→目标服务 | 只允许标准 HTTPS 443，不跟随重定向；不模拟 PAC/WPAD，不改变系统 DNS |
| 软件 | 选择运行中的程序或本机 EXE，四种场景；版本、路径、签名、进程、相关事件、运行库注册和可读拦截记录 | 不执行该 EXE；签名接口失败不影响版本检查；依赖存在不代表健康 |
| 空间 | 主动选择目录，分区空间及占用排行；扫描取消、跳过链接/无权限；单项缓存预览、确认移出、恢复 | 仅名称推测缓存；应用/用户文件不自动移出；同盘隔离不释放空间、不永久删除 |
| 外设 | 音频默认输出/静音/音量/服务、经典蓝牙配对与连接标志、打印机默认/离线/暂停/队列 | 试听主动触发且不调整系统音量；测试打印需单独确认；不采集队列文档名或所有者 |
| 历史 | 本地脱敏记录、已解决/未解决/稍后处理标记、同目标结构化记录对比 | 修复确认执行记录及复检变化本地保存；指标改善不证明因果或解决 |
| 时间线 | 最近 30 天可读安装/崩溃/系统更新/异常重启/驱动配置事件，按时间排序 | 日志有界且可能缺失；不是完整安装审计，时间相关性不等于因果 |
| 监测 | 主动开启，每两秒采 CPU/内存/磁盘/网络计数，最近十分钟、最长两小时；标记故障前 60 秒/后 30 秒 | 提前停止保留不完整片段；退出停止；不采私人内容，未做两小时持续实测 |

问题填写页新增“仍未解决的问题”和用户处理状态；截图列表可点击“裁剪 / 遮挡选中截图”，导出处理后的 PNG 副本而不改原图。编辑副本去除原图文字元数据，最多 2000 万像素，可撤销最近五次操作；不进行 OCR。预览页支持复制**当前编辑后正文**的简洁摘要，不重新加入已删除的源内容。

## 产品与隐私边界

- 信息在本机处理，不需要服务器、账号或登录。
- 基础求助包仅采集必要系统概况；专项页在用户主动触发后读取所选程序元数据/相关事件、所选目录文件大小/名称、外设或资源计数。不扫描未选择目录的完整文件列表，也不读取文件正文。
- 不自动读取浏览历史、文档内容、密码/密钥、剪贴板、Wi-Fi 密码或完整文件列表。
- 报告自动尝试隐藏用户名、用户目录、IP、MAC、邮箱和常见密钥字段。
- 截图不做 OCR 脱敏；可手动裁剪/不透明遮挡，用户必须在导出前自行检查处理后的副本。
- 自动脱敏基于规则，不能保证识别所有隐私或密钥格式。预览页允许删除系统字段并直接编辑报告。
- 基础 DNS 检查解析 `www.microsoft.com`，网关检查发送一次 ping。网络专项会向主动输入的目标发送 HTTPS HEAD 请求，向用户指定 DNS 发送该域名；不收集认证信息，不自动设置第三方 DNS。Windows Update 联网范围见下文。
- 诊断历史默认保存在本机应用数据目录的 `HelpPack/history`，自动规则脱敏但不能保证识别所有私人内容。专项结果不会自动上传；只有主动加入并导出才进入求助包。截图编辑临时副本随窗口正常关闭清理。缓存恢复清单在所选目录的 `.helppack-quarantine`，不加入求助包；重新扫描该目录可读取恢复记录。
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

本轮自动化、当前电脑只读检查及报告/ZIP 内容验证：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe .\scripts\verify_feature_completeness.py --live
```

`--live` 只扫描项目源码目录，并使用本机已配置的 DNS 对照微软网站；不修复、不试听、不打印。产物位于被忽略的 `dist/validation/completeness_*`，不要公开这些本机结果。

打开仅含虚构长文字的原生窗口并保存应用内渲染截图：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_feature_completeness.py --desktop
```

独立本地验收构建（不覆盖已发布 0.2.2）：

```powershell
.\build.ps1 -OutputDirectory dist\completeness-preview -WorkDirectory build\completeness-preview
```

当前限制：网络指定 DNS 使用普通 DNS A/AAAA 查询，不验证 DNSSEC/DoH；PAC 与浏览器完整路径未模拟，DNS 差异可来自 CDN。软件不解析全部 PE 依赖或第三方安全软件日志，本机签名模块不可加载时显示无法验证。经典蓝牙接口不覆盖所有 BLE 设备；声音试听和实体打印尚未实测。目录扫描限 20 万项/120 秒，跳过链接和不可读项目，不支持网络共享。缓存分类不是可安全删除的证明，移出前逐项确认；本机不进行真实系统修复验证。原生窗口渲染已观察，但外部桌面点击工具窗口绑定失败，未完成外部鼠标验收。更完整的逐项结果见功能验证记录。

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
- 基础 DNS 字段和本轮两域名分层检查均有覆盖限制，不代表所有 DNS、PAC 或浏览器场景正常。
- 第一版不导出完整事件日志、不解析崩溃转储正文，也不遍历全部驱动详情；任何结果都不会自动断言故障原因。
- 诊断模块只读取最近事件摘要和转储文件元数据，不解析转储正文；部分事件日志、计划任务、PnP 或磁盘健康查询在普通权限下会显示“权限不足”。
- Windows 标准接口无法覆盖所有硬件温度、电池容量或 SMART 数据；缺失时会明确显示“不支持”或“数据不可用”。
- 应用与生成的 EXE 尚未进行代码签名。

## 许可证

项目代码见 [LICENSE](LICENSE)。第三方组件及许可证概述见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 贡献

欢迎通过 Issue 报告可复现的问题，或提交范围明确的 Pull Request。涉及新诊断或修复能力时，请同时说明所需权限、可能副作用、失败行为和回滚方式，并补充对应测试；不要在 Issue、日志或附件中上传真实密钥、完整用户路径或其他私人数据。
