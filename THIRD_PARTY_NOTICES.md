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

本轮没有新增 pip 依赖。PyInstaller 的 Qt Multimedia 钩子在本地构建中带入 FFmpeg 后端及 `avcodec-61`、`avformat-61`、`avutil-59`、`swresample-5` 动态库；这些不是 HelpPack MIT 许可证覆盖的代码。公开分发新 EXE 前仍需逐项核对实际构建配置、第三方完整许可证、源码提供及 LGPL 可替换/重链接义务。本轮构建仅为本地验收，未上传新 Release。Qt 对应版本的第三方归属参考 [Qt 6.8 Multimedia 许可证与归属](https://doc.qt.io/qt-6.8/qtmultimedia-index.html#licenses-and-attributions)。

官方许可证入口：

- Python: https://docs.python.org/3/license.html
- Qt for Python: https://doc.qt.io/qtforpython-6/licenses.html
- psutil: https://github.com/giampaolo/psutil/blob/master/LICENSE
- pytest: https://github.com/pytest-dev/pytest/blob/main/LICENSE
- PyInstaller: https://pyinstaller.org/en/stable/license.html
