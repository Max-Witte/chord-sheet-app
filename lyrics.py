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


def _fetch_lyrics(artist, title):
    """Fetch real lyrics from lyrics.ovh — free, no API key needed."""
    try:
        url = f"https://api.lyrics.ovh/v1/{requests.utils.quote(artist)}/{requests.utils.quote(title)}"
        res = requests.get(url, timeout=8)
        if res.ok:
            data = res.json()
            lyrics = data.get("lyrics", "").strip()
            if lyrics:
                print(f"Got lyrics from lyrics.ovh ({len(lyrics)} chars)")
                return lyrics
    except Exception as e:
        print(f"lyrics.ovh failed: {e}")
    return None


def _add_chords_to_lyrics(title, artist, lyrics, key_bpm_hint=""):
    """Ask Gemini to annotate real lyrics with chords."""
    prompt = f"""You are a music expert and guitarist/pianist. 
Your job is to add chord annotations to the lyrics of "{title}" by {artist}.

Here are the REAL lyrics — do NOT change any words, do NOT add or remove lines:

{lyrics}

Add chord markers in [X] format immediately before the word/syllable where the chord changes.
For example: "[C]Twinkle twinkle [Am]little [F]star"

Also identify the song sections (Verse 1, Chorus, Bridge etc.) and group lines accordingly.

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
        "[C]I will leave my [Am]heart at the [F]door",
        "[G]I won't say a word"
      ]
    }},
    {{
      "label": "Chorus",
      "lines": [
        "[F]All I [C]ask"
      ]
    }}
  ]
}}

Rules:
- Use the EXACT lyrics provided above — word for word
- Place [chord] markers where chord changes happen on that syllable
- Every line must have at least one chord marker
- Standard chord notation: C, Dm, Em, F, G, Am, Bm, C#, F#, Bb, Eb, G/B, C/E etc.
- Identify all sections correctly
"""
    return _call_gemini(prompt)


def search_songs(query):
    """Return all songs Gemini knows for the query."""
    prompt = f"""You are a music database. The user searched for: "{query}"

Determine if this is a song title or artist name search, then return matching songs.

Return ONLY valid JSON, no markdown:

{{
  "type": "song",
  "artist_name": null,
  "results": [
    {{"title": "Song Title", "artist": "Artist Name"}},
    {{"title": "Song Title", "artist": "Artist Name"}}
  ]
}}

Rules:
- Return as many results as you know — no limit
- If artist name: return their most popular songs, set type to "artist" and artist_name to the artist
- If song title: return best matching songs, type stays "song"
- Only include real, well-known songs you are confident exist
- Order by popularity
"""
    raw = _call_gemini(prompt)
    try:
        return _parse_json(raw)
    except Exception as e:
        raise RuntimeError(f"Failed to parse search results: {e}\nRaw: {raw[:300]}")


def get_lyrics_and_chords(title, artist):
    """
    1. Fetch real lyrics from lyrics.ovh
    2. Send to Gemini to annotate with chords
    """
    # Step 1: get real lyrics
    lyrics = _fetch_lyrics(artist, title)

    if not lyrics:
        print("lyrics.ovh returned nothing, falling back to Gemini-generated lyrics")
        # Fallback: let Gemini do everything (less accurate but better than nothing)
        prompt = f"""You are a music expert. Produce a complete chord sheet for "{title}" by {artist}.
Use inline chord markers [X] before the syllable where the chord is played.
Return ONLY valid JSON:
{{
  "title": "{title}",
  "artist": "{artist}",
  "key": "C",
  "bpm": 120,
  "sections": [
    {{"label": "Verse 1", "lines": ["[C]example [Am]line"]}}
  ]
}}"""
        raw = _call_gemini(prompt)
    else:
        # Step 2: annotate real lyrics with chords
        raw = _add_chords_to_lyrics(title, artist, lyrics)

    try:
        return _parse_json(raw)
    except Exception as e:
        raise RuntimeError(f"Failed to parse chord sheet: {e}\nRaw: {raw[:300]}")
