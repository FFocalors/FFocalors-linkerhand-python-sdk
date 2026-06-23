#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LinkerHand GUI 入口。"""
import os
import sys

# 保证 LinkerHand 包可被导入（与原 gui_control.py 一致）
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "../.."))
if TARGET_DIR not in sys.path:
    sys.path.append(TARGET_DIR)

# 动态寻找 PyQt5 的 Qt 平台插件路径，解决 QPA 初始化失败的 Windows 环境问题
try:
    import PyQt5
    pyqt_dir = os.path.dirname(PyQt5.__file__)
    plugins_dir = os.path.join(pyqt_dir, "Qt5", "plugins")
    if os.path.exists(plugins_dir):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugins_dir
except Exception:
    pass

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from lhgui.styles.theme_manager import ThemeManager
from main_window import MainWindow


def main():
    # 重定向输出到 log 文件，方便分析和调试
    log_path = os.path.join(CURRENT_DIR, "test_out.log")
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file

    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        app = QApplication(sys.argv)
        app.setApplicationName("LinkerHand 控制台")

        theme = ThemeManager(app)
        theme.apply(ThemeManager.THEME)

        window = MainWindow()
        window.show()
        exit_code = app.exec_()
        sys.exit(exit_code)
    finally:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        log_file.close()


if __name__ == "__main__":
    main()
