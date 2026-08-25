#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：重量页面懒加载、页面生命周期和日志有界增量渲染。"""

import os
import subprocess
import sys
import time
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
GUI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, GUI_DIR)

from PyQt5.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])


class _PageSpy(QWidget):
    def __init__(self, *args):
        super().__init__()
        self.activations = 0
        self.deactivations = 0

    def activate(self):
        self.activations += 1

    def deactivate(self):
        self.deactivations += 1


class _TopBarSpy(QWidget):
    def set_demo_checked(self, _checked):
        pass


class _SidebarSpy(QWidget):
    def _on_page_changed(self, _page):
        pass

    def set_compact(self, _compact):
        pass


class _ApiSpy:
    hand_joint = "O6"

    def connect(self):
        pass

    def shutdown(self):
        pass


class _DataSourceSpy:
    def __init__(self, *_args, **_kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class _RecorderSpy:
    def stop_playback(self):
        pass


class _ActionSpy:
    def cancel(self):
        pass


class LazyPageTests(unittest.TestCase):
    def test_main_window_import_does_not_import_heavy_pages(self):
        code = (
            "import os,sys; os.environ['QT_QPA_PLATFORM']='offscreen'; "
            "sys.path.insert(0, %r); import main_window; "
            "assert 'lhgui.pages.vision_page' not in sys.modules; "
            "assert 'lhgui.pages.game_page' not in sys.modules"
        ) % GUI_DIR
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_heavy_page_is_created_once_and_lifecycle_is_called(self):
        import main_window
        from lhgui.utils.ui_state import Page

        vision_mod = types.ModuleType("lhgui.pages.vision_page")
        game_mod = types.ModuleType("lhgui.pages.game_page")
        vision_mod.VisionPage = _PageSpy
        game_mod.GamePage = _PageSpy
        with patch.dict(sys.modules, {
            "lhgui.pages.vision_page": vision_mod,
            "lhgui.pages.game_page": game_mod,
        }), patch.object(main_window, "TopBar", _TopBarSpy), \
                patch.object(main_window, "Sidebar", _SidebarSpy), \
                patch.object(main_window, "ConsolePage", _PageSpy), \
                patch.object(main_window, "LogPage", _PageSpy), \
                patch.object(main_window, "SettingsPage", _PageSpy), \
                patch.object(main_window, "DemoPage", _PageSpy), \
                patch.object(main_window, "ApiManager", _ApiSpy), \
                patch.object(main_window, "DataSource", _DataSourceSpy), \
                patch.object(main_window, "Recorder", _RecorderSpy), \
                patch.object(main_window, "ActionExecutor", _ActionSpy):
            window = main_window.MainWindow()
            # Stop the scheduled real preload; this test drives the ready
            # signal directly with fake modules.
            window._lazy_stop.set()
            self.assertNotIn(Page.VISION, window._pages)
            self.assertNotIn(Page.GAME, window._pages)
            window._switch_page(Page.VISION)
            self.assertNotIn(Page.VISION, window._pages)
            window._on_lazy_module_ready(Page.VISION, vision_mod, None)
            first = window._pages[Page.VISION]
            self.assertEqual(first.activations, 1)
            window._switch_page(Page.CONSOLE)
            self.assertEqual(first.deactivations, 1)
            window._switch_page(Page.VISION)
            self.assertIs(window._pages[Page.VISION], first)
            self.assertEqual(first.activations, 2)
            window.close()
            window.deleteLater()

    def test_slow_import_never_blocks_navigation_and_ready_page_is_reused(self):
        source = [
            "import os,sys,time,types",
            "from unittest.mock import patch",
            "os.environ['QT_QPA_PLATFORM']='offscreen'",
            "sys.path.insert(0,%r)",
            "from PyQt5.QtWidgets import QApplication,QWidget",
            "import main_window",
            "from lhgui.utils.ui_state import Page",
            "class Spy(QWidget):",
            "    def __init__(self,*args): super().__init__()",
            "    def activate(self): pass",
            "    def deactivate(self): pass",
            "class Top(QWidget):",
            "    def set_demo_checked(self,value): pass",
            "class Side(QWidget):",
            "    def _on_page_changed(self,value): pass",
            "    def set_compact(self,value): pass",
            "class Api:",
            "    hand_joint='O6'",
            "    def connect(self): pass",
            "    def shutdown(self): pass",
            "class Data:",
            "    def __init__(self,*args,**kwargs): pass",
            "    def start(self): pass",
            "    def stop(self): pass",
            "class Recorder:",
            "    def stop_playback(self): pass",
            "class Actions:",
            "    def cancel(self): pass",
            "mods={'lhgui.pages.vision_page':types.ModuleType('lhgui.pages.vision_page'), 'lhgui.pages.game_page':types.ModuleType('lhgui.pages.game_page')}",
            "mods['lhgui.pages.vision_page'].VisionPage=Spy",
            "mods['lhgui.pages.game_page'].GamePage=Spy",
            "def slow_import(name):",
            "    time.sleep(0.12); return mods[name]",
            "app=QApplication([])",
            "with patch.object(main_window,'TopBar',Top), patch.object(main_window,'Sidebar',Side), patch.object(main_window,'ConsolePage',Spy), patch.object(main_window,'LogPage',Spy), patch.object(main_window,'SettingsPage',Spy), patch.object(main_window,'DemoPage',Spy), patch.object(main_window,'ApiManager',Api), patch.object(main_window,'DataSource',Data), patch.object(main_window,'Recorder',Recorder), patch.object(main_window,'ActionExecutor',Actions), patch.object(main_window.importlib,'import_module',side_effect=slow_import):",
            "    window=main_window.MainWindow(); window._lazy_stop.clear()",
            "    start=time.perf_counter(); window._switch_page(Page.VISION); assert time.perf_counter()-start < 0.05",
            "    assert Page.VISION not in window._pages; window._start_lazy_preload()",
            "    deadline=time.monotonic()+2.0",
            "    while Page.VISION not in window._pages and time.monotonic() < deadline: app.processEvents(); time.sleep(0.01)",
            "    assert Page.VISION in window._pages; first=window._pages[Page.VISION]",
            "    window._switch_page(Page.CONSOLE); window._switch_page(Page.VISION); assert window._pages[Page.VISION] is first",
            "    window.close(); assert not window._lazy_preload_thread.is_alive(); window.deleteLater(); app.processEvents()",
        ]
        code = "\n".join(source) % GUI_DIR
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_log_page_stays_incremental_at_capacity(self):
        # Keep this text-document stress case isolated. Some older tests use
        # QCoreApplication and leave worker-thread event sources alive; mixing
        # those with QTextDocument teardown can crash the Windows Qt plugin.
        code = r'''
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, %r)
from PyQt5.QtWidgets import QApplication
from lhgui.pages.log_page import LogPage
from lhgui.utils.signal_bus import signal_bus
app = QApplication([])
page = LogPage(); page.resize(640, 360); page.show(); app.processEvents()
for index in range(page.MAX_ENTRIES + 250):
    signal_bus.connection_message.emit("info", "log-entry-%%d" %% index)
time.sleep(0.08); app.processEvents()
assert len(page._entries) == page.MAX_ENTRIES
assert page.view.document().blockCount() <= page.MAX_ENTRIES
text = page.view.toPlainText()
assert "log-entry-2249" in text and "log-entry-0" not in text
''' % GUI_DIR
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
