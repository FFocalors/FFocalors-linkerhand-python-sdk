#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉识别功能页面 — 集成 custom_11 关键点实时映射到 O6 姿态。"""
import json
import os
import sys
import time
import urllib.request
from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QGridLayout, QTextEdit, QCheckBox,
    QFrame, QSplitter,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPointF, QRectF
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QFont

# 把 vision_control 加到 path（模块内使用相对 import）
_VISION_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "vision_control"))
if _VISION_DIR not in sys.path:
    sys.path.insert(0, _VISION_DIR)

from hand_pose_mapper import Custom11ToO6PoseMapper, PRESETS
from gesture_recognizer import Custom11GestureRecognizer
from o6_gui_params_adapter import O6GuiParamsAdapter
from custom11_keypoints import validate_keypoints

from lhgui.utils.signal_bus import signal_bus
from lhgui.utils.ui_state import ui_state, ConnectionState


# ============================================================
# 手指连接关系（画线段用）
# ============================================================
FINGER_LINKS = [
    (0, 1), (1, 2),          # thumb  base → mid → tip
    (3, 4),                   # index  base → tip
    (5, 6),                   # middle base → tip
    (7, 8),                   # ring   base → tip
    (9, 10),                  # little base → tip
]

FINGER_NAMES = ["thumb", "thumb", "thumb",
                "index", "index", "middle", "middle",
                "ring", "ring", "little", "little"]

FINGER_COLORS = {
    "thumb":  QColor("#ef4444"),
    "index":  QColor("#3b82f6"),
    "middle": QColor("#22c55e"),
    "ring":   QColor("#a855f7"),
    "little": QColor("#f59e0b"),
}

BASES = {0, 3, 5, 7, 9}         # 根部点画大一些
TIPS = {2, 4, 6, 8, 10}        # 指尖
PT_LABELS = [
    "拇指根", "拇指中", "拇指尖",
    "食指根", "食指尖", "中指根", "中指尖",
    "无名指根", "无名指尖", "小指根", "小指尖",
]


# ============================================================
# 关键点画布
# ============================================================
class KeypointsCanvas(QWidget):
    """实时手部 11 点关键点可视化。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(340, 340)
        self._kps: Optional[List[tuple]] = None
        self._pose: Optional[List[int]] = None
        self._overlay: str = ""

    def update_data(self, keypoints, pose=None, overlay=""):
        self._kps = keypoints
        self._pose = pose
        self._overlay = overlay
        self.update()

    def clear(self):
        self._kps = None
        self._pose = None
        self._overlay = "等待关键点数据…"
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(self.rect(), QColor("#111827"))

        # 网格
        p.setPen(QPen(QColor("#1f2937"), 0.5))
        for gx in range(30, w, 35):
            p.drawLine(gx, 30, gx, h - 30)
        for gy in range(30, h, 35):
            p.drawLine(30, gy, w - 30, gy)

        if not self._kps:
            p.setPen(QColor("#6b7280"))
            f = QFont(); f.setPointSize(15); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self._overlay or "等待关键点数据…")
            p.end()
            return

        kps = self._kps

        # ---- 自动缩放 ----
        xs = [pt[0] for pt in kps]; ys = [pt[1] for pt in kps]
        x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys)
        pad = max((x1 - x0) * 0.25, (y1 - y0) * 0.25, 30)
        x0 -= pad; x1 += pad; y0 -= pad; y1 += pad
        span = max(x1 - x0, y1 - y0, 1)

        def tx(px, py):
            return (30 + (px - x0) / span * (w - 60),
                    30 + (py - y0) / span * (h - 60))

        # ---- 掌根连线 ----
        palm_idx = [0, 3, 5, 7, 9]
        palm_pts = [tx(kps[i][0], kps[i][1]) for i in palm_idx]
        p.setPen(QPen(QColor("#374151"), 2, Qt.DashLine))
        for i in range(len(palm_pts)):
            a = palm_pts[i]; b = palm_pts[(i + 1) % len(palm_pts)]
            p.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))

        # ---- 手指连线 ----
        for i1, i2 in FINGER_LINKS:
            a = tx(kps[i1][0], kps[i1][1])
            b = tx(kps[i2][0], kps[i2][1])
            c = FINGER_COLORS.get(FINGER_NAMES[i1], QColor("#6b7280"))
            p.setPen(QPen(c, 3))
            p.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))

        # ---- 关节点 ----
        for i, kp in enumerate(kps):
            sx, sy = tx(kp[0], kp[1])
            c = FINGER_COLORS.get(FINGER_NAMES[i], QColor("#6b7280"))
            r = 7 if i in BASES else 5
            p.setBrush(QBrush(c))
            p.setPen(QPen(QColor("#f9fafb"), 1.5))
            p.drawEllipse(QPointF(sx, sy), r, r)

            if i in TIPS:
                f = QFont(); f.setPointSize(9); p.setFont(f)
                p.setPen(QColor("#9ca3af"))
                p.drawText(int(sx + 12), int(sy + 5), PT_LABELS[i])

        # ---- 覆写文字 ----
        if self._overlay:
            f = QFont(); f.setPointSize(13); f.setBold(True); p.setFont(f)
            p.setPen(QColor("#facc15"))
            p.drawText(35, h - 12, self._overlay)

        # ---- O6 pose 条 ----
        if self._pose:
            bar_y = 40; bar_h = 70
            p.fillRect(QRectF(35, bar_y, w - 70, bar_h), QColor(0, 0, 0, 100))
            p.setPen(QColor("#9ca3af"))
            f = QFont(); f.setPointSize(9); p.setFont(f)
            p.drawText(45, bar_y + 16, "O6 控制量")
            bar_colors = ["#ef4444", "#f97316", "#3b82f6", "#22c55e", "#a855f7", "#f59e0b"]
            bw = (w - 90) // 6 - 4
            for i, (v, bc) in enumerate(zip(self._pose, bar_colors)):
                bx = 45 + i * (bw + 4)
                bh = (v / 255.0) * (bar_h - 28)
                by = bar_y + bar_h - 8 - bh
                p.fillRect(QRectF(bx, by, bw, bh), QColor(bc))
                f2 = QFont(); f2.setPointSize(8); p.setFont(f2)
                p.setPen(QColor("#f9fafb"))
                p.drawText(QRectF(bx, by - 14, bw, 12), Qt.AlignCenter, str(v))

        p.end()


# ============================================================
# 姿态柱状图
# ============================================================
class PoseBars(QWidget):
    DIMS = ["拇指弯曲", "拇指横摆", "食指弯曲", "中指弯曲", "无名指弯曲", "小指弯曲"]
    COLS = ["#ef4444", "#f97316", "#3b82f6", "#22c55e", "#a855f7", "#f59e0b"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._pose = [250] * 6

    def set_pose(self, pose):
        self._pose = list(pose)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(self.rect(), QColor("#1f2937"))

        n = 6; gap = 8; left = 8; right = 8
        bw = (w - left - right - gap * (n - 1)) // n

        for i, (name, color, val) in enumerate(zip(self.DIMS, self.COLS, self._pose)):
            x = left + i * (bw + gap)
            bar_h = (val / 255.0) * (h - 40)
            y = h - 28 - bar_h

            # 底条
            p.fillRect(QRectF(x, 18, bw, h - 46), QColor("#374151"))
            # 填充
            p.fillRect(QRectF(x, y, bw, bar_h), QColor(color))

            # 数值
            f = QFont(); f.setPointSize(9); p.setFont(f)
            p.setPen(QColor("#f3f4f6"))
            p.drawText(QRectF(x, y - 16, bw, 14), Qt.AlignCenter, str(val))

            # 标签
            f2 = QFont(); f2.setPointSize(8); p.setFont(f2)
            p.setPen(QColor("#9ca3af"))
            p.drawText(QRectF(x - 2, h - 26, bw + 4, 24), Qt.AlignCenter | Qt.TextWordWrap, name)

        p.end()


# ============================================================
# 主页面
# ============================================================
class VisionPage(QWidget):
    log_line = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VisionPage")

        # 确保 vision_control 可 import
        if _VISION_DIR not in sys.path:
            sys.path.insert(0, _VISION_DIR)

        self._gui = O6GuiParamsAdapter()
        self._mapper: Optional[Custom11ToO6PoseMapper] = None
        self._recognizer = Custom11GestureRecognizer()
        self._running = False
        self._frame_n = 0
        self._kps: Optional[List[tuple]] = None
        self._latest_pose: Optional[List[int]] = None
        self._sample_data = {}
        self._sample_idx = 0

        # Qt 定时器
        self._stream_timer = QTimer(self)
        self._stream_timer.timeout.connect(self._poll_stream)
        self._sample_timer = QTimer(self)
        self._sample_timer.timeout.connect(self._next_sample)

        self._build_ui()
        self._wire()
        self.log_line.connect(self._append_log)

        # 默认 preset
        self._rebuild_mapper()
        self.canvas.clear()

    # --------------------------------------------------------
    # UI 构建
    # --------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── 控制栏 ──
        root.addWidget(self._make_control_bar())

        # ── 主区域 ──
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)

        # 左：关键点画布
        cframe = QFrame()
        cframe.setStyleSheet("QFrame{background:#111827;border-radius:8px;}")
        cl = QVBoxLayout(cframe); cl.setContentsMargins(8, 8, 8, 8)
        self.canvas = KeypointsCanvas()
        cl.addWidget(self.canvas)
        splitter.addWidget(cframe)

        # 右：状态面板
        right = QFrame()
        right.setStyleSheet("QFrame{background:#1f2937;border-radius:8px;}")
        rl = QVBoxLayout(right); rl.setContentsMargins(12, 12, 12, 12); rl.setSpacing(10)

        # O6 柱状图
        pg = QGroupBox("O6 控制向量 (6 维)")
        pg.setStyleSheet(self._gb_style())
        pl = QVBoxLayout(pg); pl.setContentsMargins(4, 18, 4, 4)
        self.pose_bars = PoseBars()
        pl.addWidget(self.pose_bars)
        rl.addWidget(pg)

        # 手指弯曲度
        cg = QGroupBox("手指弯曲度 (curl score)")
        cg.setStyleSheet(self._gb_style())
        cgl = QGridLayout(cg); cgl.setContentsMargins(4, 18, 4, 4)
        self._curl_lbls = {}
        fingers = [("thumb_bend", "拇指"), ("index", "食指"), ("middle", "中指"),
                    ("ring", "无名指"), ("little", "小指")]
        for col, (key, label) in enumerate(fingers):
            hl = QLabel(label)
            hl.setStyleSheet("color:#9ca3af;font-size:11px;")
            hl.setAlignment(Qt.AlignCenter)
            cgl.addWidget(hl, 0, col)
            vl = QLabel("—")
            vl.setAlignment(Qt.AlignCenter)
            vl.setStyleSheet("font-size:22px;font-weight:bold;color:#3b82f6;")
            cgl.addWidget(vl, 1, col)
            self._curl_lbls[key] = vl
        rl.addWidget(cg)

        # 运行状态
        sg = QGroupBox("运行信息")
        sg.setStyleSheet(self._gb_style())
        sl = QGridLayout(sg); sl.setContentsMargins(4, 18, 4, 4)
        self._lbl_frame = QLabel("0")
        self._lbl_mode = QLabel("—")
        self._lbl_fps = QLabel("—")
        for lbl in [self._lbl_frame, self._lbl_mode, self._lbl_fps]:
            lbl.setStyleSheet("color:#e5e7eb;font-weight:bold;")
        sl.addWidget(QLabel("帧数"), 0, 0)
        sl.addWidget(self._lbl_frame, 0, 1)
        sl.addWidget(QLabel("模式"), 1, 0)
        sl.addWidget(self._lbl_mode, 1, 1)
        sl.addWidget(QLabel("FPS"), 2, 0)
        sl.addWidget(self._lbl_fps, 2, 1)
        rl.addWidget(sg)

        rl.addStretch()
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 58)
        splitter.setStretchFactor(1, 42)

        root.addWidget(splitter, stretch=1)

        # ── 日志 ──
        lg = QGroupBox("运行日志")
        lg.setStyleSheet(self._gb_style())
        ll = QVBoxLayout(lg); ll.setContentsMargins(4, 18, 4, 4)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(100)
        self._log.setStyleSheet(
            "QTextEdit{background:#111827;color:#9ca3af;border:1px solid #374151;"
            "border-radius:4px;font-family:monospace;font-size:11px;}")
        ll.addWidget(self._log)
        root.addWidget(lg)

    def _make_control_bar(self):
        bar = QFrame()
        bar.setStyleSheet(
            "QFrame{background:#1f2937;border-radius:8px;padding:8px;}")
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(12, 8, 12, 8)
        lo.setSpacing(10)

        combo_ss = (
            "QComboBox{background:#374151;color:#e5e7eb;border:1px solid #4b5563;"
            "border-radius:4px;padding:4px 8px;min-width:100px;}"
            "QComboBox:hover{border-color:#6366f1;}"
            "QComboBox QAbstractItemView{background:#1f2937;color:#e5e7eb;"
            "selection-background-color:#6366f1;border:1px solid #4b5563;}"
        )

        lo.addWidget(QLabel("输入源"))
        self._cmb_input = QComboBox()
        self._cmb_input.addItems(["sample (离线样例)", "stream (HTTP 实时)"])
        self._cmb_input.setStyleSheet(combo_ss)
        lo.addWidget(self._cmb_input)

        lo.addWidget(QLabel("控制模式"))
        self._cmb_mode = QComboBox()
        self._cmb_mode.addItems(["pose (连续姿态)", "gesture (手势识别)"])
        self._cmb_mode.setStyleSheet(combo_ss)
        lo.addWidget(self._cmb_mode)

        lo.addWidget(QLabel("实时预设"))
        self._cmb_preset = QComboBox()
        self._cmb_preset.addItems(list(PRESETS.keys()))
        self._cmb_preset.setCurrentText("balanced_realtime")
        self._cmb_preset.setStyleSheet(combo_ss)
        lo.addWidget(self._cmb_preset)

        self._hw_chk = QCheckBox("硬件控制")
        self._hw_chk.setStyleSheet(
            "QCheckBox{color:#ef4444;font-weight:bold;}"
            "QCheckBox::checked{color:#22c55e;}")
        self._hw_chk.setToolTip("⚠ 启用会直接控制机械手。确保无 CAN 总线冲突。")
        lo.addWidget(self._hw_chk)

        lo.addStretch()

        self._btn_start = QPushButton("▶ 开始")
        self._btn_start.setStyleSheet(
            "QPushButton{background:#059669;color:white;border:none;border-radius:4px;"
            "padding:6px 16px;font-weight:bold;}"
            "QPushButton:hover{background:#047857;}")
        lo.addWidget(self._btn_start)

        self._btn_stop = QPushButton("⏹ 停止")
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet(
            "QPushButton{background:#dc2626;color:white;border:none;border-radius:4px;"
            "padding:6px 16px;font-weight:bold;}"
            "QPushButton:hover{background:#b91c1c;}"
            "QPushButton:disabled{background:#374151;color:#6b7280;}")
        lo.addWidget(self._btn_stop)

        return bar

    @staticmethod
    def _gb_style():
        return (
            "QGroupBox{color:#e5e7eb;font-weight:bold;border:1px solid #374151;"
            "border-radius:6px;margin-top:10px;padding-top:16px;}")

    # --------------------------------------------------------
    # 信号绑定
    # --------------------------------------------------------
    def _wire(self):
        self._btn_start.clicked.connect(self._start)
        self._btn_stop.clicked.connect(self._stop)
        self._cmb_preset.currentTextChanged.connect(lambda _: self._rebuild_mapper())

    # --------------------------------------------------------
    # 启停逻辑
    # --------------------------------------------------------
    def _rebuild_mapper(self):
        preset = self._cmb_preset.currentText()
        p = PRESETS.get(preset, PRESETS["balanced_realtime"])
        self._mapper = Custom11ToO6PoseMapper(
            smoothing_alpha=p["smoothing_alpha"],
            max_delta=p["max_delta"],
            min_interval=p["min_interval"],
            deadzone=p["deadzone"],
        )
        self.log_line.emit(f"映射器已初始化: {preset}")

    def _start(self):
        self._running = True
        self._frame_n = 0
        self._sample_idx = 0

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._cmb_input.setEnabled(False)
        self._cmb_mode.setEnabled(False)

        is_stream = "stream" in self._cmb_input.currentText()
        if is_stream:
            self._stream_timer.start(100)
            self.log_line.emit("▶ stream 模式 — 轮询 http://127.0.0.1:8765/latest")
        else:
            sample_path = os.path.join(_VISION_DIR, "sample_keypoints_11.json")
            try:
                with open(sample_path, "r", encoding="utf-8") as f:
                    self._sample_data = json.load(f)
                self._sample_idx = 0
                self._sample_timer.start(800)
                self.log_line.emit(
                    f"▶ sample 模式 — 已加载 {len(self._sample_data)} 组样例")
            except Exception as e:
                self.log_line.emit(f"✗ 加载样例失败: {e}")
                self._stop()
                return

    def _stop(self):
        self._running = False
        self._stream_timer.stop()
        self._sample_timer.stop()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._cmb_input.setEnabled(True)
        self._cmb_mode.setEnabled(True)
        self.log_line.emit("⏹ 已停止")

    # --------------------------------------------------------
    # 帧获取 / 处理
    # --------------------------------------------------------
    def _poll_stream(self):
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8765/latest", method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return

        if not body.get("ok") or not body.get("fresh"):
            return

        frame = body.get("frame", {})
        kps = frame.get("keypoints", [])
        if len(kps) != 11:
            return
        self._handle_frame(kps)

    def _next_sample(self):
        if not self._sample_data:
            return
        names = list(self._sample_data.keys())
        if self._sample_idx >= len(names):
            self._sample_idx = 0
        name = names[self._sample_idx]
        kps = self._sample_data[name]
        self._sample_idx += 1
        self.log_line.emit(f"#{self._frame_n + 1}  sample: {name}")
        self._handle_frame(kps)

    def _handle_frame(self, kps):
        """核心帧处理管道。"""
        try:
            pts = validate_keypoints(kps)
        except Exception as exc:
            self.log_line.emit(f"校验失败: {exc}")
            return

        self._kps = pts
        self._frame_n += 1
        self._lbl_frame.setText(str(self._frame_n))

        is_pose = "pose" in self._cmb_mode.currentText()

        if is_pose:
            res = self._mapper.map_keypoints(pts)
            if not res.get("valid"):
                self.log_line.emit(f"映射失败: {res.get('reason')}")
                return
            pose = res["pose"]
            dbg = res.get("debug", {})

            # 弯曲度标签
            curl = dbg.get("curl_scores", {})
            for key, lbl in self._curl_lbls.items():
                if key == "thumb_bend":
                    v = dbg.get("thumb_bend_score", 0)
                elif key in curl:
                    v = curl[key]
                else:
                    v = 0
                lbl.setText(f"{v:.2f}")
                if v > 0.7:
                    lbl.setStyleSheet("font-size:22px;font-weight:bold;color:#ef4444;")
                elif v > 0.3:
                    lbl.setStyleSheet("font-size:22px;font-weight:bold;color:#f59e0b;")
                else:
                    lbl.setStyleSheet("font-size:22px;font-weight:bold;color:#3b82f6;")

            ts = dbg.get("thumb_swing_score", 0)
            tb = dbg.get("thumb_bend_score", 0)
            self._latest_pose = pose
            self._lbl_mode.setText(
                f"pose  thumb_swing={ts:.2f}  thumb_bend={tb:.2f}")
            self.pose_bars.set_pose(pose)
            overlay = (
                f"O6: [{', '.join(str(v) for v in pose)}]  "
                f"curl: {', '.join(f'{k}={v:.2f}' for k, v in curl.items())}")
        else:
            # 手势识别模式
            res = self._recognizer.recognize(pts)
            gesture = res["gesture"]
            try:
                action = self._gui.gesture_to_action(gesture)
                pose = self._gui.get_pose_by_action(action)
            except ValueError:
                pose = self._gui.get_pose_by_action("张开")
                action = "张开"

            self._latest_pose = pose
            self._lbl_mode.setText(f"gesture → {gesture}")
            self.pose_bars.set_pose(pose)
            overlay = f"手势: {gesture}  动作: {action}"

            # 手指状态
            for f, s in res.get("finger_states", {}).items():
                if f in self._curl_lbls:
                    self._curl_lbls[f].setText(s[:1] if s else "?")

        # 画布刷新
        self.canvas.update_data(pts, self._latest_pose, overlay)

        # 可选硬件
        if self._hw_chk.isChecked() and self._latest_pose:
            if ui_state.snapshot.connection == ConnectionState.CONNECTED:
                signal_bus.finger_move_requested.emit(list(self._latest_pose))

    # --------------------------------------------------------
    # 日志
    # --------------------------------------------------------
    def _append_log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self._log.append(f"[{ts}] {msg}")

    # --------------------------------------------------------
    # 兼容旧接口
    # --------------------------------------------------------
    def set_compact_mode(self, compact: bool):
        pass

    def closeEvent(self, event):
        self._stop()
        super().closeEvent(event)
