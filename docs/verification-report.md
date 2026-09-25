# HelpPack 发布前功能验证报告

- 验证日期：2026-09-25
- 应用版本：0.2.0
- 当前环境：Windows 11（构建 10.0.26200）、Python 3.12.14、PySide6 6.8.3
- 验证原则：真实本机只运行 L0；文件写入仅限项目/临时目录；L1/L2 只使用 Mock、拒绝路径、命令预览、备份与回滚测试。
- 隐私说明：本报告不记录真实用户名、IP、MAC、Wi-Fi 名称、设备序列号或原始事件内容。

## 门禁结论

**允许发布当前 0.2.0 版本。** 核心门禁全部通过；受当前权限、硬件或厂商接口限制的非核心能力已明确标记，没有伪装成真实验证。未执行 GitHub 创建或推送。

| 功能名称 | 分类 | 安全等级 | 当前验证状态 | 验证方式 | 实际结果 | 权限/环境限制 | 已知风险 | 允许发布 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| 最终 EXE 启动与主窗口 | 基础应用 | L0 | 真实验证通过 | 启动打包 EXE，观察标题和响应 | 窗口标题正确、响应正常 | 无 | 未签名 EXE 可能触发 SmartScreen | 是 | 最终生命周期检查 |
| 正常关闭与后台进程 | 基础应用 | L0 | 真实验证通过 | 测试环境变量触发应用自身退出 | 退出后 HelpPack 进程数为 0 | 无 | 强制结束不在本项范围 | 是 | `HELPPACK_SMOKE_EXIT_MS` 检查 |
| 窗口缩放、页面切换、滚动 | 基础应用 | L0 | 自动化测试通过 | Qt 事件与点击测试，1200×800 渲染 | 7 个主页面、4 个滚动区、主要入口切换通过 | 未完成真实桌面鼠标点击 | DPI/多屏仍需更多机器验证 | 是，注明限制 | `verify_ui_runtime.py`、`test_ui_workflow.py` |
| 简体中文视觉渲染 | 基础应用 | L0 | 自动化测试通过 | 当前电脑离屏截图并人工查看 | Microsoft YaHei 渲染清晰，无方框或明显截断 | 使用本机已安装字体 | 极简/精简系统可能缺少候选字体 | 是 | `ui_home.png`、`ui_diagnostic.png` |
| 后台检查响应 | 基础应用 | L0 | 自动化测试通过 | 慢检查运行于 QThread，同时统计主事件循环 | 约 0.4 秒内收到 16 次事件循环 tick | 非真实低配机器压力测试 | 极端系统负载下可能变慢 | 是 | `verify_ui_runtime.py` |
| 取消扫描 | 基础应用 | L0 | 自动化测试通过 | 扫描中设置线程安全取消事件 | 当前项结束后停止后续项目并标记取消 | 外部系统调用只能在超时或返回后取消 | 不强制杀死系统命令 | 是 | `test_user_cancel_stops_following_checks` |
| 单检查器失败隔离 | 基础应用 | L0 | 自动化测试通过 | 注入崩溃检查器 | 后续检查继续，失败项显示未知 | 无 | 非预期解释器级崩溃不在范围 | 是 | `test_engine_preserves_all_distinct_outcomes_and_continues_after_crash` |
| 普通用户错误信息 | 基础应用 | L0 | 自动化测试通过 | 空表单触发验证 | 显示“请填写问题标题和发生了什么” | 未做全量可用性用户研究 | 文案理解因用户而异 | 是 | `verify_ui_runtime.py` |
| 问题类型与描述填写 | 求助包 | L0 | 自动化测试通过 | Qt 表单流程测试 | 可填写标题、描述和已尝试操作 | 无 | 无 | 是 | `test_main_help_package_flow_switches_pages_and_edits_preview` |
| 截图添加、移除、格式与数量 | 求助包 | L0 | 自动化测试通过 | 临时目录虚构文件 | 合法图片可添加/移除；GIF 和第 6 张被拒绝 | 未使用私人截图 | 仅扩展名校验，不验证图片解码完整性 | 是 | `test_attachments.py`、UI 流程测试 |
| 容错系统信息收集 | 求助包 | L0 | 真实验证通过 | 当前电脑真实采集并注入单项失败 | Windows/CPU/GPU/内存/磁盘/网络返回；单项失败不中断 | 个别 CIM 数据可能无权读取 | 采集快照不证明因果关系 | 是 | `verify_artifacts.py`、`test_collector.py` |
| 报告预览、编辑与取消字段 | 求助包 | L0 | 自动化测试通过 | Qt 页面与报告测试 | 可编辑正文；取消 CPU 后不再出现 CPU 值 | 未进行真实桌面点击 | 更新选择会重新生成预览 | 是 | `test_ui_workflow.py`、`test_report.py` |
| Markdown 导出 | 求助包 | L0 | 真实验证通过 | 生成并重新读取文件 | UTF-8 内容与内存报告一致 | 仅项目验证目录 | 磁盘写满会失败并提示 | 是 | `verified_report.md`、`test_exporter.py` |
| ZIP、附件、manifest | 求助包 | L0 | 真实验证通过 | 使用纯色虚构 PNG 生成并解压 | 含 `report.md`、`manifest.json` 和选中附件 | 测试产物位于被忽略的 `dist/` | 无 | 是 | `verify_artifacts.py` |
| ZIP 文件名 | 求助包 | L0 | 真实验证通过 | 正则核对真实产物名 | 符合 `HelpPack_yyyyMMdd_HHmmss.zip` | 无 | 同秒多次导出可能覆盖，系统保存对话框会提示 | 是 | `verify_artifacts.py` |
| SHA-256 与绝对路径 | 求助包 | L0 | 真实验证通过 | 逐项复算 ZIP 内报告/附件 | 2 个 payload 哈希一致；manifest 无绝对路径 | manifest 自身不做自引用哈希 | 无 | 是 | `verify_artifacts.py`、`test_exporter.py` |
| 用户名、目录、IPv4/IPv6、MAC、邮箱 | 隐私 | L0 | 自动化测试通过 | 全部使用虚构数据 | 原文不进入报告，使用一致占位符 | 规则脱敏无法覆盖所有私有标识 | 可能漏掉非常见格式 | 是 | `test_redaction.py` |
| Bearer/GitHub/API Key/password/token/secret | 隐私 | L0 | 自动化测试通过 | 混合大小写、引号、嵌套虚构数据 | 原始虚构密钥不进入报告、manifest 或文件名 | 不识别所有厂商私有格式 | 规则存在漏报/误报可能 | 是 | `test_mixed_case_nested_bearer_github_and_api_keys`、`verify_artifacts.py` |
| 普通版本号防误删 | 隐私 | L0 | 真实验证通过 | 报告隐私扫描使用 `ipaddress` 严格确认 | 类似安全情报版本号不会误判为 IPv4 | 仍可能有其他文本误判 | 低 | 是 | `verify_diagnostics.py` |
| 诊断历史脱敏与重启读取 | 隐私/历史 | L0 | 自动化测试通过 | 新建第二个 Store 实例读取临时目录文件 | JSON 结构有效，敏感值均替换 | 当前电脑真实历史 UI 未跨系统重启验证 | 本地历史仍应按敏感文件保护 | 是 | `test_diagnostic_history.py` |
| CPU/内存/分页/磁盘与网络采样 | 系统卡顿 | L0 | 真实验证通过 | 当前电脑 2 秒采样 | 返回合理数值和采样时长 | 短样本不能证明根因 | 瞬时尖峰可能误导 | 是 | `performance.resources` |
| 高占用进程 | 系统卡顿 | L0 | 真实验证通过 | 两次进程 CPU 采样 | 返回前 8 项；已排除 Idle 进程 | 个别受保护进程不可读 | 多核进程 CPU 可超过 100% | 是 | `performance.resources` |
| 运行时间 | 系统卡顿 | L0 | 真实验证通过 | psutil boot time | 返回小时数 | 睡眠/快速启动影响理解 | 不代表稳定性 | 是 | `performance.resources` |
| 分区与临时目录估算 | 系统卡顿 | L0 | 真实验证通过 | 当前分区和有界文件遍历 | 系统盘低空间被正确提醒 | 跳过拒绝访问项，最多 20000 文件 | 估算非精确值 | 是 | `performance.storage` |
| 注册表/文件夹启动项与自动服务 | 系统卡顿 | L0 | 真实验证通过 | 当前电脑只读枚举 | 返回系统启动项、文件夹和第三方路径服务 | 不对厂商作绝对判断 | 条目存在不等于有害 | 是 | `startup.entries` |
| 登录/开机计划任务 | 系统卡顿 | L0 | 权限不足 | PowerShell 对象 JSON 查询 | 当前普通权限拒绝访问 | 需要更高权限或策略允许 | 未取得数据 | 是，注明限制 | `startup.scheduled_tasks` |
| 浏览器版本、进程、锁标记 | 软件/浏览器 | L0 | 真实验证通过 | 卸载注册表、psutil、已知锁文件元数据 | 检查器正常返回 | 非标准安装可能不在卸载注册表 | 锁标记不能证明配置损坏 | 是 | `software.browser` |
| 应用事件与 WER 元数据 | 软件/浏览器 | L0 | 真实验证通过 | 最近 7 天事件和 WER 文件元数据 | 找到相关证据并脱敏 | 不读取转储正文 | 单条事件/模块不等于根因 | 是 | `software.crash_events` |
| 崩溃异常代码/模块结构化能力 | 软件/浏览器 | L0 | 部分可用 | 事件对象 JSON + 消息脱敏 | 时间、事件 ID、Provider 和可得消息可读 | 异常字段随事件源变化 | 不能保证每种应用都有模块/代码 | 是，注明限制 | `software.crash_events`、能力矩阵 |
| 浏览器缓存处理 | 软件/浏览器 | L1/L2 | 尚未验证 | 第一版未实现真实缓存修复 | 只提供设置页建议 | 厂商目录变化大 | 误删会影响会话 | 是，不宣传自动修复 | 能力矩阵 C |
| 适配器/IP、DNS、HTTPS | 网络 | L0 | 真实验证通过 | psutil、socket、Python TLS | 接口存在；DNS 和 HTTPS 本次成功；地址已脱敏 | 单目标测试非全网结论 | 代理/CDN 可影响结果 | 是 | `network.connectivity` |
| DHCP、网关、DNS 服务器、网关连通 | 网络 | L0 | 权限不足 | Get-NetIPConfiguration JSON | 当前普通权限拒绝访问 | 需要策略允许/更高权限 | 未取得结构化数据 | 是，注明限制 | `network.configuration` |
| 用户代理、PAC、WinHTTP、Hosts | 网络 | L0 | 真实验证通过 | 注册表、WinHTTP API、Hosts 只读 | 检查器返回；Hosts 自定义项仅提醒 | 自定义配置可能合法 | 不判定恶意 | 是 | `network.proxy_hosts` |
| Wi-Fi 适配器状态 | 网络 | L0 | 部分可用 | psutil 接口 + NetIPConfiguration 尝试 | 接口状态可得；结构化详情权限不足 | 不读取 SSID/密码 | 无法验证信号强度 | 是，注明限制 | `network.connectivity`、`network.configuration` |
| 断网、无网关、超时处理 | 网络 | L0 | 自动化测试通过 | 模拟失败、超时和空结果 | 状态区分正常/未知/不支持/权限不足 | 未真实断开当前网络 | Mock 与厂商栈可能不同 | 是 | `test_diagnostic_runner.py`、引擎测试 |
| 音频/蓝牙/打印服务 | 设备 | L0 | 真实验证通过 | Windows 服务 API | 四项服务状态可读 | 服务状态不等于设备可用 | 按需服务可能停止 | 是 | `devices.services` |
| PnP 设备与错误码 | 设备 | L0 | 权限不足 | Get-PnpDevice JSON | 当前普通权限拒绝访问 | 需要更高权限/模块可用 | 未验证设备错误码 | 是，注明限制 | `devices.pnp` |
| 打印机、默认打印机、队列 | 设备 | L0 | 权限不足 | Get-Printer/Get-PrintJob + 用户默认打印机注册表 | 当前 PowerShell 查询权限不足 | 可能无打印机或模块受限 | 不能标为真实通过 | 是，注明限制 | `devices.printers` |
| 驱动提供商、版本、日期 | 设备 | L0 | 权限不足 | PnP/驱动接口尝试 | 当前未获得结构化详情 | 厂商和权限限制 | 旧日期不等于故障 | 是，注明限制 | `devices.pnp`、能力矩阵 |
| Update 服务与等待重启 | Windows Update | L0 | 真实验证通过 | 服务 API 和已知注册表标记 | 服务可读，检测到等待重启提醒 | 厂商安装器可能有其他标记 | 不自动重启 | 是 | `windows_update.basic` |
| 最近更新、失败代码、日志能力 | Windows Update | L0 | 真实验证通过 | Update 事件 JSON + 日志文件可读性 | 返回近期事件和日志能力 | 不导出完整日志 | 事件存在不表示仍失败 | 是 | `windows_update.history` |
| SFC verifyonly / DISM ScanHealth | Windows Update | L0 | 部分可用 | 只检查命令存在、构造和权限说明 | 命令存在，未实际运行 | 耗时且可能需管理员 | 未验证真实扫描结果 | 是，明确不声称运行 | `windows_update.history` |
| SFC/DISM 修复 | Windows Update | L2 | 尚未验证 | 第一版不执行 | 仅提供人工说明 | 管理员、耗时、可能联网 | 不宜发布前自动测试 | 是，不宣传自动执行 | 能力矩阵 B/D |
| BugCheck/Kernel-Power/WHEA | 稳定性 | L0 | 真实验证通过 | 最近 30 天系统事件 JSON | 返回相关事件摘要 | 事件消息因系统而异 | Kernel-Power 不等于电源损坏 | 是 | `reliability.events` |
| 小型转储存在性 | 稳定性 | L0 | 真实验证通过 | Minidump 元数据 | 当前显示未发现转储 | 不解析转储正文 | 无转储不代表无蓝屏 | 是 | `reliability.events` |
| 停止代码/转储驱动模块 | 稳定性 | L0 | 部分可用 | 事件中可得字段；不解析 DMP | 当前无转储，无法真实验证 | 需 WinDbg/符号 | 模块名不能认定根因 | 是，注明限制 | 能力矩阵 C/D |
| 电池存在与当前状态 | 硬件健康 | L0 | 真实验证通过 | psutil 电池接口 | 当前检测到电池状态 | 固件可能不准确 | 仅当前快照 | 是 | `health.battery_disk` |
| 设计/满充容量、循环次数 | 硬件健康 | L0 | 部分可用 | 明确检查接口能力 | 当前标准接口不提供 | 依赖 ACPI/厂商固件 | 不伪造健康百分比 | 是，注明限制 | `health.battery_disk` |
| 磁盘型号、介质、健康/SMART | 硬件健康 | L0 | 权限不足 | Get-PhysicalDisk JSON | 当前普通权限拒绝访问 | USB/RAID/权限限制 | SMART 正常也非绝对安全 | 是，注明限制 | `health.battery_disk` |
| 温度 | 硬件健康 | L0 | 当前环境不支持 | 标准接口能力判断 | 明确显示当前硬件或接口不支持 | 需厂商专用接口 | 不显示虚构温度 | 是 | `health.battery_disk` |
| 禁用单个 HKCU 启动项 | 修复安全 | L1 | 自动化测试通过 | FakeRegistry + 临时备份 | 拒绝不执行；确认后备份、复查、回滚 | 当前电脑未真实修改 | 用户误选会改变自启动 | 是 | `test_repairs.py` |
| 重置当前用户代理/PAC | 修复安全 | L2 | 自动化测试通过 | 白名单目标、预览和备份模型 | 未确认绝不执行；对象和风险可显示 | 当前电脑未真实修改 | 单位网络可能中断 | 是 | `test_repairs.py`、UI 确认代码 |
| 管理员权限判断 | 修复安全 | L1/L2 | 自动化测试通过 | 模拟普通用户/管理员要求 | 需管理员动作在无权限时阻止 | 未真实提升权限 | UAC 流程未端到端验证 | 是，注明限制 | `test_admin_required_action_is_blocked_without_admin` |
| 参数注入防护 | 命令安全 | L0-L2 | 自动化测试通过 | 控制字符和 shell 元字符测试 | 参数数组、`shell=False`；换行注入被拒绝 | 固定内部 PowerShell 脚本仍需代码审查 | 无用户文本进入脚本 | 是 | `test_diagnostic_runner.py` |
| Windows 10/11 路径 | 兼容性 | L0 | 自动化测试通过 | 平台分支模拟 | 10/11 支持，其他版本明确不支持 | 真实机仅 Windows 11 | Windows 10 未真机运行 | 是，注明限制 | `test_windows_10_and_11_compatibility_paths` |
| 中/英文输出、空输出、格式变化 | 兼容性 | L0 | 自动化测试通过 | JSON/本地化文本/空值模拟 | 不猜测本地化人类文本；格式异常标未知 | 不能覆盖所有第三方命令版本 | 输出变化会降级为未知 | 是 | `test_diagnostic_runner.py` |
| 待发布内容敏感扫描 | 发布 | L0 | 真实验证通过 | 扫描全部计划发布文本文件 | 0 个阻塞；仅识别到明确虚构测试 Token | 未扫描 `dist/`，因其被排除发布 | 新增文件后必须重跑 | 是 | `scan_release_content.py` |
| 依赖与静态检查 | 发布 | L0 | 真实验证通过 | pip check、Ruff、compileall | 无依赖破损；Ruff 全通过 | 无类型检查器 | 静态检查不能替代运行测试 | 是 | 命令输出 |
| 自动化测试全集 | 发布 | L0-L2 | 真实验证通过 | pytest | 37 项全部通过 | 修复操作使用 Mock | 单元测试不等于所有硬件实测 | 是 | `pytest` |

## 发现问题与修复闭环

1. 压缩 IPv6 未脱敏：测试失败后修正候选匹配器，完整测试通过。
2. PySide6 6.11.2 冻结后 QtCore DLL 失败：捕获控制台错误，固定为 PySide6 6.8.3，最终 EXE 实际启动通过。
3. `TimeoutError` 被归类为“不支持”：调整异常捕获顺序，状态测试通过。
4. 诊断历史对整段 JSON 脱敏造成引号损坏：改为逐字段脱敏后序列化，重启读取测试通过。
5. 离屏截图中文显示为方框：从本机字体目录显式加载 Microsoft YaHei，重新截图确认清晰。
6. 隐私扫描把 Defender 版本号误判为 IPv4：改用 `ipaddress.IPv4Address` 验证候选，不降低真实 IP 检查强度。
7. Windows 计划任务名中以下划线嵌入用户名时漏脱敏：改为对已知本机用户名执行不依赖单词边界的大小写无关替换，并新增回归测试。

## 发布门禁核对

- [x] 核心界面能够启动
- [x] 求助包能够生成、解压并读取
- [x] 隐私脱敏测试通过
- [x] L0 扫描前后关键配置快照一致
- [x] L1/L2 未确认绝不执行
- [x] 参数注入测试通过
- [x] 日志、报告、manifest 和文件名敏感检查通过
- [x] 自动化测试与静态检查通过
- [x] 未发现会造成数据丢失或静默系统误改的已知缺陷
- [x] README 与第一版实际能力一致
- [x] 本验证报告已生成
- [x] 计划上传文本内容敏感扫描通过

非核心限制不会阻塞发布，但必须保留在 README 和本报告中。任何后续代码或文档变化都会使本门禁结果失效，需要重新执行验证。
