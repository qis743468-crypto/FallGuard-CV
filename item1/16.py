import sys
import cv2
import time
import math
import gc
import os
import threading
import requests
import pygame
import numpy as np
import mediapipe as mp
import base64
from collections import deque
from PIL import Image

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, 
                             QPushButton, QFileDialog, QVBoxLayout, QHBoxLayout, 
                             QGroupBox, QSlider)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap, QFont

# 指定跳转界面后默认调用的视频路径
DEFAULT_VIDEO_PATH = r"D:\kdlstudy\Python\item1\show.mp4"

# PushPlus 微信推送 Token
PUSHPLUS_TOKEN = "7cb9de5282c24d0cad3252094a377080"  

# 抓拍与视频保存目录
OUTPUT_DIR = "./fall_events"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# ==================== 1. 初始化 音频系统 ====================
try:
    pygame.mixer.init()
    def generate_beep_sound(frequency=880, duration=0.4):
        sample_rate = 44100
        n_samples = int(sample_rate * duration)
        buf = np.zeros((n_samples, 2), dtype=np.int16)
        max_sample = 2 ** 15 - 1
        for i in range(n_samples):
            t = float(i) / sample_rate
            val = int(max_sample * 0.5 * math.sin(2.0 * math.pi * frequency * t))
            buf[i][0] = val
            buf[i][1] = val
        return pygame.sndarray.make_sound(buf)

    alarm_sound = generate_beep_sound()
    AUDIO_OK = True
except Exception as e:
    print("⚠️ 声音系统初始化失败:", e)
    AUDIO_OK = False

is_alarm_playing = False

def set_alarm_sound(play: bool):
    global is_alarm_playing
    if not AUDIO_OK:
        return
    try:
        if play and not is_alarm_playing:
            alarm_sound.play(loops=-1)
            is_alarm_playing = True
        elif not play and is_alarm_playing:
            alarm_sound.stop()
            is_alarm_playing = False
    except Exception:
        pass

# ==================== 2. PushPlus 微信推送 & 多节点图床上传 ====================
last_alert_time = 0
ALERT_COOLDOWN = 15.0  

def upload_image_to_imgbb(image_np):
    try:
        h, w = image_np.shape[:2]
        if w > 800:
            scale = 800.0 / w
            image_np = cv2.resize(image_np, (800, int(h * scale)))

        _, buffer = cv2.imencode('.jpg', image_np, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
        img_bytes = buffer.tobytes()
        b64_data = base64.b64encode(img_bytes).decode('utf-8')

        print("☁️ [1/2] 正在尝试节点 1 (FreeImage) 上传抓拍图片...")
        files = {'file': ('snapshot.jpg', img_bytes, 'image/jpeg')}
        response = requests.post("https://freeimage.host/api/1/upload", 
                                 data={"key": "6D2E2892B9E54CC5", "action": "upload"}, 
                                 files=files, timeout=7)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("status_code") == 200:
                img_url = res_json["image"]["url"]
                print(f"✅ [图床上传成功] 节点 1 成功生成公网地址: {img_url}")
                return img_url
    except Exception:
        print("⚠️ 节点 1 上传超时或受限，正在切换备用节点...")

    try:
        print("☁️ [2/2] 正在尝试节点 2 (ImgBB) 上传抓拍图片...")
        url = "https://api.imgbb.com/1/upload"
        payload = {
            "key": "6d70204cce8462ca15d3263507029c5b",
            "image": b64_data
        }
        res = requests.post(url, data=payload, timeout=7).json()
        if res.get("success"):
            img_url = res["data"]["url"]
            print(f"✅ [图床上传成功] 节点 2 成功生成公网地址: {img_url}")
            return img_url
    except Exception as e:
        print("⚠️ 节点 2 上传失败:", e)

    print("❌ 所有公网图床节点连接均超时，请检查本机网络或是否开启防火墙。")
    return None

def save_and_push_fall_event(snapshot_frame, video_frames, fps=15, alarm_reason="检测到跌倒姿态"):
    def _worker():
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        img_path = os.path.join(OUTPUT_DIR, f"fall_snapshot_{timestamp}.jpg")
        video_path = os.path.join(OUTPUT_DIR, f"fall_video_{timestamp}.mp4")

        cv2.imwrite(img_path, snapshot_frame)
        print(f"📸 [抓拍成功] 本地截图已保存至: {img_path}")

        if video_frames:
            h, w, _ = video_frames[0].shape
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(video_path, fourcc, fps, (w, h))
            for f in video_frames:
                out.write(f)
            out.release()
            print(f"🎥 [视频留存成功] 5s高清视频已保存至: {video_path}")

        if not PUSHPLUS_TOKEN.strip():
            print("⚠️ [PushPlus 报错] 未设置有效的 PUSHPLUS_TOKEN！")
            return

        image_url = upload_image_to_imgbb(snapshot_frame)

        if image_url:
            img_html = f'<img src="{image_url}" style="max-width:100%; border-radius:6px; border:1px solid #d9d9d9;"/>'
        else:
            img_html = f'<p style="color:#ff4d4f;">⚠️ 图床上传受限，照片已保存在本地路径：<br/><code>{img_path}</code></p>'

        url = "http://www.pushplus.plus/send"
        html_content = f"""
        <div style="padding:10px; border:2px solid #ff4d4f; border-radius:8px; background-color:#fff1f0; font-family:sans-serif;">
            <h3 style="color:#cf1322; margin-top:0; margin-bottom:8px;">🚨 监测到跌倒警告！</h3>
            <p style="margin:4px 0;"><b>告警原因：</b><span style="color:#d4380d;">{alarm_reason}</span></p>
            <p style="margin:4px 0;"><b>触发时间：</b>{time.strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p style="margin:4px 0;"><b>📸 跌倒现场抓拍照片：</b></p>
            <div style="text-align:center; margin-top:8px;">
                {img_html}
            </div>
            <hr style="border:none; border-top:1px dashed #ffccc7; margin:10px 0;"/>
            <p style="color:#8c8c8c; font-size:12px; margin:0;">提示：本地已成功自动保存 5 秒前后视频！</p>
        </div>
        """

        data = {
            "token": PUSHPLUS_TOKEN.strip(),
            "title": "🚨 跌倒告警：智能监护系统抓拍",
            "content": html_content,
            "template": "html"
        }

        try:
            print("📡 [PushPlus] 正在向微信发送推送数据...")
            response = requests.post(url, json=data, timeout=10)
            res_json = response.json()
            print(f"📩 [PushPlus 响应日志] Code: {res_json.get('code')}, Message: {res_json.get('msg')}")

        except Exception as e:
            print("❌ [网络连接异常] 发送失败:", e)

    threading.Thread(target=_worker, daemon=True).start()

def send_wechat_alarm(alarm_reason="测试消息"):
    def _send():
        if not PUSHPLUS_TOKEN.strip():
            return
        url = "http://www.pushplus.plus/send"
        data = {
            "token": PUSHPLUS_TOKEN.strip(),
            "title": "🔔 测试通知：监护系统通讯测试",
            "content": f"<p>{alarm_reason}</p><p>时间：{time.strftime('%Y-%m-%d %H:%M:%S')}</p>",
            "template": "html"
        }
        try:
            res = requests.post(url, json=data, timeout=5).json()
            print(f"📩 [测试推送响应] Code: {res.get('code')}, Message: {res.get('msg')}")
        except Exception as e:
            print("❌ 测试推送失败:", e)
    threading.Thread(target=_send, daemon=True).start()

# ==================== 3. 高清 HUD 绘制模块 ====================
COLOR_CYAN = (255, 255, 0)       
COLOR_GREEN = (0, 255, 127)     
COLOR_YELLOW = (0, 215, 255)    
COLOR_RED = (0, 0, 255)         
COLOR_DARK_BG = (10, 10, 15)    
COLOR_WHITE = (255, 255, 255)

def draw_chinese_text_hd(img, text, position, font_size=18, color=(255, 255, 255)):
    try:
        from PIL import ImageDraw, ImageFont
        pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)
        
        font = None
        font_paths = [
            "msyh.ttc", "simhei.ttf", "SimHei.ttf", "msyh.ttf", 
            "/System/Library/Fonts/PingFang.ttc",               
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc" 
        ]
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        draw.text(position, text, font=font, fill=(color[2], color[1], color[0]))
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception:
        cv2.putText(img, text, position, cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)
        return img

def draw_overlay_panel(img, x, y, w, h, alpha=0.5, border_color=COLOR_CYAN):
    overlay = img.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + h), COLOR_DARK_BG, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
    
    length = 10
    cv2.line(img, (x, y), (x + length, y), border_color, 1, cv2.LINE_AA)
    cv2.line(img, (x, y), (x, y + length), border_color, 1, cv2.LINE_AA)
    cv2.line(img, (x + w, y), (x + w - length, y), border_color, 1, cv2.LINE_AA)
    cv2.line(img, (x + w, y), (x + w, y + length), border_color, 1, cv2.LINE_AA)
    cv2.line(img, (x, y + h), (x + length, y + h), border_color, 1, cv2.LINE_AA)
    cv2.line(img, (x, y + h), (x, y + h - length), border_color, 1, cv2.LINE_AA)
    cv2.line(img, (x + w, y + h), (x + w - length, y + h), border_color, 1, cv2.LINE_AA)
    cv2.line(img, (x + w, y + h), (x + w, y + h - length), border_color, 1, cv2.LINE_AA)

def draw_gauge_hd(img, center, radius, angle_val, max_angle=90, threshold=65):
    cx, cy = center
    cv2.ellipse(img, (cx, cy), (radius, radius), 0, 180, 360, (50, 50, 50), 4, cv2.LINE_AA)
    
    thresh_start_angle = 180 + int((threshold / max_angle) * 180)
    cv2.ellipse(img, (cx, cy), (radius, radius), 0, thresh_start_angle, 360, (0, 0, 180), 4, cv2.LINE_AA)
    
    current_angle = min(angle_val, max_angle)
    active_end_angle = 180 + int((current_angle / max_angle) * 180)
    color = COLOR_GREEN if angle_val < threshold else COLOR_RED
    cv2.ellipse(img, (cx, cy), (radius, radius), 0, 180, active_end_angle, color, 4, cv2.LINE_AA)

    rad = math.radians(active_end_angle)
    px = int(cx + (radius - 8) * math.cos(rad))
    py = int(cy + (radius - 8) * math.sin(rad))
    cv2.line(img, (cx, cy), (px, py), COLOR_WHITE, 2, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 3, COLOR_WHITE, -1, cv2.LINE_AA)

def draw_full_33_skeleton_hd(img, landmarks, connections, w, h):
    points = {}
    for idx, lm in enumerate(landmarks.landmark):
        if lm.visibility > 0.3:  
            points[idx] = (int(lm.x * w), int(lm.y * h))
            
    for conn in connections:
        p1_idx, p2_idx = conn
        if p1_idx in points and p2_idx in points:
            cv2.line(img, points[p1_idx], points[p2_idx], (255, 140, 0), 2, cv2.LINE_AA)
            cv2.line(img, points[p1_idx], points[p2_idx], (255, 255, 255), 1, cv2.LINE_AA)

    for idx, pt in points.items():
        if idx in [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]:
            cv2.circle(img, pt, 5, COLOR_CYAN, -1, cv2.LINE_AA)
            cv2.circle(img, pt, 2, COLOR_WHITE, -1, cv2.LINE_AA)
        else:
            cv2.circle(img, pt, 3, (0, 215, 255), -1, cv2.LINE_AA)

def blur_face_safe(image, landmarks, w, h, mp_pose_ref):
    try:
        nose = landmarks[mp_pose_ref.PoseLandmark.NOSE]
        left_ear = landmarks[mp_pose_ref.PoseLandmark.LEFT_EAR]
        right_ear = landmarks[mp_pose_ref.PoseLandmark.RIGHT_EAR]
        
        face_x = int(nose.x * w)
        face_y = int(nose.y * h)
        ear_dist = int(abs(left_ear.x - right_ear.x) * w * 1.2)
        r = max(20, ear_dist)

        x1, y1 = max(0, face_x - r), max(0, face_y - r)
        x2, y2 = min(w, face_x + r), min(h, face_y + r)

        if (x2 - x1) > 10 and (y2 - y1) > 10:
            face_roi = image[y1:y2, x1:x2]
            if face_roi.size > 0:
                blurred_face = cv2.GaussianBlur(face_roi, (21, 21), 10)
                image[y1:y2, x1:x2] = blurred_face
    except Exception:
        pass
    return image

def calculate_angle(p1, p2):
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return math.degrees(math.atan2(abs(dx), abs(dy)))

# ==================== 4. PoseDetector 算法解析类 ====================
mp_pose = mp.solutions.pose

class PoseDetector:
    def __init__(self):
        self.pose = mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            smooth_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.smooth_angle = 0.0
        self.smooth_velocity = 0.0
        self.last_hip_y = None
        self.action_history = deque(maxlen=7)

    @staticmethod
    def calculate_angle_3pts(a, b, c):
        ang = math.degrees(
            math.atan2(c[1] - b[1], c[0] - b[0]) - math.atan2(a[1] - b[1], a[0] - b[0])
        )
        ang = abs(ang)
        return ang if ang <= 180 else 360 - ang

    def process_frame(self, frame, dt):
        h, w, _ = frame.shape
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.pose.process(rgb_frame)
        
        detected_pts = 0
        current_action = "未检测到人体"
        
        if results.pose_landmarks:
            landmarks = results.pose_landmarks.landmark
            detected_pts = sum(1 for lm in landmarks if lm.visibility > 0.3)

            draw_full_33_skeleton_hd(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS, w, h)

            def get_pt(lm_idx):
                lm = landmarks[lm_idx]
                return np.array([lm.x, lm.y])

            ls, rs = get_pt(mp_pose.PoseLandmark.LEFT_SHOULDER), get_pt(mp_pose.PoseLandmark.RIGHT_SHOULDER)
            lh, rh = get_pt(mp_pose.PoseLandmark.LEFT_HIP), get_pt(mp_pose.PoseLandmark.RIGHT_HIP)
            lk, rk = get_pt(mp_pose.PoseLandmark.LEFT_KNEE), get_pt(mp_pose.PoseLandmark.RIGHT_KNEE)
            la, ra = get_pt(mp_pose.PoseLandmark.LEFT_ANKLE), get_pt(mp_pose.PoseLandmark.RIGHT_ANKLE)

            s_center = (ls + rs) / 2.0
            h_center = (lh + rh) / 2.0
            a_center = (la + ra) / 2.0

            dx = abs(h_center[0] - s_center[0]) * w
            dy = abs(h_center[1] - s_center[1]) * h
            raw_angle = math.degrees(math.atan2(dx, max(dy, 1e-5)))

            hip_v_speed = 0.0
            if self.last_hip_y is not None and dt > 0:
                hip_v_speed = (h_center[1] - self.last_hip_y) / dt
            self.last_hip_y = h_center[1]

            self.smooth_angle = 0.7 * self.smooth_angle + 0.3 * raw_angle
            self.smooth_velocity = 0.6 * self.smooth_velocity + 0.4 * hip_v_speed

            visible_pts = [np.array([lm.x * w, lm.y * h]) for lm in landmarks if lm.visibility > 0.3]
            if visible_pts:
                pts_arr = np.array(visible_pts)
                aspect_ratio = (np.max(pts_arr, axis=0)[0] - np.min(pts_arr, axis=0)[0]) / max(np.max(pts_arr, axis=0)[1] - np.min(pts_arr, axis=0)[1], 1e-5)
            else:
                aspect_ratio = 0.5

            left_knee_ang = self.calculate_angle_3pts(lh, lk, la)
            right_knee_ang = self.calculate_angle_3pts(rh, rk, ra)
            avg_knee_angle = (left_knee_ang + right_knee_ang) / 2.0
            hip_to_ankle_dist = abs(a_center[1] - h_center[1])

            is_horizontal = (self.smooth_angle > 60.0 or aspect_ratio > 1.15)
            is_low_position = (h_center[1] > 0.62) or (hip_to_ankle_dist < 0.20)
            is_bending_over = (self.smooth_angle > 40.0) and (h_center[1] < 0.58) and (hip_to_ankle_dist > 0.25)
            is_sitting = (avg_knee_angle < 115.0) and (aspect_ratio < 0.95) and (h_center[1] > 0.48)

            if is_bending_over:
                raw_action = "弯腰"
            elif is_sitting and not is_horizontal:
                raw_action = "坐下"
            elif is_horizontal and is_low_position:
                raw_action = "倒地"
            else:
                raw_action = "正常行走"

            self.action_history.append(raw_action)
            current_action = max(set(self.action_history), key=self.action_history.count)

        return frame, self.smooth_angle, self.smooth_velocity, detected_pts, current_action

# ==================== 5. 图2：PyQt5 姿势识别与跌倒监护界面 ====================
class FallDetectionGUI(QMainWindow):
    def __init__(self, parent_controller=None):
        super().__init__()
        self.parent_controller = parent_controller
        self.setWindowTitle("AI 智能姿态分析与跌倒监护交互大屏")
        self.setGeometry(100, 100, 1280, 720)
        self.setStyleSheet("""
            QMainWindow { background-color: #0d1117; }
            QLabel { color: #e6edf3; font-family: 'Segoe UI', 'Microsoft YaHei'; }
            QGroupBox { font-weight: bold; color: #58a6ff; border: 1px solid #30363d; border-radius: 8px; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        """)

        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.detector = PoseDetector()
        self.is_paused = False
        self.last_time = time.time()

        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout()

        left_box = QVBoxLayout()
        self.video_label = QLabel("正在加载视频流...")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("border: 2px solid #30363d; background-color: #010409; border-radius: 10px;")
        self.video_label.setMinimumSize(800, 500)
        left_box.addWidget(self.video_label)

        ctrl_layout = QHBoxLayout()
        self.btn_select_video = QPushButton("📁 切换本地视频")
        self.btn_select_video.setStyleSheet(self.btn_style("#238636"))
        self.btn_select_video.clicked.connect(self.select_video)

        self.btn_pause = QPushButton("⏸️ 播放 / 暂停")
        self.btn_pause.setStyleSheet(self.btn_style("#8957e5"))
        self.btn_pause.clicked.connect(self.toggle_pause)

        self.btn_reload = QPushButton("🔄 重新播放")
        self.btn_reload.setStyleSheet(self.btn_style("#1f6feb"))
        self.btn_reload.clicked.connect(self.reload_video)

        self.btn_test_wechat = QPushButton("📱 发送微信测试推送")
        self.btn_test_wechat.setStyleSheet(self.btn_style("#da3633"))
        self.btn_test_wechat.clicked.connect(self.test_wechat_push)

        ctrl_layout.addWidget(self.btn_select_video)
        ctrl_layout.addWidget(self.btn_pause)
        ctrl_layout.addWidget(self.btn_reload)
        ctrl_layout.addWidget(self.btn_test_wechat)
        left_box.addLayout(ctrl_layout)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal { background: #21262d; height: 8px; border-radius: 4px; } 
            QSlider::handle:horizontal { background: #58a6ff; width: 16px; margin: -4px 0; border-radius: 8px; }
        """)
        self.slider.sliderMoved.connect(self.set_position)
        left_box.addWidget(self.slider)

        main_layout.addLayout(left_box, stretch=7)

        right_box = QVBoxLayout()
        action_group = QGroupBox("📌 实时动作识别分类")
        action_layout = QVBoxLayout()

        self.lbl_action_box = QLabel("等待数据接入...")
        self.lbl_action_box.setAlignment(Qt.AlignCenter)
        self.lbl_action_box.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        self.lbl_action_box.setStyleSheet("background-color: #161b22; color: #7d8590; border-radius: 8px; padding: 20px;")
        action_layout.addWidget(self.lbl_action_box)
        action_group.setLayout(action_layout)
        right_box.addWidget(action_group)

        metrics_group = QGroupBox("📊 HUD 关键姿态指标")
        metrics_layout = QVBoxLayout()

        self.lbl_angle = QLabel("躯干倾角: 0.0°")
        self.lbl_velocity = QLabel("下坠速度: 0.00 m/s")
        self.lbl_pts = QLabel("骨骼节点: 0 / 33 点")

        for lbl in [self.lbl_angle, self.lbl_velocity, self.lbl_pts]:
            lbl.setFont(QFont("Microsoft YaHei", 11))
            metrics_layout.addWidget(lbl)

        metrics_group.setLayout(metrics_layout)
        right_box.addWidget(metrics_group)

        right_box.addStretch()
        main_layout.addLayout(right_box, stretch=3)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def btn_style(self, color):
        return f"""
            QPushButton {{ 
                background-color: {color}; 
                color: white; 
                border-radius: 6px; 
                padding: 10px; 
                font-weight: bold; 
                font-family: 'Microsoft YaHei';
            }} 
            QPushButton:hover {{ 
                opacity: 0.8; 
            }}
        """

    def test_wechat_push(self):
        send_wechat_alarm("【测试推送】图2 交互大屏通讯检测正常！")

    def load_video(self, path):
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(path)
        if self.cap.isOpened():
            self.slider.setMaximum(int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            self.timer.start(33)

    def reload_video(self):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def select_video(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "选择本地视频文件", "", "Video Files (*.mp4 *.mov *.avi)")
        if file_name:
            self.load_video(file_name)

    def toggle_pause(self):
        self.is_paused = not self.is_paused

    def set_position(self, position):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, position)

    def update_frame(self):
        if self.is_paused or not self.cap or not self.cap.isOpened():
            return

        ret, frame = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            return

        pos = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        self.slider.setValue(pos)

        now = time.time()
        dt = max(now - self.last_time, 1e-3)
        self.last_time = now

        frame, angle, vel, pts, action = self.detector.process_frame(frame, dt)

        self.lbl_angle.setText(f"躯干倾角: {angle:.1f}°")
        self.lbl_velocity.setText(f"下坠速度: {vel:.2f} m/s")
        self.lbl_pts.setText(f"骨骼节点: {pts} / 33 点")

        if action == "倒地":
            self.lbl_action_box.setText("🚨 状态: 摔倒 (FALL DETECTED)")
            self.lbl_action_box.setStyleSheet("background-color: #780c12; color: #ff7b72; font-weight: bold; padding: 20px; border-radius: 8px;")
        else:
            self.lbl_action_box.setText(f"👤 状态: {action}")
            self.lbl_action_box.setStyleSheet("background-color: #116329; color: #7ee787; font-weight: bold; padding: 20px; border-radius: 8px;")

        h, w, ch = frame.shape
        bytes_per_line = ch * w
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qt_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_img).scaled(self.video_label.width(), self.video_label.height(), Qt.KeepAspectRatio)
        self.video_label.setPixmap(pixmap)

    def closeEvent(self, event):
        self.timer.stop()
        if self.cap:
            self.cap.release()
        if self.parent_controller:
            self.parent_controller.resume_camera_monitor()
        event.accept()

# ==================== 6. 主控模块 (完美依托 14.py 架构) ====================
class ApplicationController:
    def __init__(self):
        if not QApplication.instance():
            self.app = QApplication(sys.argv)
        else:
            self.app = QApplication.instance()
            
        self.gui_window = None

    def start_camera_monitor(self):
        mp_pose_ref = mp.solutions.pose

        pose = mp_pose_ref.Pose(
            static_image_mode=False,
            model_complexity=1,
            smooth_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        WINDOW_NAME = "AI 智能视觉监护系统 HD (跌倒/失能防护版)"
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, actual_w if actual_w > 0 else 1280, actual_h if actual_h > 0 else 720)

        global last_alert_time, state, suspect_start_time, last_upper_body_y, last_valid_time, last_time, privacy_mode
        last_alert_time = 0
        state = "NORMAL"
        suspect_start_time = 0
        last_upper_body_y = None
        last_valid_time = time.time()
        last_time = time.time()
        privacy_mode = 1  

        FPS_ESTIMATE = 15
        BUFFER_PRE_SECONDS = 3.0   
        BUFFER_POST_SECONDS = 2.0  
        
        pre_buffer_max = int(FPS_ESTIMATE * BUFFER_PRE_SECONDS)
        frame_ring_buffer = deque(maxlen=pre_buffer_max)

        is_recording_afterfall = False
        post_fall_frames = []
        post_fall_frame_target = int(FPS_ESTIMATE * BUFFER_POST_SECONDS)
        snapshot_to_send = None

        # 14.py 经典判定阈值
        TORSO_ANGLE_THRESHOLD = 65.0         
        FAST_DROP_VELOCITY = 0.85            
        STATIONARY_TIME_THRESHOLD = 1.2      
        LOW_POSITION_Y_THRESHOLD = 0.62      

        smooth_angle = 0.0
        smooth_velocity = 0.0
        frame_count = 0

        print("="*60)
        print("🚀 AI 监护系统已全面启动！")
        print("💡 快捷键：")
        print("   - [M] 键：切换隐私防护模式")
        print("   - [T] 键：测试推送，并载入图2 交互控制屏")
        print("   - [Q] 键：安全退出系统")
        print("="*60)

        self.monitor_running = True
        user_pressed_q = False

        while cap.isOpened() and self.monitor_running:
            try:
                success, frame = cap.read()
                if not success or frame is None:
                    time.sleep(0.01)
                    continue

                frame_count += 1
                if frame_count % 100 == 0:
                    gc.collect()

                current_time = time.time()
                dt = current_time - last_time
                last_time = current_time
                if dt <= 0:
                    dt = 0.001

                h, w, c = frame.shape
                
                if privacy_mode == 2:
                    canvas = np.zeros_like(frame)
                else:
                    canvas = frame.copy()

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb_frame.flags.writeable = False
                results = pose.process(rgb_frame)
                rgb_frame.flags.writeable = True

                status_color = COLOR_GREEN
                status_text = "SYSTEM READY / 正常监护中"

                raw_torso_angle = 0.0
                raw_drop_velocity = 0.0
                detected_points_count = 0

                if results.pose_landmarks:
                    last_valid_time = current_time
                    landmarks = results.pose_landmarks.landmark
                    detected_points_count = sum(1 for lm in landmarks if lm.visibility > 0.3)

                    if privacy_mode == 1:
                        canvas = blur_face_safe(canvas, landmarks, w, h, mp_pose_ref)

                    # 计算肩部、臀部、鼻子的核心点
                    left_shoulder = landmarks[mp_pose_ref.PoseLandmark.LEFT_SHOULDER]
                    right_shoulder = landmarks[mp_pose_ref.PoseLandmark.RIGHT_SHOULDER]
                    left_hip = landmarks[mp_pose_ref.PoseLandmark.LEFT_HIP]
                    right_hip = landmarks[mp_pose_ref.PoseLandmark.RIGHT_HIP]
                    nose = landmarks[mp_pose_ref.PoseLandmark.NOSE]

                    # 只有关键点可见度正常才进行几何计算
                    if left_shoulder.visibility > 0.3 and right_shoulder.visibility > 0.3:
                        ls = (left_shoulder.x, left_shoulder.y)
                        rs = (right_shoulder.x, right_shoulder.y)
                        shoulder_center = ((ls[0] + rs[0]) / 2.0, (ls[1] + rs[1]) / 2.0)

                        if left_hip.visibility > 0.3 and right_hip.visibility > 0.3:
                            hip_center = ((left_hip.x + right_hip.x) / 2.0, (left_hip.y + right_hip.y) / 2.0)
                            raw_torso_angle = calculate_angle(shoulder_center, hip_center)
                            upper_body_y = hip_center[1]
                        else:
                            raw_torso_angle = calculate_angle((nose.x, nose.y), shoulder_center)
                            upper_body_y = shoulder_center[1]

                        if last_upper_body_y is not None:
                            raw_drop_velocity = (upper_body_y - last_upper_body_y) / dt
                        last_upper_body_y = upper_body_y

                        smooth_angle = 0.7 * smooth_angle + 0.3 * raw_torso_angle
                        smooth_velocity = 0.6 * smooth_velocity + 0.4 * raw_drop_velocity

                        # 防误判条件：躯干大幅倾斜且处于低位；或出现瞬间高速砸下
                        is_posture_tilted = (smooth_angle > TORSO_ANGLE_THRESHOLD) and (upper_body_y > LOW_POSITION_Y_THRESHOLD)
                        is_fast_drop = (smooth_velocity > FAST_DROP_VELOCITY) and (upper_body_y > LOW_POSITION_Y_THRESHOLD)

                        is_fall_action = is_posture_tilted or is_fast_drop

                        # ================= 状态机转换规则 (完美精准) =================
                        if state == "NORMAL":
                            set_alarm_sound(False)
                            if is_fall_action:
                                state = "SUSPECTED"
                                suspect_start_time = current_time

                        elif state == "SUSPECTED":
                            duration = current_time - suspect_start_time
                            status_text = f"WARNING / 观察跌倒姿态 ({duration:.1f}s)"
                            status_color = COLOR_YELLOW

                            if not is_fall_action:
                                state = "NORMAL"
                            elif duration >= STATIONARY_TIME_THRESHOLD:
                                state = "FALL_ALERT"

                        elif state == "FALL_ALERT":
                            status_text = "🚨 ALARM / 检测到人员摔倒！"
                            status_color = COLOR_RED
                            set_alarm_sound(True)

                            if current_time - last_alert_time > ALERT_COOLDOWN and not is_recording_afterfall:
                                last_alert_time = current_time
                                snapshot_to_send = canvas.copy()
                                is_recording_afterfall = True
                                post_fall_frames = []
                                print("📸 [告警触发] 正在生成抓拍图形数据...")

                            # 人员恢复正常姿态，自动恢复
                            if smooth_angle < (TORSO_ANGLE_THRESHOLD - 20.0) and upper_body_y < LOW_POSITION_Y_THRESHOLD:
                                state = "NORMAL"
                                set_alarm_sound(False)

                        draw_full_33_skeleton_hd(canvas, results.pose_landmarks, mp_pose_ref.POSE_CONNECTIONS, w, h)
                    else:
                        # 画面中关键关节未识别全（人离开或半身入镜），立刻重置回 NORMAL
                        state = "NORMAL"
                        set_alarm_sound(False)

                else:
                    # 完全未捕捉到人体，直接重置回 NORMAL 状态，绝不上来就误报！
                    state = "NORMAL"
                    set_alarm_sound(False)

                frame_ring_buffer.append(canvas.copy())

                if is_recording_afterfall:
                    post_fall_frames.append(canvas.copy())
                    if len(post_fall_frames) >= post_fall_frame_target:
                        full_5s_video_frames = list(frame_ring_buffer) + post_fall_frames
                        save_and_push_fall_event(
                            snapshot_frame=snapshot_to_send,
                            video_frames=full_5s_video_frames,
                            fps=FPS_ESTIMATE,
                            alarm_reason=f"躯干倾角({smooth_angle:.1f}°)异常且长时间未恢复！"
                        )
                        is_recording_afterfall = False
                        post_fall_frames = []

                # ==================== 原版 HUD 渲染 ====================
                if state == "FALL_ALERT":
                    pulse = int((math.sin(current_time * 10) + 1) * 127)
                    cv2.rectangle(canvas, (0, 0), (w, h), (0, 0, pulse), 8)

                bar_h = int(h * 0.07)
                draw_overlay_panel(canvas, 15, 15, w - 30, bar_h, alpha=0.5, border_color=status_color)
                canvas = draw_chinese_text_hd(canvas, status_text, (30, int(bar_h * 0.35)), font_size=int(bar_h * 0.38), color=status_color)
                
                mode_str = ["原图模式", "人脸遮挡", "纯黑数字骨骼"][privacy_mode]
                canvas = draw_chinese_text_hd(canvas, f"模式: {mode_str} | [M] 切换 [T] 测试大屏 [Q] 退出", (w - 480, int(bar_h * 0.4)), font_size=int(bar_h * 0.28), color=COLOR_WHITE)

                panel_w = max(240, int(w * 0.22))
                panel_x = w - panel_w - 20
                panel_y = bar_h + 30
                panel_h = h - panel_y - 20
                
                draw_overlay_panel(canvas, panel_x, panel_y, panel_w, panel_h, alpha=0.4, border_color=COLOR_CYAN)

                canvas = draw_chinese_text_hd(canvas, "REAL-TIME METRICS / 姿态数据", (panel_x + 15, panel_y + 15), font_size=13, color=COLOR_CYAN)
                cv2.line(canvas, (panel_x + 15, panel_y + 35), (panel_x + panel_w - 15, panel_y + 35), (80, 80, 80), 1, cv2.LINE_AA)

                gauge_center = (panel_x + panel_w // 2, panel_y + 105)
                draw_gauge_hd(canvas, gauge_center, radius=45, angle_val=smooth_angle, threshold=TORSO_ANGLE_THRESHOLD)
                canvas = draw_chinese_text_hd(canvas, "躯干倾角 (ANGLE)", (panel_x + 15, panel_y + 118), font_size=12, color=COLOR_WHITE)
                angle_color = COLOR_RED if smooth_angle > TORSO_ANGLE_THRESHOLD else COLOR_GREEN
                canvas = draw_chinese_text_hd(canvas, f"{smooth_angle:.1f}°", (panel_x + panel_w - 65, panel_y + 115), font_size=16, color=angle_color)

                cv2.line(canvas, (panel_x + 15, panel_y + 145), (panel_x + panel_w - 15, panel_y + 145), (50, 50, 50), 1, cv2.LINE_AA)
                canvas = draw_chinese_text_hd(canvas, "下坠速度 (VELOCITY)", (panel_x + 15, panel_y + 158), font_size=12, color=COLOR_WHITE)
                
                bar_x = panel_x + 15
                bar_y = panel_y + 180
                bar_w = panel_w - 30
                cv2.rectangle(canvas, (bar_x, bar_y), (bar_x + bar_w, bar_y + 8), (40, 40, 40), -1)
                
                vel_ratio = min(max(smooth_velocity, 0.0) / 1.0, 1.0)
                fill_w = int(bar_w * vel_ratio)
                vel_color = COLOR_RED if smooth_velocity > FAST_DROP_VELOCITY else COLOR_CYAN
                cv2.rectangle(canvas, (bar_x, bar_y), (bar_x + fill_w, bar_y + 8), vel_color, -1)
                canvas = draw_chinese_text_hd(canvas, f"{smooth_velocity:.2f} m/s", (panel_x + panel_w - 75, panel_y + 156), font_size=13, color=vel_color)

                cv2.line(canvas, (panel_x + 15, panel_y + 205), (panel_x + panel_w - 15, panel_y + 205), (50, 50, 50), 1, cv2.LINE_AA)
                canvas = draw_chinese_text_hd(canvas, f"捕捉骨骼节点: {detected_points_count} / 33 点", (panel_x + 15, panel_y + 218), font_size=12, color=COLOR_CYAN)
                canvas = draw_chinese_text_hd(canvas, f"倾角阈值: {TORSO_ANGLE_THRESHOLD:.0f}°", (panel_x + 15, panel_y + 240), font_size=12, color=COLOR_WHITE)
                canvas = draw_chinese_text_hd(canvas, f"微信推送: 多节点图床已连接", (panel_x + 15, panel_y + 262), font_size=12, color=COLOR_GREEN)

                cv2.imshow(WINDOW_NAME, canvas)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == ord('Q'):
                    self.monitor_running = False
                    user_pressed_q = True
                    break
                elif key == ord('m') or key == ord('M'):
                    privacy_mode = (privacy_mode + 1) % 3
                elif key == ord('t') or key == ord('T'):
                    send_wechat_alarm("【系统测试】正在跳转至交互分析大屏...")
                    self.monitor_running = False
                    set_alarm_sound(False)
                    cap.release()
                    cv2.destroyAllWindows()
                    break

                time.sleep(0.005)

            except Exception as err:
                time.sleep(0.01)
                continue

        set_alarm_sound(False)
        if cap.isOpened():
            cap.release()
        cv2.destroyAllWindows()

        if user_pressed_q:
            print("👋 已安全彻底退出程序。")
            sys.exit(0)

        if not self.monitor_running and (key == ord('t') or key == ord('T')):
            self.open_gui_interface()

    def open_gui_interface(self):
        print("⏳ 正在载入图2视频交互分析大屏...")
        self.gui_window = FallDetectionGUI(parent_controller=self)
        self.gui_window.show()

        if os.path.exists(DEFAULT_VIDEO_PATH):
            self.gui_window.load_video(DEFAULT_VIDEO_PATH)
        else:
            self.gui_window.select_video()

    def resume_camera_monitor(self):
        print("⏳ 正在恢复摄像头实时监控模式...")
        self.gui_window = None
        gc.collect()
        self.start_camera_monitor()

    def run(self):
        self.start_camera_monitor()
        self.app.exec_()

if __name__ == "__main__":
    controller = ApplicationController()
    try:
        controller.run()
    except SystemExit:
        pass