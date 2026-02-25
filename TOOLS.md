# TOOLS.md - Local Notes

## Hardware (Raspberry Pi 5)

### Camera
- **Logitech BRIO Ultra HD** → `/dev/video0`
- Resolution: 1280x720 @ 30fps (MJPEG mode)
- Can do 4K but 720p is fine for streaming

### Bluetooth Speakers
- **Aiwa ASP-0222** → MAC: `A6:01:6D:F0:30:1B` (Trusted, offline when not on)
- **PLT_BBFIT** (Plantronics BackBeat Fit) → MAC: `0C:E0:E4:B3:57:BF`
- Connect with: `bluetoothctl connect A6:01:6D:F0:30:1B`

### Robot Vacuum Base
- **Xiaomi Robot Vacuum S40C** — not yet connected
- Python library: `python-miio`

### Network
- Pi IP: `192.168.86.43`
- Dashboard: `http://192.168.86.43:5000`

## Robot Companion Dashboard

- **Location:** `~/workspace/robot-companion/`
- **Run:** `cd robot-companion && venv/bin/python app.py`
- **Camera feed:** `/video_feed` (MJPEG stream)
- **WebSocket:** Flask-SocketIO, threading mode

## TTS (planned)
- Output to Aiwa ASP-0222 Bluetooth speaker
- Candidate: ElevenLabs via `sag` skill, or pyttsx3/espeak-ng for offline
