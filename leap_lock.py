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
from typing import Any
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
        self.armed_lock = True
        self.armed_media = True
        self.running = True
        self.last_action_text = ""
        self.last_action_time = 0.0

    def set_action_text(self, text: str):
        self.last_action_text = text
        self.last_action_time = time.monotonic()
        print(f"👉 {text}")

    def process_gestures(self, fist_count: int, is_pinch: bool) -> None:
        now = time.monotonic()

        # Handle Lock (Two fists)
        if fist_count == 0:
            self.armed_lock = True
        
        if self.armed_lock and fist_count >= 2:
            if now - self.last_lock_at >= self.config.cooldown_seconds:
                self.set_action_text("Action: Verrouillage du Mac")
                self._lock_mac()
                self.last_lock_at = now
                self.armed_lock = False

        # Handle Pinch (Play/Pause)
        if not is_pinch:
            self.armed_media = True
        
        if self.armed_media and is_pinch:
            if now - self.last_media_at >= 1.0:
                self.set_action_text("Action: Play / Pause")
                self._play_pause()
                self.last_media_at = now
                self.armed_media = False

    def _lock_mac(self) -> None:
        if self.config.dry_run:
            print("Dry run: would lock macOS now.")
            return

        print("🔒 Two closed hands detected. Locking macOS.")
        import ctypes
        try:
            login = ctypes.CDLL('/System/Library/PrivateFrameworks/login.framework/Versions/Current/login')
            login.SACLockScreenImmediate()
        except Exception as e:
            print(f"Failed to lock screen using ctypes: {e}")
            subprocess.run(LOCK_COMMAND, check=False)

    def _play_pause(self) -> None:
        if self.config.dry_run:
            print("Dry run: would play/pause media now.")
            return

        print("🎵 Pinch detected. Toggling Play/Pause globally via MediaRemote.")
        import ctypes
        try:
            MR = ctypes.CDLL('/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote')
            # 2 corresponds to kMRTogglePlayPause
            MR.MRMediaRemoteSendCommand(2, 0)
        except Exception as e:
            print(f"Failed to play/pause using MediaRemote: {e}", file=sys.stderr)


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
            
            fist_count = sum(
                1 for hand in hands
                if isinstance(hand, dict) and "grabStrength" in hand and float(hand["grabStrength"]) >= config.close_threshold
            )
            is_pinching = any(
                isinstance(hand, dict) and "pinchStrength" in hand and float(hand["pinchStrength"]) >= 0.8
                for hand in hands
            )

            manager.process_gestures(fist_count, is_pinching)
                
    finally:
        ws.close()

def is_fist(hand_landmarks) -> bool:
    """Detect if hand is a fist using mediapipe landmarks."""
    wrist = hand_landmarks.landmark[0]
    
    fingers = [(8, 6), (12, 10), (16, 14), (20, 18)]
    
    curled_fingers = 0
    for tip_idx, pip_idx in fingers:
        tip = hand_landmarks.landmark[tip_idx]
        pip = hand_landmarks.landmark[pip_idx]
        
        tip_dist = math.hypot(tip.x - wrist.x, tip.y - wrist.y)
        pip_dist = math.hypot(pip.x - wrist.x, pip.y - wrist.y)
        
        if tip_dist < pip_dist:
            curled_fingers += 1
            
    return curled_fingers >= 3

def is_pinch(hand_landmarks) -> bool:
    """Detect if thumb and index are pinched together."""
    thumb = hand_landmarks.landmark[4]
    index = hand_landmarks.landmark[8]
    dist = math.hypot(thumb.x - index.x, thumb.y - index.y)
    return dist < 0.05

def find_valid_camera(default_id: int):
    indices_to_try = [default_id] + [i for i in range(4) if i != default_id]
    
    for i in indices_to_try:
        cap = cv2.VideoCapture(i)
        if not cap.isOpened():
            continue
            
        valid = False
        for _ in range(10):
            success, frame = cap.read()
            if success:
                brightness = cv2.mean(frame)[0]
                if brightness > 2.0:
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
    hands = mp_hands.Hands(
        model_complexity=0,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )

    last_check = time.monotonic()
    
    while manager.running and cap.isOpened():
        success, image = cap.read()
        if not success:
            continue

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

        fist_count = 0
        is_pinching = False
        
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                mp_drawing.draw_landmarks(
                    image, hand_landmarks, mp_hands.HAND_CONNECTIONS
                )
                
                if is_fist(hand_landmarks):
                    fist_count += 1
                if is_pinch(hand_landmarks):
                    is_pinching = True
        
        manager.process_gestures(fist_count, is_pinching)
        
        # Mirror image for display
        image_flipped = cv2.flip(image, 1)
        
        # Draw the last action text if it occurred within the last 2 seconds
        if time.monotonic() - manager.last_action_time < 2.0:
            # Black border for readability
            cv2.putText(image_flipped, manager.last_action_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 4, cv2.LINE_AA)
            # Yellow text
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
    parser.add_argument("--camera-id", type=int, default=0, help="Webcam ID (0 for default, 1 for built-in if iPhone is connected)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    return Config(
        url=args.url,
        close_threshold=args.close_threshold,
        open_threshold=args.open_threshold,
        hold_seconds=args.hold_seconds,
        cooldown_seconds=args.cooldown_seconds,
        camera_id=args.camera_id,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

def main() -> int:
    app = SmartLock(parse_args())
    signal.signal(signal.SIGINT, app.stop)
    signal.signal(signal.SIGTERM, app.stop)
    app.run()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
