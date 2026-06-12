# Kinesis

Kinesis is a smart hand-tracking daemon for macOS that automatically switches between your Mac's built-in webcam and an external Leap Motion controller to recognize hand gestures. It runs transparently in the background.

## Features

- **Seamless Camera Switching**: Uses the Mac FaceTime HD webcam when the Mac is open, and automatically switches to the Leap Motion (via WebSocket) when the Mac is closed/docked.
- **Smart Camera Filtering**: Automatically detects and ignores infrared/grayscale cameras (like the Leap Motion IR sensor) and iOS Continuity Cameras to prevent conflicts.
- **Native macOS Actions**: Uses direct system APIs (MediaRemote, login.framework) instead of brittle UI scripting, avoiding the need for constant Accessibility permissions.
- **Always-on Background Daemon**: Runs invisibly as a `launchd` service.

## Gestures

Gestures require strict hold-times to prevent accidental triggers while you type or move naturally.

| Action | Gesture | Hold Time | Description |
| :--- | :--- | :--- | :--- |
| **Lock Screen** | 🔒 Two Fists | 1.0s | Close both hands into fists simultaneously. |
| **Play / Pause** | 🎵 Pinch | 0.8s | Pinch your thumb and index finger together. Works across all media (Spotify, Music, Chrome, VLC). |
| **Mute / Unmute Mic** | 🎤 "Shh" | 1.0s | Extend your index finger while keeping your thumb and other fingers curled. |

## Installation

1. Install Python 3.12.
2. Create the virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Compile the Leap Motion WebSocket bridge:
   ```bash
   cd UltraleapTrackingWebSocket
   mkdir build && cd build
   cmake .. && make
   ```

## Running the Background Service

Kinesis is designed to run automatically in the background using a macOS LaunchAgent.

**Start the service (Load):**
```bash
launchctl load ~/Library/LaunchAgents/com.enzogagg.kinesis.plist
```

**Pause the service temporarily:**
```bash
launchctl stop com.enzogagg.kinesis
```

**Resume the service:**
```bash
launchctl start com.enzogagg.kinesis
```

**Uninstall the service (Unload):**
```bash
launchctl unload ~/Library/LaunchAgents/com.enzogagg.kinesis.plist
```

## Logs

Even though it runs invisibly, Kinesis writes gesture logs and errors. To monitor them in real-time:
```bash
tail -f /tmp/kinesis.out
tail -f /tmp/kinesis.err
```

## Testing

Run the gesture unit tests using pytest:
```bash
.venv/bin/pytest tests/
```
