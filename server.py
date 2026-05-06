#!/usr/bin/env python3
"""
Vinge Studios — local dev server.
Zero external dependencies — uses only Python stdlib.

Usage:
  1. Add your key to api-key.txt (replace the placeholder line)
  2. Run:   python3 server.py
  3. Open:  http://localhost:3000
"""

import http.server
import json
import os
import ssl
import urllib.request
import urllib.error
from pathlib import Path

# macOS Python doesn't ship with SSL certificates, so we bypass verification
# for this local dev tool (only calls api.anthropic.com).
_ssl_ctx = ssl._create_unverified_context()

PORT = int(os.environ.get("PORT", 3000))
SERVE_DIR = Path(__file__).parent


def load_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    txt_file = SERVE_DIR / "api-key.txt"
    if txt_file.exists():
        key = txt_file.read_text().strip().strip("\"'")
        if key and not key.startswith("paste"):
            return key
    env_file = SERVE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


# ── Prompts ────────────────────────────────────────────────────────────────

IDENTIFY_PROMPT = """You are an expert botanist with decades of field experience. Analyze the image and identify the plant shown.

Return ONLY valid JSON — no markdown, no code fences, no extra text. Use this exact structure:

{
  "commonName": "Common plant name",
  "botanicalName": "Genus species",
  "family": "Plant family",
  "confidence": "high",
  "difficulty": "Beginner",
  "overview": "Write 2–3 rich paragraphs covering the plant's origin, natural habitat, why it makes a great houseplant, and any distinctive traits.",
  "careGuide": {
    "light": "Describe ideal light conditions in 1–2 sentences.",
    "water": "Describe watering frequency and method in 1–2 sentences.",
    "humidity": "Describe humidity needs in 1–2 sentences.",
    "temperature": "Describe ideal temperature range in 1–2 sentences.",
    "soil": "Describe ideal soil mix in 1–2 sentences.",
    "fertilizer": "Describe feeding schedule in 1–2 sentences."
  },
  "funFacts": [
    "An interesting fact about this plant.",
    "Another interesting fact.",
    "A third interesting fact."
  ],
  "toxicity": "Describe toxicity to pets and humans in one sentence."
}

Allowed values — confidence: "high" | "medium" | "low". difficulty: "Beginner" | "Intermediate" | "Expert".
If no plant is clearly visible, set commonName to "No plant detected" and use overview to explain what you see instead."""


HEALTH_PROMPT = """You are an expert plant doctor and horticulturist. The user has uploaded a photo of a plant they are worried about. Carefully examine the image for signs of distress — yellowing, browning, wilting, spots, pests, root problems, or anything abnormal.

Return ONLY valid JSON — no markdown, no code fences, no extra text. Use this exact structure:

{
  "plantName": "Best guess at the plant species, or 'Unknown plant' if unclear",
  "diagnosis": "Short name of the main problem, e.g. 'Overwatering / Root Rot'",
  "severity": "mild",
  "overview": "Write 2–3 paragraphs explaining what you see in the photo, what is causing the problem, and why it happens. Be warm and reassuring in tone.",
  "symptoms": [
    "Visible symptom one",
    "Visible symptom two",
    "Visible symptom three"
  ],
  "immediateActions": [
    "First thing to do right now",
    "Second urgent action",
    "Third urgent action"
  ],
  "careAdjustments": {
    "watering": "Specific watering change needed.",
    "light": "Any light adjustment required.",
    "soil": "Any repotting or soil advice.",
    "humidity": "Humidity recommendation.",
    "fertilizer": "Whether to feed or hold off, and why."
  },
  "recoveryTimeline": "Realistic timeframe for recovery, e.g. '3–6 weeks with consistent care'",
  "prognosis": "good",
  "preventionTips": [
    "How to prevent this in future",
    "Another prevention tip",
    "A third prevention tip"
  ]
}

Allowed values — severity: "mild" | "moderate" | "severe". prognosis: "good" | "fair" | "poor".
If the plant looks healthy, set diagnosis to "No issues found" and severity to "mild", and use overview to reassure the user.
If no plant is visible, set plantName to "No plant detected" and explain in overview."""


BUILD_PROMPT_TEMPLATE = """You are an expert interior designer and plant stylist. The user has uploaded a photo of a space they want to decorate with plants and decor items in a specific style.

Requested style: {style}
Plant care experience: {level} — {level_note}

Carefully study the photo — note the existing furniture, light sources, empty floor space, surfaces like shelves and tables, and wall areas. Then recommend 6–8 specific plants and decor items that would transform this space in the requested style. When suggesting plants, choose varieties that are well-suited for a {level} plant owner.

Return ONLY valid JSON — no markdown, no code fences, no extra text. Use this exact structure:

{{
  "style": "{style}",
  "overview": "2–3 sentences describing exactly how you would transform this specific space in the {style} style. Reference actual features you can see in the photo.",
  "designNote": "One practical tip about pulling the whole look together.",
  "totalEstimate": "$250–500",
  "items": [
    {{
      "id": 1,
      "type": "plant",
      "name": "Fiddle Leaf Fig",
      "placement": "Empty corner to the left of the window",
      "description": "Adds dramatic height and a bold focal point. The bright indirect light from the window will keep it thriving.",
      "priceRange": "$60–120",
      "searchTerms": "fiddle leaf fig indoor plant large",
      "x": 15,
      "y": 60
    }}
  ]
}}

Rules:
- x and y are integers 0–100 representing the percentage position from the top-left of the image where the item should be placed (x=0 is far left, x=100 is far right, y=0 is top, y=100 is bottom). Be as accurate as possible based on the actual location in the photo.
- Mix plants and decor items (pots, vases, baskets, wall art, throws, candles, etc.) appropriate for the {style} style.
- Plant difficulty must match the experience level: {level} — {level_note}.
- type must be exactly "plant" or "decor".
- Keep priceRange realistic for the item type.
- searchTerms should be a good Amazon/Etsy search query for buying this exact item."""


PRUNE_PROMPT = """You are an expert horticulturist and plant pruning specialist. The user has uploaded 1–4 photos of a plant from different angles. Carefully analyze all images and identify specific pruning points on each photo.

Return ONLY valid JSON — no markdown, no code fences, no extra text. Use this exact structure:

{
  "plantName": "Best guess at plant species, or 'Unknown plant' if unclear",
  "overview": "2–3 sentences describing the plant's current condition and overall pruning approach.",
  "pruningGoal": "One sentence describing the primary benefit of the recommended pruning.",
  "images": [
    {
      "imageIndex": 0,
      "pruningPoints": [
        {
          "x": 45,
          "y": 62,
          "label": "Cut dead stem at base",
          "type": "dead"
        }
      ]
    }
  ]
}

Rules:
- x and y are integers 0–100: percentage position from the top-left of that specific image (x=0 left, x=100 right, y=0 top, y=100 bottom). Place each point precisely on the stem, leaf, or branch to cut.
- type must be exactly "dead", "shape", or "optional":
  - "dead" — remove dead, dying, or diseased growth
  - "shape" — trim to encourage bushier growth, redirect energy, or improve plant form
  - "optional" — beneficial but not urgent cuts
- label: under 8 words, specific (e.g. "Remove yellowing lower leaf").
- Include 2–5 pruning points per image where relevant. If an image needs no pruning, use an empty pruningPoints array.
- imageIndex is 0-based and must match the order the images were provided.
- Only include entries for images that were actually provided — never invent extra image entries."""


# ── HTTP Handler ───────────────────────────────────────────────────────────

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/identify-plant":
            self._handle(IDENTIFY_PROMPT)
        elif self.path == "/api/health-check":
            self._handle(HEALTH_PROMPT)
        elif self.path == "/api/build-space":
            self._handle_build()
        elif self.path == "/api/prune-plant":
            self._handle_prune()
        else:
            self.send_error(404)

    def _handle_build(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            style = body.get("style", "Modern").strip()
            level = body.get("experienceLevel", "Beginner").strip()
            level_notes = {
                "Beginner":     "easy-care, forgiving, hard-to-kill varieties only",
                "Intermediate": "plants with moderate care needs; interesting foliage or blooms are fine",
                "Expert":       "rare, demanding, or specialty plants are encouraged",
            }
            level_note = level_notes.get(level, level_notes["Beginner"])
            prompt = BUILD_PROMPT_TEMPLATE.format(style=style, level=level, level_note=level_note)
            self._call_claude(prompt, body)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle(self, prompt):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            self._call_claude(prompt, body)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_prune(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            images = body.get("images", [])
            if not images:
                self._send_json(400, {"error": "No images provided."})
                return
            self._call_claude_multi(PRUNE_PROMPT, images)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _call_claude_multi(self, prompt, images):
        try:
            api_key = load_api_key()
            if not api_key:
                self._send_json(400, {"error": "ANTHROPIC_API_KEY not set. Add it to api-key.txt."})
                return

            content = []
            for img in images:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["mediaType"],
                        "data": img["image"],
                    },
                })
            content.append({"type": "text", "text": prompt})

            payload = json.dumps({
                "model": "claude-opus-4-7",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": content}],
            }).encode()

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )

            with urllib.request.urlopen(req, context=_ssl_ctx) as resp:
                result = json.loads(resp.read())

            text = result["content"][0]["text"].strip()
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1] if len(parts) > 1 else parts[0]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()

            self._send_json(200, json.loads(text))

        except urllib.error.HTTPError as e:
            self._send_json(500, {"error": f"Anthropic API error: {e.read().decode()}"})
        except json.JSONDecodeError as e:
            self._send_json(500, {"error": f"Could not parse response: {e}"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _call_claude(self, prompt, body):
        try:

            api_key = load_api_key()
            if not api_key:
                self._send_json(400, {"error": "ANTHROPIC_API_KEY not set. Add it to api-key.txt."})
                return

            payload = json.dumps({
                "model": "claude-opus-4-7",
                "max_tokens": 1800,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": body["mediaType"],
                                "data": body["image"],
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            }).encode()

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )

            with urllib.request.urlopen(req, context=_ssl_ctx) as resp:
                result = json.loads(resp.read())

            text = result["content"][0]["text"].strip()
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1] if len(parts) > 1 else parts[0]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()

            self._send_json(200, json.loads(text))

        except urllib.error.HTTPError as e:
            self._send_json(500, {"error": f"Anthropic API error: {e.read().decode()}"})
        except json.JSONDecodeError as e:
            self._send_json(500, {"error": f"Could not parse response: {e}"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()}  {fmt % args}")


if __name__ == "__main__":
    api_key = load_api_key()
    status = "✓ API key loaded" if api_key else "⚠  No API key — add ANTHROPIC_API_KEY to api-key.txt"
    print(f"\n  🌿 Vinge Studios")
    print(f"  {status}")
    print(f"  Running at http://localhost:{PORT}\n")
    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
