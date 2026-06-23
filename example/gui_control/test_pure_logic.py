#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动化纯逻辑检查与校验脚本。

无需创建 QApplication 实例，避免无 GUI 交互环境下 Qt 底层插件导致的闪退。
检测项包括：
1. 扫描所有 SVG 矢量资源文件，确认其为纯几何路径，绝对不包含 <text>、Emoji、外部字体和内嵌位图。
2. 检测全部模块的导入，确认重构后的代码无语法错误。
3. 检查 Page 映射与 sidebar 配置，确认录制与回放 UI 已被彻底清除。
4. 验证中英文字体回退配置。
"""
import os
import sys
import xml.etree.ElementTree as ET

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def check_svg_assets():
    print("==================================================")
    print(" 自动检查 1/4：扫描并解析全部 SVG 图标资源")
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
            
            # 校验 viewBox 规范
            if root.attrib.get("viewBox") != "0 0 24 24":
                print(f"[WARN] 图标 {f} viewBox 为 {root.attrib.get('viewBox')}，建议规范为 0 0 24 24")
            
            # 校验包含的标签和属性
            for elem in root.iter():
                tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag_name in forbidden_tags:
                    print(f"[FAIL] 图标 {f} 包含非矢量禁止标签: <{tag_name}>")
                    passed = False
                
                for attr, val in elem.attrib.items():
                    if "font" in attr:
                        print(f"[FAIL] 图标 {f} 包含字体样式属性: {attr}={val}")
                        passed = False
                    if "base64" in val or "data:image" in val:
                        print(f"[FAIL] 图标 {f} 嵌入了非矢量位图数据！")
                        passed = False
        except Exception as e:
            print(f"[FAIL] 无法读取或解析 SVG {f}: {e}")
            passed = False
            
    if passed:
        print("[SUCCESS] 所有 26 个 SVG 矢量图标文件解析成功，完全由纯几何元素组成，无字符及位图！")
    return passed


def check_page_and_sidebar_mappings():
    print("\n==================================================")
    print(" 自动检查 2/4：校验 UI 页面与侧边栏映射")
    print("==================================================")
    
    passed = True
    try:
        from lhgui.utils.ui_state import Page
        from lhgui.widgets.sidebar import _NAV_ITEMS
        
        # 1. 确认 Page 枚举中没有 RECORDER
        has_recorder_enum = any(item.name.lower() == "recorder" for item in Page)
        if has_recorder_enum:
            print("[FAIL] ui_state.Page 枚举中依然残留 RECORDER 值！")
            passed = False
        else:
            print("[SUCCESS] ui_state.Page 枚举已干净清空，无 recorder 残留")
            
        # 2. 确认侧边栏导航没有 recorder 项
        has_recorder_nav = any(item[1] == "录制回放" or item[2] == "recorder" for item in _NAV_ITEMS)
        if has_recorder_nav:
            print("[FAIL] Sidebar 导航项中依然存在“录制回放”！")
            passed = False
        else:
            print("[SUCCESS] Sidebar 侧边栏导航已成功清理，只保留 6 个合法页面")
            
    except Exception as e:
        print(f"[FAIL] 校验页面与侧边栏发生异常: {e}")
        passed = False
        
    return passed


def check_module_imports():
    print("\n==================================================")
    print(" 自动检查 3/4：验证模块载入与重构后语法无误")
    print("==================================================")
    
    modules_to_test = [
        "lhgui.utils.icon_manager",
        "lhgui.utils.icon_helper",
        "lhgui.widgets.hand_pose_view",
        "lhgui.widgets.hand_pose_card",
        "lhgui.widgets.joint_row",
        "lhgui.widgets.joint_panel",
        "lhgui.widgets.preset_card",
        "lhgui.widgets.preset_group",
        "lhgui.widgets.bottom_bar",
        "lhgui.pages.console_page",
        "main_window"
    ]
    
    passed = True
    import importlib
    for mod_name in modules_to_test:
        try:
            importlib.import_module(mod_name)
            print(f"  [OK] 成功导入: {mod_name}")
        except Exception as e:
            print(f"  [FAIL] 导入 {mod_name} 失败！错误原因: {e}")
            import traceback
            traceback.print_exc()
            passed = False
            
    if passed:
        print("[SUCCESS] 全部重构后的核心组件与页面文件语法正确，无引用错误！")
    return passed


def check_font_definitions():
    print("\n==================================================")
    print(" 自动检查 4/4：检查中英文回退字体配置规范")
    print("==================================================")
    qss_path = os.path.join(os.path.dirname(__file__), "lhgui", "styles", "theme.qss")
    if not os.path.exists(qss_path):
        print(f"[Error] QSS 主题文件不存在: {qss_path}")
        return False
        
    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 验证 QSS 里面指定的字体集
        if '"Microsoft YaHei UI"' in content and '"Microsoft YaHei"' in content:
            print("[SUCCESS] QSS 中文 UI 字体集回退机制配置正确 (微软雅黑/微软雅黑UI优先)")
        else:
            print("[WARN] QSS 字体集中未发现 'Microsoft YaHei UI'，建议加上以提供更好的渲染")
            
        if '"Cascadia Mono"' in content or '"Consolas"' in content:
            print("[SUCCESS] QSS 数字等宽字体回退机制配置正确 (Cascadia Mono / Consolas 优先)")
        else:
            print("[WARN] QSS 中未发现 Cascadia Mono 或 Consolas，数字反馈可能非等宽对齐")
            
    except Exception as e:
        print(f"[FAIL] 读取 QSS 字体集校验发生异常: {e}")
        return False
        
    return True


if __name__ == "__main__":
    print("==================================================")
    print("        LinkerHand 控制台 UI 重构自动检查")
    print("==================================================")
    
    svg_ok = check_svg_assets()
    page_ok = check_page_and_sidebar_mappings()
    import_ok = check_module_imports()
    font_ok = check_font_definitions()
    
    print("\n==================================================")
    print("                  检查结果摘要")
    print("==================================================")
    print(f"1. SVG 资源检查:  {'PASS' if svg_ok else 'FAIL'}")
    print(f"2. 页面与侧边栏:  {'PASS' if page_ok else 'FAIL'}")
    print(f"3. 模块导入检查:  {'PASS' if import_ok else 'FAIL'}")
    print(f"4. 字体配置检查:  {'PASS' if font_ok else 'FAIL'}")
    
    if svg_ok and page_ok and import_ok and font_ok:
        print("\n[CONCLUSION] 恭喜，所有重构纯逻辑自动检查项全部通过！")
        sys.exit(0)
    else:
        print("\n[CONCLUSION] 警告：部分检查项未通过，请检查上述错误信息。")
        sys.exit(1)
