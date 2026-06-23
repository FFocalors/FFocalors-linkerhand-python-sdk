#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
猜拳小游戏：摄像头识别人类石头/剪刀/布，机械手作为机器玩家随机出拳。

本页只做手势分类和游戏判定，不做人手到 O6 pose 的实时模仿映射。
"""
import os
import random
import ssl
import threading
import time
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout

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
    QScrollArea,
    QWidget,
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


# ── 摄像头打开超时包装 ────────────────────────────────────────
_CAM_OPEN_TIMEOUT = 3.0

def _open_camera_with_timeout(backend_id, timeout=_CAM_OPEN_TIMEOUT):
    """在后台线程中打开摄像头，超时则放弃返回 None。"""
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            def _do_open():
                cap = cv2.VideoCapture(0, backend_id) if backend_id else cv2.VideoCapture(0)
                if not cap.isOpened():
                    cap.release()
                    return None
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                ret, frame = cap.read()
                if not ret or frame is None:
                    cap.release()
                    return None
                return cap
            return pool.submit(_do_open).result(timeout=timeout)
    except _FuturesTimeout:
        rps_log(f"camera open timed out ({timeout}s) for backend_id={backend_id}")
        return None
    except Exception as exc:
        rps_log(f"camera open error for backend_id={backend_id}: {exc}")
        return None


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
        self._stop_event = threading.Event()
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
        try:
            # 摄像头（每个后端带超时，避免 DSHOW 阻塞）
            for name, backend_id in [("CAP_DSHOW", cv2.CAP_DSHOW), ("CAP_MSMF", cv2.CAP_MSMF), ("default", 0)]:
                if not self._running:
                    return
                rps_log(f"trying backend={name}")
                cap = _open_camera_with_timeout(backend_id)
                if cap is not None:
                    self._cap = cap
                    rps_log(f"camera opened backend={name}")
                    break

            if not self._cap:
                self.camera_error.emit("摄像头打开失败")
                self._running = False
                return

            frame = cv2.flip(self._cap.read()[1], 1)
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
        finally:
            self._release()

    def stop(self):
        self._running = False
        if self._stop_event.wait(2.0):
            return
        rps_log("stop: worker did not finish cleanup in time")
        self.wait(1000)

    def _release(self):
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._hands:
            if hasattr(self._hands, "close"):
                self._hands.close()
            self._hands = None
        self._stop_event.set()

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

    @staticmethod
    def _section_card(title_text, subtitle=""):
        card = QFrame()
        card.setObjectName("GameSectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(10)
        title_lbl = QLabel(title_text)
        title_lbl.setObjectName("SectionTitle")
        layout.addWidget(title_lbl)
        if subtitle:
            subtitle_lbl = QLabel(subtitle)
            subtitle_lbl.setObjectName("SectionDescription")
            subtitle_lbl.setWordWrap(True)
            layout.addWidget(subtitle_lbl)
        return card, layout

    def _build_ui(self):
        main = QHBoxLayout(self)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(16)

        # ═══ 左侧：互动主视图 ═══
        left_card = QFrame()
        left_card.setObjectName("GameLeftCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(18, 16, 18, 18)
        left_layout.setSpacing(12)

        hero = QHBoxLayout()
        hero.setSpacing(12)
        hero_copy = QVBoxLayout()
        hero_copy.setSpacing(2)
        eyebrow = QLabel("INTERACTION / RPS")
        eyebrow.setObjectName("PageEyebrow")
        title = QLabel("猜拳互动")
        title.setObjectName("PageTitle")
        subtitle = QLabel("实时手势识别 · 机械手同步出拳")
        subtitle.setObjectName("PageSubtitle")
        hero_copy.addWidget(eyebrow)
        hero_copy.addWidget(title)
        hero_copy.addWidget(subtitle)
        hero.addLayout(hero_copy)
        hero.addStretch()
        self.cam_status_lbl = QLabel("等待启动")
        self.cam_status_lbl.setObjectName("CameraStatusPill")
        self.cam_status_lbl.setProperty("state", "idle")
        self.cam_status_lbl.setAlignment(Qt.AlignCenter)
        hero.addWidget(self.cam_status_lbl, alignment=Qt.AlignTop)
        left_layout.addLayout(hero)

        preview_card = QFrame()
        preview_card.setObjectName("CameraPreviewCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(8)
        self.cam_view = QLabel("等待摄像头画面")
        self.cam_view.setObjectName("GameCameraView")
        self.cam_view.setMinimumSize(500, 350)
        self.cam_view.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.cam_view, stretch=1)
        preview_meta = QLabel("请将手掌保持在画面中央 · 支持石头 / 剪刀 / 布")
        preview_meta.setObjectName("CameraMeta")
        preview_layout.addWidget(preview_meta)
        left_layout.addWidget(preview_card, stretch=1)

        # 摄像头叠加层（倒计时 / 庆祝），沿用原业务引用。
        self.cam_overlay = QLabel(self.cam_view)
        self.cam_overlay.setObjectName("GameCountdownOverlay")
        self.cam_overlay.setAlignment(Qt.AlignCenter)
        self.cam_overlay.hide()
        self.celebrate = QLabel(self.cam_view)
        self.celebrate.setObjectName("GameCelebrateOverlay")
        self.celebrate.setAlignment(Qt.AlignCenter)
        self.celebrate.setWordWrap(True)
        self.celebrate.hide()

        left_hint = QFrame()
        left_hint.setObjectName("GameHintBar")
        hint_layout = QHBoxLayout(left_hint)
        hint_layout.setContentsMargins(10, 7, 10, 7)
        hint_icon = QLabel("●")
        hint_icon.setObjectName("GameHintDot")
        hint_text = QLabel("开始游戏后，将依次进行倒计时、识别与判定")
        hint_text.setObjectName("GameHintText")
        hint_layout.addWidget(hint_icon)
        hint_layout.addWidget(hint_text)
        hint_layout.addStretch()
        left_layout.addWidget(left_hint)
        main.addWidget(left_card, stretch=7)

        # ═══ 右侧：比赛控制面板 ═══
        right_scroll = QScrollArea()
        right_scroll.setObjectName("ControlPanelScroll")
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setMinimumWidth(390)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_content = QWidget()
        right_content.setObjectName("ControlPanelContent")
        right = QVBoxLayout(right_content)
        right.setContentsMargins(0, 0, 5, 0)
        right.setSpacing(12)
        right_scroll.setWidget(right_content)

        # 1. 比分
        score_card, score = self._section_card("本场比分", "比分会在每轮判定完成后自动更新。")
        score_grid = QGridLayout()
        score_grid.setSpacing(8)
        self.lbl_human_score = QLabel("0")
        self.lbl_machine_score = QLabel("0")
        self.lbl_draw_score = QLabel("0")
        score_defs = [
            ("你赢", "human", self.lbl_human_score),
            ("机械手赢", "machine", self.lbl_machine_score),
            ("平局", "draw", self.lbl_draw_score),
        ]
        for index, (label, kind, value) in enumerate(score_defs):
            tile = QFrame()
            tile.setObjectName("ScoreTile")
            tile.setProperty("kind", kind)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(8, 9, 8, 9)
            tile_layout.setSpacing(2)
            caption = QLabel(label)
            caption.setObjectName("ScoreLabel")
            caption.setAlignment(Qt.AlignCenter)
            value.setObjectName("ScoreValue")
            value.setProperty("kind", kind)
            value.setAlignment(Qt.AlignCenter)
            tile_layout.addWidget(caption)
            tile_layout.addWidget(value)
            score_grid.addWidget(tile, 0, index)
        score.addLayout(score_grid)
        right.addWidget(score_card)

        # 2. 状态
        status_card, status = self._section_card("游戏状态", "当前轮次、识别结果与机械手动作一目了然。")
        self.d_state = QLabel("IDLE")
        self.d_round = QLabel("0")
        self.d_human = QLabel("--")
        self.d_timer = QLabel("--")
        self.d_candidate = QLabel("-- stable=0/6")
        self.d_machine = QLabel("--")
        status_defs = [
            ("状态", self.d_state, "state"),
            ("轮次", self.d_round, "round"),
            ("你的手势", self.d_human, "human"),
            ("倒计时", self.d_timer, "timer"),
            ("识别候选", self.d_candidate, "candidate"),
            ("机械手", self.d_machine, "machine"),
        ]
        status_grid = QGridLayout()
        status_grid.setSpacing(7)
        for index, (label, value, kind) in enumerate(status_defs):
            tile = QFrame()
            tile.setObjectName("GameStatusTile")
            tile.setProperty("kind", kind)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(9, 7, 9, 8)
            tile_layout.setSpacing(2)
            caption = QLabel(label)
            caption.setObjectName("GameStatusLabel")
            value.setObjectName("GameStatusValue")
            tile_layout.addWidget(caption)
            tile_layout.addWidget(value)
            row, column = divmod(index, 2)
            status_grid.addWidget(tile, row, column)
        status_grid.setColumnStretch(0, 1)
        status_grid.setColumnStretch(1, 1)
        status.addLayout(status_grid)

        hardware_row = QFrame()
        hardware_row.setObjectName("StatusStrip")
        hardware_layout = QHBoxLayout(hardware_row)
        hardware_layout.setContentsMargins(10, 6, 10, 6)
        hardware_label = QLabel("机械手通信")
        hardware_label.setObjectName("StatusStripLabel")
        self.d_hw = QLabel("未启用")
        self.d_hw.setObjectName("StatusStripValue")
        hardware_layout.addWidget(hardware_label)
        hardware_layout.addStretch()
        hardware_layout.addWidget(self.d_hw)
        status.addWidget(hardware_row)

        self.d_status = QLabel("点击“开始游戏”进入第一轮")
        self.d_status.setObjectName("GamePrompt")
        self.d_status.setWordWrap(True)
        status.addWidget(self.d_status)
        right.addWidget(status_card)

        # 3. 动作测试
        action_card, action = self._section_card("动作测试", "单独验证三种出拳姿态，不影响当前比分。")
        action_grid = QGridLayout()
        action_grid.setSpacing(7)
        self.btn_test_rock = QPushButton("石头")
        self.btn_test_scissors = QPushButton("剪刀")
        self.btn_test_paper = QPushButton("布")
        self.btn_home = QPushButton("恢复初始")
        for index, button in enumerate((self.btn_test_rock, self.btn_test_scissors, self.btn_test_paper, self.btn_home)):
            button.setProperty("category", "secondary")
            button.setProperty("variant", "gameAction")
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(32)
            action_grid.addWidget(button, index // 2, index % 2)
        self.btn_home.setProperty("category", "warning")
        action.addLayout(action_grid)
        right.addWidget(action_card)

        # 4. 游戏控制
        control_card, control = self._section_card("游戏控制", "开始为主操作；停止后保留当前比分。")
        output_row = QFrame()
        output_row.setObjectName("ToggleRow")
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(10, 8, 10, 8)
        output_copy = QVBoxLayout()
        output_copy.setSpacing(1)
        output_title = QLabel("机械手同步出拳")
        output_title.setObjectName("ToggleTitle")
        output_note = QLabel("启用前请确认设备和 CAN 连接状态")
        output_note.setObjectName("ToggleDescription")
        output_copy.addWidget(output_title)
        output_copy.addWidget(output_note)
        output_layout.addLayout(output_copy)
        output_layout.addStretch()
        self.chk_hw = QCheckBox("启用")
        self.chk_hw.setObjectName("SwitchCheck")
        self.chk_hw.setChecked(False)
        output_layout.addWidget(self.chk_hw)
        control.addWidget(output_row)

        control_grid = QGridLayout()
        control_grid.setSpacing(8)
        self.btn_start = QPushButton("开始游戏")
        self.btn_start.setProperty("category", "primary")
        self.btn_stop = QPushButton("停止游戏")
        self.btn_stop.setProperty("category", "danger")
        self.btn_reset = QPushButton("重置比分")
        self.btn_reset.setProperty("category", "secondary")
        for button in (self.btn_start, self.btn_stop, self.btn_reset):
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(35)
        control_grid.addWidget(self.btn_start, 0, 0, 1, 2)
        control_grid.addWidget(self.btn_stop, 1, 0)
        control_grid.addWidget(self.btn_reset, 1, 1)
        control.addLayout(control_grid)

        self.result_card = QFrame()
        self.result_card.setObjectName("GameResultCard")
        result_layout = QVBoxLayout(self.result_card)
        result_layout.setContentsMargins(10, 8, 10, 8)
        result_layout.setSpacing(3)
        self.lbl_celebration = QLabel("")
        self.lbl_celebration.setObjectName("GameResultTitle")
        self.lbl_celebration.setAlignment(Qt.AlignCenter)
        self.lbl_celebration.setWordWrap(True)
        self.lbl_round_info = QLabel("")
        self.lbl_round_info.setObjectName("GameResultDescription")
        self.lbl_round_info.setAlignment(Qt.AlignCenter)
        self.lbl_round_info.setWordWrap(True)
        result_layout.addWidget(self.lbl_celebration)
        result_layout.addWidget(self.lbl_round_info)
        self.result_card.hide()
        control.addWidget(self.result_card)
        right.addWidget(control_card)
        right.addStretch()
        main.addWidget(right_scroll, stretch=4)
    def _lbl_title(self, text):
        label = QLabel(text)
        label.setObjectName("CardTitle")
        return label

    def _sc(self, text, color):
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"color:{color}; font-size:28px; font-weight:700;")
        return label

    def _d(self, text, color="#1E293B"):
        label = QLabel(text)
        label.setStyleSheet(f"color:{color}; font-size:12px; font-weight:600;")
        return label

    def _btn(self, text, category="secondary"):
        button = QPushButton(text)
        button.setProperty("category", category)
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
        self.d_state.setText(state)
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
        self.d_hw.setText("已启用" if checked else "未启用")
        self.d_hw.setStyleSheet(
            f"color:{'#22A06B' if checked else '#E5484D'}; font-size:12px; font-weight:600;"
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
        self.d_status.setText("正在打开摄像头...")
        self.cam_status_lbl.setText("启动中")
        self.cam_status_lbl.setStyleSheet("color:#D99000; font-size:11px;")
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
        self.d_status.setText(f"{message}")
        self._set_state(self.STATE_ERROR)
        rps_log(f"camera error: {message}")

    def _on_camera_opened(self):
        self._opening_timer.stop()
        self.cam_status_lbl.setText("运行中")
        self.cam_status_lbl.setStyleSheet("color:#22A06B; font-size:11px;")
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
        self.d_human.setText("--")
        self.d_candidate.setText("-- stable=0/6")
        self.d_machine.setText("--")
        self.d_status.setText("已停止")
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
