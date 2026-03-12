"""
Alzar Robot Companion — Dashboard Server
Serves the web dashboard and handles real-time communication
with the robot via WebSockets.
"""

from flask import Flask, render_template, jsonify, Response
from flask_socketio import SocketIO, emit
import time
import threading
import subprocess
import cv2
import os
from dotenv import load_dotenv
from modules.vision import VisionAI
from modules.gps import GPSReader

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'alzar-robot-companion'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# --- Camera ---

class Camera:
    def __init__(self, device=0):
        self.device = device
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self._start()

    def _start(self):
        self.cap = cv2.VideoCapture(self.device)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            self.running = True
            threading.Thread(target=self._capture_loop, daemon=True).start()
            print(f"✅ Camera opened on /dev/video{self.device} — {int(self.cap.get(3))}x{int(self.cap.get(4))}")
        else:
            print(f"⚠️  Camera not available on /dev/video{self.device}")

    def _capture_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.1)

    def get_jpeg(self):
        with self.lock:
            if self.frame is None:
                return None
            _, jpeg = cv2.imencode('.jpg', self.frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            return jpeg.tobytes()

    def is_available(self):
        return self.running and self.cap is not None and self.cap.isOpened()


camera = Camera(device=0)


# --- Kinect v2 Camera (RGB-only via libfreenect2) ---

class KinectCamera:
    """
    Drives the kinect_capture subprocess, reads length-prefixed JPEG frames,
    and exposes get_jpeg() compatible with the existing Camera API.
    """
    BINARY = os.path.join(os.path.dirname(__file__), 'kinect_capture')

    def __init__(self):
        self.frame = None
        self.lock  = threading.Lock()
        self.running = False
        self.rgb_enabled = True   # False while robot is moving
        self._proc = None
        self._new_frame = threading.Event()  # set each time a fresh frame arrives
        self._start()

    def _start(self):
        if not os.path.isfile(self.BINARY):
            print("⚠️  kinect_capture binary not found — Kinect disabled")
            return
        try:
            self._proc = subprocess.Popen(
                [self.BINARY],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                start_new_session=True,  # own process group — no stale parent signals
            )
            self.running = True
            threading.Thread(target=self._read_loop,  daemon=True).start()
            threading.Thread(target=self._log_stderr, daemon=True).start()
            print("✅ Kinect v2 RGB stream started")
        except Exception as e:
            print(f"⚠️  Failed to start Kinect capture: {e}")
            threading.Thread(target=self._retry_loop, daemon=True).start()

    def _retry_loop(self):
        """Retry launching every 10s if the subprocess exits unexpectedly."""
        while True:
            time.sleep(10)
            if not self.running and os.path.isfile(self.BINARY):
                print("🔄 Retrying Kinect capture...")
                self._start()
                return

    def _read_loop(self):
        import struct
        stdout = self._proc.stdout
        while self.running:
            try:
                hdr = self._read_exact(stdout, 4)
                if hdr is None:
                    break
                sz = struct.unpack('<I', hdr)[0]
                if sz == 0 or sz > 10_000_000:
                    print(f"⚠️  Kinect: implausible frame size {sz}, skipping")
                    continue
                data = self._read_exact(stdout, sz)
                if data is None:
                    break
                with self.lock:
                    self.frame = data
                self._new_frame.set()  # wake any waiting generators
            except Exception as e:
                print(f"Kinect read error: {e}")
                break
        self.running = False
        self.frame = None
        print("⚠️  Kinect capture stream ended — will retry in 10s")
        threading.Thread(target=self._retry_loop, daemon=True).start()

    def _read_exact(self, fp, n):
        buf = b''
        while len(buf) < n:
            chunk = fp.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _log_stderr(self):
        for line in self._proc.stderr:
            print(f"[kinect] {line.decode(errors='replace').rstrip()}")

    def get_jpeg(self):
        """Return the latest JPEG frame, or None if RGB processing is disabled."""
        if not self.rgb_enabled:
            return None
        with self.lock:
            return self.frame

    def wait_for_new_frame(self, timeout: float = 0.5) -> bool:
        """Block until a fresh frame arrives (or timeout). Returns True if new frame ready."""
        got = self._new_frame.wait(timeout=timeout)
        if got:
            self._new_frame.clear()
        return got

    def is_available(self):
        return self.running and self.frame is not None

    def set_rgb_enabled(self, enabled: bool):
        """Enable or disable RGB frame delivery (e.g. disable while moving)."""
        self.rgb_enabled = enabled
        print(f"Kinect: RGB processing {'enabled' if enabled else 'disabled'}")

    def stop(self):
        self.running = False
        if self._proc:
            self._proc.terminate()


kinect = KinectCamera()


# --- TTS ---

PIPER_BIN = "/home/alzar/piper/piper/piper"
PIPER_MODEL = "/home/alzar/piper/voices/en_US-lessac-medium.onnx"


class TTS:
    """
    Text-to-speech using ElevenLabs (Matilda, Australian female).
    Falls back to Piper TTS (offline, ARM-native) if ElevenLabs is unavailable.
    Queued so commentary never overlaps.
    """
    def __init__(self, api_key: str = None, voice_id: str = None):
        self.queue = []
        self.lock = threading.Lock()
        self.speaking = False
        self.enabled = True
        self.api_key = api_key
        self.voice_id = voice_id or "XrExE9yKIg1WjnnlVkGX"  # Matilda
        self.use_elevenlabs = bool(api_key)
        self.use_piper = os.path.isfile(PIPER_BIN) and os.path.isfile(PIPER_MODEL)
        if self.use_elevenlabs:
            print(f"✅ TTS: ElevenLabs (Matilda) | fallback: {'Piper' if self.use_piper else 'espeak-ng'}")
        elif self.use_piper:
            print(f"✅ TTS: Piper (offline)")
        else:
            print(f"✅ TTS: espeak-ng (fallback)")

    def speak(self, text, priority=False):
        if not self.enabled:
            return
        with self.lock:
            if priority:
                self.queue.clear()
            self.queue.append(text)
        if not self.speaking:
            threading.Thread(target=self._process_queue, daemon=True).start()

    def _process_queue(self):
        self.speaking = True
        while True:
            with self.lock:
                if not self.queue:
                    self.speaking = False
                    return
                text = self.queue.pop(0)
            try:
                if self.use_elevenlabs:
                    self._speak_elevenlabs(text)
                elif self.use_piper:
                    self._speak_piper(text)
                else:
                    self._speak_espeak(text)
            except Exception as e:
                print(f"TTS error: {e}")
                self._speak_piper(text) if self.use_piper else self._speak_espeak(text)

    def _speak_elevenlabs(self, text: str):
        import requests, tempfile, os
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}
            },
            timeout=15
        )
        if r.status_code == 200:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(r.content)
                tmp = f.name
            subprocess.run(['ffplay', '-nodisp', '-autoexit', tmp],
                           capture_output=True, timeout=60)
            os.unlink(tmp)
        else:
            print(f"ElevenLabs error {r.status_code}: {r.text[:100]}")
            self._speak_piper(text) if self.use_piper else self._speak_espeak(text)

    def _speak_piper(self, text: str):
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        try:
            subprocess.run(
                [PIPER_BIN, '--model', PIPER_MODEL, '--output_file', tmp],
                input=text.encode(), capture_output=True, timeout=30
            )
            subprocess.run(['ffplay', '-nodisp', '-autoexit', tmp],
                           capture_output=True, timeout=60)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _speak_espeak(self, text: str):
        subprocess.run(
            ['espeak-ng', '-v', 'en-us+m3', '-s', '140', '-p', '38', text],
            timeout=30, capture_output=True
        )

    def stop(self):
        with self.lock:
            self.queue.clear()
        subprocess.run(['pkill', '-f', 'ffplay'], capture_output=True)
        subprocess.run(['pkill', '-f', 'espeak-ng'], capture_output=True)


tts = TTS(
    api_key=os.environ.get('ELEVENLABS_API_KEY'),
    voice_id=os.environ.get('ELEVENLABS_VOICE_ID', 'XrExE9yKIg1WjnnlVkGX')
)


# --- Vision AI ---

_openai_key = os.environ.get('OPENAI_API_KEY')
if _openai_key:
    vision = VisionAI(api_key=_openai_key)
    print("✅ Vision AI ready (GPT-4o-mini)")
else:
    vision = None
    print("⚠️  No OPENAI_API_KEY found — vision AI disabled")


# --- Simulated robot state (replace with real data later) ---
robot_state = {
    "connected": True,
    "battery": 87,
    "mode": "normal",          # normal | talkative | quiet
    "gps": {"lat": -33.8688, "lng": 151.2093, "accuracy": 5, "fix": 0, "sats": 0, "alt": 0},  # defaults until GPS fix
    "drone": {
        "status": "docked",    # docked | launching | airborne | returning | charging
        "battery": 92,
    },
    "camera": "ground",        # ground | drone
    "moving": False,
    "speed": 0,
    "kinect_mode": "stationary",  # stationary | moving
}

commentary_log = []


# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/state')
def get_state():
    return jsonify(robot_state)

@app.route('/api/commentary')
def get_commentary():
    return jsonify(commentary_log[-50:])  # Last 50 entries

@app.route('/video_feed')
def video_feed():
    """MJPEG stream from the ground camera."""
    def generate():
        while True:
            jpeg = camera.get_jpeg()
            if jpeg:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
            time.sleep(0.033)  # ~30 fps
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

def _make_placeholder_jpeg(width=320, height=180, text="Kinect initialising\u2026"):
    """Generate a dark placeholder JPEG using numpy + cv2."""
    import numpy as np
    img = np.zeros((height, width, 3), dtype=np.uint8)  # black frame
    img[:, :] = (18, 22, 30)  # dark panel colour
    cv2.putText(img, text, (20, height // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 90, 110), 1, cv2.LINE_AA)
    _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return buf.tobytes()

_KINECT_PLACEHOLDER = None  # lazily generated

@app.route('/kinect_feed')
def kinect_feed():
    """MJPEG stream from the Kinect v2 RGB camera."""
    global _KINECT_PLACEHOLDER
    if _KINECT_PLACEHOLDER is None:
        try:
            _KINECT_PLACEHOLDER = _make_placeholder_jpeg()
        except Exception:
            pass

    def generate():
        while True:
            if kinect.rgb_enabled:
                # Block until a genuinely new frame arrives (max 0.5s)
                kinect.wait_for_new_frame(timeout=0.5)
                jpeg = kinect.get_jpeg()
                if jpeg:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
                    continue
            # rgb disabled or no frame yet — send placeholder to keep connection alive
            if _KINECT_PLACEHOLDER:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + _KINECT_PLACEHOLDER + b'\r\n')
            time.sleep(0.5)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/camera_status')
def camera_status():
    return jsonify({
        "available": camera.is_available(),
        "kinect_available": kinect.is_available(),
    })

@app.route('/docs')
def docs():
    return render_template('docs.html')

@app.route('/hardware')
def hardware():
    return render_template('hardware.html')


# --- WebSocket events ---

@socketio.on('connect')
def on_connect():
    print(f'Client connected')
    emit('state_update', robot_state)
    emit('commentary_history', commentary_log[-20:])

@socketio.on('disconnect')
def on_disconnect():
    print(f'Client disconnected')

@socketio.on('set_mode')
def on_set_mode(data):
    mode = data.get('mode', 'normal')
    if mode in ('normal', 'talkative', 'quiet'):
        robot_state['mode'] = mode
        if vision:
            vision.set_cooldown(mode)
            vision.reset_scene()  # re-survey with new object count
        socketio.emit('state_update', robot_state)
        add_commentary(f"Switched to {mode} mode.", "system")

@socketio.on('set_camera')
def on_set_camera(data):
    camera = data.get('camera', 'ground')
    if camera in ('ground', 'drone', 'kinect'):
        robot_state['camera'] = camera
        socketio.emit('state_update', robot_state)

@socketio.on('set_kinect_mode')
def on_set_kinect_mode(data):
    """Toggle Kinect between stationary (RGB on) and moving (RGB off)."""
    mode = data.get('mode', 'stationary')
    if mode not in ('stationary', 'moving'):
        return
    robot_state['kinect_mode'] = mode
    kinect.set_rgb_enabled(mode == 'stationary')
    socketio.emit('state_update', robot_state)
    label = "stationary — RGB processing active" if mode == 'stationary' else "moving — RGB processing paused"
    add_commentary(f"Kinect mode: {label}.", "system")

@socketio.on('drone_launch')
def on_drone_launch():
    if robot_state['drone']['status'] == 'docked':
        robot_state['drone']['status'] = 'launching'
        socketio.emit('state_update', robot_state)
        add_commentary("Launching drone for aerial reconnaissance.", "system")
        # Simulate launch sequence
        def complete_launch():
            time.sleep(3)
            robot_state['drone']['status'] = 'airborne'
            socketio.emit('state_update', robot_state)
            add_commentary("Drone is airborne. Switching to aerial view.", "alzar")
        threading.Thread(target=complete_launch, daemon=True).start()

@socketio.on('drone_return')
def on_drone_return():
    if robot_state['drone']['status'] == 'airborne':
        robot_state['drone']['status'] = 'returning'
        socketio.emit('state_update', robot_state)
        add_commentary("Recalling drone.", "system")
        def complete_return():
            time.sleep(5)
            robot_state['drone']['status'] = 'docked'
            socketio.emit('state_update', robot_state)
            add_commentary("Drone docked safely.", "system")
        threading.Thread(target=complete_return, daemon=True).start()

@socketio.on('move')
def on_move(data):
    direction = data.get('direction')
    robot_state['moving'] = direction is not None
    socketio.emit('state_update', robot_state)

@socketio.on('request_commentary')
def on_request_commentary(data):
    question = data.get('question', '')
    if question == '__test_voice__':
        add_commentary("Voice test. I am Alzar, your travel companion. Ready to explore.", "alzar")
        return

    def _respond():
        if vision and camera.is_available():
            jpeg = camera.get_jpeg()
            if jpeg:
                text = vision.observe(jpeg, question=question)
                if text:
                    add_commentary(text, "alzar")
                    return
        add_commentary("I can't see anything right now — camera or AI unavailable.", "alzar")

    threading.Thread(target=_respond, daemon=True).start()





# --- Helpers ---

def add_commentary(text, source="alzar"):
    entry = {
        "text": text,
        "source": source,
        "timestamp": time.strftime("%H:%M:%S"),
    }
    commentary_log.append(entry)
    if len(commentary_log) > 500:
        commentary_log.pop(0)
    socketio.emit('commentary', entry)
    # Speak aloud — only Alzar's own commentary, not system messages or user input
    if source == "alzar":
        tts.speak(text)


@socketio.on('reset_scene')
def on_reset_scene():
    if vision:
        vision.reset_scene()
    add_commentary("Scene reset — scanning new environment.", "system")

@socketio.on('set_tts')
def on_set_tts(data):
    tts.enabled = data.get('enabled', True)
    socketio.emit('state_update', robot_state)

@socketio.on('tts_stop')
def on_tts_stop():
    tts.stop()


# --- Demo: simulate talkative mode commentary ---
def vision_loop():
    """
    Background loop: periodically observe the world and generate commentary.
    Frequency is controlled by vision.cooldown (set by talk mode).
    """
    print("Vision loop: waiting 5s for warmup...")
    time.sleep(5)
    print("Vision loop: starting observation cycle")
    while True:
        try:
            time.sleep(3)
            if robot_state['mode'] == 'quiet':
                continue
            if not vision:
                print("Vision loop: no vision AI")
                continue
            if not camera.is_available():
                print("Vision loop: camera not available")
                continue
            jpeg = camera.get_jpeg()
            if not jpeg:
                print("Vision loop: no jpeg frame")
                continue
            text = vision.observe(jpeg)
            if text:
                print(f"Vision loop: commentary → {text[:60]}...")
                add_commentary(text, "alzar")
        except Exception as e:
            print(f"Vision loop error: {e}")

threading.Thread(target=vision_loop, daemon=True).start()

# --- GPS ---
gps = GPSReader(robot_state, socketio=socketio)
gps.start()
print("✅ Vision loop started")


if __name__ == '__main__':
    print("🔮 Alzar Robot Companion — Dashboard starting on http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
