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
        self.covered_topics: list[str] = []  # explicit list of already-covered subjects

    def frame_to_b64(self, jpeg_bytes: bytes) -> str:
        return base64.standard_b64encode(jpeg_bytes).decode("utf-8")

    def observe(self, jpeg_bytes: bytes, question: str = None) -> str | None:
        """
        Analyse a camera frame and return commentary.
        - question: if provided, answer it specifically
        Returns None if within cooldown (for automatic observations).
        """
        now = time.time()
        if question is None:
            with self.lock:
                if now - self.last_commentary_time < self.cooldown:
                    return None

        b64 = self.frame_to_b64(jpeg_bytes)

        # Build system prompt with explicit covered objects
        system = SYSTEM_PROMPT

        if not question:
            covered_str = ", ".join(self.covered_topics) if self.covered_topics else "none yet"
            system += f"""

STRICT RULES FOR THIS RESPONSE:
1. First, identify ALL distinct physical objects visible (e.g. desk, PC, screen, AC unit, chair, lamp...).
2. These objects have ALREADY been commented on — you MUST skip them entirely: {covered_str}
3. Pick ONE object NOT in that list. If every visible object is already covered, reply: NOTHING_NEW
4. Format your reply EXACTLY as two lines:
   OBJECT: <the physical object name in 1-3 words>
   <your commentary sentence(s) about it>"""

        if question:
            user_text = question
        else:
            user_text = "What physical object haven't you commented on yet?"

        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
            },
            {"type": "text", "text": user_text},
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=130,
                temperature=0.7,
            )
            raw = response.choices[0].message.content.strip()

            if not raw or raw == "NOTHING_NEW":
                print("Vision: nothing new to observe")
                return None

            # Parse OBJECT: / commentary format
            if raw.startswith("OBJECT:"):
                lines = raw.split("\n", 1)
                obj = lines[0].replace("OBJECT:", "").strip().lower()
                commentary = lines[1].strip() if len(lines) > 1 else ""
                if obj and obj not in self.covered_topics:
                    with self.lock:
                        self.covered_topics.append(obj)
                        self.last_commentary_time = now
                    print(f"Vision: [{obj}] → {commentary[:60]}...")
                    print(f"Vision: covered → {self.covered_topics}")
                    return commentary if commentary else None
                else:
                    # Already covered — skip silently
                    with self.lock:
                        self.last_commentary_time = now
                    return None
            else:
                # Fallback: model didn't follow format, use raw but don't track
                with self.lock:
                    self.last_commentary_time = now
                return raw

        except Exception as e:
            print(f"Vision AI error: {e}")

        return None

    def set_cooldown(self, mode: str):
        """Adjust observation frequency based on talk mode."""
        self.cooldown = {
            "talkative": 12,
            "normal":    30,
            "quiet":    999,
        }.get(mode, 30)
