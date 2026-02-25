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
        self.last_response = ""
        self.cooldown = 20  # seconds between automatic observations

    def frame_to_b64(self, jpeg_bytes: bytes) -> str:
        return base64.standard_b64encode(jpeg_bytes).decode("utf-8")

    def observe(self, jpeg_bytes: bytes, question: str = None, history: list = None) -> str | None:
        """
        Analyse a camera frame and return commentary.
        - question: if provided, answer it specifically
        - history: list of previous commentary strings — Alzar won't repeat these topics
        Returns None if within cooldown (for automatic observations).
        """
        now = time.time()
        if question is None:
            with self.lock:
                if now - self.last_commentary_time < self.cooldown:
                    return None

        b64 = self.frame_to_b64(jpeg_bytes)

        # Build system prompt with history context
        system = SYSTEM_PROMPT
        if history:
            recent = history[-30:]  # last 30 observations
            history_text = "\n".join(f"- {h}" for h in recent)
            system += f"\n\nYou have already commented on the following — do NOT repeat or revisit these topics:\n{history_text}"

        if question:
            user_text = question
        else:
            user_text = "What's worth noticing right now? Pick something you haven't mentioned before."

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
                max_tokens=120,
                temperature=0.85,
            )
            text = response.choices[0].message.content.strip()

            if text:
                self.last_response = text
                with self.lock:
                    self.last_commentary_time = now
                return text

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
