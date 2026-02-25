"""
Alzar Vision Module
Captures a frame from the camera and generates travel commentary
using GPT-4o vision. The AI responds as Alzar — a knowledgeable,
curious travel companion.
"""

import base64
import time
import threading
from openai import OpenAI

# System prompt — Alzar's personality and role
SYSTEM_PROMPT = """You are Alzar, an AI travel companion riding aboard a small robot. 
You observe the world through a camera and share insightful, curious commentary about what you see.

Your personality:
- Knowledgeable but conversational — like a well-travelled friend, not a tour guide
- Genuinely curious and observational — notice details others might miss
- Concise: 1-3 sentences per observation unless asked for more
- Occasionally wry or dry humour when appropriate
- Confident opinions, not hedging everything

What to comment on:
- Architecture, design, history of buildings or spaces
- Interesting objects, signs, textures, lighting
- What the environment suggests about the place or time of day
- Unusual or noteworthy details
- Context clues about where you might be

What NOT to do:
- Don't say "I can see..." or "The image shows..." — just observe naturally
- Don't repeat the same observation twice
- Don't be overly enthusiastic or use filler phrases
- Don't describe the obvious; find the interesting angle
- Keep it under 40 words unless it's genuinely fascinating

When answering a direct question, answer it specifically and add one extra observation if relevant."""


class VisionAI:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o-mini"
        self.lock = threading.Lock()
        self.last_commentary_time = 0
        self.cooldown = 20  # seconds between automatic observations
        self.scene_queue: list[str] = []   # ordered list of objects to comment on
        self.covered_topics: list[str] = []  # objects already spoken about
        self.scene_scanned = False           # has this scene been surveyed yet
        self.max_objects = 3                 # how many objects to cover (mode-dependent)

    def frame_to_b64(self, jpeg_bytes: bytes) -> str:
        return base64.standard_b64encode(jpeg_bytes).decode("utf-8")

    def _scan_scene(self, b64: str) -> list[str]:
        """
        One-shot scene survey: identify and rank the top 4 most interesting
        objects visible. Returns an ordered list of object names.
        """
        n = self.max_objects
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "You are a sharp observer. Your job is to survey a scene and identify "
                        "the most interesting physical objects to comment on."
                    )},
                    {"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}},
                        {"type": "text", "text": (
                            f"List the {n} most interesting distinct physical objects visible, "
                            f"ranked from most to least interesting. "
                            f"Reply with ONLY a numbered list, one object per line, 1-4 words each. "
                            f"Example:\n1. gaming PC\n2. wooden desk\n3. dual monitors"
                        )},
                    ]},
                ],
                max_tokens=max(40, n * 12),
                temperature=0.3,
            )
            raw = r.choices[0].message.content.strip()
            objects = []
            for line in raw.splitlines():
                line = line.strip()
                # Strip any "1." / "2." etc numbering
                import re
                line = re.sub(r"^\d+\.\s*", "", line)
                if line:
                    objects.append(line.lower())
            print(f"Vision: scene survey ({n} objects) → {objects}")
            return objects[:n]
        except Exception as e:
            print(f"Vision scan error: {e}")
            return []

    def _comment_on(self, b64: str, obj: str) -> str | None:
        """Generate a commentary sentence specifically about one named object."""
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}},
                        {"type": "text",
                         "text": f"Comment specifically on the {obj}. 1-3 sentences, be insightful and concise."},
                    ]},
                ],
                max_tokens=100,
                temperature=0.85,
            )
            return r.choices[0].message.content.strip()
        except Exception as e:
            print(f"Vision comment error: {e}")
            return None

    def reset_scene(self):
        """Call this when the robot moves to a new location."""
        with self.lock:
            self.scene_queue.clear()
            self.covered_topics.clear()
            self.scene_scanned = False
        print("Vision: scene reset — ready for new environment")

    def observe(self, jpeg_bytes: bytes, question: str = None) -> str | None:
        """
        Observe the scene and return commentary.
        - Automatic: surveys scene once → builds top-4 queue → works through it
        - question: direct question answered against current frame
        """
        now = time.time()
        b64 = self.frame_to_b64(jpeg_bytes)

        # --- Direct question mode ---
        if question:
            return self._comment_on(b64, question)

        # --- Cooldown check ---
        with self.lock:
            if now - self.last_commentary_time < self.cooldown:
                return None

        # --- Scene survey (first time) ---
        if not self.scene_scanned:
            objects = self._scan_scene(b64)
            with self.lock:
                self.scene_queue = objects
                self.scene_scanned = True
                self.last_commentary_time = now  # pause after scan
            return None  # let cooldown pass before first comment

        # --- Work through queue ---
        with self.lock:
            if not self.scene_queue:
                # All done — stay quiet
                return None
            obj = self.scene_queue.pop(0)
            self.covered_topics.append(obj)
            self.last_commentary_time = now

        commentary = self._comment_on(b64, obj)
        if commentary:
            print(f"Vision: [{obj}] → {commentary[:60]}...")
            print(f"Vision: remaining → {self.scene_queue}")
        return commentary

    def set_cooldown(self, mode: str):
        """Adjust observation frequency and object count based on talk mode."""
        self.cooldown = {
            "talkative": 12,
            "normal":    30,
            "quiet":    999,
        }.get(mode, 30)
        self.max_objects = {
            "talkative": 6,
            "normal":    3,
            "quiet":     0,
        }.get(mode, 3)
