import os
import anthropic
import json
import re

# Hardcoded fallback — replace with your actual key
# Better: set ANTHROPIC_API_KEY in Railway environment variables
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

def _get_client():
    key = ANTHROPIC_API_KEY
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Add it in Railway → your service → Variables tab."
        )
    return anthropic.Anthropic(api_key=key)


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


def get_lyrics_and_chords_from_search(query: str) -> dict:
    """
    Given a search query like 'Bohemian Rhapsody Queen',
    return a chord sheet JSON using Claude.
    """
    client = _get_client()
    
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"{CHORD_SHEET_PROMPT}\n\nSong: {query}"
            }
        ]
    )
    
    raw = message.content[0].text.strip()
    return _parse_response(raw, query)


def get_lyrics_and_chords_from_url(url: str) -> dict:
    """
    Given a YouTube URL, extract the song title/artist from it
    and return a chord sheet using Claude.
    Falls back to asking Claude to identify the song from the URL.
    """
    client = _get_client()

    # First, ask Claude to identify the song from the YouTube URL
    identify_prompt = f"""Given this YouTube URL: {url}

If you can identify the song from the URL (often the video title is encoded in it), 
return a chord sheet for that song.

If you cannot identify the specific song, return a JSON error object:
{{"error": "Could not identify song from URL", "url": "{url}"}}

{CHORD_SHEET_PROMPT}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user", 
                "content": identify_prompt
            }
        ]
    )
    
    raw = message.content[0].text.strip()
    
    # Check if Claude returned an error
    try:
        parsed = _parse_json(raw)
        if "error" in parsed and "sections" not in parsed:
            # Try yt-dlp to get the video title, then retry
            title = _get_youtube_title(url)
            if title:
                return get_lyrics_and_chords_from_search(title)
            raise RuntimeError(f"Could not identify song from URL: {url}")
        return parsed
    except (json.JSONDecodeError, ValueError):
        return _parse_response(raw, url)


def _get_youtube_title(url: str) -> str | None:
    """Use yt-dlp to extract the video title without downloading."""
    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title", "")
    except Exception:
        return None


def _parse_json(text: str) -> dict:
    """Strip markdown fences and parse JSON."""
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    return json.loads(text.strip())


def _parse_response(raw: str, fallback_title: str) -> dict:
    """Parse Claude's response, with a fallback error structure."""
    try:
        return _parse_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        # Return a structured error that the frontend can display
        return {
            "error": f"Failed to parse chord sheet: {str(e)}",
            "raw": raw[:500],
            "title": fallback_title,
            "artist": "",
            "key": "",
            "bpm": None,
            "sections": []
        }
