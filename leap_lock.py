#!/usr/bin/env python3
"""Lock macOS or control media with Leap Motion / Webcam hand gestures."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, List
import math

import websocket

try:
    import cv2
    import mediapipe as mp
except ImportError:
    cv2 = None
    mp = None

DEFAULT_WS_URL = "ws://127.0.0.1:6437/v6.json"
LOCK_COMMAND = (
    "osascript",
    "-e",
    'tell application "System Events" to keystroke "q" using {control down, command down}',
)

@dataclass(frozen=True)
class Config:
    url: str
    close_threshold: float
    open_threshold: float
    hold_seconds: float
    cooldown_seconds: float
    camera_id: int
    dry_run: bool
    verbose: bool

@dataclass
class HandState:
    is_fist: bool
    is_pinch: bool
    is_index_up: bool
    is_open: bool

def is_clamshell_closed() -> bool:
    try:
        output = subprocess.check_output(
            ["ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"], text=True
        )
        for line in output.splitlines():
            if "AppleClamshellState" in line and "Yes" in line:
                return True
        return False
    except Exception:
        return False

class GestureManager:
    def __init__(self, config: Config):
        self.config = config
        
        self.last_lock_at = 0.0
        self.last_media_at = 0.0
        self.last_shh_at = 0.0
        self.last_swipe_at = 0.0
        
        self.armed_lock = True
        self.armed_media = True
        self.armed_shh = True
        
        self.running = True
        self.last_action_text = ""
        self.last_action_time = 0.0
        
        # Timers to prevent accidental triggers (Strict 1-second holds for everything)
        self.pinch_start_time = 0.0
        self.lock_start_time = 0.0
        self.shh_start_time = 0.0

    def set_action_text(self, text: str):
        self.last_action_text = text
        self.last_action_time = time.monotonic()
        print(f"👉 {text}")

    def process_gestures(self, hand_states: List[HandState]) -> None:
        now = time.monotonic()
        
        fist_count = sum(1 for h in hand_states if h.is_fist)
        is_pinch = any(h.is_pinch for h in hand_states)
        is_index_up = any(h.is_index_up for h in hand_states)

        # 1. LOCK (2 Fists for 1s)
        if fist_count >= 2:
            if self.lock_start_time == 0.0:
                self.lock_start_time = now
            elif now - self.lock_start_time >= 1.0:
                if self.armed_lock and (now - self.last_lock_at >= self.config.cooldown_seconds):
                    self.set_action_text("Action: Verrouillage du Mac 🔒")
                    self._lock_mac()
                    self.last_lock_at = now
                    self.armed_lock = False
        else:
            self.lock_start_time = 0.0
            if fist_count == 0:
                self.armed_lock = True

        # 2. PLAY / PAUSE (Pinch strictly for 0.8s to avoid accidental triggers)
        if is_pinch:
            if self.pinch_start_time == 0.0:
                self.pinch_start_time = now
            elif now - self.pinch_start_time >= 0.8:
                if self.armed_media and (now - self.last_media_at >= 1.0):
                    self.set_action_text("Action: Play / Pause 🎵")
                    self._play_pause()
                    self.last_media_at = now
                    self.armed_media = False
        else:
            self.pinch_start_time = 0.0
            self.armed_media = True

        # 3. MUTE MICROPHONE (Index up "Shh" strictly for 1.0s)
        if is_index_up:
            if self.shh_start_time == 0.0:
                self.shh_start_time = now
            elif now - self.shh_start_time >= 1.0:
                if self.armed_shh and (now - self.last_shh_at >= 1.0):
                    self.set_action_text("Action: Toggle Micro 🎤")
                    self._toggle_mute()
                    self.last_shh_at = now
                    self.armed_shh = False
        else:
            self.shh_start_time = 0.0
            self.armed_shh = True

    def _lock_mac(self) -> None:
        if self.config.dry_run: return
        import ctypes
        try:
            login = ctypes.CDLL('/System/Library/PrivateFrameworks/login.framework/Versions/Current/login')
            login.SACLockScreenImmediate()
        except Exception:
            subprocess.run(LOCK_COMMAND, check=False)

    def _play_pause(self) -> None:
        if self.config.dry_run: return
        import ctypes
        try:
            MR = ctypes.CDLL('/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote')
            MR.MRMediaRemoteSendCommand(2, 0)
        except Exception: pass

    def _next_track(self):
        if self.config.dry_run: return
        import ctypes
        try:
            MR = ctypes.CDLL('/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote')
            MR.MRMediaRemoteSendCommand(4, 0)
        except Exception: pass

    def _prev_track(self):
        if self.config.dry_run: return
        import ctypes
        try:
            MR = ctypes.CDLL('/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote')
            MR.MRMediaRemoteSendCommand(5, 0)
        except Exception: pass

    def _vol_up(self):
        if self.config.dry_run: return
        subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) + 15)"], check=False)

    def _vol_down(self):
        if self.config.dry_run: return
        subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) - 15)"], check=False)

    def _toggle_mute(self):
        if self.config.dry_run: return
        script = '''
        set currentMicVol to input volume of (get volume settings)
        if currentMicVol > 0 then
            set volume input volume 0
        else
            set volume input volume 100
        end if
        '''
        subprocess.run(["osascript", "-e", script], check=False)


def run_leap_motion(config: Config, manager: GestureManager) -> None:
    ws = websocket.create_connection(config.url, timeout=5)
    print(f"✅ Caméra sélectionnée : Leap Motion (WebSocket {config.url})")
    try:
        while manager.running:
            ws.settimeout(2.0)
            try:
                frame_data = ws.recv()
            except websocket.WebSocketTimeoutException:
                if not is_clamshell_closed():
                    print("Lid opened. Switching to webcam.")
                    return
                continue
            
            frame = json.loads(frame_data)
            hands = frame.get("hands") or []
            
            hand_states = []
            for hand in hands:
                if not isinstance(hand, dict): continue
                
                x_mm = hand.get("palmPosition", [0,0,0])[0]
                y_mm = hand.get("palmPosition", [0,0,0])[1]
                
                # Normalize approx to 0-1
                x = (x_mm + 200) / 400.0
                y = 1.0 - (y_mm / 400.0)
                
                grab = float(hand.get("grabStrength", 0))
                pinch = float(hand.get("pinchStrength", 0))
                extended = hand.get("extended", [False]*5)
                
                is_fist = grab >= config.close_threshold
                is_pinch = pinch >= 0.8
                is_open = grab <= 0.1 and pinch <= 0.1
                is_index_up = extended[1] and not extended[2] and not extended[3] and not extended[4] and not extended[0] # Thumb must be curled
                
                hand_states.append(HandState(is_fist, is_pinch, is_index_up, is_open))

            manager.process_gestures(hand_states)
                
    finally:
        ws.close()


def is_fist(hand_landmarks) -> bool:
    wrist = hand_landmarks.landmark[0]
    fingers = [(8, 6), (12, 10), (16, 14), (20, 18)]
    curled = 0
    for tip_idx, pip_idx in fingers:
        tip, pip = hand_landmarks.landmark[tip_idx], hand_landmarks.landmark[pip_idx]
        if math.hypot(tip.x - wrist.x, tip.y - wrist.y) < math.hypot(pip.x - wrist.x, pip.y - wrist.y):
            curled += 1
    return curled >= 3

def is_open(hand_landmarks) -> bool:
    wrist = hand_landmarks.landmark[0]
    fingers = [(8, 6), (12, 10), (16, 14), (20, 18)]
    ext = 0
    for tip_idx, pip_idx in fingers:
        tip, pip = hand_landmarks.landmark[tip_idx], hand_landmarks.landmark[pip_idx]
        if math.hypot(tip.x - wrist.x, tip.y - wrist.y) > math.hypot(pip.x - wrist.x, pip.y - wrist.y):
            ext += 1
    return ext >= 3

def is_index_up(hand_landmarks) -> bool:
    wrist = hand_landmarks.landmark[0]
    def is_ext(tip_idx, pip_idx):
        t, p = hand_landmarks.landmark[tip_idx], hand_landmarks.landmark[pip_idx]
        return math.hypot(t.x - wrist.x, t.y - wrist.y) > math.hypot(p.x - wrist.x, p.y - wrist.y)
    
    # Check that thumb is not widely extended (thumb tip vs pinky base)
    thumb_tip = hand_landmarks.landmark[4]
    pinky_base = hand_landmarks.landmark[17]
    thumb_ext = math.hypot(thumb_tip.x - pinky_base.x, thumb_tip.y - pinky_base.y) > 0.3
    
    return is_ext(8, 6) and not is_ext(12, 10) and not is_ext(16, 14) and not is_ext(20, 18) and not thumb_ext

def is_pinch(hand_landmarks) -> bool:
    thumb, index = hand_landmarks.landmark[4], hand_landmarks.landmark[8]
    return math.hypot(thumb.x - index.x, thumb.y - index.y) < 0.05

def find_valid_camera(default_id: int):
    base_order = [1, 0, 2, 3]
    indices_to_try = [default_id] + [i for i in base_order if i != default_id]
    
    for i in indices_to_try:
        cap = cv2.VideoCapture(i)
        if not cap.isOpened(): continue
        
        valid = False
        for _ in range(10):
            success, frame = cap.read()
            if success:
                b, g, r = cv2.mean(frame)[:3]
                if ((b + g + r) / 3.0) > 5.0 and (abs(b - g) + abs(b - r) + abs(g - r)) > 1.0:
                    valid = True
                    break
            time.sleep(0.05)
            
        if valid:
            print(f"✅ Caméra sélectionnée : Webcam du Mac (index {i})")
            return cap
        cap.release()
    return None

def run_webcam(config: Config, manager: GestureManager) -> None:
    print("Started Webcam tracking. Searching for valid camera...")
    if not cv2 or not mp:
        print("OpenCV or Mediapipe not installed.", file=sys.stderr)
        time.sleep(2)
        return
        
    cap = find_valid_camera(config.camera_id)
    if cap is None:
        print("No valid camera found! (All returned black frames or failed).", file=sys.stderr)
        time.sleep(2)
        return
        
    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    hands = mp_hands.Hands(model_complexity=0, min_detection_confidence=0.5, min_tracking_confidence=0.5)

    last_check = time.monotonic()
    while manager.running and cap.isOpened():
        success, image = cap.read()
        if not success: continue

        now = time.monotonic()
        if now - last_check > 2.0:
            last_check = now
            if is_clamshell_closed():
                print("Lid closed. Switching to Leap Motion.")
                break

        image.flags.writeable = False
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = hands.process(image)

        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        hand_states = []
        if results.multi_hand_landmarks:
            for hl in results.multi_hand_landmarks:
                mp_drawing.draw_landmarks(image, hl, mp_hands.HAND_CONNECTIONS)
                hand_states.append(HandState(
                    is_fist=is_fist(hl),
                    is_pinch=is_pinch(hl),
                    is_index_up=is_index_up(hl),
                    is_open=is_open(hl)
                ))
        
        manager.process_gestures(hand_states)
        
        image_flipped = cv2.flip(image, 1)
        if time.monotonic() - manager.last_action_time < 2.0:
            cv2.putText(image_flipped, manager.last_action_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(image_flipped, manager.last_action_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2, cv2.LINE_AA)
            
        cv2.imshow('Mac Webcam - Hand Tracking', image_flipped)
        if cv2.waitKey(5) & 0xFF == 27:
            manager.running = False
            break

    cap.release()
    cv2.destroyAllWindows()

class SmartLock:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.manager = GestureManager(config)
        self.ws_process = None

    def start_websocket_server(self):
        ws_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "UltraleapTrackingWebSocket", "build", "Ultraleap-Tracking-WS")
        if os.path.exists(ws_path):
            print("🚀 Démarrage du pont WebSocket en arrière-plan...")
            self.ws_process = subprocess.Popen([ws_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print(f"⚠️ Attention: Serveur WebSocket introuvable à {ws_path}", file=sys.stderr)

    def stop(self, *_: Any) -> None:
        self.manager.running = False
        if self.ws_process is not None:
            print("\n🛑 Arrêt du pont WebSocket...")
            self.ws_process.terminate()
            self.ws_process.wait()
            self.ws_process = None

    def run(self) -> None:
        self.start_websocket_server()
        while self.manager.running:
            try:
                if is_clamshell_closed():
                    run_leap_motion(self.config, self.manager)
                else:
                    run_webcam(self.config, self.manager)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                print(f"Tracking failed: {exc}", file=sys.stderr)
                if self.manager.running:
                    print("Retrying in 2 seconds...", file=sys.stderr)
                    time.sleep(2)

def parse_args() -> Config:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_WS_URL, help="Leap WebSocket URL.")
    parser.add_argument("--close-threshold", type=float, default=0.75)
    parser.add_argument("--open-threshold", type=float, default=0.35)
    parser.add_argument("--hold-seconds", type=float, default=0.05)
    parser.add_argument("--cooldown-seconds", type=float, default=3.0)
    parser.add_argument("--camera-id", type=int, default=0, help="Webcam ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    return Config(
        url=args.url, close_threshold=args.close_threshold, open_threshold=args.open_threshold,
        hold_seconds=args.hold_seconds, cooldown_seconds=args.cooldown_seconds,
        camera_id=args.camera_id, dry_run=args.dry_run, verbose=args.verbose,
    )

def main() -> int:
    app = SmartLock(parse_args())
    signal.signal(signal.SIGINT, app.stop)
    signal.signal(signal.SIGTERM, app.stop)
    app.run()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
