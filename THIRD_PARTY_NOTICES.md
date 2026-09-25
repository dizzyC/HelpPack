# 第三方依赖与许可证

HelpPack 自身使用 MIT License。构建和运行涉及以下第三方组件；正式分发前应根据实际打包版本再次核对其完整许可证文本与义务。

| 组件 | 用途 | 许可证（概述） |
|---|---|---|
| Python 3.12 | 运行时 | Python Software Foundation License |
| PySide6 / Qt for Python | Windows 图形界面 | LGPLv3 / GPLv3 / 商业许可（依 Qt 官方条款） |
| psutil | 系统状态采集 | BSD 3-Clause |
| pytest | 自动化测试（仅开发） | MIT |
| PyInstaller | Windows 打包（仅开发） | GPLv2-or-later，带 Bootloader Exception |

项目没有联网加载字体、图片或前端资源。应用运行时的 DNS 检测会尝试解析 `www.microsoft.com`，默认网关检测会向本机默认网关发送一次 ping。

官方许可证入口：

- Python: https://docs.python.org/3/license.html
- Qt for Python: https://doc.qt.io/qtforpython-6/licenses.html
- psutil: https://github.com/giampaolo/psutil/blob/master/LICENSE
- pytest: https://github.com/pytest-dev/pytest/blob/main/LICENSE
- PyInstaller: https://pyinstaller.org/en/stable/license.html
