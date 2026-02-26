# 🔮 Travel Companion Robot

> *A machine that sees the world and has things to say about it.*

An AI-powered travel companion robot built on Raspberry Pi 5. It observes its surroundings through a camera, generates spoken commentary using vision AI, knows where it is via GPS, and roams the world on a repurposed robot vacuum base — with a drone for aerial scouting.

---

## ✅ Current Status

| Feature | Status |
|---|---|
| Web dashboard (mission control UI) | ✅ Live |
| Live camera feed (MJPEG stream) | ✅ Live |
| Vision AI commentary (GPT-4o-mini) | ✅ Live |
| ElevenLabs TTS (Matilda voice) | ✅ Live |
| Talk modes: Quiet / Normal / Talkative | ✅ Live |
| Project documentation (`/docs`) | ✅ Live |
| GPS integration | 🔜 Next |
| Robot vacuum base (Xiaomi S40C) | 🔜 Next |
| Offline vision (Ollama / LLaVA) | 📋 Planned |
| Drone platform (iFlight) | 📋 Planned |

---

## 🛠 Hardware

- **Raspberry Pi 5** (16GB RAM)
- **Logitech BRIO 4K** — `/dev/video0`, streaming at 1280×720
- **Aiwa ASP-0222** Bluetooth speaker
- **Xiaomi Robot Vacuum S40C** — ground mobility platform (via `python-miio`)
- **iFlight drone** (TBD) — aerial scouting & launch capability

---

## 🧰 Tech Stack

- **Backend:** Python 3, Flask, Flask-SocketIO
- **Vision AI:** OpenAI GPT-4o-mini with vision
- **TTS:** ElevenLabs API (Matilda, Australian female) + espeak-ng fallback
- **Frontend:** Leaflet.js map, WebSocket, MJPEG stream
- **Audio:** ffplay → PipeWire → Bluetooth speaker

---

## 🚀 Running the Dashboard

```bash
cd robot-companion
cp .env.example .env        # add your API keys
pip install -r requirements.txt
python app.py
```

Open `http://<pi-ip>:5000` for the mission control dashboard.  
Open `http://<pi-ip>:5000/docs` for the project documentation page.

---

## 🔑 Environment Variables

Create `robot-companion/.env`:

```env
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=XrExE9yKIg1WjnnlVkGX   # Matilda (default)
```

---

## 📖 Documentation

Full project log, milestones, hardware inventory, and roadmap:  
**`http://<pi-ip>:5000/docs`** — *For the Greater Good*

---

*Built by Irwin. Powered by Alzar 🔮*
