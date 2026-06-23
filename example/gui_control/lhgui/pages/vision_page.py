#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视觉模仿控制：摄像头 + MediaPipe 21点 → 11控制点 → 关节角度 curl → O6 6维 pose。

默认仅识别显示，勾选"允许下发到机械手"后开通实机控制 (~8Hz, EMA, deadband, 最大步长限制)。
"""
import os, ssl, time, math, urllib.request, json, threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
from datetime import datetime
import cv2, mediapipe as mp, numpy as np

from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QMessageBox,
    QFileDialog, QComboBox, QSpinBox, QDoubleSpinBox, QGridLayout, QScrollArea,
    QWidget, QTextEdit,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPixmap

from lhgui.utils.signal_bus import signal_bus
from lhgui.config.constants import HAND_CONFIGS

# ── O6 端点（只读复用 constants.py） ──────────────────────────
_O6 = HAND_CONFIGS["O6"]
OPEN_POSE  = list(_O6.preset_actions["张开"])   # [250,250,250,250,250,250]
CLOSE_POSE = list(_O6.preset_actions["握拳"])   # [102, 18,  0,  0,  0,  0]
HOME_POSE  = list(_O6.init_pos)                  # [250]*6
SAFE_NEUTRAL = list(HOME_POSE)
POSE_MIN   = 0
POSE_MAX   = 255
INVERT     = [False]*6  # 默认不反转
EMA_ALPHA  = 0.35
DEADBAND   = 4
THUMB_BEND_MIN = 0
THUMB_BEND_MAX = 255
THUMB_SWING_MIN = 0
THUMB_SWING_MAX = 255
THUMB_SWING_INVERT_DEFAULT = False
THUMB_BEND_INVERT = False
FINGER_PROXIMAL_WEIGHT = 0.45
FINGER_DISTAL_WEIGHT = 0.35
FINGER_TIP_AUX_WEIGHT = 0.20
MAX_STEP_FINGER = 35
MAX_STEP_THUMB_SWING = 20
SEND_INTERVAL = 0.12  # ~8Hz
RECORD_INTERVAL = 0.12
MAX_REPLAY_STEP = 30
MIN_RECORD_POSE_DELTA = 3
RECORD_KEEPALIVE_INTERVAL = 0.60
MIN_RECORD_DURATION = 0.30
MAX_RECORD_DURATION = 60.0
MIN_RECORD_FRAMES = 3
MIN_PLAYBACK_FRAMES = 2
MIN_PLAYBACK_INTERVAL = 0.03
MAX_PLAYBACK_INTERVAL = 0.30
PLAYBACK_SPEEDS = ["0.5x","1.0x","1.5x","2.0x"]
RECORDING_TYPE = "linkerhand_gesture_recording"
POSE_FIELDS = ["thumb_bend","thumb_swing","index","middle","ring","little"]
RECORDING_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "recordings"))

# ── 11 控制点（从 MediaPipe 21 点中抽取）───────────────────────
# 顺序: [wrist, thumb_mcp, thumb_tip, index_mcp, index_tip,
#         middle_mcp, middle_tip, ring_mcp, ring_tip, pinky_mcp, pinky_tip]
C11_IDX = [0, 2, 4, 5, 8, 9, 12, 13, 16, 17, 20]
C11_NAMES = ["wrist","thumb_mcp","thumb_tip","index_mcp","index_tip",
             "middle_mcp","middle_tip","ring_mcp","ring_tip","pinky_mcp","pinky_tip"]
C11_COLORS = [
    (255,255,255), (255,0,255), (255,0,255),
    (0,255,0), (0,255,0), (0,255,255), (0,255,255),
    (255,255,0), (255,255,0), (0,128,255), (0,128,255),
]
HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(17,18),(18,19),(19,20),
    (0,17),
]
TASK_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"


def _vlog(message):
    print(f"[VisionSync] {message}", flush=True)


def _jlog(message):
    print(f"[VisionJoint] {message}", flush=True)


def _glog(message):
    print(f"[GestureRecord] {message}", flush=True)

# ── 摄像头打开超时包装 ────────────────────────────────────────
_CAM_OPEN_TIMEOUT = 3.0  # 每个后端的打开超时秒数

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
        _vlog(f"camera open timed out ({timeout}s) for backend_id={backend_id}")
        return None
    except Exception as e:
        _vlog(f"camera open error for backend_id={backend_id}: {e}")
        return None

# ── 工作线程 ──────────────────────────────────────────────────
class ImitationWorker(QThread):
    _task_model_buffer=None

    frame_ready = pyqtSignal(QImage)
    pose_computed = pyqtSignal(list, dict)       # pose, debug_info
    status_update = pyqtSignal(str, str)
    camera_error = pyqtSignal(str)
    camera_opened = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running=False; self._cap=None; self._hands=None
        self._stop_event=threading.Event()
        self._calib_open=None; self._calib_close=None
        self._thumb_open_baseline=None; self._thumb_close_baseline=None
        self._thumb_swing_invert=THUMB_SWING_INVERT_DEFAULT
        self._thumb_bend_invert=THUMB_BEND_INVERT
        self._mp_hands=None; self._mp_drawing=None
        self._mp_vision=None; self._backend=None
        self._frame_idx=0
        self._last_log_t=0.0

    def set_calibration(self, open_vec, close_vec):
        self._calib_open=list(open_vec) if open_vec else None
        self._calib_close=list(close_vec) if close_vec else None

    def set_thumb_config(self, open_baseline, close_baseline, swing_invert, bend_invert=None):
        self._thumb_open_baseline=float(open_baseline) if open_baseline is not None else None
        self._thumb_close_baseline=float(close_baseline) if close_baseline is not None else None
        self._thumb_swing_invert=bool(swing_invert)
        if bend_invert is not None:
            self._thumb_bend_invert=bool(bend_invert)

    def run(self):
        self._running=True
        _vlog("worker run entered")
        try:
            # 摄像头（每个后端带超时，避免 DSHOW 阻塞）
            for name,bid in [("CAP_DSHOW",cv2.CAP_DSHOW),("CAP_MSMF",cv2.CAP_MSMF),("default",0)]:
                if not self._running: return
                _vlog(f"trying backend={name}")
                cap=_open_camera_with_timeout(bid)
                if cap is not None:
                    self._cap=cap
                    _vlog(f"camera opened backend={name}")
                    break
            if not self._cap:
                self.camera_error.emit("摄像头打开失败"); self._running=False; return

            frame=cv2.flip(self._cap.read()[1],1)
            self.camera_opened.emit()
            fr=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            hh,ww,ch=fr.shape
            self.frame_ready.emit(QImage(fr.data,ww,hh,ch*ww,QImage.Format_RGB888).copy())

            # MediaPipe
            _vlog("mediapipe init start")
            try:
                self._init_mediapipe()
                _vlog(f"mediapipe init ok backend={self._backend}")
            except Exception as e:
                _vlog(f"mediapipe init failed: {e}")
                self._hands=None

            while self._running:
                ret,frame=self._cap.read()
                self._frame_idx+=1
                if self._frame_idx == 1 or self._frame_idx % 30 == 0:
                    _vlog(f"frame read ret={ret} shape={getattr(frame,'shape',None)}")
                if not ret or frame is None: break
                frame=cv2.flip(frame,1)

                pose=None; debug={}; hands_detected=0
                if self._hands is not None:
                    rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
                    rgb.flags.writeable=False
                    h,hands_detected=self._detect_hand(rgb)
                    should_log=self._frame_idx == 1 or self._frame_idx % 15 == 0
                    if should_log:
                        _vlog(f"frame={self._frame_idx} hands_detected={1 if hands_detected else 0}")
                    if h is not None:
                        if should_log:
                            _vlog("hand detected")
                        self._draw_landmarks(frame,h)
                        pose,debug=self._compute_pose(h)
                        debug["frame_idx"]=self._frame_idx
                        debug["log_joint"]=should_log
                        if should_log:
                            _vlog("control11 ready")
                        curls=debug.get("curls",[])
                        spread=debug.get("thumb_spread",0.0)
                        if should_log:
                            _vlog(
                                "curls thumb={:.3f} index={:.3f} middle={:.3f} ring={:.3f} little={:.3f} spread={:.3f}".format(
                                    curls[0],curls[1],curls[2],curls[3],curls[4],spread
                                )
                            )
                            fingers=debug.get("fingers",{})
                            for name in ("index","middle","ring","little"):
                                fd=fingers.get(name,{})
                                _jlog(
                                    "{} prox={:.3f} dist={:.3f} tip_aux={:.3f} fused={:.3f}".format(
                                        name,
                                        fd.get("proximal",0.0),
                                        fd.get("distal",0.0),
                                        fd.get("tip_aux",0.0),
                                        fd.get("fused",0.0),
                                    )
                                )
                            thumb=debug.get("thumb",{})
                            _jlog(
                                "thumb bend_raw={:.3f} bend_mapped={} swing_raw={:.3f} swing_norm={:.3f} swing_mapped={} invert={}".format(
                                    thumb.get("bend_raw",0.0),
                                    thumb.get("bend_mapped",0),
                                    thumb.get("swing_raw",0.0),
                                    thumb.get("swing_norm",0.0),
                                    thumb.get("swing_mapped",0),
                                    thumb.get("swing_invert",False),
                                )
                            )
                            _jlog(f"raw pose: {[int(v) for v in pose]}")
                        self._draw_overlay(frame,True,curls,spread,pose)
                        self.pose_computed.emit(pose,debug)
                        if should_log:
                            _vlog("pose signal emitted")
                        self.status_update.emit("hand","detected")
                    else:
                        self._draw_overlay(frame,False,None,None,None)
                        if self._frame_idx % 15 == 0:
                            _vlog("no hand, skip pose")
                        self.status_update.emit("hand","no_hand")
                else:
                    self._draw_overlay(frame,False,None,None,None)

                fr=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
                fr=np.ascontiguousarray(fr)
                hh,ww,ch=fr.shape
                self.frame_ready.emit(QImage(fr.data,ww,hh,ch*ww,QImage.Format_RGB888).copy())
                self.msleep(30)

            _vlog("stopped")
        finally:
            self._release()

    def stop(self):
        self._running=False
        if self._stop_event.wait(2.0):
            return
        _vlog("stop: worker did not finish cleanup in time")
        self.wait(1000)

    def _release(self):
        if self._cap: self._cap.release(); self._cap=None
        if self._hands: self._hands.close(); self._hands=None
        self._stop_event.set()

    def _init_mediapipe(self):
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
            self._mp_hands=mp.solutions.hands
            self._mp_drawing=mp.solutions.drawing_utils
            self._hands=self._mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                model_complexity=0,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._backend="solutions"
            return

        from mediapipe.tasks import python as mp_tasks_python
        from mediapipe.tasks.python import vision as mp_tasks_vision

        model_buffer=self._load_task_model_buffer()
        options=mp_tasks_vision.HandLandmarkerOptions(
            base_options=mp_tasks_python.BaseOptions(model_asset_buffer=model_buffer),
            running_mode=mp_tasks_vision.RunningMode.IMAGE,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._hands=mp_tasks_vision.HandLandmarker.create_from_options(options)
        self._mp_vision=mp_tasks_vision
        self._backend="tasks"

    def _load_task_model_buffer(self):
        if ImitationWorker._task_model_buffer is not None:
            return ImitationWorker._task_model_buffer

        model_path=os.environ.get("MEDIAPIPE_HAND_LANDMARKER_TASK","").strip()
        if model_path and os.path.exists(model_path):
            _vlog(f"tasks model load path={model_path}")
            with open(model_path,"rb") as f:
                ImitationWorker._task_model_buffer=f.read()
            return ImitationWorker._task_model_buffer

        _vlog("tasks model download start")
        try:
            with urllib.request.urlopen(TASK_MODEL_URL,timeout=20) as resp:
                ImitationWorker._task_model_buffer=resp.read()
        except Exception as e:
            _vlog(f"tasks model verified download failed: {e}; retry unverified ssl")
            ctx=ssl._create_unverified_context()
            with urllib.request.urlopen(TASK_MODEL_URL,timeout=20,context=ctx) as resp:
                ImitationWorker._task_model_buffer=resp.read()
        _vlog(f"tasks model download ok bytes={len(ImitationWorker._task_model_buffer)}")
        return ImitationWorker._task_model_buffer

    def _detect_hand(self, rgb):
        if self._backend == "solutions":
            res=self._hands.process(rgb)
            if res.multi_hand_landmarks:
                return res.multi_hand_landmarks[0], len(res.multi_hand_landmarks)
            return None,0

        if self._backend == "tasks":
            image=mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(rgb))
            res=self._hands.detect(image)
            if res.hand_landmarks:
                class _Hand:
                    pass
                hand=_Hand()
                hand.landmark=res.hand_landmarks[0]
                return hand,len(res.hand_landmarks)
            return None,0

        return None,0

    def _draw_landmarks(self, frame, hand_landmarks):
        if self._mp_drawing is not None and self._mp_hands is not None:
            self._mp_drawing.draw_landmarks(
                frame,
                hand_landmarks,
                self._mp_hands.HAND_CONNECTIONS,
            )
        h,w=frame.shape[:2]
        for a,b in HAND_CONNECTIONS:
            pa=hand_landmarks.landmark[a]
            pb=hand_landmarks.landmark[b]
            cv2.line(
                frame,
                (int(pa.x*w),int(pa.y*h)),
                (int(pb.x*w),int(pb.y*h)),
                (150,150,150),
                1,
            )
        for idx,p in enumerate(hand_landmarks.landmark):
            cv2.circle(frame,(int(p.x*w),int(p.y*h)),2,(220,220,220),-1)
        proximal_color=(255,160,40)
        distal_color=(40,160,255)
        thumb_color=(255,0,255)
        for mcp,pip,dip,tip in [(5,6,7,8),(9,10,11,12),(13,14,15,16),(17,18,19,20)]:
            for a,b,color in [(mcp,pip,proximal_color),(pip,dip,distal_color),(dip,tip,distal_color)]:
                pa=hand_landmarks.landmark[a]
                pb=hand_landmarks.landmark[b]
                cv2.line(frame,(int(pa.x*w),int(pa.y*h)),(int(pb.x*w),int(pb.y*h)),color,3)
            for idx in (mcp,pip,dip,tip):
                p=hand_landmarks.landmark[idx]
                cv2.circle(frame,(int(p.x*w),int(p.y*h)),4,(0,0,0),-1)
                cv2.circle(frame,(int(p.x*w),int(p.y*h)),3,proximal_color if idx in (mcp,pip) else distal_color,-1)
        for a,b in [(1,2),(2,3),(3,4)]:
            pa=hand_landmarks.landmark[a]
            pb=hand_landmarks.landmark[b]
            cv2.line(frame,(int(pa.x*w),int(pa.y*h)),(int(pb.x*w),int(pb.y*h)),thumb_color,3)
        for i,idx in enumerate(C11_IDX):
            p=hand_landmarks.landmark[idx]
            px,py=int(p.x*w),int(p.y*h)
            color=C11_COLORS[i]
            radius=7 if i == 0 else 5
            cv2.circle(frame,(px,py),radius,color,-1)
            cv2.circle(frame,(px,py),radius+2,(0,0,0),1)
            cv2.putText(frame,str(i),(px+5,py-5),cv2.FONT_HERSHEY_SIMPLEX,0.38,color,1,cv2.LINE_AA)
        for b,t in [(1,2),(3,4),(5,6),(7,8),(9,10)]:
            pb=hand_landmarks.landmark[C11_IDX[b]]
            pt=hand_landmarks.landmark[C11_IDX[t]]
            color=(255,0,255) if b == 1 else (20,220,20)
            cv2.line(
                frame,
                (int(pb.x*w),int(pb.y*h)),
                (int(pt.x*w),int(pt.y*h)),
                color,
                2,
            )

    def _draw_overlay(self, frame, has_hand, curls, spread, pose):
        status="YES" if has_hand else "NO"
        color=(20,220,20) if has_hand else (40,40,255)
        lines=[f"HAND: {status}"]
        if has_hand and curls:
            lines.append(
                "curl T={:.2f} I={:.2f} M={:.2f} R={:.2f} L={:.2f} S={:.2f}".format(
                    curls[0],curls[1],curls[2],curls[3],curls[4],spread or 0.0
                )
            )
            lines.append(f"pose {[int(v) for v in pose]}")
        for i,text in enumerate(lines):
            y=28+i*24
            cv2.putText(frame,text,(12,y),cv2.FONT_HERSHEY_SIMPLEX,0.62,(0,0,0),4,cv2.LINE_AA)
            cv2.putText(frame,text,(12,y),cv2.FONT_HERSHEY_SIMPLEX,0.62,color,2,cv2.LINE_AA)

    def _compute_pose(self, h):
        """MediaPipe 21 landmarks -> joint-angle curl -> O6 6D pose."""
        lm=h.landmark
        pts=np.array([[p.x,p.y,p.z] for p in lm],dtype=float)
        c11=np.array([[lm[i].x,lm[i].y,lm[i].z] for i in C11_IDX],dtype=float)
        palm_center=np.mean(pts[[0,5,9,13,17]],axis=0)
        palm_scale=max(np.linalg.norm(pts[5]-pts[17]),np.linalg.norm(pts[0]-pts[9]),1e-6)

        def clamp01(v):
            return max(0.0,min(1.0,float(v)))

        def angle_at(a,b,c):
            ba=pts[a]-pts[b]
            bc=pts[c]-pts[b]
            n=np.linalg.norm(ba)*np.linalg.norm(bc)
            if n <= 1e-8:
                return math.pi
            return math.acos(max(-1.0,min(1.0,float(np.dot(ba,bc)/n))))

        def chain_len(indices):
            return sum(np.linalg.norm(pts[indices[i+1]]-pts[indices[i]]) for i in range(len(indices)-1))

        def bend_from_angle(angle, straight=2.75, bent=1.05):
            return clamp01((straight-float(angle))/(straight-bent))

        def tip_aux_curl(mcp,tip,chain):
            tip_dist=np.linalg.norm(pts[tip]-palm_center)
            mcp_dist=np.linalg.norm(pts[mcp]-palm_center)
            length=max(chain_len(chain),1e-6)
            extension=max(0.0,tip_dist-mcp_dist)/(length*0.75)
            return 1.0-clamp01(extension)

        def finger_detail(name,wrist,mcp,pip,dip,tip):
            mcp_bend=bend_from_angle(angle_at(wrist,mcp,pip),straight=2.65,bent=1.05)
            pip_bend=bend_from_angle(angle_at(mcp,pip,dip),straight=2.85,bent=1.00)
            dip_bend=bend_from_angle(angle_at(pip,dip,tip),straight=2.85,bent=1.00)
            proximal=clamp01(0.45*mcp_bend+0.55*pip_bend)
            distal=clamp01(0.55*pip_bend+0.45*dip_bend)
            tip_aux=tip_aux_curl(mcp,tip,[mcp,pip,dip,tip])
            fused=clamp01(
                FINGER_PROXIMAL_WEIGHT*proximal
                + FINGER_DISTAL_WEIGHT*distal
                + FINGER_TIP_AUX_WEIGHT*tip_aux
            )
            return {
                "mcp":mcp_bend,
                "pip":pip_bend,
                "dip":dip_bend,
                "proximal":proximal,
                "distal":distal,
                "tip_aux":tip_aux,
                "fused":fused,
            }

        fingers={
            "index":finger_detail("index",0,5,6,7,8),
            "middle":finger_detail("middle",0,9,10,11,12),
            "ring":finger_detail("ring",0,13,14,15,16),
            "little":finger_detail("little",0,17,18,19,20),
        }

        thumb_mcp_bend=bend_from_angle(angle_at(1,2,3),straight=2.55,bent=1.05)
        thumb_ip_bend=bend_from_angle(angle_at(2,3,4),straight=2.85,bent=1.00)
        thumb_bend_raw=clamp01(0.65*thumb_mcp_bend+0.35*thumb_ip_bend)
        spread_dist=np.linalg.norm(pts[4]-pts[5])/palm_scale
        thumb_swing_raw=clamp01((spread_dist-0.25)/0.85)
        thumb_swing_norm=thumb_swing_raw
        if self._thumb_open_baseline is not None and self._thumb_close_baseline is not None:
            diff=self._thumb_open_baseline-self._thumb_close_baseline
            if abs(diff)>0.02:
                thumb_swing_norm=clamp01((thumb_swing_raw-self._thumb_close_baseline)/diff)
        if self._thumb_swing_invert:
            thumb_swing_norm=1.0-thumb_swing_norm

        raw_curls=[
            thumb_bend_raw,
            fingers["index"]["fused"],
            fingers["middle"]["fused"],
            fingers["ring"]["fused"],
            fingers["little"]["fused"],
        ]

        curls=list(raw_curls)
        if self._calib_open and self._calib_close:
            for i in range(5):
                oi=self._calib_open[i]
                ci=self._calib_close[i]
                diff=ci-oi
                if abs(diff)>0.02:
                    curls[i]=(raw_curls[i]-oi)/diff
                curls[i]=clamp01(curls[i])
        if self._thumb_bend_invert:
            curls[0]=1.0-curls[0]

        def lerp(f,a,b):
            return int(a+f*(b-a))

        def clamp_int(v,lo,hi):
            return int(max(lo,min(hi,int(v))))

        def r3(v):
            return round(float(v),3)

        pose=[
            clamp_int(lerp(curls[0],OPEN_POSE[0],CLOSE_POSE[0]),THUMB_BEND_MIN,THUMB_BEND_MAX),
            clamp_int(lerp(thumb_swing_norm,CLOSE_POSE[1],OPEN_POSE[1]),THUMB_SWING_MIN,THUMB_SWING_MAX),
            clamp_int(lerp(curls[1],OPEN_POSE[2],CLOSE_POSE[2]),POSE_MIN,POSE_MAX),
            clamp_int(lerp(curls[2],OPEN_POSE[3],CLOSE_POSE[3]),POSE_MIN,POSE_MAX),
            clamp_int(lerp(curls[3],OPEN_POSE[4],CLOSE_POSE[4]),POSE_MIN,POSE_MAX),
            clamp_int(lerp(curls[4],OPEN_POSE[5],CLOSE_POSE[5]),POSE_MIN,POSE_MAX),
        ]
        for i,inv in enumerate(INVERT):
            if inv:
                pose[i]=int(OPEN_POSE[i]+CLOSE_POSE[i]-pose[i])
        pose[0]=clamp_int(pose[0],THUMB_BEND_MIN,THUMB_BEND_MAX)
        pose[1]=clamp_int(pose[1],THUMB_SWING_MIN,THUMB_SWING_MAX)
        for i in range(2,6):
            pose[i]=clamp_int(pose[i],POSE_MIN,POSE_MAX)

        debug={
            "palm_scale":round(float(palm_scale),4),
            "control11":c11.tolist(),
            "raw_curls":[r3(v) for v in raw_curls],
            "curls":[r3(v) for v in curls],
            "thumb_spread":r3(thumb_swing_norm),
            "thumb":{
                "bend_raw":r3(thumb_bend_raw),
                "bend_calibrated":r3(curls[0]),
                "bend_mapped":pose[0],
                "swing_raw":r3(thumb_swing_raw),
                "swing_norm":r3(thumb_swing_norm),
                "swing_mapped":pose[1],
                "swing_invert":bool(self._thumb_swing_invert),
                "bend_invert":bool(self._thumb_bend_invert),
                "swing_open_baseline":self._thumb_open_baseline,
                "swing_close_baseline":self._thumb_close_baseline,
                "spread_dist":r3(spread_dist),
            },
            "fingers":{
                name:{k:r3(v) for k,v in detail.items() if isinstance(v,(int,float))}
                for name,detail in fingers.items()
            },
            "calibrated":bool(self._calib_open and self._calib_close),
        }
        return pose, debug

# ── 视觉模仿页面 ──────────────────────────────────────────────
class VisionPage(QFrame):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName("VisionPage")
        self._worker=None; self._state="unstarted"
        self._hw_enabled=False
        self._ema_pose=None; self._last_sent=None; self._last_sent_t=0
        self._ema_alpha=EMA_ALPHA; self._deadband=DEADBAND; self._emit_iv=SEND_INTERVAL
        self._max_delta=[MAX_STEP_FINGER,MAX_STEP_THUMB_SWING,MAX_STEP_FINGER,MAX_STEP_FINGER,MAX_STEP_FINGER,MAX_STEP_FINGER]
        self._sent_cnt=0; self._skip_cnt=0
        self._calib_open=None; self._calib_close=None
        self._thumb_open_baseline=None; self._thumb_close_baseline=None
        self._thumb_swing_invert=THUMB_SWING_INVERT_DEFAULT
        self._thumb_bend_invert=THUMB_BEND_INVERT
        self._last_dbg=None; self._last_has_hand=False; self._last_curls=None
        self._last_no_hand_log_t=0.0
        self._start_t=0.0
        self._recording=False
        self._record_frames=[]
        self._record_started_t=0.0
        self._last_record_t=0.0
        self._last_record_pose=None
        self._record_skip_log_t=0.0
        self._record_file_path=""
        self._playing=False
        self._playback_paused=False
        self._playback_idx=0
        self._playback_speed=1.0
        self._playback_loop=False
        self._playback_last_sent=None
        self._last_playback_pose=None
        self._live_emit_blocked_by_playback=False
        self._playback_timer=QTimer(self); self._playback_timer.setSingleShot(True)
        self._playback_timer.timeout.connect(self._playback_tick)
        self._opening_timer=QTimer(self); self._opening_timer.setSingleShot(True)
        self._opening_timer.timeout.connect(self._on_opening_timeout)
        self._build_ui(); self._wire()
        self._set_state("unstarted")

    # ── 统一卡片工厂 ──
    @staticmethod
    def _section_card(title_text):
        card = QFrame()
        card.setObjectName("VisionSectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        title_lbl = QLabel(title_text)
        title_lbl.setObjectName("CardTitle")
        layout.addWidget(title_lbl)
        return card, layout

    def _build_ui(self):
        from PyQt5.QtWidgets import QScrollArea
        main = QHBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(12)

        # ═══ 左侧: 摄像头主区域 (现代大卡片化) ═══
        left_card = QFrame()
        left_card.setObjectName("VisionLeftCard")
        ll = QVBoxLayout(left_card)
        ll.setContentsMargins(16, 16, 16, 16)
        ll.setSpacing(12)

        # 左侧 Header
        left_header = QHBoxLayout()
        left_header.setContentsMargins(0, 0, 0, 0)
        left_header.setSpacing(8)
        left_title = QLabel("视觉识别")
        left_title.setObjectName("CardTitle")
        left_header.addWidget(left_title)
        left_header.addStretch()
        self.cam_status_lbl = QLabel("等待启动")
        self.cam_status_lbl.setStyleSheet("color:#64748B; font-size:11px;")
        left_header.addWidget(self.cam_status_lbl)
        ll.addLayout(left_header)

        # 摄像头预览区 (白卡片包裹深色画面，精致圆角)
        preview_card = QFrame()
        preview_card.setObjectName("CameraPreviewCard")
        pv = QVBoxLayout(preview_card)
        pv.setContentsMargins(8, 8, 8, 8)
        self.cam_view = QLabel()
        self.cam_view.setMinimumSize(480, 360)
        self.cam_view.setAlignment(Qt.AlignCenter)
        self.cam_view.setStyleSheet("background:#1E1E2E; border-radius:8px; color:#64748B; font-size:13px;")
        self.cam_view.setText("等待启动")
        pv.addWidget(self.cam_view, stretch=1)
        ll.addWidget(preview_card, stretch=1)

        # 底部控制条 (开始/停止/复位)
        left_ctrl = QHBoxLayout()
        left_ctrl.setContentsMargins(0, 4, 0, 0)
        left_ctrl.setSpacing(10)
        self.btn_start = QPushButton("开始模仿")
        self.btn_start.setProperty("category", "primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedHeight(34)
        left_ctrl.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("停止模仿")
        self.btn_stop.setProperty("category", "danger")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setFixedHeight(34)
        left_ctrl.addWidget(self.btn_stop)
        
        self.btn_home = QPushButton("复位")
        self.btn_home.setProperty("category", "secondary")
        self.btn_home.setCursor(Qt.PointingHandCursor)
        self.btn_home.setFixedHeight(34)
        left_ctrl.addWidget(self.btn_home)
        left_ctrl.addStretch()
        ll.addLayout(left_ctrl)

        main.addWidget(left_card, stretch=3)

        # ═══ 右侧: 卡片式控制面板 (可滚动) ═══
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setStyleSheet("background:transparent; border:none;")

        right_content = QWidget()
        right_content.setStyleSheet("background:transparent;")
        right = QVBoxLayout(right_content)
        right.setContentsMargins(0, 0, 4, 0)
        right.setSpacing(12)
        right_scroll.setWidget(right_content)

        # ── Card 1: MimicControlCard ──
        card1, c1 = self._section_card("模仿控制")
        
        self.chk_hw = QCheckBox("允许下发到机械手")
        self.chk_hw.setChecked(False)
        self.chk_hw.toggled.connect(self._on_hw_toggled)
        self.chk_hw.setStyleSheet("font-weight: 500; font-size: 12px; margin-bottom: 4px;")
        c1.addWidget(self.chk_hw)

        cal_grid = QGridLayout()
        cal_grid.setSpacing(8)
        self.btn_cal_open = QPushButton("校准张开")
        self.btn_cal_open.setProperty("category", "secondary")
        self.btn_cal_close = QPushButton("校准握拳")
        self.btn_cal_close.setProperty("category", "secondary")
        self.btn_test_open = QPushButton("测试张开")
        self.btn_test_open.setProperty("category", "secondary")
        self.btn_test_close = QPushButton("测试握拳")
        self.btn_test_close.setProperty("category", "secondary")
        
        for btn in [self.btn_cal_open, self.btn_cal_close, self.btn_test_open, self.btn_test_close]:
            btn.setFixedHeight(30)
            btn.setCursor(Qt.PointingHandCursor)
            
        cal_grid.addWidget(self.btn_cal_open, 0, 0)
        cal_grid.addWidget(self.btn_cal_close, 0, 1)
        cal_grid.addWidget(self.btn_test_open, 1, 0)
        cal_grid.addWidget(self.btn_test_close, 1, 1)
        c1.addLayout(cal_grid)
        right.addWidget(card1)

        # ── Card 2: GestureMappingCard ──
        card2, c2 = self._section_card("手势映射")

        # 拇指行
        thumb_lbl = QLabel("拇指校准")
        thumb_lbl.setStyleSheet("color:#64748B; font-size:11px; font-weight:600; margin-top:4px;")
        c2.addWidget(thumb_lbl)
        
        thumb_btn_row = QHBoxLayout()
        thumb_btn_row.setSpacing(8)
        self.btn_cal_thumb_open = QPushButton("Cal thumb out")
        self.btn_cal_thumb_open.setProperty("category", "secondary")
        self.btn_cal_thumb_open.setFixedHeight(28)
        self.btn_cal_thumb_open.setCursor(Qt.PointingHandCursor)
        self.btn_cal_thumb_close = QPushButton("Cal thumb in")
        self.btn_cal_thumb_close.setProperty("category", "secondary")
        self.btn_cal_thumb_close.setFixedHeight(28)
        self.btn_cal_thumb_close.setCursor(Qt.PointingHandCursor)
        
        thumb_btn_row.addWidget(self.btn_cal_thumb_open)
        thumb_btn_row.addWidget(self.btn_cal_thumb_close)
        thumb_btn_row.addStretch()
        c2.addLayout(thumb_btn_row)

        # 手指测试
        finger_lbl = QLabel("手指单步测试")
        finger_lbl.setStyleSheet("color:#64748B; font-size:11px; font-weight:600; margin-top:6px;")
        c2.addWidget(finger_lbl)
        
        finger_grid = QGridLayout()
        finger_grid.setSpacing(6)
        finger_btns = [
            ("T bend", lambda: self._send_o6_test_pose("thumb_bend", [CLOSE_POSE[0],OPEN_POSE[1],OPEN_POSE[2],OPEN_POSE[3],OPEN_POSE[4],OPEN_POSE[5]])),
            ("T swing", lambda: self._send_o6_test_pose("thumb_swing", [OPEN_POSE[0],CLOSE_POSE[1],OPEN_POSE[2],OPEN_POSE[3],OPEN_POSE[4],OPEN_POSE[5]])),
            ("Index", lambda: self._send_o6_test_pose("index", [OPEN_POSE[0],OPEN_POSE[1],CLOSE_POSE[2],OPEN_POSE[3],OPEN_POSE[4],OPEN_POSE[5]])),
            ("Middle", lambda: self._send_o6_test_pose("middle", [OPEN_POSE[0],OPEN_POSE[1],OPEN_POSE[2],CLOSE_POSE[3],OPEN_POSE[4],OPEN_POSE[5]])),
            ("Ring", lambda: self._send_o6_test_pose("ring", [OPEN_POSE[0],OPEN_POSE[1],OPEN_POSE[2],OPEN_POSE[3],CLOSE_POSE[4],OPEN_POSE[5]])),
            ("Little", lambda: self._send_o6_test_pose("little", [OPEN_POSE[0],OPEN_POSE[1],OPEN_POSE[2],OPEN_POSE[3],OPEN_POSE[4],CLOSE_POSE[5]])),
        ]
        self._finger_test_btns = {}
        for idx, (label, cb) in enumerate(finger_btns):
            btn = QPushButton(label)
            btn.setProperty("category", "tool")
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(cb)
            finger_grid.addWidget(btn, idx // 3, idx % 3)
            self._finger_test_btns[label] = btn
        c2.addLayout(finger_grid)

        # 反向设置
        invert_lbl = QLabel("防抖与反转设置")
        invert_lbl.setStyleSheet("color:#64748B; font-size:11px; font-weight:600; margin-top:6px;")
        c2.addWidget(invert_lbl)
        
        invert_row = QHBoxLayout()
        invert_row.setSpacing(12)
        self.chk_thumb_bend_invert = QCheckBox("Invert bend")
        self.chk_thumb_bend_invert.setChecked(self._thumb_bend_invert)
        self.chk_thumb_bend_invert.toggled.connect(self._on_thumb_bend_invert_toggled)
        self.chk_thumb_invert = QCheckBox("Invert swing")
        self.chk_thumb_invert.setChecked(self._thumb_swing_invert)
        self.chk_thumb_invert.toggled.connect(self._on_thumb_invert_toggled)
        invert_row.addWidget(self.chk_thumb_bend_invert)
        invert_row.addWidget(self.chk_thumb_invert)
        invert_row.addStretch()
        c2.addLayout(invert_row)
        right.addWidget(card2)

        # ── Card 3: TuningCard ──
        card3, c3 = self._section_card("高级参数")
        tune_grid = QGridLayout()
        tune_grid.setSpacing(8)
        self.spin_ema = QDoubleSpinBox(); self.spin_ema.setRange(0.05, 0.95); self.spin_ema.setSingleStep(0.05); self.spin_ema.setDecimals(2); self.spin_ema.setValue(self._ema_alpha); self.spin_ema.valueChanged.connect(self._on_tuning_changed)
        self.spin_db = QSpinBox(); self.spin_db.setRange(0, 30); self.spin_db.setValue(self._deadband); self.spin_db.valueChanged.connect(self._on_tuning_changed)
        self.spin_iv = QDoubleSpinBox(); self.spin_iv.setRange(0.03, 0.50); self.spin_iv.setSingleStep(0.01); self.spin_iv.setDecimals(2); self.spin_iv.setValue(self._emit_iv); self.spin_iv.valueChanged.connect(self._on_tuning_changed)
        self.spin_fs = QSpinBox(); self.spin_fs.setRange(1, 80); self.spin_fs.setValue(MAX_STEP_FINGER); self.spin_fs.valueChanged.connect(self._on_tuning_changed)
        self.spin_ts = QSpinBox(); self.spin_ts.setRange(1, 80); self.spin_ts.setValue(MAX_STEP_THUMB_SWING); self.spin_ts.valueChanged.connect(self._on_tuning_changed)
        
        for spin in [self.spin_ema, self.spin_db, self.spin_iv, self.spin_fs, self.spin_ts]:
            spin.setFixedHeight(28)
            
        params = [("EMA", self.spin_ema), ("DB", self.spin_db), ("IV", self.spin_iv), ("Fstep", self.spin_fs), ("Tstep", self.spin_ts)]
        for i, (name, spin) in enumerate(params):
            lbl = QLabel(name)
            lbl.setStyleSheet("color:#64748B; font-size:11px; font-weight:600;")
            tune_grid.addWidget(lbl, i // 2, (i % 2) * 2)
            tune_grid.addWidget(spin, i // 2, (i % 2) * 2 + 1)
        c3.addLayout(tune_grid)
        right.addWidget(card3)

        # ── Card 4: StatusLogCard ──
        card4, c4 = self._section_card("识别状态")
        summary_widget = QFrame()
        summary_widget.setObjectName("ParamBlock")
        summary_layout = QHBoxLayout(summary_widget)
        summary_layout.setContentsMargins(10, 6, 10, 6)
        summary_layout.setSpacing(12)
        
        self.d_hand = QLabel("手势: 等待")
        self.d_hand.setStyleSheet("color:#4F7FF7; font-size:11px; font-weight:600;")
        self.d_hw = QLabel("下发: 未启用")
        self.d_hw.setStyleSheet("color:#E5484D; font-size:11px; font-weight:600;")
        self.d_freq = QLabel("freq: --")
        self.d_freq.setStyleSheet("color:#64748B; font-size:11px; font-weight:600;")
        summary_layout.addWidget(self.d_hand)
        summary_layout.addWidget(self.d_hw)
        summary_layout.addWidget(self.d_freq)
        summary_layout.addStretch()
        c4.addWidget(summary_widget)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(90)
        self.log_view.setStyleSheet("""
            QTextEdit { background:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px;
                padding:6px; font-family:Consolas,monospace; font-size:10px; color:#475569; }
        """)
        self._log_lines = []
        c4.addWidget(self.log_view)
        right.addWidget(card4)

        # ── Card 5: RecorderPlaybackCard ──
        card5, c5 = self._section_card("录制与回放")

        # 1. 录制组
        rec_title = QLabel("动作录制")
        rec_title.setStyleSheet("color:#64748B; font-size:10px; font-weight:600; margin-top:2px;")
        c5.addWidget(rec_title)
        
        rec_row = QHBoxLayout()
        rec_row.setSpacing(6)
        self.btn_record_start = QPushButton("开始录制")
        self.btn_record_start.setProperty("category", "secondary")
        self.btn_record_stop = QPushButton("停止录制")
        self.btn_record_stop.setProperty("category", "danger")
        self.btn_record_clear = QPushButton("清空")
        self.btn_record_clear.setProperty("category", "tool")
        
        for btn in [self.btn_record_start, self.btn_record_stop, self.btn_record_clear]:
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            rec_row.addWidget(btn)
        rec_row.addStretch()
        c5.addLayout(rec_row)

        # 2. 文件与保存组
        file_title = QLabel("文件保存")
        file_title.setStyleSheet("color:#64748B; font-size:10px; font-weight:600; margin-top:4px;")
        c5.addWidget(file_title)
        
        file_row = QHBoxLayout()
        file_row.setSpacing(6)
        self.btn_record_save = QPushButton("保存录制")
        self.btn_record_save.setProperty("category", "secondary")
        self.btn_record_load = QPushButton("加载录制")
        self.btn_record_load.setProperty("category", "secondary")
        
        for btn in [self.btn_record_save, self.btn_record_load]:
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            file_row.addWidget(btn)
        file_row.addStretch()
        c5.addLayout(file_row)

        # 3. 回放控制组
        play_title = QLabel("动作回放")
        play_title.setStyleSheet("color:#64748B; font-size:10px; font-weight:600; margin-top:4px;")
        c5.addWidget(play_title)
        
        play_row = QHBoxLayout()
        play_row.setSpacing(6)
        self.btn_play_start = QPushButton("开始回放")
        self.btn_play_start.setProperty("category", "primary")
        self.btn_play_pause = QPushButton("暂停回放")
        self.btn_play_pause.setProperty("category", "warning")
        self.btn_play_stop = QPushButton("停止回放")
        self.btn_play_stop.setProperty("category", "danger")
        
        for btn in [self.btn_play_start, self.btn_play_pause, self.btn_play_stop]:
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            play_row.addWidget(btn)
        play_row.addStretch()
        c5.addLayout(play_row)

        # 选项行
        opts_row = QHBoxLayout()
        opts_row.setSpacing(10)
        self.chk_play_loop = QCheckBox("循环回放")
        self.chk_play_loop.toggled.connect(lambda checked: setattr(self, "_playback_loop", bool(checked)))
        self.cmb_play_speed = QComboBox()
        self.cmb_play_speed.addItems(PLAYBACK_SPEEDS)
        self.cmb_play_speed.setCurrentText("1.0x")
        self.cmb_play_speed.currentTextChanged.connect(self._on_playback_speed_changed)
        self.cmb_play_speed.setFixedHeight(26)
        
        opts_row.addWidget(self.chk_play_loop)
        speed_lbl = QLabel("速度")
        speed_lbl.setStyleSheet("color:#64748B; font-size:11px;")
        opts_row.addWidget(speed_lbl)
        opts_row.addWidget(self.cmb_play_speed)
        opts_row.addStretch()
        c5.addLayout(opts_row)

        # 状态摘要行 (轻量化气泡)
        self.d_rec_state = QLabel("录制: 未录制")
        self.d_rec_state.setStyleSheet("color:#64748B; font-size:11px; font-weight:500;")
        self.d_play_state = QLabel("回放: 未回放")
        self.d_play_state.setStyleSheet("color:#64748B; font-size:11px; font-weight:500;")
        
        status_widget = QFrame()
        status_widget.setObjectName("ParamBlock")
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(8, 4, 8, 4)
        status_layout.setSpacing(12)
        status_layout.addWidget(self.d_rec_state)
        status_layout.addWidget(self.d_play_state)
        status_layout.addStretch()
        c5.addWidget(status_widget)

        right.addWidget(card5)
        right.addStretch()
        main.addWidget(right_scroll, stretch=2)

        # ── 保留旧版属性供业务逻辑引用（不可删除！）──
        self.d_status = QLabel("状态: 等待启动")
        self.d_c11 = QLabel("11点: 等待")
        self.d_tuning = QLabel(self._tuning_text())
        self.d_range = QLabel("range: O6 6D TB/TS/I/M/R/L 0-255")
        self.d_o6_mode = QLabel("mode: O6 finger_move 6D only")
        self.d_curl = QLabel("curl: --")
        self.d_thumb = QLabel("thumb: --")
        self.d_index = QLabel("index: --")
        self.d_middle = QLabel("middle: --")
        self.d_ring = QLabel("ring: --")
        self.d_little = QLabel("little: --")
        self.d_pose_raw = QLabel("raw pose: --")
        self.d_pose_ema = QLabel("ema pose: --")
        self.d_similarity = QLabel("similarity: --")
        self.d_errors = QLabel("errors: --")
        self.d_pose_sent = QLabel("sent: --")
        self.d_last_test = QLabel("last test: --")
        self.d_record_params = QLabel("params: --")
        self.d_play_options = QLabel("playback opts: --")
        self.d_play_live = QLabel("live block: no")
        self.d_play_pose = QLabel("playback pose: --")
        self.d_play_pose.setStyleSheet("color:#1E293B; font-size:11px; font-weight:500;")
        self.d_rec_frames = QLabel("录制帧数: 0")
        self.d_rec_frames.setStyleSheet("color:#1E293B; font-size:11px; font-weight:500;")
        self.d_rec_duration = QLabel("录制时长: 0.00s")
        self.d_rec_duration.setStyleSheet("color:#1E293B; font-size:11px; font-weight:500;")
        self.d_play_progress = QLabel("回放进度: 0%")
        self.d_play_progress.setStyleSheet("color:#1E293B; font-size:11px; font-weight:500;")
        self.d_play_frame = QLabel("回放帧: 0/0")
        self.d_play_frame.setStyleSheet("color:#1E293B; font-size:11px; font-weight:500;")
        self.d_record_file = QLabel("文件: --")
        self.d_record_file.setStyleSheet("color:#1E293B; font-size:11px; font-weight:500;")
        self.d_record_error = QLabel("错误: --")
        self.d_record_error.setStyleSheet("color:#E5484D; font-size:11px; font-weight:500;")

    def _lbl_title(self,t):
        l=QLabel(t); l.setObjectName("CardTitle"); return l
    def _d(self,t,c="#64748B"):
        l=QLabel(t); l.setStyleSheet(f"color:{c};font-size:11px;font-family:monospace;font-weight:500;"); return l
    def _btn(self,text,category="secondary",fs=10):
        b=QPushButton(text); b.setProperty("category",category); return b

    def _tuning_text(self):
        return f"tuning: ema={self._ema_alpha:.2f} deadband={self._deadband} interval={self._emit_iv:.2f}s step={self._max_delta}"

    def _sync_tuning_label(self):
        # 保留兼容性 — 不再更新单独的 label
        pass

    def _wire(self):
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop_page)
        self.btn_home.clicked.connect(self._go_home)
        # Calibration buttons
        self.btn_cal_open.clicked.connect(self._calibrate_open)
        self.btn_cal_close.clicked.connect(self._calibrate_close)
        self.btn_cal_thumb_open.clicked.connect(self._calibrate_thumb_open)
        self.btn_cal_thumb_close.clicked.connect(self._calibrate_thumb_close)
        self.chk_thumb_bend_invert.toggled.connect(self._on_thumb_bend_invert_toggled)
        self.chk_thumb_invert.toggled.connect(self._on_thumb_invert_toggled)
        # Test buttons
        self.btn_test_open.clicked.connect(lambda: self._send_o6_test_pose("open", OPEN_POSE))
        self.btn_test_close.clicked.connect(lambda: self._send_o6_test_pose("fist", CLOSE_POSE))
        # Recording & Playback
        self.btn_record_start.clicked.connect(self._start_recording)
        self.btn_record_stop.clicked.connect(self._stop_recording)
        self.btn_record_clear.clicked.connect(self._clear_recording)
        self.btn_record_save.clicked.connect(self._save_recording)
        self.btn_record_load.clicked.connect(self._load_recording)
        self.btn_play_start.clicked.connect(self._start_playback)
        self.btn_play_pause.clicked.connect(self._toggle_playback_pause)
        self.btn_play_stop.clicked.connect(self._stop_playback)
        self.chk_play_loop.toggled.connect(lambda checked: setattr(self,"_playback_loop",bool(checked)))
        self.cmb_play_speed.currentTextChanged.connect(self._on_playback_speed_changed)
        self.spin_ema.valueChanged.connect(self._on_tuning_changed)
        self.spin_db.valueChanged.connect(self._on_tuning_changed)
        self.spin_iv.valueChanged.connect(self._on_tuning_changed)
        self.spin_fs.valueChanged.connect(self._on_tuning_changed)
        self.spin_ts.valueChanged.connect(self._on_tuning_changed)

    def _on_tuning_changed(self,*_):
        self._ema_alpha=float(self.spin_ema.value())
        self._deadband=int(self.spin_db.value())
        self._emit_iv=float(self.spin_iv.value())
        finger_step=int(self.spin_fs.value())
        thumb_step=int(self.spin_ts.value())
        self._max_delta=[finger_step,thumb_step,finger_step,finger_step,finger_step,finger_step]
        _jlog(self._tuning_text())

    def _on_hw_toggled(self,checked):
        if checked:
            reply=QMessageBox.question(self,"确认启用实时同步",
                "请确认：\n1. 机械手已上电\n2. CAN 已连接\n3. 右上角状态为「已连接」\n\n是否启用实时同步？",
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if reply!=QMessageBox.Yes:
                self.chk_hw.blockSignals(True); self.chk_hw.setChecked(False); self.chk_hw.blockSignals(False)
                return
        self._hw_enabled=checked
        if checked:
            self.d_hw.setText("下发: 已启用 (~8Hz)"); self.d_hw.setStyleSheet("color:#22A06B; font-size:11px; font-weight:600;")
            _vlog("hardware ENABLED")
        else:
            self.d_hw.setText("下发: 未启用"); self.d_hw.setStyleSheet("color:#E5484D; font-size:11px; font-weight:600;")
            _vlog("hardware DISABLED")

    def _safe_emit(self,pose,tag=""):
        pose=self._sanitize_pose(pose)
        if pose is None:
            self.d_status.setText("状态: invalid O6 pose, skipped")
            _jlog(f"invalid pose skipped tag={tag or 'live'}")
            return False
        if not self._hw_enabled:
            self.d_status.setText("状态: hardware output disabled, pose not sent")
            _vlog("hardware disabled, pose not sent")
            _jlog(f"hardware disabled, pose not sent tag={tag or 'live'} pose={pose}")
            return False
        try:
            signal_bus.finger_move_requested.emit(pose)
            _vlog(f"emit finger_move_requested ok tag={tag or 'live'} pose={pose}")
            _jlog(f"emit ok tag={tag or 'live'} pose={pose}")
            self.d_pose_sent.setText(f"sent: {pose} ({tag})")
            self._last_sent=list(pose); self._last_sent_t=time.time()
            return True
        except Exception as e:
            self.d_status.setText(f"状态: emit 失败 {e}")
            _vlog(f"emit finger_move_requested failed: {e}")
            _jlog(f"emit failed tag={tag or 'live'} err={e}")
            return False

    def _send_o6_test_pose(self, name, pose):
        safe=self._sanitize_pose(pose)
        if safe is None:
            self.d_last_test.setText(f"last test: {name} invalid")
            self.d_status.setText("状态: invalid O6 test pose")
            _jlog(f"O6 test invalid name={name} pose={pose}")
            return False
        ok=self._safe_emit(safe,f"test_{name}")
        if ok:
            self.d_last_test.setText(f"last test: {name} {safe}")
            self.d_status.setText(f"状态: O6 test sent {name}")
        else:
            self.d_last_test.setText(f"last test: {name} blocked {safe}")
        return ok

    # ── 校准 ──
    def _calibrate_open(self):
        if self._state!="running":
            self.d_status.setText("状态: 请先开始模仿再校准张开")
            return
        _,dbg=self._compute_current()
        raw=dbg.get("raw_curls",[]) if dbg else []
        if self._last_has_hand and len(raw) == 5:
            self._calib_open=list(raw)
            if self._worker: self._worker.set_calibration(self._calib_open,self._calib_close)
            self.d_status.setText("状态: 已校准张开")
            self._check_calibration_spacing()
            _vlog(f"calib OPEN: {self._calib_open}")
        else:
            self.d_status.setText("状态: 未检测到有效手势，不能校准张开")

    def _calibrate_close(self):
        if self._state!="running":
            self.d_status.setText("状态: 请先开始模仿再校准握拳")
            return
        _,dbg=self._compute_current()
        raw=dbg.get("raw_curls",[]) if dbg else []
        if self._last_has_hand and len(raw) == 5:
            self._calib_close=list(raw)
            if self._worker: self._worker.set_calibration(self._calib_open,self._calib_close)
            self.d_status.setText("状态: 已校准握拳")
            self._check_calibration_spacing()
            _vlog(f"calib CLOSE: {self._calib_close}")
        else:
            self.d_status.setText("状态: 未检测到有效手势，不能校准握拳")

    def _check_calibration_spacing(self):
        if not (self._calib_open and self._calib_close):
            return
        names=["thumb_bend","index","middle","ring","little"]
        close_dims=[]
        for i,name in enumerate(names):
            if i >= len(self._calib_open) or i >= len(self._calib_close):
                continue
            if abs(float(self._calib_close[i])-float(self._calib_open[i])) <= 0.02:
                close_dims.append(name)
        if close_dims:
            msg="calibration warning: open/fist baselines too close for " + ",".join(close_dims)
            self.d_status.setText("状态: " + msg)
            _jlog(msg)

    def _apply_thumb_config(self):
        if self._worker:
            self._worker.set_thumb_config(
                self._thumb_open_baseline,
                self._thumb_close_baseline,
                self._thumb_swing_invert,
                self._thumb_bend_invert,
            )

    def _current_thumb_swing_raw(self):
        _,dbg=self._compute_current()
        thumb=dbg.get("thumb",{}) if dbg else {}
        raw=thumb.get("swing_raw")
        return raw if isinstance(raw,(int,float)) else None

    def _calibrate_thumb_open(self):
        if self._state!="running":
            self.d_status.setText("status: start imitation before thumb-out calibration")
            return
        raw=self._current_thumb_swing_raw()
        if self._last_has_hand and raw is not None:
            self._thumb_open_baseline=float(raw)
            self._apply_thumb_config()
            self.d_status.setText(f"status: thumb out calibrated raw={raw:.3f}")
            _jlog(f"thumb swing open baseline={raw:.3f}")
            self._check_thumb_spacing()
        else:
            self.d_status.setText("status: no valid hand for thumb-out calibration")

    def _calibrate_thumb_close(self):
        if self._state!="running":
            self.d_status.setText("status: start imitation before thumb-in calibration")
            return
        raw=self._current_thumb_swing_raw()
        if self._last_has_hand and raw is not None:
            self._thumb_close_baseline=float(raw)
            self._apply_thumb_config()
            self.d_status.setText(f"status: thumb in calibrated raw={raw:.3f}")
            _jlog(f"thumb swing close baseline={raw:.3f}")
            self._check_thumb_spacing()
        else:
            self.d_status.setText("status: no valid hand for thumb-in calibration")

    def _check_thumb_spacing(self):
        if self._thumb_open_baseline is None or self._thumb_close_baseline is None:
            return
        diff=abs(float(self._thumb_open_baseline)-float(self._thumb_close_baseline))
        if diff <= 0.02:
            self.d_status.setText("status: thumb swing out/in baselines too close")
            _jlog(f"thumb swing calibration warning diff={diff:.3f}")

    def _on_thumb_invert_toggled(self,checked):
        self._thumb_swing_invert=bool(checked)
        self._apply_thumb_config()
        _jlog(f"thumb swing invert={self._thumb_swing_invert}")

    def _on_thumb_bend_invert_toggled(self,checked):
        self._thumb_bend_invert=bool(checked)
        self._apply_thumb_config()
        _jlog(f"thumb bend invert={self._thumb_bend_invert}")

    def _compute_current(self):
        """从最后缓存的 debug 读取当前 curl。"""
        if hasattr(self,'_last_dbg') and self._last_dbg:
            return None, self._last_dbg
        return None, None

    def _sanitize_pose(self, pose):
        if not isinstance(pose,(list,tuple)) or len(pose) != 6:
            return None
        safe=[]
        for value in pose:
            try:
                safe.append(int(max(POSE_MIN,min(POSE_MAX,round(float(value))))))
            except Exception:
                return None
        return safe

    def _strict_pose(self, pose):
        if not isinstance(pose,(list,tuple)) or len(pose) != 6:
            return None
        safe=[]
        for value in pose:
            try:
                number=float(value)
            except Exception:
                return None
            rounded=round(number)
            if abs(number-rounded) > 1e-6 or rounded < POSE_MIN or rounded > POSE_MAX:
                return None
            safe.append(int(rounded))
        return safe

    def _norm01(self, value):
        try:
            return max(0.0,min(1.0,float(value)))
        except Exception:
            return 0.0

    def _pose_axis_drive(self, value, open_value, close_value):
        denom=float(close_value)-float(open_value)
        if abs(denom) < 1e-6:
            return 0.0
        return self._norm01((float(value)-float(open_value))/denom)

    def _pose_axis_spread(self, value, closed_value, open_value):
        denom=float(open_value)-float(closed_value)
        if abs(denom) < 1e-6:
            return 0.0
        return self._norm01((float(value)-float(closed_value))/denom)

    def _human_drive_from_debug(self, debug):
        curls=debug.get("curls",[]) if debug else []
        thumb=debug.get("thumb",{}) if debug else {}
        if not isinstance(curls,(list,tuple)) or len(curls) != 5:
            return None
        return [
            self._norm01(curls[0]),
            self._norm01(thumb.get("swing_norm",debug.get("thumb_spread",0.0))),
            self._norm01(curls[1]),
            self._norm01(curls[2]),
            self._norm01(curls[3]),
            self._norm01(curls[4]),
        ]

    def _robot_drive_from_pose(self, pose):
        safe=self._sanitize_pose(pose)
        if safe is None:
            return None
        return [
            self._pose_axis_drive(safe[0],OPEN_POSE[0],CLOSE_POSE[0]),
            self._pose_axis_spread(safe[1],CLOSE_POSE[1],OPEN_POSE[1]),
            self._pose_axis_drive(safe[2],OPEN_POSE[2],CLOSE_POSE[2]),
            self._pose_axis_drive(safe[3],OPEN_POSE[3],CLOSE_POSE[3]),
            self._pose_axis_drive(safe[4],OPEN_POSE[4],CLOSE_POSE[4]),
            self._pose_axis_drive(safe[5],OPEN_POSE[5],CLOSE_POSE[5]),
        ]

    def _compute_similarity(self, pose, debug):
        human=self._human_drive_from_debug(debug)
        robot=self._robot_drive_from_pose(pose)
        if not human or not robot:
            return None, None
        errors=[abs(human[i]-robot[i]) for i in range(6)]
        score=max(0.0,min(1.0,1.0-(sum(errors)/len(errors))))*100.0
        return score, errors

    def _pose_delta(self, a, b):
        pose_a=self._sanitize_pose(a)
        pose_b=self._sanitize_pose(b)
        if pose_a is None or pose_b is None:
            return None
        return max(abs(pose_a[i]-pose_b[i]) for i in range(6))

    def _should_record_pose(self, pose, now):
        if not self._recording or self._playing:
            return False
        if MAX_RECORD_DURATION and now-self._record_started_t > MAX_RECORD_DURATION:
            self._set_record_error(f"record max duration reached ({MAX_RECORD_DURATION:.0f}s)")
            _glog("record stop: max duration reached")
            self._stop_recording()
            return False
        if self._last_record_t and now-self._last_record_t < RECORD_INTERVAL:
            return False
        if self._last_record_pose is None:
            return True
        delta=self._pose_delta(self._last_record_pose,pose)
        if delta is None:
            return False
        if delta < MIN_RECORD_POSE_DELTA and now-self._last_record_t < RECORD_KEEPALIVE_INTERVAL:
            if now-self._record_skip_log_t >= 1.0:
                _glog(f"frame skipped duplicate delta={delta}")
                self._record_skip_log_t=now
            return False
        return True

    def _update_record_buttons(self):
        has_frames=bool(self._record_frames)
        self.btn_record_start.setEnabled(not self._recording and not self._playing)
        self.btn_record_stop.setEnabled(self._recording)
        self.btn_record_clear.setEnabled(has_frames or self._recording or self._playing)
        self.btn_record_save.setEnabled(has_frames and not self._recording)
        self.btn_record_load.setEnabled(not self._recording and not self._playing)
        self.btn_play_start.setEnabled(has_frames and not self._recording and not self._playing)
        self.btn_play_pause.setEnabled(self._playing)
        self.btn_play_stop.setEnabled(self._playing or self._playback_paused)

    def _set_record_error(self, text):
        self.d_record_error.setText(f"错误: {text or '--'}")

    def _recording_duration(self):
        if self._recording:
            return max(0.0,time.time()-self._record_started_t)
        if self._record_frames:
            return float(self._record_frames[-1].get("t",0.0))
        return 0.0

    def _update_record_ui(self):
        if self._recording:
            state="录制中"
        elif self._record_frames:
            state="已停止"
        else:
            state="未录制"
        self.d_rec_state.setText(f"录制: {state}")
        self.d_rec_frames.setText(f"录制帧数: {len(self._record_frames)}")
        self.d_rec_duration.setText(f"录制时长: {self._recording_duration():.2f}s")
        filename=os.path.basename(self._record_file_path) if self._record_file_path else "--"
        self.d_record_file.setText(f"文件: {filename}")
        self.d_record_params.setText(
            f"params: rec={RECORD_INTERVAL:.2f}s emit={SEND_INTERVAL:.2f}s "
            f"ema={EMA_ALPHA:.2f} db={DEADBAND} delta={MIN_RECORD_POSE_DELTA}"
        )
        self._update_playback_ui()

    def _update_playback_ui(self):
        total=len(self._record_frames)
        idx=min(self._playback_idx,total)
        percent=int((idx/max(total,1))*100) if total else 0
        if self._playing and self._playback_paused:
            state="暂停"
        elif self._playing:
            state="回放中"
        elif total and idx >= total:
            state="已结束"
        else:
            state="未回放"
        self.d_play_state.setText(f"回放: {state}")
        self.d_play_progress.setText(f"回放进度: {percent}%")
        self.d_play_frame.setText(f"回放帧: {idx}/{total}")

        self.d_play_options.setText(
            f"playback opts: speed={self._playback_speed:.1f}x "
            f"loop={'yes' if self._playback_loop else 'no'} step={MAX_REPLAY_STEP} "
            f"interval={MIN_PLAYBACK_INTERVAL:.2f}-{MAX_PLAYBACK_INTERVAL:.2f}s"
        )
        self.d_play_live.setText(f"live block: {'yes' if self._live_emit_blocked_by_playback else 'no'}")
        self.d_play_pose.setText(f"playback pose: {self._last_playback_pose if self._last_playback_pose else '--'}")
        self._update_record_buttons()

    def _start_recording(self):
        if self._playing:
            self._set_record_error("回放中不能录制")
            _glog("record start blocked: playback active")
            return
        if self._state != "running":
            self._set_record_error("请先开始视觉模仿")
            return
        self._record_frames=[]
        self._record_started_t=time.time()
        self._last_record_t=0.0
        self._last_record_pose=None
        self._record_skip_log_t=0.0
        self._recording=True
        self._record_file_path=""
        self._playback_idx=0
        self._playback_last_sent=None
        self._last_playback_pose=None
        self._set_record_error("")
        self._update_record_ui()
        _glog("record start")
        if not self._last_has_hand:
            self._set_record_error("waiting hand to record")
            _glog("waiting hand to record")

    def _stop_recording(self):
        if not self._recording:
            return
        self._recording=False
        duration=self._recording_duration()
        if len(self._record_frames) < MIN_RECORD_FRAMES or duration < MIN_RECORD_DURATION:
            self._set_record_error(f"record too short frames={len(self._record_frames)} duration={duration:.2f}s")
        self._update_record_ui()
        _glog(f"record stop frames={len(self._record_frames)} duration={duration:.3f}")

    def _clear_recording(self):
        if self._playing:
            self._stop_playback()
        self._recording=False
        self._record_frames=[]
        self._record_started_t=0.0
        self._last_record_t=0.0
        self._last_record_pose=None
        self._record_skip_log_t=0.0
        self._record_file_path=""
        self._playback_idx=0
        self._playback_last_sent=None
        self._last_playback_pose=None
        self._set_record_error("")
        self._update_record_ui()
        _glog("record cleared")

    def _record_pose(self, pose, raw_pose, debug):
        if not self._recording or self._playing:
            return
        now=time.time()
        if debug and debug.get("hand_detected") is False:
            _glog("invalid pose skipped: no hand")
            return
        if not self._last_has_hand:
            if now-self._record_skip_log_t >= 1.0:
                _glog("waiting hand to record")
                self._record_skip_log_t=now
            return
        safe_pose=self._sanitize_pose(pose)
        safe_raw=self._sanitize_pose(raw_pose)
        if safe_pose is None:
            _glog("invalid pose skipped")
            return
        if not self._should_record_pose(safe_pose,now):
            return
        curls=debug.get("curls",[]) if debug else []
        if isinstance(curls,dict):
            curl_map={
                "thumb":float(curls.get("thumb",0.0)),
                "index":float(curls.get("index",0.0)),
                "middle":float(curls.get("middle",0.0)),
                "ring":float(curls.get("ring",0.0)),
                "little":float(curls.get("little",0.0)),
            }
        else:
            curl_map={
                "thumb":float(curls[0]) if len(curls)>0 else 0.0,
                "index":float(curls[1]) if len(curls)>1 else 0.0,
                "middle":float(curls[2]) if len(curls)>2 else 0.0,
                "ring":float(curls[3]) if len(curls)>3 else 0.0,
                "little":float(curls[4]) if len(curls)>4 else 0.0,
            }
        frame_t=round(now-self._record_started_t,3)
        if self._record_frames and frame_t <= float(self._record_frames[-1].get("t",0.0)):
            frame_t=round(float(self._record_frames[-1].get("t",0.0))+RECORD_INTERVAL,3)
        frame={
            "t":frame_t,
            "pose":safe_pose,
            "raw_pose":safe_raw if safe_raw is not None else list(safe_pose),
            "ema_pose":list(safe_pose),
            "curls":curl_map,
            "hand_detected":True,
        }
        self._record_frames.append(frame)
        self._last_record_t=now
        self._last_record_pose=list(safe_pose)
        self._update_record_ui()
        _glog(f"frame recorded t={frame['t']:.3f} pose={safe_pose}")

    def _build_recording_payload(self):
        frames=[]
        base_t=float(self._record_frames[0].get("t",0.0)) if self._record_frames else 0.0
        for item in self._record_frames:
            frame=dict(item)
            frame["t"]=round(max(0.0,float(frame.get("t",0.0))-base_t),3)
            frame["pose"]=self._sanitize_pose(frame.get("pose")) or list(SAFE_NEUTRAL)
            frame["raw_pose"]=self._sanitize_pose(frame.get("raw_pose")) or list(frame["pose"])
            frame["ema_pose"]=self._sanitize_pose(frame.get("ema_pose")) or list(frame["pose"])
            frame["hand_detected"]=bool(frame.get("hand_detected",True))
            if not isinstance(frame.get("curls"),dict):
                frame["curls"]={}
            frames.append(frame)
        duration=float(frames[-1].get("t",0.0)) if frames else 0.0
        return {
            "version":1,
            "type":RECORDING_TYPE,
            "mode":"O6",
            "range":[POSE_MIN,POSE_MAX],
            "created_at":datetime.now().isoformat(timespec="seconds"),
            "duration":round(duration,3),
            "frame_count":len(frames),
            "record_interval":RECORD_INTERVAL,
            "pose_fields":list(POSE_FIELDS),
            "fps_hint":round(1.0/RECORD_INTERVAL,1),
            "frames":frames,
        }

    def _default_recording_path(self):
        name=datetime.now().strftime("gesture_record_%Y%m%d_%H%M%S.json")
        return os.path.join(RECORDING_DIR,name)

    def _save_recording(self):
        if not self._record_frames:
            self._set_record_error("没有可保存的录制")
            _glog("save failed: no frames")
            return
        os.makedirs(RECORDING_DIR,exist_ok=True)
        path,_=QFileDialog.getSaveFileName(self,"保存动作录制",self._default_recording_path(),"JSON Files (*.json)")
        if not path:
            return
        self._save_recording_to_path(path)

    def _save_recording_to_path(self, path):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)),exist_ok=True)
            with open(path,"w",encoding="utf-8") as f:
                json.dump(self._build_recording_payload(),f,ensure_ascii=False,indent=2)
            self._record_file_path=os.path.abspath(path)
            self._set_record_error("")
            self._update_record_ui()
            _glog(f"saved path={self._record_file_path}")
            return True
        except Exception as e:
            self._set_record_error(f"保存失败 {e}")
            _glog(f"save failed: {e}")
            return False

    def _load_recording(self):
        path,_=QFileDialog.getOpenFileName(self,"加载动作录制",RECORDING_DIR,"JSON Files (*.json)")
        if not path:
            return
        self._load_recording_from_path(path)

    def _load_recording_from_path(self, path):
        try:
            with open(path,"r",encoding="utf-8") as f:
                data=json.load(f)
            if data.get("version") != 1:
                raise ValueError("version must be 1")
            if data.get("type",RECORDING_TYPE) != RECORDING_TYPE:
                raise ValueError("type must be linkerhand_gesture_recording")
            if data.get("mode") != "O6":
                raise ValueError("mode must be O6")
            if list(data.get("range",[])) != [POSE_MIN,POSE_MAX]:
                raise ValueError("range must be [0,255]")
            raw_frames=data.get("frames")
            if not isinstance(raw_frames,list) or not raw_frames:
                raise ValueError("frames must be a non-empty list")
            expected_count=data.get("frame_count")
            if expected_count is not None and int(expected_count) != len(raw_frames):
                raise ValueError("frame_count does not match frames length")
            frames=[]
            last_t=None
            skipped=0
            for item in raw_frames:
                if not isinstance(item,dict):
                    skipped+=1; _glog("invalid pose skipped")
                    continue
                if not item.get("hand_detected",True):
                    skipped+=1
                    continue
                pose=self._strict_pose(item.get("pose"))
                if pose is None:
                    skipped+=1; _glog("invalid pose skipped")
                    continue
                raw=self._strict_pose(item.get("raw_pose")) or list(pose)
                ema=self._strict_pose(item.get("ema_pose")) or list(pose)
                try:
                    t=max(0.0,float(item.get("t")))
                except Exception:
                    skipped+=1; _glog("invalid pose skipped")
                    continue
                if last_t is not None and t < last_t:
                    skipped+=1; _glog("invalid pose skipped: non-monotonic t")
                    continue
                last_t=t
                curls=item.get("curls",{})
                if not isinstance(curls,dict):
                    curls={}
                frames.append({
                    "t":round(t,3),
                    "pose":pose,
                    "raw_pose":raw,
                    "ema_pose":ema,
                    "curls":curls,
                    "hand_detected":True,
                })
            if len(frames) < MIN_PLAYBACK_FRAMES:
                raise ValueError(f"need at least {MIN_PLAYBACK_FRAMES} valid frames, got {len(frames)}")
            base_t=frames[0]["t"]
            for frame in frames:
                frame["t"]=round(max(0.0,frame["t"]-base_t),3)
            if skipped:
                _glog(f"load skipped invalid frames={skipped}")
            self._stop_recording()
            self._stop_playback()
            self._record_frames=frames
            self._record_file_path=os.path.abspath(path)
            self._playback_idx=0
            self._playback_last_sent=None
            self._last_playback_pose=None
            self._set_record_error("")
            self._update_record_ui()
            _glog(f"loaded path={self._record_file_path} frames={len(frames)} duration={frames[-1]['t']:.3f}")
            return True
        except Exception as e:
            self._set_record_error(f"加载失败 {e}")
            _glog(f"load failed: {e}")
            return False

    def _on_playback_speed_changed(self, text):
        try:
            self._playback_speed=max(0.1,float(text.replace("x","")))
        except Exception:
            self._playback_speed=1.0
        if hasattr(self,"d_play_options"):
            self._update_playback_ui()

    def _start_playback(self):
        if not self._record_frames:
            self._set_record_error("没有可回放的动作")
            _glog("no frames to play")
            return
        if len(self._record_frames) < MIN_PLAYBACK_FRAMES:
            self._set_record_error(f"need at least {MIN_PLAYBACK_FRAMES} frames to play")
            _glog("no frames to play")
            return
        if self._playing and self._playback_paused:
            self._toggle_playback_pause()
            return
        if self._playing:
            return
        if self._recording:
            self._stop_recording()
        if self._hw_enabled:
            reply=QMessageBox.question(self,"确认回放","开始回放将暂停实时下发，是否继续？",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        reply=QMessageBox.question(self,"确认开始回放","请确认机械手已上电、CAN 已连接、右上角状态为已连接。是否开始回放？",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._begin_playback()

    def _begin_playback(self):
        self._on_playback_speed_changed(self.cmb_play_speed.currentText())
        self._playback_loop=self.chk_play_loop.isChecked()
        if self._hw_enabled:
            self.chk_hw.setChecked(False)
            self._hw_enabled=False
        self._playing=True
        self._playback_paused=False
        self._live_emit_blocked_by_playback=True
        self._playback_idx=0
        self._playback_last_sent=None
        self.btn_play_pause.setText("暂停回放")
        self._set_record_error("")
        self._update_playback_ui()
        _glog(f"playback start frames={len(self._record_frames)} speed={self._playback_speed:.1f}")
        self._playback_timer.start(0)

    def _toggle_playback_pause(self):
        if not self._playing:
            return
        self._playback_paused=not self._playback_paused
        if self._playback_paused:
            self._playback_timer.stop()
            self.btn_play_pause.setText("继续回放")
            _glog("playback paused")
        else:
            self.btn_play_pause.setText("暂停回放")
            _glog("playback resumed")
            self._playback_timer.start(0)
        self._update_playback_ui()

    def _stop_playback(self, finished=False):
        was_playing=self._playing or self._playback_paused
        self._playback_timer.stop()
        self._playing=False
        self._playback_paused=False
        self._live_emit_blocked_by_playback=False
        self.btn_play_pause.setText("暂停回放")
        if finished:
            self._playback_idx=len(self._record_frames)
            _glog("playback finished")
        elif was_playing:
            _glog("playback stopped")
        self._update_playback_ui()

    def _playback_tick(self):
        if not self._playing or self._playback_paused:
            return
        if self._playback_idx >= len(self._record_frames):
            if self._playback_loop:
                _glog("playback loop restart")
                self._playback_idx=0
            else:
                self._stop_playback(finished=True)
                return

        frame=self._record_frames[self._playback_idx]
        target=self._sanitize_pose(frame.get("pose"))
        if target is None:
            _glog("invalid pose skipped")
            self._playback_idx+=1
            self._playback_timer.start(1)
            return
        safe=self._limit_step(self._playback_last_sent,target,MAX_REPLAY_STEP)
        self._send_playback_pose(safe,self._playback_idx,frame.get("t",0.0))
        reached=safe == target
        if reached:
            current_idx=self._playback_idx
            self._playback_idx+=1
            delay=self._next_playback_delay_ms(current_idx)
        else:
            delay=max(1,int(MIN_PLAYBACK_INTERVAL*1000))
        self._update_playback_ui()
        self._playback_timer.start(delay)

    def _next_playback_delay_ms(self, sent_idx):
        next_idx=sent_idx+1
        if next_idx >= len(self._record_frames):
            return 1
        t0=float(self._record_frames[sent_idx].get("t",0.0))
        t1=float(self._record_frames[next_idx].get("t",t0))
        interval=(t1-t0)/max(self._playback_speed,0.1)
        interval=max(MIN_PLAYBACK_INTERVAL,min(MAX_PLAYBACK_INTERVAL,interval))
        return max(1,int(interval*1000))

    def _limit_step(self, last_pose, target_pose, max_step):
        target=self._sanitize_pose(target_pose)
        if target is None:
            return None
        if not last_pose:
            return list(target)
        safe=[]
        for i,(last,target_value) in enumerate(zip(last_pose,target)):
            delta=target_value-last
            limit=min(max_step,MAX_STEP_THUMB_SWING) if i == 1 else max_step
            if abs(delta)>limit:
                safe.append(int(last+(limit if delta>0 else -limit)))
            else:
                safe.append(int(target_value))
        return safe

    def _send_playback_pose(self, pose, idx, frame_t):
        safe=self._sanitize_pose(pose)
        if safe is None:
            _glog("invalid pose skipped")
            return
        _glog(f"playback send idx={idx} t={float(frame_t):.3f} pose={safe}")
        try:
            signal_bus.finger_move_requested.emit(safe)
            self._playback_last_sent=list(safe)
            self._last_playback_pose=list(safe)
            self._last_sent=list(safe)
            self._last_sent_t=time.time()
            self.d_pose_sent.setText(f"sent: {safe} (playback)")
            self._update_playback_ui()
        except Exception as e:
            self._set_record_error(f"回放下发失败 {e}")
            _glog(f"emit failed: {e}")
            self._stop_playback()

    # ── 控制 ──
    def _start(self):
        if self._state in ("opening","running"): return
        self._set_state("opening"); self.btn_start.setEnabled(False)
        self.cam_view.setText("正在打开摄像头..."); self.d_status.setText("状态: 打开摄像头...")
        self._ema_pose=None; self._last_sent=None; self._last_sent_t=0
        self._sent_cnt=0; self._skip_cnt=0; self._start_t=time.time()
        self._last_dbg=None; self._last_has_hand=False; self._last_curls=None
        self.d_c11.setText("11点: 等待")
        _vlog("start clicked")

        self._worker=ImitationWorker()
        self._worker.set_calibration(self._calib_open,self._calib_close)
        self._apply_thumb_config()
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.pose_computed.connect(self._on_pose)
        self._worker.status_update.connect(self._on_status)
        self._worker.camera_error.connect(self._on_camera_error)
        self._worker.camera_opened.connect(self._on_camera_opened)
        self._worker.start()
        self._opening_timer.start(3000)

    def _on_opening_timeout(self):
        if self._state=="opening": self._on_camera_error("摄像头线程超时")

    def _on_camera_error(self,msg):
        self._opening_timer.stop(); self._set_state("error"); self._stop_worker()
        self.cam_view.setText("错误"); self._log_status(f"状态: {msg}"); self.btn_start.setEnabled(True)
        _vlog(f"camera error: {msg}")

    def _on_camera_opened(self):
        self._opening_timer.stop(); self._set_state("running")
        self._log_status("运行中 — 勾选下发开关才控制机械手")
        self.d_hw.setText("下发: 未启用")
        self.d_hw.setStyleSheet("color:#E5484D; font-size:11px; font-weight:600;")
        self.cam_status_lbl.setText("运行中")
        self.cam_status_lbl.setStyleSheet("color:#22A06B; font-size:11px;")
        _vlog("camera_opened, running")

    def _log_status(self, msg):
        self._log_lines.append(msg)
        if len(self._log_lines) > 80:
            self._log_lines = self._log_lines[-80:]
        self.log_view.setPlainText("\n".join(self._log_lines))

    def _stop_page(self):
        self._opening_timer.stop(); self._set_state("stopped")
        self._stop_recording()
        self._stop_playback()
        self._hw_enabled=False; self.chk_hw.setChecked(False)
        self._stop_worker(); self._ema_pose=None; self._last_sent=None
        self.cam_view.setText("已停止"); self.d_hand.setText("手势: 已停止")
        self.d_c11.setText("11点: 未检测到手")
        self.d_curl.setText("curl: --"); self.d_pose_raw.setText("raw pose: --")
        self.d_thumb.setText("thumb: --")
        self.d_index.setText("index prox/dist/tip/fused: --")
        self.d_middle.setText("middle prox/dist/tip/fused: --")
        self.d_ring.setText("ring prox/dist/tip/fused: --")
        self.d_little.setText("little prox/dist/tip/fused: --")
        self.d_pose_ema.setText("ema pose: --")
        self.d_similarity.setText("similarity: --")
        self.d_errors.setText("errors: --")
        self.d_pose_sent.setText("sent: --")
        self.d_freq.setText("freq: --"); self.d_status.setText("状态: 已停止"); self.btn_start.setEnabled(True)
        _vlog("stopped")

    def _stop_worker(self):
        if self._worker: self._worker.stop(); self._worker=None

    def _go_home(self):
        if self._playing:
            self._stop_playback()
        if self._safe_emit(SAFE_NEUTRAL,"home"):
            self.d_status.setText("状态: 复位已发送")

    def _set_state(self,s):
        self._state=s; self.btn_stop.setEnabled(s in ("opening","running"))
        if hasattr(self,"btn_record_start"):
            self._update_record_buttons()

    # ── 重置视角兼容 ──
    def set_compact_mode(self, compact: bool):
        pass

    # ── 隐藏时自动停止 ──
    def hideEvent(self, event):
        if self._state in ("opening","running"):
            self._hw_enabled=False; self.chk_hw.setChecked(False); self._stop_page()
        super().hideEvent(event)

    def closeEvent(self, event=None):
        self._hw_enabled=False
        self._stop_recording()
        self._stop_playback()
        if self._worker: self._worker.stop(); self._worker=None
        if event: super().closeEvent(event)

    # ── 主线程 pose 接收 ──
    def _on_pose(self,raw_pose,debug):
        if debug.get("log_joint"):
            _vlog("pose slot received")
        if len(raw_pose) != 6:
            self.d_status.setText("状态: pose 长度错误，已丢弃")
            _vlog(f"invalid pose length: {len(raw_pose)}")
            return
        self._last_dbg=debug  # 缓存供校准使用
        self._last_has_hand=True
        now=time.time()
        raw=[int(max(POSE_MIN,min(POSE_MAX,v))) for v in raw_pose]
        curls=debug.get("curls",[])
        spread=debug.get("thumb_spread",0.0)
        self._last_curls=list(curls) if len(curls) == 5 else None
        self.d_c11.setText("11点: 正常")
        self.d_c11.setStyleSheet("color:#047857;font-size:12px;font-family:monospace;font-weight:700;")
        self.d_curl.setText(f"curl: T={curls[0] if len(curls)>0 else 0:.2f} I={curls[1] if len(curls)>1 else 0:.2f} M={curls[2] if len(curls)>2 else 0:.2f} R={curls[3] if len(curls)>3 else 0:.2f} L={curls[4] if len(curls)>4 else 0:.2f} S={spread:.2f}")
        thumb=debug.get("thumb",{})
        fingers=debug.get("fingers",{})
        self.d_thumb.setText(
            "thumb: bend {:.2f}->{} inv={}, swing {:.2f}/{:.2f}->{} inv={}".format(
                thumb.get("bend_raw",0.0),
                thumb.get("bend_mapped",raw[0]),
                thumb.get("bend_invert",False),
                thumb.get("swing_raw",0.0),
                thumb.get("swing_norm",spread),
                thumb.get("swing_mapped",raw[1]),
                thumb.get("swing_invert",False),
            )
        )
        for name,label in [
            ("index",self.d_index),
            ("middle",self.d_middle),
            ("ring",self.d_ring),
            ("little",self.d_little),
        ]:
            fd=fingers.get(name,{})
            label.setText(
                "{} prox/dist/tip/fused: {:.2f}/{:.2f}/{:.2f}/{:.2f}".format(
                    name,
                    fd.get("proximal",0.0),
                    fd.get("distal",0.0),
                    fd.get("tip_aux",0.0),
                    fd.get("fused",0.0),
                )
            )
        self.d_pose_raw.setText(f"raw pose: {raw}")

        # EMA
        if self._ema_pose is None: self._ema_pose=[float(v) for v in raw]
        else:
            for i in range(6): self._ema_pose[i]+=self._ema_alpha*(raw[i]-self._ema_pose[i])
        ema=[int(max(POSE_MIN,min(POSE_MAX,v))) for v in self._ema_pose]
        self.d_pose_ema.setText(f"ema pose: {ema}")
        if debug.get("log_joint"):
            _jlog(f"ema pose: {ema}")

        score,errors=self._compute_similarity(ema,debug)
        if score is not None and errors:
            self.d_similarity.setText(f"similarity: {score:.1f}%")
            self.d_errors.setText(
                "errors: " + " ".join(
                    f"{name}={err:.2f}" for name,err in zip(POSE_FIELDS,errors)
                )
            )
            if debug.get("log_joint"):
                _jlog(f"similarity={score:.1f}% errors={[round(e,3) for e in errors]}")
        else:
            self.d_similarity.setText("similarity: --")
            self.d_errors.setText("errors: --")

        self._record_pose(ema,raw,debug)

        if self._live_emit_blocked_by_playback or self._playing:
            self.d_status.setText("状态: 回放中，实时 pose 不下发")
            if debug.get("log_joint"):
                _glog("live emit blocked by playback")
            return

        if not self._hw_enabled:
            self.d_status.setText("状态: 硬件未启用，pose 不下发")
            if debug.get("log_joint"):
                _vlog("hardware disabled, pose not sent")
                _jlog("hardware disabled, pose not sent")
            return

        # 限频
        if now-self._last_sent_t<self._emit_iv: return

        # 最大步长
        clamped=list(ema)
        if self._last_sent:
            for i in range(6):
                d=clamped[i]-self._last_sent[i]
                limit=self._max_delta[i] if isinstance(self._max_delta,(list,tuple)) else self._max_delta
                if abs(d)>limit:
                    clamped[i]=self._last_sent[i]+(limit if d>0 else -limit)

        # deadband
        if self._last_sent:
            md=max(abs(clamped[i]-self._last_sent[i]) for i in range(6))
            if md<self._deadband:
                self._skip_cnt+=1
                self.d_status.setText(f"状态: 无变化跳过 (Δ={md})")
                if debug.get("log_joint"):
                    _jlog(f"deadband skip delta={md}")
                return

        _vlog(f"sending pose: {clamped}")
        _jlog(f"sending pose: {clamped}")
        if self._safe_emit(clamped,"live"):
            self._sent_cnt+=1
            hz=self._sent_cnt/max(now-self._start_t,1.0)
            self.d_freq.setText(f"freq: ~{hz:.1f}Hz sent={self._sent_cnt}")
            self.d_status.setText(f"状态: 已下发 #{self._sent_cnt}")

    # ── 回调 ──
    def _on_frame(self,qimg):
        pix=QPixmap.fromImage(qimg).scaled(self.cam_view.width(),self.cam_view.height(),
                                            Qt.KeepAspectRatio,Qt.SmoothTransformation)
        self.cam_view.setPixmap(pix)

    def _on_status(self,key,value):
        if key=="hand":
            if value=="detected":
                self._last_has_hand=True
                self.d_hand.setText("手势: 检测到手"); self.d_hand.setStyleSheet("color:#047857;font-size:12px;font-family:monospace;font-weight:700;")
            else:
                self._last_has_hand=False
                self.d_hand.setText("手势: 未检测到手"); self.d_hand.setStyleSheet("color:#b91c1c;font-size:12px;font-family:monospace;font-weight:700;")
                self.d_c11.setText("11点: 未检测到手"); self.d_c11.setStyleSheet("color:#b91c1c;font-size:12px;font-family:monospace;font-weight:700;")
                self.d_similarity.setText("similarity: --")
                self.d_errors.setText("errors: --")
                now=time.time()
                if now-self._last_no_hand_log_t > 1.0:
                    _jlog("no hand, skip sending")
                    self._last_no_hand_log_t=now
                if self._hw_enabled:
                    self.d_status.setText("状态: 未检测到手，跳过下发")

    # ── 生命周期 ──
    def set_compact_mode(self,compact:bool): pass

    def hideEvent(self,event):
        if self._state in ("opening","running"):
            self._hw_enabled=False; self.chk_hw.setChecked(False); self._stop_page()
        super().hideEvent(event)

    def closeEvent(self,event=None):
        self._hw_enabled=False
        self._stop_recording()
        self._stop_playback()
        if self._worker: self._worker.stop(); self._worker=None
        if event: super().closeEvent(event)
