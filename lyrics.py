import os
import anthropic
import json
import re

ANTHROPIC_API_KEY = "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"

def fetch_lyrics(title: str, artist: str) -> dict:
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = f"""Return the full lyrics for "{title}" by {artist if artist else "unknown artist"}.

Format your response as a JSON object exactly like this:
{{
  "title": "song title",
  "artist": "artist name",
  "sections": [
    {{
      "label": "Verse 1",
      "lines": [
        {{"words": ["word1", "word2", "word3"]}}
      ]
    }}
  ]
}}

Rules:
- Split lyrics into sections like Verse 1, Pre-Chorus, Chorus, Bridge etc.
- Each line of lyrics becomes one entry in "lines"
- Each word in a line goes into the "words" array
- Do not include chords, only lyrics
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
        data = json.loads(raw)
        for section in data.get("sections", []):
            for line in section.get("lines", []):
                if "chords" not in line:
                    line["chords"] = [""] * len(line.get("words", []))
        return data
    except Exception as e:
        print(f"Lyrics fetch error: {e}")
        return {"title": title, "artist": artist, "key": "C", "sections": [{"label": "Error", "lines": [{"chords": [""], "words": ["Lyrics not found"]}]}]}
