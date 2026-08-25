"""离屏回归测试：实时数据不应在采样回调中触发绘制。"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt5.QtWidgets import QApplication

# unittest imports all test modules before invoking their setUpClass methods.
# Create the GUI application at module import time so other Qt-only tests do
# not leave behind a QCoreApplication before these QWidget/OpenGL checks run.
APP = QApplication.instance() or QApplication([])


class RenderPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = APP

    def test_waveform_sampling_is_bounded_and_render_is_deferred(self):
        from lhgui.widgets.waveform_panel import WaveformPanel

        panel = WaveformPanel("O6")
        panel._on_data({"state": [1, 2, 3, 4, 5, 6]})
        # The signal callback only writes the ring; PlotDataItems remain empty.
        self.assertEqual(panel._sample_count, 1)
        self.assertIsNone(panel.lines[0].getData()[1])

        for i in range(panel.MAX_POINTS + 37):
            panel._on_data({"state": [i] * 6})
        self.assertEqual(panel._sample_count, panel.MAX_POINTS)
        self.assertEqual(panel._joint_buffer.shape, (6, panel.MAX_POINTS))

        panel.show()
        panel._render_frame()
        x, y = panel.lines[0].getData()
        self.assertEqual(len(x), panel.MAX_POINTS)
        self.assertEqual(len(y), panel.MAX_POINTS)
        self.assertEqual(float(y[-1]), float(panel.MAX_POINTS + 36))

        panel.set_collapsed(True)
        self.assertFalse(panel._render_timer.isActive())
        panel.set_collapsed(False)
        self.assertTrue(panel._render_timer.isActive())
        panel.hide()
        self.assertFalse(panel._render_timer.isActive())
        panel.deleteLater()

    def test_hand_pose_is_limited_to_30fps_and_uses_restartable_highlight_timer(self):
        from lhgui.widgets.hand_pose_view import HandPoseView

        view = HandPoseView("O6")
        self.assertGreaterEqual(view._anim_timer.interval(), 33)
        self.assertTrue(view._highlight_timer.isSingleShot())
        view.update_joint_values([1, 2, 3, 4, 5, 6])
        self.assertTrue(view._anim_timer.isActive())
        view.show()
        view.hide()
        self.assertFalse(view._anim_timer.isActive())
        self.assertFalse(view._highlight_timer.isActive())
        view.show()
        view.deleteLater()


if __name__ == "__main__":
    unittest.main()
