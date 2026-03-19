import os
import json
import re
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

CHORD_SHEET_PROMPT = """You are a music expert. Given a song title and artist, produce a complete chord sheet in a specific JSON format.

The chord sheet format uses inline chord markers like [C] [Am] [F] [G] placed immediately before the syllable they're played on, inline with the lyrics.

Return ONLY valid JSON, no markdown, no explanation. Format:

{
  "title": "Song Title",
  "artist": "Artist Name",
  "key": "C",
  "bpm": 120,
  "sections": [
    {
      "label": "Verse 1",
      "lines": [
        "[C]Twinkle twinkle [Am]little [F]star",
        "[G]How I wonder [C]what you [G]are"
      ]
    },
    {
      "label": "Chorus",
      "lines": [
        "[F]Up above the [C]world so [G]high",
        "[F]Like a [C]diamond [G]in the [C]sky"
      ]
    }
  ]
}

Rules:
- Place chord markers [X] immediately before the syllable/word they're played on
- Include all verses, chorus, bridge, outro — the full song
- Use standard chord notation: C, Dm, Em, F, G, Am, Bm, etc. Sharps: C#, F#. Flats: Bb, Eb
- BPM should be approximate if unknown
- Section labels: Verse 1, Verse 2, Pre-Chorus, Chorus, Bridge, Outro, Intro
- If you don't know the song well, use a common key and simple chords that fit the style
"""


def _call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it in Render environment variables.")

    response = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8192}
        }
    )
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    return json.loads(text.strip())


def _parse_response(raw: str, fallback_title: str) -> dict:
    try:
        return _parse_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return {
            "error": f"Failed to parse chord sheet: {str(e)}",
            "raw": raw[:500],
            "title": fallback_title,
            "artist": "",
            "key": "",
            "bpm": None,
            "sections": []
        }


def get_lyrics_and_chords_from_search(query: str) -> dict:
    prompt = f"{CHORD_SHEET_PROMPT}\n\nSong: {query}"
    raw = _call_gemini(prompt)
    return _parse_response(raw, query)


def get_lyrics_and_chords_from_url(url: str) -> dict:
    prompt = f"""{CHORD_SHEET_PROMPT}

The user provided this YouTube URL: {url}
Identify the song from the URL if possible and return the chord sheet.
If you cannot identify it, return: {{"error": "Could not identify song from URL"}}"""

    raw = _call_gemini(prompt)

    try:
        parsed = _parse_json(raw)
        if "error" in parsed and "sections" not in parsed:
            title = _get_youtube_title(url)
            if title:
                return get_lyrics_and_chords_from_search(title)
            raise RuntimeError(f"Could not identify song from URL: {url}")
        return parsed
    except (json.JSONDecodeError, ValueError):
        return _parse_response(raw, url)


def _get_youtube_title(url: str) -> str | None:
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title", "")
    except Exception:
        return None
