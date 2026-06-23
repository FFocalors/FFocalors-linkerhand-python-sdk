#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猜拳小游戏：摄像头识别人类石头/剪刀/布，机械手作为机器玩家随机出拳。

本页只做手势分类和游戏判定，不做人手到 O6 pose 的实时模仿映射。
"""
import os
import random
import ssl
import time
import urllib.request
from collections import deque

import cv2
import mediapipe as mp
import numpy as np

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from lhgui.config.constants import HAND_CONFIGS
from lhgui.utils.signal_bus import signal_bus

_O6 = HAND_CONFIGS["O6"]
ROCK_POSE = list(_O6.preset_actions["握拳"])
PAPER_POSE = list(_O6.preset_actions["张开"])
SCISSORS_POSE = list(_O6.preset_actions["贰"])
HOME_POSE = list(_O6.init_pos)

VALID_GESTURES = ("石头", "剪刀", "布")
RPS_POSES = {
    "石头": ROCK_POSE,
    "剪刀": SCISSORS_POSE,
    "布": PAPER_POSE,
}

STABLE_FRAMES = 6
HUMAN_LOCK_WINDOW = 2.0
ROUND_RESULT_DELAY_MS = 1800
TASK_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]


def rps_log(message):
    print(f"[RPSGame] {message}", flush=True)


def judge_result(human, machine):
    if human not in VALID_GESTURES:
        return "invalid"
    if human == machine:
        return "draw"
    if (
        (human == "石头" and machine == "剪刀")
        or (human == "剪刀" and machine == "布")
        or (human == "布" and machine == "石头")
    ):
        return "human"
    return "machine"


class RPSWorker(QThread):
    _task_model_buffer = None

    frame_ready = pyqtSignal(QImage)
    gesture_guess = pyqtSignal(str)
    status_update = pyqtSignal(str, str)
    camera_error = pyqtSignal(str)
    camera_opened = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._cap = None
        self._hands = None
        self._backend = None
        self._mp_hands = None
        self._mp_drawing = None
        self._frame_idx = 0
        self._overlay_candidate = "未识别"
        self._overlay_run = 0
        self._overlay_hand = False

    def run(self):
        self._running = True
        rps_log("worker thread run entered")

        for name, backend_id in [("CAP_DSHOW", cv2.CAP_DSHOW), ("CAP_MSMF", cv2.CAP_MSMF), ("default", 0)]:
            self._cap = cv2.VideoCapture(0, backend_id) if backend_id else cv2.VideoCapture(0)
            if self._cap.isOpened():
                rps_log(f"camera opened backend={name}")
                break
            if self._cap:
                self._cap.release()

        if not self._cap or not self._cap.isOpened():
            self.camera_error.emit("摄像头打开失败")
            self._running = False
            return

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        ret, frame = self._cap.read()
        if not ret or frame is None:
            self.camera_error.emit("摄像头读取失败")
            self._running = False
            self._release()
            return

        frame = cv2.flip(frame, 1)
        self.camera_opened.emit()
        self._emit_frame(frame)

        rps_log("mediapipe init start")
        try:
            self._init_mediapipe()
            rps_log(f"mediapipe init ok backend={self._backend}")
        except Exception as exc:
            rps_log(f"mediapipe init failed: {exc}")
            self._hands = None

        while self._running:
            ret, frame = self._cap.read()
            self._frame_idx += 1
            if not ret or frame is None:
                break

            frame = cv2.flip(frame, 1)
            candidate = "未识别"
            has_hand = False

            if self._hands is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                hand, count = self._detect_hand(rgb)
                has_hand = hand is not None and count > 0
                if has_hand:
                    self._draw_landmarks(frame, hand)
                    candidate = self._classify(hand)
                    self.status_update.emit("hand", "detected")
                else:
                    self.status_update.emit("hand", "no_hand")
            else:
                self.status_update.emit("hand", "no_model")

            self._update_overlay_state(candidate, has_hand)
            self._draw_overlay(frame, candidate, has_hand)
            self.gesture_guess.emit(candidate)
            self._emit_frame(frame)
            self.msleep(30)

        rps_log("worker loop ended")
        self._release()

    def stop(self):
        self._running = False
        self.wait(3000)
        self._release()

    def _release(self):
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._hands:
            if hasattr(self._hands, "close"):
                self._hands.close()
            self._hands = None

    def _emit_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        h, w, ch = rgb.shape
        self.frame_ready.emit(QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy())

    def _init_mediapipe(self):
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
            self._mp_hands = mp.solutions.hands
            self._mp_drawing = mp.solutions.drawing_utils
            self._hands = self._mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                model_complexity=0,
                min_detection_confidence=0.6,
                min_tracking_confidence=0.6,
            )
            self._backend = "solutions"
            return

        from mediapipe.tasks import python as mp_tasks_python
        from mediapipe.tasks.python import vision as mp_tasks_vision

        model_buffer = self._load_task_model_buffer()
        options = mp_tasks_vision.HandLandmarkerOptions(
            base_options=mp_tasks_python.BaseOptions(model_asset_buffer=model_buffer),
            running_mode=mp_tasks_vision.RunningMode.IMAGE,
            num_hands=1,
            min_hand_detection_confidence=0.55,
            min_hand_presence_confidence=0.55,
            min_tracking_confidence=0.55,
        )
        self._hands = mp_tasks_vision.HandLandmarker.create_from_options(options)
        self._backend = "tasks"

    def _load_task_model_buffer(self):
        if RPSWorker._task_model_buffer is not None:
            return RPSWorker._task_model_buffer

        model_path = os.environ.get("MEDIAPIPE_HAND_LANDMARKER_TASK", "").strip()
        if model_path and os.path.exists(model_path):
            rps_log(f"tasks model load path={model_path}")
            with open(model_path, "rb") as file_obj:
                RPSWorker._task_model_buffer = file_obj.read()
            return RPSWorker._task_model_buffer

        rps_log("tasks model download start")
        try:
            with urllib.request.urlopen(TASK_MODEL_URL, timeout=20) as response:
                RPSWorker._task_model_buffer = response.read()
        except Exception as exc:
            rps_log(f"tasks model verified download failed: {exc}; retry unverified ssl")
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(TASK_MODEL_URL, timeout=20, context=context) as response:
                RPSWorker._task_model_buffer = response.read()
        rps_log(f"tasks model download ok bytes={len(RPSWorker._task_model_buffer)}")
        return RPSWorker._task_model_buffer

    def _detect_hand(self, rgb):
        if self._backend == "solutions":
            result = self._hands.process(rgb)
            if result.multi_hand_landmarks:
                return result.multi_hand_landmarks[0], len(result.multi_hand_landmarks)
            return None, 0

        if self._backend == "tasks":
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            result = self._hands.detect(image)
            if result.hand_landmarks:
                class Hand:
                    pass

                hand = Hand()
                hand.landmark = result.hand_landmarks[0]
                return hand, len(result.hand_landmarks)
            return None, 0

        return None, 0

    def _draw_landmarks(self, frame, hand):
        if self._mp_drawing is not None and self._mp_hands is not None:
            self._mp_drawing.draw_landmarks(frame, hand, self._mp_hands.HAND_CONNECTIONS)
            return

        h, w = frame.shape[:2]
        for a, b in HAND_CONNECTIONS:
            pa = hand.landmark[a]
            pb = hand.landmark[b]
            cv2.line(frame, (int(pa.x * w), int(pa.y * h)), (int(pb.x * w), int(pb.y * h)), (70, 220, 180), 2)
        for point in hand.landmark:
            cv2.circle(frame, (int(point.x * w), int(point.y * h)), 3, (255, 255, 255), -1)

    def _draw_overlay(self, frame, candidate, has_hand):
        status = "YES" if has_hand else "NO"
        lines = [
            f"HAND: {status}",
            f"candidate: {candidate}",
            f"stable={self._overlay_run}/{STABLE_FRAMES}",
        ]
        color = (40, 220, 40) if has_hand else (40, 40, 255)
        for idx, text in enumerate(lines):
            y = 28 + idx * 24
            cv2.putText(frame, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.64, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(frame, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.64, color, 2, cv2.LINE_AA)

    def _update_overlay_state(self, candidate, has_hand):
        if not has_hand:
            self._overlay_candidate = "未识别"
            self._overlay_run = 0
            self._overlay_hand = False
            return
        if candidate == self._overlay_candidate:
            self._overlay_run = min(STABLE_FRAMES, self._overlay_run + 1)
        else:
            self._overlay_candidate = candidate
            self._overlay_run = 1 if candidate in VALID_GESTURES else 0
        self._overlay_hand = True

    def _classify(self, hand):
        lm = hand.landmark
        pts = np.array([[p.x, p.y, p.z] for p in lm], dtype=float)
        palm_center = np.mean(pts[[0, 5, 9, 13, 17]], axis=0)
        palm_scale = max(np.linalg.norm(pts[5] - pts[17]), np.linalg.norm(pts[0] - pts[9]), 1e-6)

        def clamp01(value):
            return max(0.0, min(1.0, float(value)))

        def angle_at(a, b, c):
            ba = pts[a] - pts[b]
            bc = pts[c] - pts[b]
            norm = np.linalg.norm(ba) * np.linalg.norm(bc)
            if norm <= 1e-8:
                return np.pi
            cos_v = float(np.dot(ba, bc) / norm)
            return np.arccos(max(-1.0, min(1.0, cos_v)))

        def bend_from_angle(angle, straight=2.75, bent=1.0):
            return clamp01((straight - float(angle)) / (straight - bent))

        def finger_state(mcp, pip, dip, tip):
            mcp_bend = bend_from_angle(angle_at(0, mcp, pip), straight=2.65, bent=1.05)
            pip_bend = bend_from_angle(angle_at(mcp, pip, dip), straight=2.85, bent=1.00)
            dip_bend = bend_from_angle(angle_at(pip, dip, tip), straight=2.85, bent=1.00)
            curl = clamp01(0.35 * mcp_bend + 0.45 * pip_bend + 0.20 * dip_bend)
            tip_dist = np.linalg.norm(pts[tip] - palm_center) / palm_scale
            extension = clamp01((tip_dist - 0.85) / 0.55)
            score = clamp01(0.72 * (1.0 - curl) + 0.28 * extension)
            if score >= 0.62:
                return True
            if score <= 0.42:
                return False
            return None

        index = finger_state(5, 6, 7, 8)
        middle = finger_state(9, 10, 11, 12)
        ring = finger_state(13, 14, 15, 16)
        little = finger_state(17, 18, 19, 20)
        states = [index, middle, ring, little]

        if all(state is True for state in states):
            return "布"
        if all(state is False for state in states):
            return "石头"
        if index is True and middle is True and ring is False and little is False:
            return "剪刀"
        return "未识别"


class GamePage(QFrame):
    STATE_IDLE = "IDLE"
    STATE_CAMERA_OPENING = "CAMERA_OPENING"
    STATE_COUNTDOWN = "COUNTDOWN"
    STATE_SHOOT = "SHOOT"
    STATE_JUDGING = "JUDGING"
    STATE_ROUND_RESULT = "ROUND_RESULT"
    STATE_STOPPED = "STOPPED"
    STATE_ERROR = "ERROR"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GamePage")
        self._worker = None
        self._state = self.STATE_IDLE
        self._running_game = False
        self._hw_enabled = False
        self._score = {"human": 0, "machine": 0, "draw": 0}
        self._round_num = 0
        self._machine_gesture = None
        self._locked_human = None
        self._last_candidate = "未识别"
        self._last_stable_count = 0
        self._gesture_history = deque(maxlen=STABLE_FRAMES)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_value = 0

        self._judge_timer = QTimer(self)
        self._judge_timer.setSingleShot(True)
        self._judge_timer.timeout.connect(self._on_judge_timeout)

        self._round_resume = QTimer(self)
        self._round_resume.setSingleShot(True)
        self._round_resume.timeout.connect(self._next_round)

        self._opening_timer = QTimer(self)
        self._opening_timer.setSingleShot(True)
        self._opening_timer.timeout.connect(self._on_opening_timeout)

        self._build_ui()
        self._wire()
        self._set_state(self.STATE_IDLE)

    def _build_ui(self):
        main = QHBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(8)

        left = QVBoxLayout()
        left.addWidget(QLabel("摄像头"))
        self.cam_view = QLabel()
        self.cam_view.setMinimumSize(480, 360)
        self.cam_view.setAlignment(Qt.AlignCenter)
        self.cam_view.setStyleSheet("background:#1a1a2e;border:2px solid #2a2a4e;border-radius:8px;color:#ccc;")
        self.cam_view.setText("等待启动")
        left.addWidget(self.cam_view, stretch=1)

        self.cam_overlay = QLabel(self.cam_view)
        self.cam_overlay.setAlignment(Qt.AlignCenter)
        self.cam_overlay.setStyleSheet("font-size:72px;font-weight:bold;color:white;background:rgba(0,0,0,80);")
        self.cam_overlay.hide()

        self.celebrate = QLabel(self.cam_view)
        self.celebrate.setAlignment(Qt.AlignCenter)
        self.celebrate.setWordWrap(True)
        self.celebrate.hide()

        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(self._lbl_title("猜拳小游戏"))

        hw_row = QHBoxLayout()
        self.chk_hw = QCheckBox("启用机械手出拳")
        self.chk_hw.setChecked(False)
        self.chk_hw.toggled.connect(self._on_hw_toggled)
        hw_row.addWidget(self.chk_hw)
        hw_row.addStretch()
        right.addLayout(hw_row)

        score = QFrame()
        score.setObjectName("score")
        score.setStyleSheet("#score{background:#16213e;border-radius:8px;padding:6px;}")
        score_grid = QGridLayout(score)
        self.lbl_human_score = self._sc("0", "#00ff88")
        self.lbl_machine_score = self._sc("0", "#ff7675")
        self.lbl_draw_score = self._sc("0", "#74b9ff")
        for col, (title, label) in enumerate([
            ("你赢", self.lbl_human_score),
            ("机械手赢", self.lbl_machine_score),
            ("平局", self.lbl_draw_score),
        ]):
            title_label = QLabel(title)
            title_label.setStyleSheet("color:#dbeafe;font-size:12px;font-weight:bold;")
            score_grid.addWidget(title_label, 0, col)
            score_grid.addWidget(label, 1, col)
        right.addWidget(score)

        self.result_card = QFrame()
        self.result_card.setObjectName("resultCard")
        self.result_card.setStyleSheet("#resultCard{background:#0f3460;border:2px solid #0984e3;border-radius:8px;padding:12px;}")
        result_layout = QVBoxLayout(self.result_card)
        result_layout.setSpacing(4)
        self.lbl_celebration = QLabel("")
        self.lbl_celebration.setAlignment(Qt.AlignCenter)
        self.lbl_celebration.setWordWrap(True)
        self.lbl_celebration.setStyleSheet("font-size:24px;font-weight:bold;color:#ffffff;padding:8px 0;")
        self.lbl_round_info = QLabel("")
        self.lbl_round_info.setAlignment(Qt.AlignCenter)
        self.lbl_round_info.setWordWrap(True)
        self.lbl_round_info.setStyleSheet("font-size:13px;color:#e5e7eb;")
        result_layout.addWidget(self.lbl_celebration)
        result_layout.addWidget(self.lbl_round_info)
        self.result_card.hide()
        right.addWidget(self.result_card)

        debug = QFrame()
        debug.setObjectName("debugPanel")
        debug.setStyleSheet("#debugPanel{background:#0d1b2a;border-radius:8px;padding:6px;}")
        debug_layout = QVBoxLayout(debug)
        debug_layout.setSpacing(2)
        self.d_state = self._d("状态: IDLE")
        self.d_round = self._d("轮次: 0")
        self.d_human = self._d("人类: --")
        self.d_candidate = self._d("候选: -- stable=0/6")
        self.d_machine = self._d("机械手出: --")
        self.d_hw = self._d("机械手: 未启用", "#e74c3c")
        self.d_status = self._d("提示: 点击开始游戏")
        for widget in [self.d_state, self.d_round, self.d_human, self.d_candidate, self.d_machine, self.d_hw, self.d_status]:
            debug_layout.addWidget(widget)
        right.addWidget(debug)

        test_row = QHBoxLayout()
        self.btn_test_rock = self._btn("测试石头", "#636e72", 10)
        self.btn_test_scissors = self._btn("测试剪刀", "#636e72", 10)
        self.btn_test_paper = self._btn("测试布", "#636e72", 10)
        self.btn_home = self._btn("复位", "#0984e3", 10)
        test_row.addWidget(self.btn_test_rock)
        test_row.addWidget(self.btn_test_scissors)
        test_row.addWidget(self.btn_test_paper)
        test_row.addWidget(self.btn_home)
        right.addLayout(test_row)

        control_row = QHBoxLayout()
        self.btn_start = self._btn("开始游戏", "#00b894", 12)
        self.btn_stop = self._btn("停止游戏", "#d63031", 12)
        self.btn_reset = self._btn("重置比分", "#636e72", 12)
        control_row.addWidget(self.btn_start)
        control_row.addWidget(self.btn_stop)
        control_row.addWidget(self.btn_reset)
        right.addLayout(control_row)
        right.addStretch()

        main.addLayout(left, 3)
        main.addLayout(right, 2)

    def _lbl_title(self, text):
        label = QLabel(text)
        label.setStyleSheet("color:#0f172a;font-size:20px;font-weight:700;")
        return label

    def _sc(self, text, color):
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"color:{color};font-size:24px;font-weight:bold;")
        return label

    def _d(self, text, color="#cbd5e1"):
        label = QLabel(text)
        label.setStyleSheet(f"color:{color};font-size:12px;font-family:monospace;font-weight:700;")
        return label

    def _btn(self, text, color, font_size):
        button = QPushButton(text)
        button.setStyleSheet(
            "QPushButton{"
            f"background:{color};color:white;border:none;border-radius:4px;"
            f"padding:5px 10px;font-size:{font_size}px;font-weight:bold;"
            "}"
            "QPushButton:hover{background:#00a884;}"
            "QPushButton:pressed{background:#008b5e;}"
            "QPushButton:disabled{background:#555;}"
        )
        return button

    def _wire(self):
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop_page)
        self.btn_reset.clicked.connect(self._reset_score)
        self.btn_home.clicked.connect(self._emit_home)
        self.btn_test_rock.clicked.connect(lambda: self._send_manual_pose("石头"))
        self.btn_test_scissors.clicked.connect(lambda: self._send_manual_pose("剪刀"))
        self.btn_test_paper.clicked.connect(lambda: self._send_manual_pose("布"))

    def _set_state(self, state):
        old = self._state
        self._state = state
        self.d_state.setText(f"状态: {state}")
        self.btn_start.setEnabled(state in (self.STATE_IDLE, self.STATE_STOPPED, self.STATE_ERROR))
        self.btn_stop.setEnabled(state not in (self.STATE_IDLE, self.STATE_STOPPED, self.STATE_ERROR))
        rps_log(f"state {old} -> {state}")

    def _on_hw_toggled(self, checked):
        if checked:
            reply = QMessageBox.question(
                self,
                "确认启用机械手出拳",
                "请确认机械手已上电、CAN 已连接、右上角状态为已连接。是否启用机械手出拳？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.chk_hw.blockSignals(True)
                self.chk_hw.setChecked(False)
                self.chk_hw.blockSignals(False)
                return

        self._hw_enabled = checked
        self.d_hw.setText("机械手: 已启用" if checked else "机械手: 未启用")
        self.d_hw.setStyleSheet(
            f"color:{'#00b894' if checked else '#e74c3c'};"
            "font-size:12px;font-family:monospace;font-weight:700;"
        )
        rps_log(f"hardware {'ENABLED' if checked else 'DISABLED'}")

    def _start(self):
        if self._running_game:
            return
        rps_log("start clicked")
        self._running_game = True
        self._round_num = 0
        self._machine_gesture = None
        self._locked_human = None
        self._gesture_history.clear()
        self.result_card.hide()
        self.celebrate.hide()
        self.cam_overlay.hide()
        self.d_status.setText("提示: 正在打开摄像头...")
        self._set_state(self.STATE_CAMERA_OPENING)

        self._worker = RPSWorker()
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.gesture_guess.connect(self._on_gesture)
        self._worker.status_update.connect(self._on_status)
        self._worker.camera_error.connect(self._on_camera_error)
        self._worker.camera_opened.connect(self._on_camera_opened)
        self._worker.start()
        self._opening_timer.start(3000)

    def _on_opening_timeout(self):
        if self._state == self.STATE_CAMERA_OPENING:
            self._on_camera_error("摄像头线程超时")

    def _on_camera_error(self, message):
        self._opening_timer.stop()
        self._running_game = False
        self._stop_worker()
        self.cam_view.setText("错误")
        self.d_status.setText(f"提示: {message}")
        self._set_state(self.STATE_ERROR)
        rps_log(f"camera error: {message}")

    def _on_camera_opened(self):
        self._opening_timer.stop()
        rps_log("camera opened")
        self._start_next_round()

    def _stop_page(self):
        self._running_game = False
        self._countdown_timer.stop()
        self._judge_timer.stop()
        self._round_resume.stop()
        self._opening_timer.stop()
        self._stop_worker()
        self._locked_human = None
        self._gesture_history.clear()
        self.cam_overlay.hide()
        self.celebrate.hide()
        self.result_card.hide()
        self.cam_view.setText("已停止")
        self.d_human.setText("人类: --")
        self.d_candidate.setText("候选: -- stable=0/6")
        self.d_machine.setText("机械手出: --")
        self.d_status.setText("提示: 已停止")
        self._set_state(self.STATE_STOPPED)
        rps_log("stopped by user")

    def _stop_worker(self):
        if self._worker:
            self._worker.stop()
            self._worker = None

    def _reset_score(self):
        self._score = {"human": 0, "machine": 0, "draw": 0}
        self._update_score()
        self.d_status.setText("提示: 比分已重置")

    def _start_next_round(self):
        if not self._running_game:
            return
        self._round_num += 1
        self._machine_gesture = None
        self._locked_human = None
        self._last_candidate = "未识别"
        self._last_stable_count = 0
        self._gesture_history.clear()
        self.result_card.hide()
        self.celebrate.hide()
        self.d_round.setText(f"轮次: {self._round_num}")
        self.d_human.setText("人类: --")
        self.d_candidate.setText(f"候选: -- stable=0/{STABLE_FRAMES}")
        self.d_machine.setText("机械手出: --")
        self.d_status.setText("提示: 倒计时中，请准备出拳")
        self._countdown_value = 3
        self._set_state(self.STATE_COUNTDOWN)
        self._resize_overlays()
        self.cam_overlay.show()
        self._on_countdown_tick()
        self._countdown_timer.start(1000)

    def _on_countdown_tick(self):
        if self._state != self.STATE_COUNTDOWN:
            return
        if self._countdown_value > 0:
            self.cam_overlay.setText(str(self._countdown_value))
            rps_log(f"round {self._round_num} countdown {self._countdown_value}")
            self._countdown_value -= 1
            return

        self._countdown_timer.stop()
        self.cam_overlay.setText("开始！")
        self._set_state(self.STATE_SHOOT)
        rps_log(f"round {self._round_num} shoot")
        self._shoot_machine_once()
        QTimer.singleShot(500, self.cam_overlay.hide)

    def _shoot_machine_once(self):
        self._machine_gesture = random.choice(["石头", "剪刀", "布"])
        rps_log(f"round {self._round_num} machine random: {self._machine_gesture}")
        self.d_machine.setText(f"机械手出: {self._machine_gesture}")

        pose = RPS_POSES[self._machine_gesture]
        if self._hw_enabled:
            self._emit_pose_once(pose, "machine")
            self.d_status.setText(f"提示: 机械手随机出 {self._machine_gesture}，正在识别人类手势")
        else:
            rps_log("hardware disabled, pose not sent")
            self.d_status.setText(f"提示: 机器随机出 {self._machine_gesture}，机械手未启用")

        self._gesture_history.clear()
        self._locked_human = None
        self._last_candidate = "未识别"
        self._last_stable_count = 0
        self._set_state(self.STATE_JUDGING)
        self._judge_timer.start(int(HUMAN_LOCK_WINDOW * 1000))

    def _on_gesture(self, candidate):
        if candidate in VALID_GESTURES:
            self.d_candidate.setText(f"候选: {candidate} stable={self._last_stable_count}/{STABLE_FRAMES}")
        else:
            self.d_candidate.setText(f"候选: 未识别 stable=0/{STABLE_FRAMES}")

        if self._state != self.STATE_JUDGING:
            return

        if candidate not in VALID_GESTURES:
            self._gesture_history.clear()
            self._last_candidate = "未识别"
            self._last_stable_count = 0
            self.d_human.setText("人类: 识别中...")
            return

        self._gesture_history.append(candidate)
        stable_count = 1
        for index in range(len(self._gesture_history) - 1, 0, -1):
            if self._gesture_history[index] == self._gesture_history[index - 1]:
                stable_count += 1
            else:
                break

        self._last_candidate = candidate
        self._last_stable_count = stable_count
        self.d_candidate.setText(f"候选: {candidate} stable={stable_count}/{STABLE_FRAMES}")
        self.d_human.setText(f"人类: {candidate}")
        rps_log(f"human candidate: {candidate} stable={stable_count}/{STABLE_FRAMES}")

        if stable_count >= STABLE_FRAMES:
            self._lock_human(candidate)

    def _lock_human(self, gesture):
        if self._locked_human is not None:
            return
        self._locked_human = gesture
        self._judge_timer.stop()
        rps_log(f"human locked: {gesture}")
        self._finish_round(judge_result(gesture, self._machine_gesture), gesture)

    def _on_judge_timeout(self):
        if self._state == self.STATE_JUDGING and self._locked_human is None:
            self._finish_round("invalid", "未识别")

    def _finish_round(self, result, human_gesture):
        self._judge_timer.stop()
        if result in self._score:
            self._score[result] += 1
            self._update_score()

        machine = self._machine_gesture or "--"
        rps_log(f"judge result: {result}")

        result_cfg = {
            "human": {
                "title": "🎉 你赢啦！",
                "short": "你赢啦",
                "overlay_bg": "rgba(0,150,90,180)",
                "card_bg": "#064e3b",
                "border": "#10b981",
                "color": "#ffffff",
            },
            "machine": {
                "title": "🤖 机械手赢啦！",
                "short": "机械手赢啦",
                "overlay_bg": "rgba(220,90,20,180)",
                "card_bg": "#431407",
                "border": "#f97316",
                "color": "#ffffff",
            },
            "draw": {
                "title": "🤝 平局，再来一轮！",
                "short": "平局",
                "overlay_bg": "rgba(45,95,180,180)",
                "card_bg": "#0f172a",
                "border": "#38bdf8",
                "color": "#ffffff",
            },
            "invalid": {
                "title": "⚠️ 没识别清楚，请再来一次！",
                "short": "未识别",
                "overlay_bg": "rgba(210,130,0,185)",
                "card_bg": "#422006",
                "border": "#f59e0b",
                "color": "#ffffff",
            },
        }
        cfg = result_cfg[result]
        rps_log(f"celebration: {cfg['short']}")
        rps_log(
            "score human={} machine={} draw={}".format(
                self._score["human"], self._score["machine"], self._score["draw"]
            )
        )

        self._set_state(self.STATE_ROUND_RESULT)
        self.d_human.setText(f"人类: {human_gesture}")
        self.d_status.setText(f"提示: {cfg['title']}")

        self._resize_overlays()
        self.celebrate.setText(cfg["title"])
        self.celebrate.setStyleSheet(
            "font-size:28px;font-weight:bold;"
            f"color:{cfg['color']};background:{cfg['overlay_bg']};"
            "border-radius:8px;padding:16px;"
        )
        self.celebrate.show()

        self.result_card.setStyleSheet(
            f"#resultCard{{background:{cfg['card_bg']};border:2px solid {cfg['border']};"
            "border-radius:8px;padding:12px;}}"
        )
        self.lbl_celebration.setText(cfg["title"])
        self.lbl_celebration.setStyleSheet(
            f"font-size:24px;font-weight:bold;color:{cfg['color']};padding:8px 0;"
        )
        self.lbl_round_info.setText(
            "你出: {}  |  机械手出: {}\n比分 你:{} 机械手:{} 平局:{}  |  第{}轮".format(
                human_gesture,
                machine,
                self._score["human"],
                self._score["machine"],
                self._score["draw"],
                self._round_num,
            )
        )
        self.result_card.show()
        self._round_resume.start(ROUND_RESULT_DELAY_MS)

    def _next_round(self):
        if self._state != self.STATE_ROUND_RESULT:
            return
        self.celebrate.hide()
        if self._running_game:
            rps_log("schedule next round")
            self._start_next_round()

    def _emit_pose_once(self, pose, tag):
        safe_pose = [int(max(0, min(255, value))) for value in pose]
        try:
            if tag == "machine":
                rps_log(f"sending machine pose once: {safe_pose}")
            else:
                rps_log(f"sending {tag} pose once: {safe_pose}")
            signal_bus.finger_move_requested.emit(safe_pose)
            if tag == "machine":
                rps_log("emit machine pose ok")
            else:
                rps_log(f"emit {tag} pose ok")
            self.d_status.setText(f"提示: 已发送 {tag} {safe_pose}")
        except Exception as exc:
            self.d_status.setText(f"提示: 下发失败 {exc}")
            rps_log(f"emit {tag} pose failed: {exc}")

    def _send_manual_pose(self, gesture):
        if gesture not in RPS_POSES:
            return
        if not self._hw_enabled:
            rps_log(f"hardware disabled, test {gesture} pose not sent")
            self.d_status.setText(f"提示: 机械手未启用，测试{gesture}未下发")
            return
        self._emit_pose_once(RPS_POSES[gesture], f"test_{gesture}")

    def _emit_home(self):
        if not self._hw_enabled:
            rps_log("hardware disabled, home pose not sent")
            self.d_status.setText("提示: 机械手未启用，复位未下发")
            return
        self._emit_pose_once(HOME_POSE, "home")

    def _update_score(self):
        self.lbl_human_score.setText(str(self._score["human"]))
        self.lbl_machine_score.setText(str(self._score["machine"]))
        self.lbl_draw_score.setText(str(self._score["draw"]))

    def _on_frame(self, image):
        self._resize_overlays()
        pixmap = QPixmap.fromImage(image).scaled(
            self.cam_view.width(),
            self.cam_view.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.cam_view.setPixmap(pixmap)

    def _on_status(self, key, value):
        if key != "hand":
            return
        if value == "detected":
            if self._state == self.STATE_JUDGING and self._locked_human is None:
                self.d_status.setText("提示: 检测到手，正在稳定锁定")
        elif value == "no_hand":
            if self._state == self.STATE_JUDGING and self._locked_human is None:
                self.d_status.setText("提示: 未检测到手，请把手放入画面")
        elif value == "no_model":
            self.d_status.setText("提示: MediaPipe 初始化失败，无法识别")

    def _resize_overlays(self):
        w = max(1, self.cam_view.width())
        h = max(1, self.cam_view.height())
        self.cam_overlay.setGeometry(0, 0, w, h)
        self.celebrate.setGeometry(20, max(20, h // 2 - 95), max(1, w - 40), 190)

    def resizeEvent(self, event):
        self._resize_overlays()
        super().resizeEvent(event)

    def set_compact_mode(self, compact):
        pass

    def hideEvent(self, event):
        if self._state not in (self.STATE_IDLE, self.STATE_STOPPED, self.STATE_ERROR):
            self._hw_enabled = False
            self.chk_hw.setChecked(False)
            self._stop_page()
        super().hideEvent(event)

    def closeEvent(self, event=None):
        self._running_game = False
        self._countdown_timer.stop()
        self._judge_timer.stop()
        self._round_resume.stop()
        self._opening_timer.stop()
        if self._worker:
            self._worker.stop()
            self._worker = None
        if event:
            super().closeEvent(event)
