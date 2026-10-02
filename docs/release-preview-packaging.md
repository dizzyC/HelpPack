# 预览版分发验证（2026-10-02）

本次分发标签为 `v0.2.2-repair-preview.1`，EXE 内部版本仍为 0.2.2，不替换稳定版 v0.2.2。

- 中文版 151、英文版 171 项 pytest 回归测试通过。
- 两版新 EXE 在当前 Windows 11 上使用原生 Qt Windows 平台启动成功。
- 清空 PYTHONPATH、PATH 只保留 Windows 系统目录时，默认启动退出码和 `--plan-self-check` 退出码均为 0。
- 打包后只读网络、连续资源采样、软件诊断，以及修复计划预览并取消、Unicode Markdown/ZIP 导出检查通过。原生窗口显示、长文本和事件循环检查通过；未验证外部鼠标操作。
- 164 个许可证/归属材料嵌入 EXE，并提供独立许可证 ZIP；源码入口和库替换说明在其中的 SOURCE-AND-REBUILD.md。
- 未使用的 Qt Virtual Keyboard、Qt PDF 及对应插件排除；分发档案逐项验证嵌入材料 SHA-256。
- 系统修改、提权拒绝、回滚冲突等采用模拟测试；本机未执行任何 DNS、代理、服务或系统文件修复。尚无隔离虚拟机真实修复验证，也无英文 Windows 真实验证。
- EXE 未签名，可能触发 SmartScreen 提示。修改库后重建流程尚未验证。

构建脚本先运行 `scripts/prepare_distribution.py`。首次构建需要访问官方上游许可证材料；后续使用校验过的 `dist/distribution-licenses/` 缓存。缓存缺失或校验失败时不打包。构建使用 README 中的虚拟环境命令；不要将 dist、build 或真实诊断数据提交到 Git。
