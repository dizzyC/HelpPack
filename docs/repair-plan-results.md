# 本轮最终验证结果（2026-10-02）

## 实际执行

| 检查 | 中文版 | 英文版 |
|---|---|---|
| 全部 pytest（独立测试目录，不共享缓存） | 151 passed | 171 passed |
| Ruff | All checks passed | All checks passed |
| 敏感内容审计 | 无阻断项；密钥样本仅限明确虚构测试 | 无阻断项；密钥样本仅限明确虚构测试 |
| 英文固定文案审计 | 共享双语资源 | 未审查中文产品文字为 0；兼容 ID/原始数据保留 |
| Windows 原生源码窗口 | 网络、六次资源采样、EXE 信息/崩溃日志只读流程完成 | 相同流程完成 |
| 最终单文件 EXE 原生验收 | 退出码 0，frozen=true，platform=windows | 退出码 0，frozen=true，platform=windows |
| EXE 默认首页启动（自动退出检查） | 退出码 0 | 退出码 0 |
| 计划窗口与窄窗口 | 有可见窗口，长内容可滚动，高影响动作默认未选，取消未执行 | 相同；已查看原生渲染截图 |
| 虚构报告 | Unicode Markdown/ZIP/manifest SHA-256 通过 | 相同；英文固定标题与 Unicode 用户输入保留 |
| 模拟修复 GUI 完整流程 | 后台线程 → 结果 → 本地历史 → 加入报告通过 | 相同 |

最终 EXE 验收清空 `PYTHONPATH`，`PATH` 仅含 Windows 根目录和 System32，不包含开发 Python 或 Windows PowerShell 路径；内置命令由原生系统目录接口定位。没有系统级安装或配置修改。

软件只读检查共七组结果：版本/路径、进程、事件、结构化崩溃字段和运行环境可读取；本机签名查询无法验证，如实保留未知。空事件集合不代表已模拟真实闪退，也不判定任何原因。

## 产物

- 中文版：`dist/repair-plan/HelpPack.exe`，56,903,158 bytes。
  SHA-256：`2ae9e6463aa8e6b8f4a992d3d663cf82985d07c70c31868da441714df249d825`
- 英文版：英文工作区 `dist/repair-plan/HelpPack-English.exe`，56,977,974 bytes。
  SHA-256：`6f9d92222812b4091b7b2e107ff009553adf95383713c1f0d252b7c7cf9eca58`

本工作区最终 EXE 验收证据：`dist/exe-plan-final/246d682c13774da6ae91876f58c3059d/results.json` 及同目录虚构报告/ZIP/界面渲染。英文工作区对应 `dist/exe-plan-final/c28131810e4e49519ed81dac74e0f6bf/`。这些本地文件由 `.gitignore` 排除。

## 未验证和限制

没有真实修改开发电脑的 DNS、代理、服务、启动项、打印队列或组件。修复/权限拒绝/超时用 Mock，缓存恢复用测试自建临时目录，DPAPI 用虚构字节。本轮未测试可还原虚拟机真实修复、实际 UAC 点击、外部鼠标完整交互、英文 Windows 实机或物理外设。

系统修改尚不能标为生产环境真实验收；等待系统写入完成期间不会强杀。签名查询、磁盘活动忙碌计数和部分日志可能不可读；PAC/WPAD、浏览器完整连接链路及精准时钟差异仍有限。缓存隔离不释放同盘空间，旧备份没有修改后快照时拒绝自动恢复。

动作、单独确认及恢复能力见 [修复计划验收矩阵](repair-plan-verification.md)。保留 `main` 与 `english` 的原 HEAD，不产生提交、推送或 Release。所有变更保留在本地工作区供后续审阅。
