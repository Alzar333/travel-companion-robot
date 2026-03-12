#!/usr/bin/env python3
"""
Alzar Voice Assistant
---------------------
Wake word ("hey jarvis" placeholder) → record → Whisper transcribe
→ OpenClaw /v1/chat/completions → ElevenLabs TTS → speaker

To use a real "Hey Alzar" wake word, train a custom model at:
  https://colab.research.google.com/drive/1q1oe2zOyZelnHz577NV6eqMQh1YVm7SY
and pass the .onnx path via WAKE_MODEL env var.
"""

import os
import sys
import time
import json
import wave
import struct
import tempfile
import threading
import subprocess
import warnings

# Suppress onnxruntime GPU warning
os.environ["ORT_LOGGING_LEVEL"] = "3"
warnings.filterwarnings("ignore")

import re
import numpy as np
import pyaudio
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ─── Config ───────────────────────────────────────────────────────────────────

SAMPLE_RATE       = 16000
CHUNK_SIZE        = 1280        # 80ms frames (required by openwakeword)
FORMAT            = pyaudio.paInt16
CHANNELS          = 1

SILENCE_THRESHOLD = 600         # RMS energy — tune up if too sensitive
SILENCE_DURATION  = 1.8         # seconds of silence to stop recording
MAX_RECORD_SECS   = 15          # hard cap on recording length

WAKE_THRESHOLD    = 0.5         # confidence score to trigger

# Default model: hey_jarvis (placeholder until custom "hey alzar" is trained)
# Override with: WAKE_MODEL=/path/to/hey_alzar.onnx python voice_assistant.py
WAKE_MODEL = os.environ.get(
    "WAKE_MODEL",
    os.path.join(
        os.path.dirname(__file__),
        "venv/lib/python3.14/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx"
    )
)

# OpenClaw API (reads token from openclaw.json)
OPENCLAW_URL   = "http://127.0.0.1:18789/v1/chat/completions"
OPENCLAW_TOKEN = None   # loaded below from openclaw.json
SESSION_USER   = "voice-home"   # stable key = persistent conversation

# ElevenLabs
ELEVENLABS_API_KEY  = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "XrExE9yKIg1WjnnlVkGX")

# Piper (offline fallback)
PIPER_BIN   = "/home/alzar/piper/piper/piper"
PIPER_MODEL = "/home/alzar/piper/voices/en_US-lessac-medium.onnx"

# ─── Load OpenClaw token ───────────────────────────────────────────────────────

def _load_openclaw_token():
    try:
        cfg_path = os.path.expanduser("~/.openclaw/openclaw.json")
        with open(cfg_path) as f:
            cfg = json.load(f)
        return cfg.get("gateway", {}).get("auth", {}).get("token", "")
    except Exception as e:
        print(f"⚠️  Could not read OpenClaw token: {e}")
        return ""

OPENCLAW_TOKEN = _load_openclaw_token()

# ─── TTS ──────────────────────────────────────────────────────────────────────

class TTS:
    def __init__(self):
        self.speaking = False
        self._lock = threading.Lock()
        self.use_elevenlabs = bool(ELEVENLABS_API_KEY)
        self.use_piper = os.path.isfile(PIPER_BIN) and os.path.isfile(PIPER_MODEL)

        if self.use_elevenlabs:
            print(f"🔊 TTS: ElevenLabs (Matilda) | fallback: {'Piper' if self.use_piper else 'espeak-ng'}")
        elif self.use_piper:
            print("🔊 TTS: Piper (offline)")
        else:
            print("🔊 TTS: espeak-ng (last resort)")

    def speak(self, text: str):
        """Speak text (blocks until done)."""
        with self._lock:
            self.speaking = True
            try:
                if self.use_elevenlabs:
                    self._elevenlabs(text)
                elif self.use_piper:
                    self._piper(text)
                else:
                    self._espeak(text)
            except Exception as e:
                print(f"⚠️  TTS error: {e}")
                if self.use_piper:
                    self._piper(text)
                else:
                    self._espeak(text)
            finally:
                self.speaking = False

    def _elevenlabs(self, text: str):
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={"text": text, "model_id": "eleven_multilingual_v2",
                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
            timeout=15
        )
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(resp.content)
            tmp = f.name
        try:
            subprocess.run(["ffplay", "-nodisp", "-autoexit", tmp],
                           capture_output=True, check=True)
        finally:
            os.unlink(tmp)

    def _piper(self, text: str):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        try:
            subprocess.run([PIPER_BIN, "--model", PIPER_MODEL, "--output_file", tmp],
                           input=text.encode(), capture_output=True, check=True)
            subprocess.run(["ffplay", "-nodisp", "-autoexit", tmp],
                           capture_output=True, check=True)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _espeak(self, text: str):
        subprocess.run(["espeak-ng", "-v", "en-us+f3", "-s", "150", text], check=True)


tts = TTS()

# ─── Text cleaning (strip markdown before TTS) ────────────────────────────────

def clean_for_speech(text: str) -> str:
    """Remove markdown and symbols that TTS reads aloud awkwardly."""
    # Remove code blocks entirely
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]*`", "", text)
    # Remove markdown headers (### Heading → Heading)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    # Remove bullet points and list markers
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # Remove links [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove bare URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove remaining special chars that get read aloud
    text = re.sub(r"[|\\~<>]", "", text)
    # Collapse extra whitespace/blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

# ─── Whisper transcription ─────────────────────────────────────────────────────

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

def transcribe(audio_data: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """Transcribe PCM audio bytes via OpenAI Whisper API."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    try:
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data)
        with open(tmp, "rb") as audio_file:
            result = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        return result.strip() if isinstance(result, str) else result.text.strip()
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

# ─── OpenClaw chat ─────────────────────────────────────────────────────────────

def ask_alzar(message: str) -> str:
    """Send message to Alzar via OpenClaw chat completions endpoint."""
    headers = {
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
        "x-openclaw-agent-id": "main"
    }
    payload = {
        "model": "openclaw",
        "messages": [{"role": "user", "content": message}],
        "user": SESSION_USER   # stable session key for conversation context
    }
    resp = requests.post(OPENCLAW_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()

# ─── Audio helpers ─────────────────────────────────────────────────────────────

def rms(chunk: bytes) -> float:
    """Root mean square energy of a PCM chunk."""
    samples = struct.unpack(f"<{len(chunk)//2}h", chunk)
    return (sum(s*s for s in samples) / len(samples)) ** 0.5

def record_until_silence(stream: pyaudio.Stream) -> bytes:
    """Record audio frames until silence detected, return raw PCM bytes."""
    print("🎙  Listening...")
    frames = []
    silent_chunks = 0
    max_chunks = int(SAMPLE_RATE / CHUNK_SIZE * MAX_RECORD_SECS)
    silence_chunks_needed = int(SAMPLE_RATE / CHUNK_SIZE * SILENCE_DURATION)

    for _ in range(max_chunks):
        data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
        frames.append(data)
        if rms(data) < SILENCE_THRESHOLD:
            silent_chunks += 1
            if silent_chunks >= silence_chunks_needed:
                break
        else:
            silent_chunks = 0

    return b"".join(frames)

# ─── Wake word detection ───────────────────────────────────────────────────────

def load_wake_model():
    from openwakeword.model import Model
    if not os.path.isfile(WAKE_MODEL):
        print(f"❌ Wake model not found: {WAKE_MODEL}")
        sys.exit(1)
    print(f"🔮 Loading wake model: {os.path.basename(WAKE_MODEL)}")
    return Model(wakeword_model_paths=[WAKE_MODEL])

# ─── Main loop ─────────────────────────────────────────────────────────────────

def main():
    print("\n✨ Alzar Voice Assistant")
    print(f"   Wake word : {os.path.basename(WAKE_MODEL).replace('.onnx','')}")
    print(f"   OpenClaw  : {OPENCLAW_URL}")
    print(f"   Session   : {SESSION_USER}")
    print()

    if not OPENCLAW_TOKEN:
        print("❌ No OpenClaw token found — cannot continue.")
        sys.exit(1)

    oww = load_wake_model()

    pa = pyaudio.PyAudio()

    # Find the BRIO microphone (or default)
    mic_index = None
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0 and "brio" in info["name"].lower():
            mic_index = i
            print(f"🎤 Using mic: {info['name']} (index {i})")
            break
    if mic_index is None:
        print("🎤 BRIO not found — using default input device")

    stream = pa.open(
        rate=SAMPLE_RATE,
        channels=CHANNELS,
        format=FORMAT,
        input=True,
        input_device_index=mic_index,
        frames_per_buffer=CHUNK_SIZE
    )

    tts.speak("Alzar is ready. Say hey Jarvis to activate.")
    print("\n👂 Waiting for wake word...")

    model_name = os.path.basename(WAKE_MODEL).replace(".onnx", "")

    try:
        while True:
            # Read a chunk for wake word detection
            audio_chunk = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            audio_np = np.frombuffer(audio_chunk, dtype=np.int16)

            # Feed to openwakeword
            prediction = oww.predict(audio_np)

            # Check scores
            score = prediction.get(model_name, 0.0)
            if score >= WAKE_THRESHOLD:
                oww.reset()
                print(f"\n🔔 Wake word detected! (score: {score:.2f})")

                # Play a short chime / acknowledgement
                tts.speak("Yes?")

                # Record the user's question
                audio_data = record_until_silence(stream)

                if len(audio_data) < CHUNK_SIZE * 4:
                    print("⚠️  Too short — ignoring")
                    print("\n👂 Waiting for wake word...")
                    continue

                # Transcribe
                print("📝 Transcribing...")
                try:
                    text = transcribe(audio_data)
                except Exception as e:
                    print(f"❌ Transcription error: {e}")
                    tts.speak("Sorry, I couldn't hear that clearly.")
                    print("\n👂 Waiting for wake word...")
                    continue

                if not text:
                    print("⚠️  Empty transcript — ignoring")
                    print("\n👂 Waiting for wake word...")
                    continue

                print(f"🗣  You: {text}")

                # Ask Alzar
                print("🔮 Asking Alzar...")
                try:
                    response = ask_alzar(text)
                except Exception as e:
                    print(f"❌ OpenClaw error: {e}")
                    tts.speak("Sorry, something went wrong on my end.")
                    print("\n👂 Waiting for wake word...")
                    continue

                print(f"💬 Alzar: {response[:200]}{'...' if len(response) > 200 else ''}")

                # Speak the response (cleaned of markdown)
                tts.speak(clean_for_speech(response))
                print("\n👂 Waiting for wake word...")

    except KeyboardInterrupt:
        print("\n\n👋 Shutting down.")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


if __name__ == "__main__":
    main()
