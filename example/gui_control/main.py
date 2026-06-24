#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LinkerHand GUI 入口。"""
# ---- 强制诊断加载路径，在任何本地导入之前最先执行 ----
import sys
import os
print("================== PYTHON PATH DEBUG ==================", flush=True)
print("DEBUG: main.py argv:", sys.argv, flush=True)
print("DEBUG: main.py CWD:", os.getcwd(), flush=True)
print("DEBUG: main.py file:", os.path.abspath(__file__), flush=True)
print("DEBUG: main.py sys.path:", sys.path, flush=True)

# 保证 100% 优先导入当前目录下的本地 lhgui 包，避免虚拟环境 site-packages 中的旧版本干扰
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
TARGET_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "../.."))
if TARGET_DIR not in sys.path:
    sys.path.insert(0, TARGET_DIR)

try:
    import lhgui
    import lhgui.styles.theme_manager as tm
    print("DEBUG: lhgui package location:", os.path.abspath(lhgui.__file__), flush=True)
    print("DEBUG: theme_manager location:", os.path.abspath(tm.__file__), flush=True)
    _qss = os.path.join(os.path.dirname(tm.__file__), "theme.qss")
    print("DEBUG: theme.qss target path:", os.path.abspath(_qss), flush=True)
    if os.path.exists(_qss):
        print("DEBUG: theme.qss file size on disk:", os.path.getsize(_qss), flush=True)
    else:
        print("DEBUG: theme.qss FILE NOT FOUND!", flush=True)
except Exception as _e:
    print("DEBUG: Path diagnosis failed:", _e, flush=True)
print("=======================================================", flush=True)

# 动态寻找 PyQt5 的 Qt 平台插件路径，解决 QPA 初始化失败 of Windows 环境问题
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
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        app = QApplication(sys.argv)
        app.setApplicationName("LinkerHand 控制台 - 重构测试版 [7C2D28B]")

        theme = ThemeManager(app)
        theme.apply(theme.saved_theme)

        window = MainWindow()
        theme.refresh_widgets(window)
        window.setWindowTitle("LinkerHand 控制台 - 重构测试版 [7C2D28B]")
        window.show()
        exit_code = app.exec_()
        sys.exit(exit_code)
    except Exception as e:
        # 崩溃时写入日志方便排查
        import traceback
        log_path = os.path.join(CURRENT_DIR, "test_out.log")
        with open(log_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise


if __name__ == "__main__":
    main()
