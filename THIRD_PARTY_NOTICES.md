# 第三方依赖与许可证

HelpPack 自身使用 MIT License。构建和运行涉及以下第三方组件；正式分发前应根据实际打包版本再次核对其完整许可证文本与义务。

| 组件 | 用途 | 许可证（概述） |
|---|---|---|
| Python 3.12 | 运行时 | Python Software Foundation License |
| PySide6 / Qt for Python | Windows 图形界面 | LGPLv3 / GPLv3 / 商业许可（依 Qt 官方条款） |
| Qt Multimedia / Qt Print Support | 音频输出枚举与主动试听、用户确认打印（PySide6 自带模块） | 依 Qt 对应模块条款；实际构建还包含 Qt 自动部署的媒体后端/FFmpeg 库 |
| psutil | 系统状态采集 | BSD 3-Clause |
| pytest | 自动化测试（仅开发） | MIT |
| PyInstaller | Windows 打包（仅开发） | GPLv2-or-later，带 Bootloader Exception |

项目没有联网加载字体、图片或前端资源。应用运行时的 DNS 检测会尝试解析 `www.microsoft.com`，默认网关检测会向本机默认网关发送一次 ping。

没有新增 pip 依赖。实际 FFmpeg 动态库版本为 7.1，运行时报告 LGPL 2.1-or-later，构建参数未启用 GPL、nonfree 或外部库；本分发选择 LGPLv3。这些组件不由 HelpPack MIT 许可证覆盖。

发布构建通过 `scripts/prepare_distribution.py` 收集对应版本的完整许可证和第三方归属说明（164 个文件），嵌入 EXE 的 `licenses/`，并生成 `HelpPack-Third-Party-Licenses.zip`。其中 `SOURCE-AND-REBUILD.md` 提供精确版本源码下载入口及替换库后重新打包说明；修改库重建流程尚未实际验证。正式 spec 排除未使用的 Qt Virtual Keyboard、Qt PDF 及对应插件。Qt 第三方归属参考 [Qt 6.8 Multimedia 许可证与归属](https://doc.qt.io/qt-6.8/qtmultimedia-index.html#licenses-and-attributions)。许可证清单不是法律意见或专利许可保证。

官方许可证入口：

- Python: https://docs.python.org/3/license.html
- Qt for Python: https://doc.qt.io/qtforpython-6/licenses.html
- psutil: https://github.com/giampaolo/psutil/blob/master/LICENSE
- pytest: https://github.com/pytest-dev/pytest/blob/main/LICENSE
- PyInstaller: https://pyinstaller.org/en/stable/license.html
