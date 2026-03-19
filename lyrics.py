import os
import json
import re
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def _call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    response = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8192}
        }
    )

    if not response.ok:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text}")

    data = response.json()
    print("Gemini raw response:", json.dumps(data)[:500])

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"No candidates in Gemini response: {json.dumps(data)}")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"No parts in Gemini response: {json.dumps(data)}")

    return parts[0]["text"].strip()


def _parse_json(text):
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    return json.loads(text.strip())


def search_songs(query):
    """
    Returns a list of up to 6 songs matching the query.
    Handles both song titles and artist names.
    """
    prompt = f"""You are a music database. The user searched for: "{query}"

Determine if this is a song title search or an artist search, then return matching songs.

Return ONLY valid JSON, no markdown, no explanation:

{{
  "type": "song" or "artist",
  "artist_name": "Artist Name if artist search, else null",
  "results": [
    {{"title": "Song Title", "artist": "Artist Name"}},
    {{"title": "Song Title", "artist": "Artist Name"}}
  ]
}}

Rules:
- Return up to 6 results
- If it looks like an artist name, return their most popular/well-known songs
- If it looks like a song title, return the best matching songs (could be covers or songs by different artists)
- Order by popularity/relevance
- Only include real, well-known songs you are confident exist
"""
    raw = _call_gemini(prompt)
    try:
        return _parse_json(raw)
    except Exception as e:
        raise RuntimeError(f"Failed to parse search results: {e}\nRaw: {raw[:300]}")


def get_lyrics_and_chords(title, artist):
    """
    Returns a full chord sheet for a specific song by a specific artist.
    """
    prompt = f"""You are a music expert. Produce a complete chord sheet for:
Title: {title}
Artist: {artist}

Use inline chord markers like [C] [Am] [F] [G] placed immediately before the syllable they're played on.

Return ONLY valid JSON, no markdown, no explanation:

{{
  "title": "{title}",
  "artist": "{artist}",
  "key": "C",
  "bpm": 120,
  "sections": [
    {{
      "label": "Verse 1",
      "lines": [
        "[C]Twinkle twinkle [Am]little [F]star",
        "[G]How I wonder [C]what you [G]are"
      ]
    }}
  ]
}}

Rules:
- Place chord markers [X] immediately before the syllable/word they're played on
- Include ALL sections: intro, all verses, pre-chorus, chorus, bridge, outro
- Use standard chord notation: C, Dm, Em, F, G, Am, Bm, C#, F#, Bb, Eb etc.
- BPM approximate is fine
- Section labels: Intro, Verse 1, Verse 2, Pre-Chorus, Chorus, Bridge, Outro
"""
    raw = _call_gemini(prompt)
    try:
        return _parse_json(raw)
    except Exception as e:
        raise RuntimeError(f"Failed to parse chord sheet: {e}\nRaw: {raw[:300]}")
