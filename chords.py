import os
import anthropic
import json
import re

ANTHROPIC_API_KEY = "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"

def detect_chords(audio_path: str, title: str = "", artist: str = "") -> dict:
    if title:
        result = lookup_chords_from_ug(title, artist)
        if result:
            return result
    return {"key": "C", "bpm": None, "timeline": [], "sections": []}

def lookup_chords_from_ug(title: str, artist: str = "") -> dict | None:
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = f"""Return the chords for "{title}" by {artist if artist else "unknown artist"}.

Format your response as a JSON object exactly like this:
{{
  "key": "C",
  "sections": [
    {{
      "label": "Verse 1",
      "lines": [
        {{
          "chords": ["Am", "", "F", "", "C", ""],
          "words": ["Only", "know", "you", "love", "her", "when"]
        }}
      ]
    }}
  ]
}}

Rules:
- Include the actual lyrics words with chords placed above the correct syllable
- Each line must have the same number of entries in "chords" and "words"
- Put the chord name where it is played, empty string "" where no chord change happens
- Split into sections: Verse 1, Pre-Chorus, Chorus, Bridge etc.
- "key" should be the key the song is in
- Return ONLY the JSON, no other text"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except Exception as e:
        print(f"Chord lookup error: {e}")
        return None
