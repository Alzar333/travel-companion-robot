/**
 * Alzar Robot Companion — Dashboard JS
 * Handles WebSocket connection, state updates, map, and controls.
 */

// ─── Socket.IO ───────────────────────────
const socket = io();

socket.on('connect', () => {
  setConnectionStatus(true);
});

socket.on('disconnect', () => {
  setConnectionStatus(false);
});

socket.on('state_update', (state) => {
  updateState(state);
});

socket.on('commentary', (entry) => {
  addCommentEntry(entry);
});

socket.on('commentary_history', (entries) => {
  commentaryLog.innerHTML = '';
  commentCount = 0;
  entries.forEach(addCommentEntry);
});


// ─── Map ─────────────────────────────────
let map, robotMarker, droneMarker, trackLine;
let trackPoints = [];

function initMap() {
  map = L.map('map', {
    center: [-33.8688, 151.2093], // Sydney default
    zoom: 16,
    zoomControl: true,
    attributionControl: false,
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
  }).addTo(map);

  // Robot marker
  const robotIcon = L.divIcon({
    html: '<div class="map-robot-marker">🔮</div>',
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    className: '',
  });

  robotMarker = L.marker([-33.8688, 151.2093], { icon: robotIcon }).addTo(map);

  // Track line
  trackLine = L.polyline([], {
    color: '#7c5cfc',
    weight: 2,
    opacity: 0.7,
  }).addTo(map);
}

function updateMapPosition(lat, lng) {
  if (!map) return;
  const latlng = [lat, lng];
  robotMarker.setLatLng(latlng);
  trackPoints.push(latlng);
  trackLine.setLatLngs(trackPoints);
  // Only follow if near edge
  const bounds = map.getBounds();
  if (!bounds.contains(latlng)) {
    map.panTo(latlng);
  }

  document.getElementById('gps-status').textContent =
    `📡 ${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}

// Add custom map marker style
const markerStyle = document.createElement('style');
markerStyle.textContent = `
  .map-robot-marker {
    font-size: 22px;
    filter: drop-shadow(0 0 6px #7c5cfc);
  }
`;
document.head.appendChild(markerStyle);

initMap();


// ─── State Updates ────────────────────────
function updateState(state) {
  // Battery
  const rb = state.battery ?? '—';
  document.getElementById('battery-robot').textContent = `${rb}%`;
  document.getElementById('battery-robot').style.color = rb < 20 ? 'var(--red)' : 'var(--text)';

  const db = state.drone?.battery ?? '—';
  document.getElementById('battery-drone').textContent = `${db}%`;
  document.getElementById('drone-battery-label').textContent = `${db}%`;

  // Mode
  const modeLabels = { normal: '💬 Normal', talkative: '🎙️ Talkative', quiet: '🤫 Quiet' };
  document.getElementById('mode-label').textContent = modeLabels[state.mode] ?? state.mode;
  ['quiet', 'normal', 'talkative'].forEach(m => {
    document.getElementById(`mode-${m}`)?.classList.toggle('active', state.mode === m);
  });

  // GPS
  if (state.gps?.lat && state.gps?.lng) {
    updateMapPosition(state.gps.lat, state.gps.lng);
  }

  // Drone
  const droneStatus = state.drone?.status ?? 'unknown';
  const droneBadgeEl = document.getElementById('drone-badge');
  const droneEmojis = {
    docked:     '🚁 Docked',
    launching:  '🚀 Launching…',
    airborne:   '✈️ Airborne',
    returning:  '↩ Returning…',
    charging:   '🔋 Charging',
  };
  droneBadgeEl.textContent = droneEmojis[droneStatus] ?? droneStatus;

  const launchBtn = document.getElementById('btn-launch');
  const returnBtn = document.getElementById('btn-return');
  launchBtn.disabled = droneStatus !== 'docked';
  returnBtn.disabled = droneStatus !== 'airborne';

  // Camera toggle
  ['ground', 'drone'].forEach(cam => {
    document.getElementById(`btn-cam-${cam}`)?.classList.toggle('active', state.camera === cam);
  });
}


// ─── Commentary ───────────────────────────
const commentaryLog = document.getElementById('commentary-log');
let commentCount = 0;

function addCommentEntry(entry) {
  // Remove empty placeholder
  const empty = commentaryLog.querySelector('.commentary-empty');
  if (empty) empty.remove();

  commentCount++;
  document.getElementById('commentary-count').textContent =
    `${commentCount} entr${commentCount === 1 ? 'y' : 'ies'}`;

  const div = document.createElement('div');
  div.className = 'comment-entry';
  div.innerHTML = `
    <div class="comment-meta">
      <span class="comment-source ${entry.source}">${entry.source === 'alzar' ? '🔮 Alzar' : entry.source === 'system' ? '⚙️ System' : '👤 You'}</span>
      <span class="comment-time">${entry.timestamp}</span>
    </div>
    <div class="comment-text">${escapeHtml(entry.text)}</div>
  `;

  commentaryLog.appendChild(div);
  commentaryLog.scrollTop = commentaryLog.scrollHeight;
}

function escapeHtml(text) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(text));
  return d.innerHTML;
}


// ─── Controls ────────────────────────────
function setMode(mode) {
  socket.emit('set_mode', { mode });
}

function setCamera(camera) {
  socket.emit('set_camera', { camera });
}

function droneLaunch() {
  socket.emit('drone_launch');
}

function droneReturn() {
  socket.emit('drone_return');
}

function move(direction) {
  socket.emit('move', { direction });
}

function setTTS(enabled) {
  socket.emit('set_tts', { enabled });
  document.getElementById('btn-tts-on').classList.toggle('active', enabled);
  document.getElementById('btn-tts-off').classList.toggle('active', !enabled);
}

function testVoice() {
  socket.emit('request_commentary', { question: '__test_voice__' });
}

function resetScene() {
  socket.emit('reset_scene');
}

function askQuestion() {
  const input = document.getElementById('question-input');
  const question = input.value.trim();
  if (!question) return;

  // Show in log as user message
  addCommentEntry({
    text: question,
    source: 'user',
    timestamp: new Date().toLocaleTimeString('en-AU', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }),
  });

  socket.emit('request_commentary', { question });
  input.value = '';
}

function handleQuestionKey(e) {
  if (e.key === 'Enter') askQuestion();
}


// ─── Connection Status ────────────────────
function setConnectionStatus(connected) {
  const dot = document.getElementById('connection-dot');
  const label = document.getElementById('connection-label');
  const pill = document.getElementById('connection-pill');

  if (connected) {
    dot.classList.add('connected');
    dot.classList.remove('disconnected');
    label.textContent = 'Connected';
  } else {
    dot.classList.remove('connected');
    dot.classList.add('disconnected');
    label.textContent = 'Disconnected';
  }
}

// ─── Camera Feed ─────────────────────────
function onStreamFrame() {
  // Called once when the MJPEG stream first connects
  document.getElementById('camera-stream').style.display = 'block';
  document.getElementById('camera-placeholder').style.display = 'none';
  setLiveStatus(true);
}

function onStreamError() {
  setLiveStatus(false);
  showCameraPlaceholder();
}

function showCameraPlaceholder() {
  document.getElementById('camera-stream').style.display = 'none';
  document.getElementById('camera-placeholder').style.display = 'flex';
}

function setLiveStatus(live) {
  const badge = document.getElementById('live-badge');
  const label = document.getElementById('live-label');
  badge.classList.toggle('is-live', live);
  badge.classList.toggle('is-stale', !live);
  label.textContent = live ? 'LIVE' : 'STALE';
}

function refreshCamera() {
  const stream = document.getElementById('camera-stream');
  const btn = document.getElementById('btn-refresh-cam');
  btn.textContent = '↻';
  btn.disabled = true;
  // Bust cache by appending timestamp
  stream.src = `/video_feed?t=${Date.now()}`;
  setTimeout(() => {
    btn.textContent = '⟳';
    btn.disabled = false;
  }, 1500);
}

function checkCameraStatus() {
  fetch('/api/camera_status')
    .then(r => r.json())
    .then(data => {
      const stream = document.getElementById('camera-stream');
      const placeholder = document.getElementById('camera-placeholder');
      if (data.available) {
        setLiveStatus(true);
        if (stream.style.display === 'none') {
          stream.src = `/video_feed?t=${Date.now()}`;
          stream.style.display = 'block';
          placeholder.style.display = 'none';
        }
      } else {
        showCameraPlaceholder();
        setLiveStatus(false);
      }
    })
    .catch(() => { showCameraPlaceholder(); setLiveStatus(false); });
}

// Check camera on load and periodically
checkCameraStatus();
setInterval(checkCameraStatus, 5000);


// ─── Keyboard shortcuts ───────────────────
document.addEventListener('keydown', (e) => {
  // Don't capture if typing in input
  if (document.activeElement.tagName === 'INPUT') return;

  switch (e.key) {
    case 'ArrowUp':    e.preventDefault(); move('forward'); break;
    case 'ArrowDown':  e.preventDefault(); move('backward'); break;
    case 'ArrowLeft':  e.preventDefault(); move('left'); break;
    case 'ArrowRight': e.preventDefault(); move('right'); break;
    case ' ':          e.preventDefault(); move(null); break;
    case 't':          setMode('talkative'); break;
    case 'n':          setMode('normal'); break;
    case 'q':          setMode('quiet'); break;
  }
});

document.addEventListener('keyup', (e) => {
  if (document.activeElement.tagName === 'INPUT') return;
  const arrows = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
  if (arrows.includes(e.key)) move(null);
});
