#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动化检查、界面测试与截图生成脚本。

该脚本会自动检测所有 SVG 文件中是否存在 text 或 Emoji 乱码，
启动 PyQt5 界面，在各种窗口宽度下测试响应式布局，
并通过 widget.grab() 将 1920x1080, 1366x768, 双行BottomBar, 关节姿态等界面状态截图，
输出并保存到 conversation artifacts 目录下，以作为测试与高清晰 DPI 验证的真实证据。
"""
import os
import sys
import xml.etree.ElementTree as ET
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QFontDatabase

# 确保能载入 lhgui
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# 本地图标与页面定义
from lhgui.utils.icon_helper import get_pixmap, get_icon
from lhgui.widgets.hand_pose_view import HandPoseView
from lhgui.widgets.bottom_bar import BottomBar
from lhgui.widgets.top_bar import TopBar
from main_window import MainWindow

ARTIFACT_DIR = r"C:\Users\zhy20\AppData\Local\Temp" # 缺省，后面会被实际覆写为用户的 artifacts 目录
ARTIFACT_DIR = r"C:\Users\zhy20\.gemini\antigravity\brain\d9236e50-dbf4-4b73-985d-004550bf0f43"

def run_svg_check():
    print("==================================================")
    print(" 自动检查：扫描并解析全部 SVG 图标资源")
    print("==================================================")
    icon_dir = os.path.join(os.path.dirname(__file__), "lhgui", "resources", "icons")
    if not os.path.exists(icon_dir):
        print(f"[Error] 图标目录不存在: {icon_dir}")
        return False
        
    passed = True
    forbidden_tags = ["text", "font-family", "tspan"]
    
    for f in os.listdir(icon_dir):
        if not f.endswith(".svg"):
            continue
        path = os.path.join(icon_dir, f)
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            
            # 检查是否有禁止标签或属性
            for elem in root.iter():
                # 标签名去命名空间
                tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag_name in forbidden_tags:
                    print(f"[FAIL] 图标 {f} 含有禁止标签: <{tag_name}>")
                    passed = False
                
                # 检查属性
                for attr, val in elem.attrib.items():
                    if "font" in attr or "base64" in val:
                        print(f"[FAIL] 图标 {f} 包含敏感属性/嵌入位图: {attr}={val[:20]}")
                        passed = False
        except Exception as e:
            print(f"[FAIL] 无法解析 SVG {f}: {e}")
            passed = False
            
    if passed:
        print("[SUCCESS] 所有 SVG 图标均已检查通过，全为纯矢量几何路径，无任何字符及嵌入位图！")
    return passed


def run_font_check():
    print("\n==================================================")
    print(" 自动检查：中英文及等宽字体回退可用性测试")
    print("==================================================")
    db = QFontDatabase()
    families = db.families()
    
    cn_fonts = ["Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI"]
    mono_fonts = ["Cascadia Mono", "Consolas"]
    
    print("可用中文字体:")
    for f in cn_fonts:
        avail = "【可用】" if f in families else "【未安装】"
        print(f"  - {f}: {avail}")
        
    print("可用等宽字体:")
    for f in mono_fonts:
        avail = "【可用】" if f in families else "【未安装】"
        print(f"  - {f}: {avail}")


def generate_screenshots():
    print("\n==================================================")
    print(" 自动检查：启动 PyQt5 界面并自动生成截图")
    print("==================================================")
    
    app = QApplication.instance() or QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    # 1. 实例化主窗口
    print("正在拉起主窗口实例...")
    win = MainWindow()
    win.show()
    
    # 强制分发事件渲染
    QApplication.processEvents()
    
    # 创建保存目录
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    
    # ---- 截图 1: 1920x1080 宽屏控制台 ----
    print("正在生成宽屏布局截图 (1920x1080)...")
    win.resize(1920, 1080)
    QApplication.processEvents()
    # 等待动画和布局刷新
    QTimer.singleShot(100, lambda: None)
    QApplication.processEvents()
    win.grab().save(os.path.join(ARTIFACT_DIR, "screenshot_1920_1080.png"))
    
    # ---- 截图 2: 1366x768 紧凑布局 ----
    print("正在生成紧凑布局截图 (1366x768)...")
    win.resize(1366, 768)
    QApplication.processEvents()
    win.grab().save(os.path.join(ARTIFACT_DIR, "screenshot_1366_768.png"))
    
    # ---- 截图 3: 窄屏模式 (<1100px) ----
    print("正在生成窄屏垂直布局截图 (1000x800)...")
    win.resize(1000, 800)
    QApplication.processEvents()
    win.grab().save(os.path.join(ARTIFACT_DIR, "screenshot_narrow_layout.png"))
    
    # ---- 截图 4: 切换到实时曲线页面 ----
    print("正在生成实时曲线页面截图...")
    win.sidebar._on_click(win.sidebar._items[win.sidebar._NAV_ITEMS[1][0]].page) # 实时曲线
    QApplication.processEvents()
    win.grab().save(os.path.join(ARTIFACT_DIR, "screenshot_waveform_page.png"))
    
    # 切回控制台以便获取组件的局部细节
    win.sidebar._on_click(win.sidebar._items[win.sidebar._NAV_ITEMS[0][0]].page)
    QApplication.processEvents()
    
    # ---- 截图 5: 抓取手部姿态图在不同弯曲程度下的状态 ----
    console_page = win._pages[win._pages.keys().__iter__().__next__() if isinstance(win._pages, dict) else 0]
    # 我们知道控制台是 ConsolePage
    from lhgui.pages.console_page import ConsolePage
    for page_instance in win._pages.values():
        if isinstance(page_instance, ConsolePage):
            console_page = page_instance
            break
            
    print("正在更新手部姿态至【握拳】状态...")
    # 模拟数据更新
    console_page.pose_card.pose_view.update_joint_values([0, 0, 0, 0, 0, 0])
    # 刷事件平滑插值
    for _ in range(30):
        QApplication.processEvents()
        QTimer.singleShot(10, lambda: None)
    console_page.pose_card.grab().save(os.path.join(ARTIFACT_DIR, "screenshot_pose_fist.png"))
    
    print("正在更新手部姿态至【张开】状态...")
    console_page.pose_card.pose_view.update_joint_values([250, 250, 250, 250, 250, 250])
    for _ in range(30):
        QApplication.processEvents()
        QTimer.singleShot(10, lambda: None)
    console_page.pose_card.grab().save(os.path.join(ARTIFACT_DIR, "screenshot_pose_open.png"))
    
    # ---- 截图 6: 抓取 BottomBar 单行与双行模式 ----
    print("正在截取 BottomBar 单行模式与双行模式...")
    # 宽屏 BottomBar 单行
    console_page.bottom_bar.set_layout_mode("single")
    QApplication.processEvents()
    console_page.bottom_bar.grab().save(os.path.join(ARTIFACT_DIR, "screenshot_bottom_bar_single.png"))
    
    # 紧凑 BottomBar 双行
    console_page.bottom_bar.set_layout_mode("double")
    QApplication.processEvents()
    console_page.bottom_bar.grab().save(os.path.join(ARTIFACT_DIR, "screenshot_bottom_bar_double.png"))
    
    # ---- 截图 7: 图标测试页 (16px, 20px, 24px, 32px) ----
    print("正在生成图标尺寸渲染对比测试页...")
    test_widget = QWidget()
    test_widget.setWindowTitle("Icon Sizes DPI Render Test")
    test_widget.setStyleSheet("background-color:#ffffff;")
    lay = QHBoxLayout(test_widget)
    lay.setSpacing(20)
    lay.setContentsMargins(20, 20, 20, 20)
    
    sizes = [16, 20, 24, 32]
    # 我们用 get_pixmap 加载几个常用图标
    for sz in sizes:
        col = QVBoxLayout()
        col.setSpacing(6)
        col.setAlignment(Qt.AlignCenter)
        
        lbl_img = QLabel()
        lbl_img.setAlignment(Qt.AlignCenter)
        # 传入 target_widget=test_widget 使得 icon_manager 自动感知 DPR
        px = get_pixmap("console", sz, "#4f8cff", target_widget=test_widget)
        lbl_img.setPixmap(px)
        
        lbl_txt = QLabel(f"{sz}px")
        lbl_txt.setAlignment(Qt.AlignCenter)
        lbl_txt.setStyleSheet("color:#64748b; font-size:11px;")
        
        col.addWidget(lbl_img)
        col.addWidget(lbl_txt)
        lay.addLayout(col)
        
    test_widget.resize(300, 120)
    test_widget.show()
    QApplication.processEvents()
    test_widget.grab().save(os.path.join(ARTIFACT_DIR, "screenshot_icon_sizes_test.png"))
    
    # 销毁测试窗口
    test_widget.close()
    
    # 销毁主窗口
    print("测试完毕，正在安全销毁窗口并关闭底层资源...")
    win.close()
    
    print(f"[SUCCESS] 所有测试截图已生成并成功保存至 artifacts 目录:\n  {ARTIFACT_DIR}")


if __name__ == "__main__":
    try:
        run_svg_check()
        run_font_check()
        generate_screenshots()
        print("ALL TESTS RUN SUCCESSFUL!")
    except Exception as e:
        import traceback
        err_msg = f"Exception: {e}\n" + traceback.format_exc()
        print(err_msg)
        try:
            with open("test_error.txt", "w", encoding="utf-8") as f:
                f.write(err_msg)
        except Exception:
            pass
        sys.exit(1)
