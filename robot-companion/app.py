"""
Alzar Robot Companion — Dashboard Server
Serves the web dashboard and handles real-time communication
with the robot via WebSockets.
"""

from flask import Flask, render_template, jsonify, Response
from flask_socketio import SocketIO, emit
import time
import threading
import cv2

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


# --- Simulated robot state (replace with real data later) ---
robot_state = {
    "connected": True,
    "battery": 87,
    "mode": "normal",          # normal | talkative | quiet
    "gps": {"lat": -33.8688, "lng": 151.2093, "accuracy": 5},  # Sydney default
    "drone": {
        "status": "docked",    # docked | launching | airborne | returning | charging
        "battery": 92,
    },
    "camera": "ground",        # ground | drone
    "moving": False,
    "speed": 0,
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

@app.route('/api/camera_status')
def camera_status():
    return jsonify({"available": camera.is_available()})


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
        socketio.emit('state_update', robot_state)
        add_commentary(f"Switched to {mode} mode.", "system")

@socketio.on('set_camera')
def on_set_camera(data):
    camera = data.get('camera', 'ground')
    if camera in ('ground', 'drone'):
        robot_state['camera'] = camera
        socketio.emit('state_update', robot_state)

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
    # Placeholder — replace with real AI call
    add_commentary(f"[Response to: '{question}'] — AI commentary coming soon.", "alzar")


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


# --- Demo: simulate talkative mode commentary ---
def simulate_commentary():
    """Periodically emit simulated commentary when in talkative mode."""
    sample_comments = [
        "I notice the light here has a warm quality — late afternoon, I'd estimate around 4 PM.",
        "There's an interesting architectural detail on that building — looks like 1970s brutalist style.",
        "The foot traffic here suggests we're near a transit hub or market.",
        "Wind speed is mild. Good conditions for a drone sweep if you want an aerial view.",
        "That signage ahead appears to be in multiple languages. We might be in a multicultural district.",
        "The shadows are lengthening — we've been moving for a while.",
    ]
    idx = 0
    while True:
        time.sleep(15)
        if robot_state['mode'] == 'talkative' and robot_state['connected']:
            add_commentary(sample_comments[idx % len(sample_comments)], "alzar")
            idx += 1

threading.Thread(target=simulate_commentary, daemon=True).start()


if __name__ == '__main__':
    print("🔮 Alzar Robot Companion — Dashboard starting on http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
