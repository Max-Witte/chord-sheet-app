import os
import json
import re
import requests
from functools import lru_cache
from scraper import search_ug, fetch_ug_chords

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
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192}
        }
    )

    if not response.ok:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text}")

    data = response.json()
    print("Gemini raw:", json.dumps(data)[:300])

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"No candidates: {json.dumps(data)}")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"No parts: {json.dumps(data)}")

    return parts[0]["text"].strip()


def _parse_json(text):
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    return json.loads(text.strip())


def _fetch_lyrics_ovh(artist, title):
    """Fetch real lyrics from lyrics.ovh as fallback."""
    try:
        url = f"https://api.lyrics.ovh/v1/{requests.utils.quote(artist)}/{requests.utils.quote(title)}"
        res = requests.get(url, timeout=8)
        if res.ok:
            lyrics = res.json().get("lyrics", "").strip()
            if lyrics:
                print(f"Got lyrics from lyrics.ovh ({len(lyrics)} chars)")
                return lyrics
    except Exception as e:
        print(f"lyrics.ovh failed: {e}")
    return None


def _gemini_chords_from_lyrics(title, artist, lyrics):
    """Ask Gemini to annotate real lyrics with chords."""
    prompt = f"""You are a music expert. Add chord annotations to the lyrics of "{title}" by {artist}.

Here are the REAL lyrics — do NOT change any words:

{lyrics}

Add chord markers [X] immediately before the word/syllable where the chord changes.
Identify song sections (Verse 1, Chorus, Bridge etc.)

Return ONLY valid JSON:
{{
  "title": "{title}",
  "artist": "{artist}",
  "key": "C",
  "bpm": 120,
  "sections": [
    {{
      "label": "Verse 1",
      "lines": ["[C]I will [G/B]leave my [Am]heart at the [G]door"]
    }}
  ]
}}

Rules:
- Use the EXACT lyrics provided — word for word
- Every line must have at least one chord marker
- Standard notation: C, Dm, Em, F, G, Am, G/B, C/E, F#, Bb etc.
"""
    raw = _call_gemini(prompt)
    return _parse_json(raw)


def _gemini_fallback(title, artist):
    """Full Gemini fallback when everything else fails."""
    prompt = f"""Produce a complete chord sheet for "{title}" by {artist}.
Use inline chord markers [X] before each syllable where chord changes.
Return ONLY valid JSON:
{{
  "title": "{title}",
  "artist": "{artist}",
  "key": "C",
  "bpm": 120,
  "sections": [{{"label": "Verse 1", "lines": ["[C]example [Am]line"]}}]
}}"""
    raw = _call_gemini(prompt)
    return _parse_json(raw)


def search_songs(query):
    """Return songs matching the query."""
    prompt = f"""You are a music database. The user searched for: "{query}"

Return ONLY valid JSON, no markdown:
{{
  "type": "song",
  "artist_name": null,
  "results": [
    {{"title": "Song Title", "artist": "Artist Name"}}
  ]
}}

Rules:
- Return as many results as you know — no limit
- If artist name: return their most popular songs, set type to "artist" and artist_name to the artist
- If song title: return best matching songs, type stays "song"
- Only include real songs you are confident exist
- Order by popularity
"""
    raw = _call_gemini(prompt)
    try:
        return _parse_json(raw)
    except Exception as e:
        raise RuntimeError(f"Failed to parse search results: {e}\nRaw: {raw[:300]}")


def get_ug_versions(title, artist):
    """Get available UG chord sheet versions for a song."""
    return search_ug(title, artist)


@lru_cache(maxsize=100)
def get_lyrics_and_chords(title, artist, ug_url=None):
    """
    1. Try Ultimate Guitar (most accurate)
    2. Fall back to lyrics.ovh + Gemini chord annotation
    3. Fall back to pure Gemini
    """
    # Step 1: Try UG
    if ug_url:
        print(f"Fetching UG chords from: {ug_url}")
        ug_result = fetch_ug_chords(ug_url)
        if ug_result and ug_result.get("sections"):
            return {
                "title": title,
                "artist": artist,
                "key": ug_result.get("key", ""),
                "bpm": ug_result.get("bpm"),
                "source": "ultimate-guitar",
                "sections": ug_result["sections"],
            }

    # Try searching UG automatically
    print("Searching UG automatically...")
    versions = search_ug(title, artist)
    if versions:
        best = versions[0]
        ug_result = fetch_ug_chords(best["url"])
        if ug_result and ug_result.get("sections"):
            return {
                "title": title,
                "artist": artist,
                "key": ug_result.get("key", best.get("key", "")),
                "bpm": ug_result.get("bpm"),
                "source": "ultimate-guitar",
                "versions": versions,
                "sections": ug_result["sections"],
            }

    # Step 2: lyrics.ovh + Gemini
    print("UG failed, trying lyrics.ovh + Gemini...")
    lyrics = _fetch_lyrics_ovh(artist, title)
    if lyrics:
        try:
            result = _gemini_chords_from_lyrics(title, artist, lyrics)
            result["source"] = "gemini+lyrics"
            return result
        except Exception as e:
            print(f"Gemini annotation failed: {e}")

    # Step 3: Pure Gemini fallback
    print("Falling back to pure Gemini...")
    result = _gemini_fallback(title, artist)
    result["source"] = "gemini"
    return result
